"""
Input injection fallback via `sendevent` (no root needed on many devices).
Also contains key mappings: COMBO_KEYS, KEY_NAME_MAP, _KEYCODE_TO_LINUX.

These are used when the device denies INJECT_EVENTS permission.
"""
import asyncio
import re

from engine.adb import run_adb


# ── Combo action → ADB keyevent sequences ──────────────────────────
COMBO_KEYS = {
    "select_all":     ["KEYCODE_CTRL_LEFT", "KEYCODE_A", "KEYCODE_CTRL_LEFT"],
    "copy":           ["KEYCODE_CTRL_LEFT", "KEYCODE_C", "KEYCODE_CTRL_LEFT"],
    "paste":          ["KEYCODE_CTRL_LEFT", "KEYCODE_V", "KEYCODE_CTRL_LEFT"],
    "cut":            ["KEYCODE_CTRL_LEFT", "KEYCODE_X", "KEYCODE_CTRL_LEFT"],
    "undo":           ["KEYCODE_CTRL_LEFT", "KEYCODE_Z", "KEYCODE_CTRL_LEFT"],
    "back":           ["KEYCODE_BACK"],
    "home":           ["KEYCODE_HOME"],
    "recents":        ["KEYCODE_APP_SWITCH"],
    "notifications":  ["KEYCODE_NOTIFICATION"],
    "enter":          ["KEYCODE_ENTER"],
    "delete":         ["KEYCODE_DEL"],
    "tab":            ["KEYCODE_TAB"],
    "escape":         ["KEYCODE_ESCAPE"],
    "volume_up":      ["KEYCODE_VOLUME_UP"],
    "volume_down":    ["KEYCODE_VOLUME_DOWN"],
    "power":          ["KEYCODE_POWER"],
    "screenshot":     ["KEYCODE_VOLUME_DOWN", "KEYCODE_POWER"],
}

# Map user-friendly key names → Android KeyEvent constant names
KEY_NAME_MAP = {
    "HOME":           "KEYCODE_HOME",
    "BACK":           "KEYCODE_BACK",
    "RECENTS":        "KEYCODE_APP_SWITCH",
    "ENTER":          "KEYCODE_ENTER",
    "DELETE":         "KEYCODE_DEL",
    "TAB":            "KEYCODE_TAB",
    "ESCAPE":         "KEYCODE_ESCAPE",
    "SPACE":          "KEYCODE_SPACE",
    "VOLUME_UP":      "KEYCODE_VOLUME_UP",
    "VOLUME_DOWN":    "KEYCODE_VOLUME_DOWN",
    "VOLUME_MUTE":    "KEYCODE_VOLUME_MUTE",
    "POWER":          "KEYCODE_POWER",
    "MENU":           "KEYCODE_MENU",
    "SEARCH":         "KEYCODE_SEARCH",
    "CAMERA":         "KEYCODE_CAMERA",
    "FOCUS":          "KEYCODE_FOCUS",
    "NOTIFICATION":   "KEYCODE_NOTIFICATION",
    "DPAD_UP":        "KEYCODE_DPAD_UP",
    "DPAD_DOWN":      "KEYCODE_DPAD_DOWN",
    "DPAD_LEFT":      "KEYCODE_DPAD_LEFT",
    "DPAD_RIGHT":     "KEYCODE_DPAD_RIGHT",
    "DPAD_CENTER":    "KEYCODE_DPAD_CENTER",
    "MEDIA_PLAY":     "KEYCODE_MEDIA_PLAY",
    "MEDIA_PAUSE":    "KEYCODE_MEDIA_PAUSE",
    "MEDIA_NEXT":     "KEYCODE_MEDIA_NEXT",
    "MEDIA_PREVIOUS": "KEYCODE_MEDIA_PREVIOUS",
}

