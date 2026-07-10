"""
AI / LLM integration module.
Supports OpenAI-compatible APIs for keyboard mapping via vision.
"""
import base64
import json
import os

import httpx

from config import AI_URL, AI_KEY, AI_MODEL


def _is_configured() -> bool:
    """Check if AI is properly configured."""
    return bool(AI_URL and AI_KEY and AI_MODEL)


def _extract_json_object(text: str) -> dict | None:
    """
    Extract a JSON object dict from arbitrary text using multiple strategies.
    Returns None if nothing valid found.
    """
    import re

    text = text.strip()
    if not text:
        return None

    # 0) Strip markdown code fences: ```json ... ``` or ``` ... ```
    fence_match = re.match(r'```(?:json|JSON)?\s*\n(.*?)\n\s*```\s*$', text, re.DOTALL)
    if not fence_match:
        fence_match = re.match(r'```(?:json|JSON)?\s*(.*?)\s*```\s*$', text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    # Also handle single-backtick wrapping: `{...}`
    if text.startswith("`") and text.endswith("`"):
        text = text[1:-1].strip()

    # 1) Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2) Balanced-brace extraction: find the first complete top-level JSON object
    # This handles cases like:
    #   {"keys": {...}} some trailing garbage
    #   Some prefix text {"keys": {...}}
    #   Truncated output: [model stops mid-JSON] — strip to last valid state
    start = text.find("{")
    if start >= 0:
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break  # malformed, give up

    # 3) Truncated JSON recovery: if max_tokens cut off the response, try to
    #    salvage by closing unmatched braces/quotes and parsing.
    if start >= 0:
        truncated = text[start:]
        # Count open vs close braces in truncated text
        open_count = 0
        close_count = 0
        in_string = False
        escape = False
        for ch in truncated:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                open_count += 1
            elif ch == "}":
                close_count += 1

        if open_count > close_count:
            # Try to repair: add missing closing braces
            # First, strip trailing incomplete element (e.g., halfway through a key/value)
            repaired = truncated.rstrip()
            # Remove trailing incomplete fragment after last comma
            last_comma = repaired.rfind(",")
            last_close = repaired.rfind("}")
            if last_comma > last_close:
                repaired = repaired[:last_comma]
            # Add missing closing braces
            repaired += "}" * (open_count - close_count)
            # Close any unclosed string
            if in_string:
                repaired += '"'
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                pass

    return None


def _get_image_dimensions(image_path: str) -> tuple[int, int]:
    """
    Get the width and height of an image file using only the standard library.
    Supports JPEG, PNG, GIF, BMP, WebP.
    Returns (width, height) or (0, 0) on failure.
    """
    import struct

    try:
        with open(image_path, "rb") as f:
            header = f.read(32)

        if len(header) < 4:
            return (0, 0)

        # JPEG: look for SOF0/1/2 marker (0xFFC0, 0xFFC1, 0xFFC2)
        if header[:2] == b"\xff\xd8":
            with open(image_path, "rb") as f:
                f.read(2)  # SOI
                while True:
                    b = f.read(2)
                    if len(b) < 2:
                        break
                    marker = b
                    if marker[0:1] != b"\xff":
                        break
                    # SOS marker — scan data follows, stop searching
                    if marker == b"\xff\xda":
                        break
                    # RST markers (0xFFD0-0xFFD7) have no length field
                    if b"\xff\xd0" <= marker <= b"\xff\xd7":
                        continue
                    # Other markers have a 2-byte length (includes the 2 length bytes)
                    length_bytes = f.read(2)
                    if len(length_bytes) < 2:
                        break
                    length = struct.unpack(">H", length_bytes)[0]
                    if marker in (b"\xff\xc0", b"\xff\xc1", b"\xff\xc2"):
                        # SOF0/SOF1/SOF2: precision (1), height (2), width (2)
                        f.read(1)
                        h = struct.unpack(">H", f.read(2))[0]
                        w = struct.unpack(">H", f.read(2))[0]
                        return (w, h)
                    # Skip remaining segment data
                    if length > 2:
                        f.read(length - 2)
            return (0, 0)

        # PNG: 8-byte signature, then IHDR at offset 16 (width:4, height:4)
        if header[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = struct.unpack(">II", header[16:24])
            return (w, h)

        # GIF: bytes 6-7 = width, 8-9 = height (little-endian)
        if header[:3] == b"GIF" and header[3:6] in (b"87a", b"89a"):
            w, h = struct.unpack("<HH", header[6:10])
            return (w, h)

        # BMP: offset 18 = width, 22 = height (signed LE int32)
        if header[:2] == b"BM":
            w = struct.unpack("<i", header[18:22])[0]
            h = abs(struct.unpack("<i", header[22:26])[0])
            return (w, h)

        # WebP: RIFF container, look for "VP8 " or "VP8L" or "VP8X"
        if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
            # For simple VP8/VP8L we can parse; VP8X is extended
            with open(image_path, "rb") as f:
                f.read(12)
                chunk = f.read(10)
                if chunk[:4] == b"VP8 ":
                    # VP8 lossy: 10 bytes frame header; w/h are in the first keyframe
                    # width at bits [23:10] & 0x3fff, height at bits [41:26] & 0x3fff
                    f.read(10)  # skip to keyframe payload
                    kf = f.read(10)
                    if len(kf) >= 6:
                        w = struct.unpack("<H", kf[:2])[0] & 0x3fff
                        h = struct.unpack("<H", kf[4:6])[0] & 0x3fff
                        return (w, h)
                elif chunk[:4] == b"VP8L":
                    bits = struct.unpack("<I", chunk[4:8])[0]
                    w = (bits & 0x3fff) + 1
                    h = ((bits >> 14) & 0x3fff) + 1
                    return (w, h)
                elif chunk[:4] == b"VP8X":
                    # Extended format: width+1 at bits [30:28], height+1 at [58:56]
                    # Actually let's read the VP8X header properly
                    f.read(10)  # already read chunk header
                    xh = f.read(10)
                    if len(xh) >= 10:
                        w = struct.unpack("<I", xh[4:8])[0] & 0x00ffffff
                        h = (struct.unpack("<I", xh[6:10])[0] >> 8) & 0x00ffffff
                        if w and h:
                            return (w + 1, h + 1)
            return (0, 0)

        return (0, 0)
    except Exception:
        return (0, 0)


async def analyze_keyboard_screenshot(image_path: str, device_width: int, device_height: int) -> dict:
    """
    Send a keyboard screenshot to the AI and get back key mapping coordinates.

    The AI is asked to identify all visible keys and return their bounding box
    centers as (x, y) coordinates. Coordinates are automatically scaled from
    the actual image resolution to the device's screen resolution.

    Returns:
        dict with:
          - success: bool
          - keys: dict {char: {x, y}} if successful
          - error: str if failed
          - raw_response: str for debugging
    """
    if not _is_configured():
        return {
            "success": False,
            "error": "AI not configured. Set AI_URL, AI_KEY, AI_MODEL env vars.",
            "keys": {},
        }

    # Read & encode image
    try:
        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")
    except FileNotFoundError:
        return {"success": False, "error": f"Screenshot not found: {image_path}", "keys": {}}
    except Exception as e:
        return {"success": False, "error": f"Failed to read screenshot: {e}", "keys": {}}

    # Detect image mime type
    ext = os.path.splitext(image_path)[-1].lower()
    mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp"}
    mime_type = mime_map.get(ext, "image/png")

    # Determine the actual image pixel dimensions
    img_width, img_height = _get_image_dimensions(image_path)
    # Fallback to device resolution if detection fails
    if img_width <= 0 or img_height <= 0:
        img_width, img_height = device_width, device_height

    # Use actual image dimensions for the AI prompt
    # The AI returns coordinates in image-pixel space; we'll scale to device space later
    prompt_width, prompt_height = img_width, img_height
    scale_x = device_width / img_width if img_width > 0 else 1.0
    scale_y = device_height / img_height if img_height > 0 else 1.0

    system_prompt = (
        "You are a computer vision assistant that analyzes screenshots of mobile keyboards. "
        "Your task is to locate every visible key on the keyboard and return its center coordinates. "
        "CRITICAL: You MUST output RAW JSON only — do NOT wrap it in ```json fences, "
        "do NOT use markdown formatting, do NOT add any text before or after the JSON. "
        "Your entire response must start with '{' and end with '}'."
    )

    user_prompt = (
        f"This is a screenshot of a mobile keyboard. The image is exactly {prompt_width}x{prompt_height} pixels. "
        f"Please identify EVERY visible key on the keyboard. For each key, determine the "
        f"center pixel coordinates (x, y) where the key should be tapped.\n\n"
        f"Return your answer as a JSON object ONLY, with this exact structure:\n"
        f'{{"keys": {{"q": {{"x": 123, "y": 456}}, "w": {{"x": 234, "y": 456}}, ...}}}}\n\n'
        f"IMPORTANT RULES:\n"
        f"1. The x coordinate is horizontal (0 = left edge of image, {prompt_width} = right edge).\n"
        f"2. The y coordinate is vertical (0 = top edge of image, {prompt_height} = bottom edge).\n"
        f"3. Include ALL keys you can see: letters, numbers, space, enter, backspace, shift, "
        f"symbols, punctuation, emoji key, etc.\n"
        f"4. For special keys, use these labels: \"ENTER\", \"BACKSPACE\", \"SPACE\", \"SHIFT\", "
        f"\"CAPS\", \"TAB\", \"DOT\" (for '.'), \"COMMA\" (for ','), \"SLASH\" (for '/'), "
        f"\"AT\" (for '@'), etc.\n"
        f"5. Coordinates must be integers, within the image bounds (0 to {prompt_width-1} for x, 0 to {prompt_height-1} for y).\n"
        f"6. Return ONLY the JSON object, no other text, no markdown code blocks, no explanation.\n"
        f"7. Estimate carefully — look at the keyboard layout in THIS image and proportionally "
        f"map each key to its correct pixel position within the {prompt_width}x{prompt_height} image."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_prompt},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{image_data}",
                        "detail": "high",
                    },
                },
            ],
        },
    ]

    # Build the API URL — append /chat/completions if not already present
    api_url = AI_URL.rstrip("/")
    if not api_url.endswith("/chat/completions"):
        api_url += "/chat/completions"

    headers = {
        "Authorization": f"Bearer {AI_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": AI_MODEL,
        "messages": messages,
        "max_tokens": 8192,
        "temperature": 0.1,
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(api_url, json=payload, headers=headers)
            resp.raise_for_status()
            raw_text = resp.text

            # Some providers return the JSON with extra trailing data
            # (e.g., newlines, whitespace, or additional objects).
            # Try to extract just the first complete JSON object.
            data = None
            try:
                data = json.loads(raw_text)
            except json.JSONDecodeError:
                # Try to find the first valid JSON object boundary
                stripped = raw_text.strip()
                # Find balanced braces
                if stripped.startswith("{"):
                    depth = 0
                    end_idx = 0
                    for i, ch in enumerate(stripped):
                        if ch == "{":
                            depth += 1
                        elif ch == "}":
                            depth -= 1
                            if depth == 0:
                                end_idx = i + 1
                                break
                    if end_idx > 0:
                        try:
                            data = json.loads(stripped[:end_idx])
                        except json.JSONDecodeError:
                            pass
                if data is None:
                    raise
    except httpx.TimeoutException:
        return {"success": False, "error": "AI request timed out (60s)", "keys": {}}
    except httpx.HTTPStatusError as e:
        return {"success": False, "error": f"AI API error: {e.response.status_code}", "keys": {}}
    except Exception as e:
        return {"success": False, "error": f"AI request failed: {e}", "keys": {}}

    # Extract the assistant's message
    try:
        message = data["choices"][0]["message"]
        content = message.get("content", "") or ""
        # Some reasoning models (e.g., deepseek-r1) put their output in
        # `reasoning_content` and leave `content` empty.
        reasoning = message.get("reasoning_content", "") or ""
    except (KeyError, IndexError, TypeError) as e:
        return {
            "success": False,
            "error": f"Unexpected AI response format: {e}",
            "keys": {},
            "raw_response": json.dumps(data, ensure_ascii=False)[:2000],
        }

    # Check if the model complained about missing vision support
    no_vision_clues = [
        "no vision support", "image omitted", "cannot see",
        "can't see the image", "unable to view", "not a vision model",
        "no image provided", "can't analyze", "cannot analyze",
    ]
    combined = (reasoning + " " + content).lower()
    for clue in no_vision_clues:
        if clue in combined:
            return {
                "success": False,
                "error": (
                    f"Model '{AI_MODEL}' tidak mendukung vision (image analysis). "
                    f"Ganti ke model vision seperti: gpt-4o, claude-3.5-sonnet, "
                    f"gemini-2.0-flash, atau qwen-vl-max."
                ),
                "keys": {},
                "raw_response": (reasoning + content)[:500],
            }

    # Use reasoning_content as fallback if content is empty
    if not content.strip() and reasoning.strip():
        content = reasoning

    if not content or not content.strip():
        return {
            "success": False,
            "error": f"AI returned empty response. "
                      f"Model mungkin tidak mendukung vision. Ganti ke model vision-capable. "
                      f"Response: {json.dumps(data, ensure_ascii=False)[:500]}",
            "keys": {},
            "raw_response": "",
        }

    raw_content = content.strip()

    # Parse the JSON from the response using multiple strategies
    parsed = _extract_json_object(raw_content)

    if parsed is None:
        return {
            "success": False,
            "error": "AI response is not valid JSON",
            "keys": {},
            "raw_response": raw_content[:1000],
        }

    keys = parsed.get("keys", {})

    # Validate, scale & sanitize keys
    # AI returns coordinates in image-pixel space; scale to device space
    sanitized = {}
    for char, coord in keys.items():
        if not isinstance(coord, dict):
            continue
        x = coord.get("x")
        y = coord.get("y")
        if x is None or y is None:
            continue
        try:
            x = round(float(x) * scale_x)
            y = round(float(y) * scale_y)
        except (ValueError, TypeError):
            continue
        # Clamp to device screen bounds
        x = max(0, min(device_width, x))
        y = max(0, min(device_height, y))
        sanitized[str(char)] = {"x": x, "y": y}

    return {
        "success": True,
        "keys": sanitized,
        "key_count": len(sanitized),
        "image_resolution": f"{img_width}x{img_height}",
        "device_resolution": f"{device_width}x{device_height}",
        "scale": f"{scale_x:.4f}x{scale_y:.4f}",
        "raw_response": raw_content[:500],
    }
