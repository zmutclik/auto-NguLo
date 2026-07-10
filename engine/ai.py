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
        "Your task is to locate every visible key on the keyboard and return its center coordinates."
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
        "max_tokens": 4096,
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
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        return {
            "success": False,
            "error": f"Unexpected AI response format: {e}",
            "keys": {},
            "raw_response": str(data),
        }

    # Parse the JSON from the response — try to extract from markdown if needed
    raw_content = content.strip()
    parsed = None

    # Try direct JSON parse
    try:
        parsed = json.loads(raw_content)
    except json.JSONDecodeError:
        pass

    # Try extracting JSON from markdown code blocks
    if parsed is None:
        import re
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw_content, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

    # Try finding raw JSON object in text
    if parsed is None:
        import re
        match = re.search(r'\{[\s\S]*"keys"[\s\S]*\}', raw_content)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

    if parsed is None:
        return {
            "success": False,
            "error": "AI response is not valid JSON",
            "keys": {},
            "raw_response": raw_content[:500],
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