# Android keycode → Linux input event key code mapping (for sendevent fallback)
KEYCODE_TO_LINUX = {
    # Alphabet keys
    "KEYCODE_A": 30, "KEYCODE_B": 48, "KEYCODE_C": 46, "KEYCODE_D": 32,
    "KEYCODE_E": 18, "KEYCODE_F": 33, "KEYCODE_G": 34, "KEYCODE_H": 35,
    "KEYCODE_I": 23, "KEYCODE_J": 36, "KEYCODE_K": 37, "KEYCODE_L": 38,
    "KEYCODE_M": 50, "KEYCODE_N": 49, "KEYCODE_O": 24, "KEYCODE_P": 25,
    "KEYCODE_Q": 16, "KEYCODE_R": 19, "KEYCODE_S": 31, "KEYCODE_T": 20,
    "KEYCODE_U": 22, "KEYCODE_V": 47, "KEYCODE_W": 17, "KEYCODE_X": 45,
    "KEYCODE_Y": 21, "KEYCODE_Z": 44,
    # Numbers
    "KEYCODE_0": 11, "KEYCODE_1": 2, "KEYCODE_2": 3, "KEYCODE_3": 4,
    "KEYCODE_4": 5, "KEYCODE_5": 6, "KEYCODE_6": 7, "KEYCODE_7": 8,
    "KEYCODE_8": 9, "KEYCODE_9": 10,
    # Navigation / function
    "KEYCODE_HOME": 102, "KEYCODE_BACK": 158, "KEYCODE_ENTER": 28,
    "KEYCODE_DEL": 14, "KEYCODE_TAB": 15, "KEYCODE_ESCAPE": 1,
    "KEYCODE_SPACE": 57, "KEYCODE_VOLUME_UP": 115, "KEYCODE_VOLUME_DOWN": 114,
    "KEYCODE_POWER": 116, "KEYCODE_MENU": 139, "KEYCODE_SEARCH": 217,
    "KEYCODE_DPAD_UP": 103, "KEYCODE_DPAD_DOWN": 108,
    "KEYCODE_DPAD_LEFT": 105, "KEYCODE_DPAD_RIGHT": 106,
    "KEYCODE_DPAD_CENTER": 28, "KEYCODE_APP_SWITCH": 187,
    "KEYCODE_NOTIFICATION": 83,
    # Media
    "KEYCODE_MEDIA_PLAY": 207, "KEYCODE_MEDIA_PAUSE": 119,
    "KEYCODE_MEDIA_NEXT": 163, "KEYCODE_MEDIA_PREVIOUS": 165,
    # Modifiers (Ctrl, Alt, etc.) — approximate
    "KEYCODE_CTRL_LEFT": 29, "KEYCODE_CTRL_RIGHT": 97,
    "KEYCODE_ALT_LEFT": 56, "KEYCODE_ALT_RIGHT": 100,
    "KEYCODE_SHIFT_LEFT": 42, "KEYCODE_SHIFT_RIGHT": 54,
}

# ── Cached device capabilities ──────────────────────────────────────
_inject_perms_granted: bool = False
_device_touch_event: str | None = None   # e.g. /dev/input/event2
_device_key_event: str | None = None     # e.g. /dev/input/event0
_device_max_x: int = 1080
_device_max_y: int = 1920
_sendevent_available: bool | None = None


# ── Permission helpers ──────────────────────────────────────────────

async def _try_grant_inject_permission(serial: str | None = None) -> bool:
    """Try multiple ways to grant INJECT_EVENTS permission to shell."""
    global _inject_perms_granted
    if _inject_perms_granted:
        return True

    adb_prefix = ("-s", serial) if serial else ()

    # Method 1: appops (Android 4.4+)
    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                "adb", *(adb_prefix + ("shell", "appops", "set", "com.android.shell", "INJECT_EVENTS", "allow")),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            ),
            timeout=3.0,
        )
        await asyncio.wait_for(proc.communicate(), timeout=3.0)
        if proc.returncode == 0:
            _inject_perms_granted = True
            return True
    except Exception:
        pass

    # Method 2: settings put global (some ROMs)
    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                "adb", *(adb_prefix + ("shell", "settings", "put", "global",
                "inject_events_whitelist", "com.android.shell")),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            ),
            timeout=3.0,
        )
        await asyncio.wait_for(proc.communicate(), timeout=3.0)
    except Exception:
        pass

    return False


# ── Device detection ────────────────────────────────────────────────

