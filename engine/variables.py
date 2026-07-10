"""
Global shared variable store — persisted to `data/variables/global.json`.
Used by the ScriptExecutor to share variables across scripts (call_script, goto_script).
"""
import json
import pathlib
import threading

_GLOBAL_VARS_FILE = pathlib.Path("data/variables/global.json")
_global_vars_lock = threading.Lock()


def load_global_vars() -> dict:
    """Load global variables from JSON file. Returns empty dict if not found."""
    try:
        if _GLOBAL_VARS_FILE.exists():
            return json.loads(_GLOBAL_VARS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_global_vars(variables: dict) -> None:
    """Save global variables to JSON file (thread-safe)."""
    try:
        _GLOBAL_VARS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _global_vars_lock:
            _GLOBAL_VARS_FILE.write_text(
                json.dumps(variables, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    except Exception:
        pass
