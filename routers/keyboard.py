"""Keyboard mapping router — CRUD for touch keyboard layouts used by type_text action."""
import json
import os

from fastapi import APIRouter, HTTPException
from database.connection import get_db
from schemas.requests import KeyboardMappingCreate, KeyboardMappingUpdate

router = APIRouter(prefix="/api/keyboard", tags=["keyboard"])


def _row_to_dict(row) -> dict:
    if row is None:
        return None
    d = dict(row)
    # Parse keys_json from string to dict
    if "keys_json" in d and isinstance(d["keys_json"], str):
        try:
            d["keys_json"] = json.loads(d["keys_json"])
        except (json.JSONDecodeError, TypeError):
            d["keys_json"] = {}
    return d


def _get_key_map(layout_type: str) -> list[str]:
    """Return the list of key labels for a given layout type (for UI display)."""
    if layout_type == "number":
        return [
            "1", "2", "3", "4", "5", "6", "7", "8", "9", "0",
            ".", ",", "ENTER", "BACKSPACE",
        ]
    elif layout_type == "qwerty":
        return [
            "q", "w", "e", "r", "t", "y", "u", "i", "o", "p",
            "a", "s", "d", "f", "g", "h", "j", "k", "l",
            "z", "x", "c", "v", "b", "n", "m",
            "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
            " ", "ENTER", "BACKSPACE",
            ".", ",", "!", "?", "@", "#", "$", "%", "&", "*", "-", "_", "+", "=",
            "/", "\\", ":", ";", "'", "\"", "(", ")", "[", "]", "{", "}",
            "<", ">", "|", "~", "`", "^",
        ]
    else:
        # Custom/unknown layout — no pre-populated keys
        return []


@router.get("")
async def list_mappings():
    """List all keyboard mappings."""
    db = await get_db()
    cursor = await db.execute("SELECT * FROM keyboard_mappings ORDER BY layout_type, id")
    rows = [_row_to_dict(r) for r in await cursor.fetchall()]
    for r in rows:
        r["key_list"] = _get_key_map(r.get("layout_type", "custom"))
    return rows