async def detect_sendevent(serial: str | None = None) -> bool:
    """Detect if sendevent injection is available (no root needed on many devices)."""
    global _sendevent_available, _device_touch_event, _device_key_event
    global _device_max_x, _device_max_y

    if _sendevent_available is not None:
        return _sendevent_available

    adb_prefix = ("-s", serial) if serial else ()

    # 1. Check if getevent works (indicates input group access)
    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                "adb", *(adb_prefix + ("shell", "getevent", "-p")),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            ),
            timeout=4.0,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=4.0)
        out = stdout.decode("utf-8", errors="replace")
        print(f"[detect_sendevent] getevent -p raw output ({len(out)} bytes):")
        print(out[:2000])
    except Exception as e:
        print(f"[detect_sendevent] getevent -p failed: {e}")
        _sendevent_available = False
        return False

    # 2. Parse: find touchscreen and keyboard devices
    lines = out.split("\n")
    current_dev = None
    current_name = ""
    max_abs_x = 0
    max_abs_y = 0

    best_key_dev = None
    best_key_name = ""

    for line in lines:
        line = line.strip()
        if line.startswith("add device"):
            current_dev = line.split(":", 1)[1].strip()
            current_name = ""
        elif line.startswith("name:"):
            current_name = line.split(":", 1)[1].strip().strip('"')
            if "touch" in current_name.lower() or "fts" in current_name.lower():
                _device_touch_event = current_dev
        elif line.startswith("keyboard") and not _device_key_event:
            if current_dev and not _device_key_event:
                _device_key_event = current_dev
        elif "ABS_MT_POSITION_X" in line or "ABS_X" in line:
            parts = line.split(",")
            for p in parts:
                p = p.strip()
                if p.startswith("max "):
                    try:
                        val = int(p.split()[-1])
                        if val > max_abs_x:
                            max_abs_x = val
                    except ValueError:
                        pass
        elif "ABS_MT_POSITION_Y" in line or "ABS_Y" in line:
            parts = line.split(",")
            for p in parts:
                p = p.strip()
                if p.startswith("max "):
                    try:
                        val = int(p.split()[-1])
                        if val > max_abs_y:
                            max_abs_y = val
                    except ValueError:
                        pass

    # 2.5 Find the device that supports POWER (116) / VOLUME (114/115) keys
    for line in lines:
        line = line.strip()
        if line.startswith("add device"):
            current_dev = line.split(":", 1)[1].strip()
            current_name = ""
        elif line.startswith("name:"):
            current_name = line.split(":", 1)[1].strip().strip('"')
        elif line.startswith("events:"):
            m = re.search(r"EV_KEY\s*\(0001\):\s*(.*)", line)
            if m and current_dev:
                key_codes = [int(k, 16) for k in m.group(1).split()]
                has_power = 116 in key_codes
                has_vol_down = 114 in key_codes
                has_vol_up = 115 in key_codes
                if has_power or has_vol_down:
                    best_key_dev = current_dev
                    best_key_name = current_name
                    print(f"[detect_sendevent] found hardware keys device: {best_key_dev} ({best_key_name}) — power={has_power}, vol_down={has_vol_down}, vol_up={has_vol_up}")

    # 3. Get screen resolution as fallback for max x/y
    try:
        proc2 = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                "adb", *(adb_prefix + ("shell", "wm", "size")),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            ),
            timeout=3.0,
        )
        stdout2, _ = await asyncio.wait_for(proc2.communicate(), timeout=3.0)
        size_str = stdout2.decode("utf-8", errors="replace").strip()
        m = re.search(r"(\d+)\s*[×x]\s*(\d+)", size_str)
        if m:
            _device_max_x = int(m.group(1))
            _device_max_y = int(m.group(2))
    except Exception:
        pass

    if best_key_dev:
        _device_key_event = best_key_dev
        print(f"[detect_sendevent] using hardware keys device: {best_key_dev} ({best_key_name})")

    if max_abs_x > 0:
        _device_max_x = max_abs_x
    if max_abs_y > 0:
        _device_max_y = max_abs_y

    if _device_touch_event:
        _sendevent_available = True
        print(f"[detect_sendevent] OK — touch={_device_touch_event}, key={_device_key_event}, max={_device_max_x}x{_device_max_y}")
        return True

    _sendevent_available = False
    print(f"[detect_sendevent] FAILED — no touch device found. touch={_device_touch_event}, key={_device_key_event}")
    return False


def get_sendevent_device_info() -> dict:
    """Return cached sendevent device info (for external readers)."""
    return {
        "available": _sendevent_available,
        "touch_event": _device_touch_event,
        "key_event": _device_key_event,
        "max_x": _device_max_x,
        "max_y": _device_max_y,
    }


# ── Low-level sendevent primitives ──────────────────────────────────

async def _send_event_cmd(serial: str | None, dev: str, ev_type: int, ev_code: int, ev_value: int):
    """Inject a single input event via /dev/input/eventN — no root needed if in input group."""
    adb_prefix = ("-s", serial) if serial else ()
    cmd = f"sendevent {dev} {ev_type} {ev_code} {ev_value}"
    print(f"[sendevent] adb shell {cmd}")
    await run_adb(*(adb_prefix + ("shell", cmd)), timeout=3.0)


