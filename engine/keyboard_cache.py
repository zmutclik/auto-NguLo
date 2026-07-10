"""
Keyboard mapping cache — loads key coordinates from DB on demand.
Used by type_text action with keyboard_mapping_id.
"""
import json
import threading

_keyboard_mapping_cache: dict[int, dict] = {}  # mapping_id → keys dict
_keyboard_mapping_cache_lock = threading.Lock()


async def load_keyboard_mapping(mapping_id: int, log_fn=None) -> dict:
    """Load keyboard mapping keys from DB (with thread-safe cache). Returns {char: {x, y}} dict."""
    global _keyboard_mapping_cache, _keyboard_mapping_cache_lock

    with _keyboard_mapping_cache_lock:
        if mapping_id in _keyboard_mapping_cache:
            return _keyboard_mapping_cache[mapping_id]

    try:
        import aiosqlite
        from config import DATABASE_PATH
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT keys_json FROM keyboard_mappings WHERE id=?", (mapping_id,)
            )
            row = await cursor.fetchone()
            if row and row["keys_json"]:
                keys = json.loads(row["keys_json"])
                with _keyboard_mapping_cache_lock:
                    _keyboard_mapping_cache[mapping_id] = keys
                return keys
    except Exception as e:
        if log_fn:
            log_fn("error", f"  Failed to load keyboard mapping #{mapping_id}: {e}")

    with _keyboard_mapping_cache_lock:
        _keyboard_mapping_cache[mapping_id] = {}
    return {}


def clear_keyboard_cache(mapping_id: int | None = None) -> None:
    """Clear keyboard mapping cache. If mapping_id is None, clears all."""
    global _keyboard_mapping_cache, _keyboard_mapping_cache_lock
    with _keyboard_mapping_cache_lock:
        if mapping_id is None:
            _keyboard_mapping_cache.clear()
        elif mapping_id in _keyboard_mapping_cache:
            del _keyboard_mapping_cache[mapping_id]