@router.get("/{mapping_id}")
async def get_mapping(mapping_id: int):
    """Get a single keyboard mapping by ID."""
    db = await get_db()
    cursor = await db.execute("SELECT * FROM keyboard_mappings WHERE id=?", (mapping_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Keyboard mapping not found")
    result = _row_to_dict(row)
    result["key_list"] = _get_key_map(result.get("layout_type", "custom"))
    return result


@router.post("")
async def create_mapping(data: KeyboardMappingCreate):
    """Create a new keyboard mapping."""
    db = await get_db()
    keys_str = json.dumps(data.keys_json or {}, ensure_ascii=False)
    cursor = await db.execute(
        "INSERT INTO keyboard_mappings (name, layout_type, keys_json, screenshot_path) VALUES (?, ?, ?, ?)",
        (data.name, data.layout_type, keys_str, data.screenshot_path or ""),
    )
    await db.commit()
    return _row_to_dict(
        await (await db.execute("SELECT * FROM keyboard_mappings WHERE id=?", (cursor.lastrowid,))).fetchone()
    )


@router.put("/{mapping_id}")
async def update_mapping(mapping_id: int, data: KeyboardMappingUpdate):
    """Update a keyboard mapping (name, layout_type, or keys_json)."""
    db = await get_db()
    cursor = await db.execute("SELECT * FROM keyboard_mappings WHERE id=?", (mapping_id,))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Keyboard mapping not found")

    set_parts = []
    values = []
    if data.name is not None:
        set_parts.append("name=?")
        values.append(data.name)
    if data.layout_type is not None:
        set_parts.append("layout_type=?")
        values.append(data.layout_type)
    if data.keys_json is not None:
        set_parts.append("keys_json=?")
        values.append(json.dumps(data.keys_json, ensure_ascii=False))
    if data.screenshot_path is not None:
        set_parts.append("screenshot_path=?")
        values.append(data.screenshot_path)

    if set_parts:
        set_parts.append("updated_at=datetime('now')")
        await db.execute(
            f"UPDATE keyboard_mappings SET {', '.join(set_parts)} WHERE id=?",
            [*values, mapping_id],
        )
        await db.commit()

    return _row_to_dict(
        await (await db.execute("SELECT * FROM keyboard_mappings WHERE id=?", (mapping_id,))).fetchone()
    )


@router.put("/{mapping_id}/keys")
async def update_single_key(mapping_id: int, char: str, x: float, y: float):
    """Update or add a single key coordinate in a mapping. More efficient than sending full keys_json."""
    db = await get_db()
    cursor = await db.execute("SELECT * FROM keyboard_mappings WHERE id=?", (mapping_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Keyboard mapping not found")

    keys = {}
    raw = row["keys_json"]
    if raw:
        try:
            keys = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            keys = {}

    keys[char] = {"x": x, "y": y}
    await db.execute(
        "UPDATE keyboard_mappings SET keys_json=?, updated_at=datetime('now') WHERE id=?",
        (json.dumps(keys, ensure_ascii=False), mapping_id),
    )
    await db.commit()
    return {"char": char, "x": x, "y": y, "total_keys": len(keys)}


@router.delete("/{mapping_id}/keys/{char}")
async def delete_single_key(mapping_id: int, char: str):
    """Delete a single key from a mapping."""
    db = await get_db()
    cursor = await db.execute("SELECT * FROM keyboard_mappings WHERE id=?", (mapping_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Keyboard mapping not found")

    keys = {}
    raw = row["keys_json"]
    if raw:
        try:
            keys = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            keys = {}

    if char in keys:
        del keys[char]
        await db.execute(
            "UPDATE keyboard_mappings SET keys_json=?, updated_at=datetime('now') WHERE id=?",
            (json.dumps(keys, ensure_ascii=False), mapping_id),
        )
        await db.commit()

    return {"char": char, "deleted": True, "total_keys": len(keys)}


@router.post("/{mapping_id}/test-tap")
async def test_tap_key(mapping_id: int, char: str):
    """Test-tap a single key by character: sends ADB tap to the mapped coordinate.
    Uses the ADB 'input tap' command directly for quick feedback."""
    db = await get_db()
    cursor = await db.execute("SELECT * FROM keyboard_mappings WHERE id=?", (mapping_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Keyboard mapping not found")

    keys = {}
    raw = row["keys_json"]
    if raw:
        try:
            keys = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            keys = {}

    if char not in keys:
        raise HTTPException(status_code=404, detail=f"Key '{char}' not mapped in this keyboard layout")

    coord = keys[char]
    x, y = int(coord["x"]), int(coord["y"])

    # Try to tap via ADB
    import asyncio

    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                "adb", "shell", "input", "tap", str(x), str(y),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            ),
            timeout=5.0,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace").strip()
            return {"success": False, "error": err, "x": x, "y": y, "char": char}
        return {"success": True, "x": x, "y": y, "char": char}
    except asyncio.TimeoutError:
        return {"success": False, "error": "ADB timeout", "x": x, "y": y, "char": char}
    except (FileNotFoundError, OSError):
        return {"success": False, "error": "ADB not found", "x": x, "y": y, "char": char}


@router.delete("/{mapping_id}")
async def delete_mapping(mapping_id: int):
    """Delete a keyboard mapping."""
    db = await get_db()
    cursor = await db.execute("SELECT id FROM keyboard_mappings WHERE id=?", (mapping_id,))
    if not await cursor.fetchone():
        raise HTTPException(status_code=404, detail="Keyboard mapping not found")

    await db.execute("DELETE FROM keyboard_mappings WHERE id=?", (mapping_id,))
    await db.commit()

    # Clear cache for this mapping
    from engine.keyboard_cache import clear_keyboard_cache
    clear_keyboard_cache(mapping_id)

    return {"message": "Mapping deleted"}


# ── AI-powered keyboard mapping ──────────────────────────────────────

@router.post("/{mapping_id}/ai-map")
async def ai_map_keyboard(mapping_id: int, image_path: str):
    """Use AI to analyze a keyboard screenshot and auto-fill key coordinates.

    Args:
        mapping_id: The keyboard mapping ID to update.
        image_path: Relative path to the uploaded screenshot (e.g., 'templates/kb.png').
    """
    db = await get_db()
    cursor = await db.execute("SELECT * FROM keyboard_mappings WHERE id=?", (mapping_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Keyboard mapping not found")

    # Resolve the full path to the screenshot
    from config import TEMPLATE_DIR
    full_path = os.path.join(TEMPLATE_DIR, os.path.basename(image_path))
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=400, detail=f"Screenshot not found: {image_path}")

    # Default device resolution (will be overridden if device info available)
    device_width = 1080
    device_height = 1920
    try:
        from engine.adb import run_adb
        proc = await run_adb("shell", "wm", "size", timeout=5.0)
        # Output: "Physical size: 1080x1920" or "Override size: 1080x2400"
        import re
        match = re.search(r'(\d+)x(\d+)', proc)
        if match:
            device_width = int(match.group(1))
            device_height = int(match.group(2))
    except Exception:
        pass  # use defaults

    # Call the AI engine
    from engine.ai import analyze_keyboard_screenshot
    result = await analyze_keyboard_screenshot(full_path, device_width, device_height)

    if not result.get("success"):
        return {
            "success": False,
            "error": result.get("error", "Unknown AI error"),
            "raw_response": result.get("raw_response", ""),
        }

    ai_keys = result.get("keys", {})

    # Merge AI keys with existing mapping (AI overrides existing, preserves only unknowns)
    existing_keys = {}
    raw = row["keys_json"]
    if raw:
        try:
            existing_keys = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            existing_keys = {}

    # AI keys take precedence; keep any existing keys not covered by AI
    merged = {**existing_keys, **ai_keys}

    # Save to DB
    await db.execute(
        "UPDATE keyboard_mappings SET keys_json=?, updated_at=datetime('now') WHERE id=?",
        (json.dumps(merged, ensure_ascii=False), mapping_id),
    )
    await db.commit()

    return {
        "success": True,
        "message": f"AI mapped {len(ai_keys)} keys",
        "keys": ai_keys,
        "total_keys": len(merged),
        "raw_response": result.get("raw_response", ""),
    }