async def sendevent_key(serial: str | None, android_keycode: str):
    """Inject a key event using sendevent (press + release)."""
    dev = _device_key_event or _device_touch_event
    if not dev:
        raise RuntimeError("No input device found for sendevent")

    linux_code = KEYCODE_TO_LINUX.get(android_keycode, 102)  # default HOME
    print(f"[sendevent_key] android_keycode={android_keycode} → linux_code={linux_code}, dev={dev}")

    await _send_event_cmd(serial, dev, 1, linux_code, 1)   # down
    await _send_event_cmd(serial, dev, 0, 0, 0)
    await _send_event_cmd(serial, dev, 1, linux_code, 0)   # up
    await _send_event_cmd(serial, dev, 0, 0, 0)


async def sendevent_key_down(serial: str | None, android_keycode: str):
    """Press a key (down only). For multi-key combos."""
    dev = _device_key_event or _device_touch_event
    if not dev:
        raise RuntimeError("No input device found for sendevent")
    linux_code = KEYCODE_TO_LINUX.get(android_keycode, 102)
    await _send_event_cmd(serial, dev, 1, linux_code, 1)
    await _send_event_cmd(serial, dev, 0, 0, 0)


async def sendevent_key_up(serial: str | None, android_keycode: str):
    """Release a key (up only). For multi-key combos."""
    dev = _device_key_event or _device_touch_event
    if not dev:
        raise RuntimeError("No input device found for sendevent")
    linux_code = KEYCODE_TO_LINUX.get(android_keycode, 102)
    await _send_event_cmd(serial, dev, 1, linux_code, 0)
    await _send_event_cmd(serial, dev, 0, 0, 0)


async def sendevent_combo(serial: str | None, keys: list[str], hold_ms: int = 150):
    """Execute a simultaneous key combo via sendevent (press all, hold, release)."""
    if not keys:
        return

    if not await detect_sendevent(serial):
        raise RuntimeError("sendevent not available for combo")

    for key in keys:
        await sendevent_key_down(serial, key)

    await asyncio.sleep(hold_ms / 1000.0)

    for key in reversed(keys):
        await sendevent_key_up(serial, key)


async def sendevent_text_char(serial: str | None, ch: str):
    """Inject a single text character via sendevent."""
    if ch == " ":
        await sendevent_key(serial, "KEYCODE_SPACE")
    elif ch == "\n":
        await sendevent_key(serial, "KEYCODE_ENTER")
    else:
        upper_ch = ch.upper()
        keycode = f"KEYCODE_{upper_ch}"
        if keycode in KEYCODE_TO_LINUX:
            await sendevent_key(serial, keycode)
        else:
            await sendevent_key(serial, f"KEYCODE_{upper_ch}")


async def sendevent_tap(serial: str | None, x: int, y: int):
    """Inject a tap at (x, y) using sendevent to the touchscreen device."""
    dev = _device_touch_event
    if not dev:
        raise RuntimeError("No touchscreen device found for sendevent")

    abs_x = max(0, min(x, _device_max_x))
    abs_y = max(0, min(y, _device_max_y))

    await _send_event_cmd(serial, dev, 3, 57, 0)        # ABS_MT_TRACKING_ID
    await _send_event_cmd(serial, dev, 3, 53, abs_x)     # ABS_MT_POSITION_X
    await _send_event_cmd(serial, dev, 3, 54, abs_y)     # ABS_MT_POSITION_Y
    await _send_event_cmd(serial, dev, 1, 330, 1)        # BTN_TOUCH down
    await _send_event_cmd(serial, dev, 0, 0, 0)          # EV_SYN

    await _send_event_cmd(serial, dev, 3, 57, -1)       # ABS_MT_TRACKING_ID (end)
    await _send_event_cmd(serial, dev, 1, 330, 0)        # BTN_TOUCH up
    await _send_event_cmd(serial, dev, 0, 0, 0)          # EV_SYN
    await asyncio.sleep(0.03)


async def sendevent_long_press(serial: str | None, x: int, y: int, duration_ms: int = 500):
    """Inject a long press via sendevent — touch down, hold, touch up."""
    dev = _device_touch_event
    if not dev:
        raise RuntimeError("No touchscreen device found for sendevent")

    abs_x = max(0, min(x, _device_max_x))
    abs_y = max(0, min(y, _device_max_y))

    await _send_event_cmd(serial, dev, 3, 57, 0)        # ABS_MT_TRACKING_ID
    await _send_event_cmd(serial, dev, 3, 53, abs_x)
    await _send_event_cmd(serial, dev, 3, 54, abs_y)
    await _send_event_cmd(serial, dev, 1, 330, 1)        # BTN_TOUCH down
    await _send_event_cmd(serial, dev, 0, 0, 0)

    await asyncio.sleep(duration_ms / 1000)

    await _send_event_cmd(serial, dev, 3, 57, -1)
    await _send_event_cmd(serial, dev, 1, 330, 0)
    await _send_event_cmd(serial, dev, 0, 0, 0)
    await asyncio.sleep(0.03)


