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


async def analyze_keyboard_screenshot(image_path: str, device_width: int, device_height: int) -> dict:
    """
    Send a keyboard screenshot to the AI and get back key mapping coordinates.

    The AI is asked to identify all visible keys and return their bounding box
    centers as (x, y) coordinates in the device's screen resolution.

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

    system_prompt = (
        "You are a computer vision assistant that analyzes screenshots of mobile keyboards. "
        "Your task is to locate every visible key on the keyboard and return its center coordinates. "
        "CRITICAL: You MUST output RAW JSON only — do NOT wrap it in ```json fences, "
        "do NOT use markdown formatting, do NOT add any text before or after the JSON. "
        "Your entire response must start with '{' and end with '}'."
    )

    user_prompt = (
        f"This is a screenshot of a mobile keyboard displayed on a device with resolution "
        f"{device_width}x{device_height} pixels. "
        f"Please identify EVERY visible key on the keyboard. For each key, determine the "
        f"center pixel coordinates (x, y) where the key should be tapped.\n\n"
        f"Return your answer as a JSON object ONLY, with this exact structure:\n"
        f'{{"keys": {{"q": {{"x": 123, "y": 456}}, "w": {{"x": 234, "y": 456}}, ...}}}}\n\n'
        f"IMPORTANT RULES:\n"
        f"1. The x coordinate is horizontal (0 = left edge, {device_width} = right edge).\n"
        f"2. The y coordinate is vertical (0 = top edge, {device_height} = bottom edge).\n"
        f"3. Include ALL keys you can see: letters, numbers, space, enter, backspace, shift, "
        f"symbols, punctuation, emoji key, etc.\n"
        f"4. For special keys, use these labels: \"ENTER\", \"BACKSPACE\", \"SPACE\", \"SHIFT\", "
        f"\"CAPS\", \"TAB\", \"DOT\" (for '.'), \"COMMA\" (for ','), \"SLASH\" (for '/'), "
        f"\"AT\" (for '@'), etc.\n"
        f"5. Coordinates must be integers, in the device's native resolution ({device_width}x{device_height}).\n"
        f"6. Return ONLY the JSON object, no other text, no markdown code blocks, no explanation.\n"
        f"7. Estimate carefully — look at the keyboard layout and proportionally map each key "
        f"to its correct pixel position."
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

    # Validate & sanitize keys — ensure coordinates are numbers
    sanitized = {}
    for char, coord in keys.items():
        if not isinstance(coord, dict):
            continue
        x = coord.get("x")
        y = coord.get("y")
        if x is None or y is None:
            continue
        try:
            x = round(float(x))
            y = round(float(y))
        except (ValueError, TypeError):
            continue
        # Clamp to screen bounds
        x = max(0, min(device_width, x))
        y = max(0, min(device_height, y))
        sanitized[str(char)] = {"x": x, "y": y}

    return {
        "success": True,
        "keys": sanitized,
        "key_count": len(sanitized),
        "raw_response": raw_content[:500],
    }