async def sendevent_swipe(serial: str | None, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300):
    """Inject a swipe gesture using sendevent with linear interpolation."""
    dev = _device_touch_event
    if not dev:
        raise RuntimeError("No touchscreen device found for sendevent")

    steps = max(5, duration_ms // 16)

    sx = max(0, min(x1, _device_max_x))
    sy = max(0, min(y1, _device_max_y))
    await _send_event_cmd(serial, dev, 3, 57, 0)
    await _send_event_cmd(serial, dev, 3, 53, sx)
    await _send_event_cmd(serial, dev, 3, 54, sy)
    await _send_event_cmd(serial, dev, 1, 330, 1)
    await _send_event_cmd(serial, dev, 0, 0, 0)

    for i in range(1, steps + 1):
        t = i / steps
        cx = max(0, min(int(x1 + (x2 - x1) * t), _device_max_x))
        cy = max(0, min(int(y1 + (y2 - y1) * t), _device_max_y))
        await _send_event_cmd(serial, dev, 3, 53, cx)
        await _send_event_cmd(serial, dev, 3, 54, cy)
        await _send_event_cmd(serial, dev, 0, 0, 0)
        if i < steps:
            await asyncio.sleep(duration_ms / 1000 / steps)

    await _send_event_cmd(serial, dev, 3, 57, -1)
    await _send_event_cmd(serial, dev, 1, 330, 0)
    await _send_event_cmd(serial, dev, 0, 0, 0)
    await asyncio.sleep(0.03)


# ── High-level input dispatcher ─────────────────────────────────────

async def run_adb_input(serial: str | None, *input_args, timeout: float = 5.0) -> str:
    """
    Run an 'adb shell input <args>' command.
    Falls back to sendevent (no root needed) if INJECT_EVENTS permission is denied.
    """
    adb_prefix = ("-s", serial) if serial else ()

    # Strategy 1: Direct call
    try:
        return await run_adb(*(adb_prefix + ("shell", "input") + input_args), timeout=timeout)
    except RuntimeError as e:
        err_str = str(e)
        if "INJECT_EVENTS" not in err_str and "SecurityException" not in err_str:
            raise

    # Strategy 2: Try granting INJECT_EVENTS permission, then retry
    if not _inject_perms_granted:
        granted = await _try_grant_inject_permission(serial)
        if granted:
            try:
                return await run_adb(*(adb_prefix + ("shell", "input") + input_args), timeout=timeout)
            except RuntimeError as e:
                err_str = str(e)
                if "INJECT_EVENTS" not in err_str and "SecurityException" not in err_str:
                    raise

    # Strategy 3: Fallback to sendevent
    sendevent_ok = await detect_sendevent(serial)
    if sendevent_ok:
        if input_args[0] == "keyevent":
            await sendevent_key(serial, input_args[1])
            return ""
        elif input_args[0] == "text":
            for ch in input_args[1]:
                await sendevent_text_char(serial, ch)
                await asyncio.sleep(0.02)
            return ""
        elif input_args[0] == "tap":
            x, y = int(input_args[1]), int(input_args[2])
            await sendevent_tap(serial, x, y)
            return ""
        elif input_args[0] == "swipe":
            x1, y1, x2, y2 = int(input_args[1]), int(input_args[2]), int(input_args[3]), int(input_args[4])
            duration_ms = int(input_args[5]) if len(input_args) > 5 else 300
            if abs(x1 - x2) <= 1 and abs(y1 - y2) <= 1 and duration_ms > 100:
                await sendevent_long_press(serial, x1, y1, duration_ms)
            else:
                await sendevent_swipe(serial, x1, y1, x2, y2, duration_ms)
            return ""

    raise RuntimeError(
        f"INJECT_EVENTS permission denied. This device does not allow ADB input injection.\n"
        f"Try: 1) Enable 'USB debugging (Security Settings)' in Developer Options\n"
        f"     2) Settings → Developer options → Allow screen overlays on settings"
    )
