"""
Script Executor — walks through actions of a script and executes them.
Supports both real (ADB/uiautomator2) and mock mode for Termux dev.
"""
import asyncio
import json
import os
import time
import re
import tempfile
from typing import Callable, Optional

# OpenCV — optional, used for template matching on screenshots
try:
    import cv2
    import numpy as np
    _OPENCV_AVAILABLE = True
except ImportError:
    _OPENCV_AVAILABLE = False

# ---- ADB Helper utilities ----

# Combo action → ADB keyevent sequences
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


# Cached device capabilities
_inject_perms_granted: bool = False
# sendevent device paths (cached after first detection)
_device_touch_event: str | None = None   # e.g. /dev/input/event2
_device_key_event: str | None = None     # e.g. /dev/input/event0
_device_max_x: int = 1080
_device_max_y: int = 1920
_sendevent_available: bool | None = None

# Android keycode → Linux input event key code mapping (for sendevent fallback)
_KEYCODE_TO_LINUX = {
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

async def _detect_sendevent(serial: str | None = None) -> bool:
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
        print(f"[_detect_sendevent] getevent -p raw output ({len(out)} bytes):")
        # Print first 2000 chars for debugging
        print(out[:2000])
    except Exception as e:
        print(f"[_detect_sendevent] getevent -p failed: {e}")
        _sendevent_available = False
        return False

    # 2. Parse: find touchscreen and keyboard devices
    lines = out.split("\n")
    current_dev = None
    current_name = ""
    current_keys = {}
    max_abs_x = 0
    max_abs_y = 0

    # Device candidates
    best_key_dev = None          # device that supports POWER/VOLUME keys
    best_key_name = ""

    for i, line in enumerate(lines):
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
    # Hardware keys often use gpio-keys, not the main keyboard/touch input
    for i, line in enumerate(lines):
        line = line.strip()
        if line.startswith("add device"):
            current_dev = line.split(":", 1)[1].strip()
            current_name = ""
        elif line.startswith("name:"):
            current_name = line.split(":", 1)[1].strip().strip('"')
        elif line.startswith("events:"):
            # events: EV_KEY (0001): 0001 0002 ... 0072 0073 ... etc.
            # Keys are space-separated hex codes after "EV_KEY (0001):"
            m = re.search(r"EV_KEY\s*\(0001\):\s*(.*)", line)
            if m and current_dev:
                key_codes = [int(k, 16) for k in m.group(1).split()]
                has_power = 116 in key_codes
                has_vol_down = 114 in key_codes
                has_vol_up = 115 in key_codes
                if has_power or has_vol_down:
                    best_key_dev = current_dev
                    best_key_name = current_name
                    print(f"[_detect_sendevent] found hardware keys device: {best_key_dev} ({best_key_name}) — power={has_power}, vol_down={has_vol_down}, vol_up={has_vol_up}")

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

    # If we found a dedicated hardware keys device (gpio-keys), prefer it for key events
    if best_key_dev:
        _device_key_event = best_key_dev
        print(f"[_detect_sendevent] using hardware keys device: {best_key_dev} ({best_key_name})")

    if max_abs_x > 0:
        _device_max_x = max_abs_x
    if max_abs_y > 0:
        _device_max_y = max_abs_y

    # sendevent is available if we found at least a touch device
    if _device_touch_event:
        _sendevent_available = True
        print(f"[_detect_sendevent] OK — touch={_device_touch_event}, key={_device_key_event}, max={_device_max_x}x{_device_max_y}")
        return True

    _sendevent_available = False
    print(f"[_detect_sendevent] FAILED — no touch device found. touch={_device_touch_event}, key={_device_key_event}")
    return False

async def _run_adb(*args, timeout: float = 5.0) -> str:
    """Run ADB command asynchronously, return stdout. Raises RuntimeError on failure."""
    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                "adb", *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            ),
            timeout=timeout,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode != 0:
            err_msg = stderr.decode("utf-8", errors="replace").strip()
            if not err_msg:
                err_msg = stdout.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"ADB exit {proc.returncode}: {err_msg}")
        return stdout.decode("utf-8", errors="replace").strip()
    except asyncio.TimeoutError:
        raise RuntimeError(f"ADB timeout after {timeout}s: adb {' '.join(args)}")
    except (FileNotFoundError, OSError) as e:
        raise RuntimeError(f"ADB not found: {e}")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"ADB unexpected error: {e}")

async def _send_event_cmd(serial: str | None, dev: str, ev_type: int, ev_code: int, ev_value: int):
    """Inject a single input event via /dev/input/eventN — no root needed if in input group."""
    adb_prefix = ("-s", serial) if serial else ()
    cmd = f"sendevent {dev} {ev_type} {ev_code} {ev_value}"
    print(f"[sendevent] adb shell {cmd}")
    await _run_adb(*(adb_prefix + ("shell", cmd)), timeout=3.0)

async def _sendevent_key(serial: str | None, android_keycode: str):
    """
    Inject a key event using sendevent (press + release).
    Falls back to KEYCODE_HOME if unknown.
    """
    dev = _device_key_event or _device_touch_event
    if not dev:
        raise RuntimeError("No input device found for sendevent")

    linux_code = _KEYCODE_TO_LINUX.get(android_keycode, 102)  # default HOME
    print(f"[sendevent_key] android_keycode={android_keycode} → linux_code={linux_code}, dev={dev}")

    # Key down
    await _send_event_cmd(serial, dev, 1, linux_code, 1)   # EV_KEY = 1, value=1 (down)
    await _send_event_cmd(serial, dev, 0, 0, 0)             # EV_SYN = 0
    # Key up
    await _send_event_cmd(serial, dev, 1, linux_code, 0)   # EV_KEY = 1, value=0 (up)
    await _send_event_cmd(serial, dev, 0, 0, 0)             # EV_SYN = 0

async def _sendevent_key_down(serial: str | None, android_keycode: str):
    """Press a key (down only, no release). For multi-key combos."""
    dev = _device_key_event or _device_touch_event
    if not dev:
        raise RuntimeError("No input device found for sendevent")
    linux_code = _KEYCODE_TO_LINUX.get(android_keycode, 102)
    print(f"[sendevent_key_down] {android_keycode} → linux={linux_code}, dev={dev}")
    await _send_event_cmd(serial, dev, 1, linux_code, 1)   # EV_KEY down
    await _send_event_cmd(serial, dev, 0, 0, 0)             # EV_SYN

async def _sendevent_key_up(serial: str | None, android_keycode: str):
    """Release a key (up only). For multi-key combos."""
    dev = _device_key_event or _device_touch_event
    if not dev:
        raise RuntimeError("No input device found for sendevent")
    linux_code = _KEYCODE_TO_LINUX.get(android_keycode, 102)
    print(f"[sendevent_key_up] {android_keycode} → linux={linux_code}, dev={dev}")
    await _send_event_cmd(serial, dev, 1, linux_code, 0)   # EV_KEY up
    await _send_event_cmd(serial, dev, 0, 0, 0)             # EV_SYN

async def _sendevent_combo(serial: str | None, keys: list[str], hold_ms: int = 150):
    """
    Execute a simultaneous key combo via sendevent.
    Presses all keys together, holds, then releases all.
    This is needed because ADB's `input keyevent` only supports
    press-and-release per key, not holding multiple keys at once.
    """
    if not keys:
        return

    # Ensure sendevent is detected
    if not await _detect_sendevent(serial):
        raise RuntimeError("sendevent not available for combo")

    # Press all keys
    for key in keys:
        await _sendevent_key_down(serial, key)

    # Hold
    await asyncio.sleep(hold_ms / 1000.0)

    # Release all keys (reverse order)
    for key in reversed(keys):
        await _sendevent_key_up(serial, key)

async def _sendevent_text_char(serial: str | None, ch: str):
    """Inject a single text character via sendevent (simplified — uses keyevent)."""
    if ch == " ":
        await _sendevent_key(serial, "KEYCODE_SPACE")
    elif ch == "\n":
        await _sendevent_key(serial, "KEYCODE_ENTER")
    else:
        upper_ch = ch.upper()
        keycode = f"KEYCODE_{upper_ch}"
        if keycode in _KEYCODE_TO_LINUX:
            # TODO: handle shift for lowercase — for now just send uppercase keyevent
            await _sendevent_key(serial, keycode)
            # For lowercase, ADB input text handles this; sendevent needs manual shift handling
        else:
            # Try sending as-is via KEYCODE_ prefix
            await _sendevent_key(serial, f"KEYCODE_{upper_ch}")

async def _sendevent_tap(serial: str | None, x: int, y: int):
    """
    Inject a tap at (x, y) using sendevent to the touchscreen device.
    Converts screen coordinates to absolute touch coordinates.
    """
    dev = _device_touch_event
    if not dev:
        raise RuntimeError("No touchscreen device found for sendevent")

    # Scale coordinates to device max range
    # Most touchscreens use 0..max range; some use different ranges. We use detected max.
    abs_x = max(0, min(x, _device_max_x))
    abs_y = max(0, min(y, _device_max_y))

    # Touch down sequence:
    # ABS_MT_TRACKING_ID = 57 (start tracking)
    # ABS_MT_POSITION_X = 53, ABS_MT_POSITION_Y = 54
    # BTN_TOUCH = 330
    await _send_event_cmd(serial, dev, 3, 57, 0)        # ABS_MT_TRACKING_ID
    await _send_event_cmd(serial, dev, 3, 53, abs_x)     # ABS_MT_POSITION_X
    await _send_event_cmd(serial, dev, 3, 54, abs_y)     # ABS_MT_POSITION_Y
    await _send_event_cmd(serial, dev, 1, 330, 1)        # BTN_TOUCH down
    await _send_event_cmd(serial, dev, 0, 0, 0)          # EV_SYN

    # Touch up sequence:
    await _send_event_cmd(serial, dev, 3, 57, -1)       # ABS_MT_TRACKING_ID (end)
    await _send_event_cmd(serial, dev, 1, 330, 0)        # BTN_TOUCH up
    await _send_event_cmd(serial, dev, 0, 0, 0)          # EV_SYN
    await asyncio.sleep(0.03)

async def _sendevent_swipe(serial: str | None, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300):
    """
    Inject a swipe gesture using sendevent with linear interpolation.
    """
    dev = _device_touch_event
    if not dev:
        raise RuntimeError("No touchscreen device found for sendevent")

    # Number of interpolation steps
    steps = max(5, duration_ms // 16)  # ~60fps touch sampling

    # Touch down at start position
    sx = max(0, min(x1, _device_max_x))
    sy = max(0, min(y1, _device_max_y))
    await _send_event_cmd(serial, dev, 3, 57, 0)        # ABS_MT_TRACKING_ID
    await _send_event_cmd(serial, dev, 3, 53, sx)        # ABS_MT_POSITION_X
    await _send_event_cmd(serial, dev, 3, 54, sy)        # ABS_MT_POSITION_Y
    await _send_event_cmd(serial, dev, 1, 330, 1)        # BTN_TOUCH down
    await _send_event_cmd(serial, dev, 0, 0, 0)          # EV_SYN

    # Interpolate positions
    for i in range(1, steps + 1):
        t = i / steps
        cx = max(0, min(int(x1 + (x2 - x1) * t), _device_max_x))
        cy = max(0, min(int(y1 + (y2 - y1) * t), _device_max_y))
        await _send_event_cmd(serial, dev, 3, 53, cx)    # ABS_MT_POSITION_X
        await _send_event_cmd(serial, dev, 3, 54, cy)    # ABS_MT_POSITION_Y
        await _send_event_cmd(serial, dev, 0, 0, 0)      # EV_SYN
        if i < steps:
            await asyncio.sleep(duration_ms / 1000 / steps)

    # Touch up
    await _send_event_cmd(serial, dev, 3, 57, -1)       # ABS_MT_TRACKING_ID (end)
    await _send_event_cmd(serial, dev, 1, 330, 0)        # BTN_TOUCH up
    await _send_event_cmd(serial, dev, 0, 0, 0)          # EV_SYN
    await asyncio.sleep(0.03)

async def _run_adb_input(serial: str | None, *input_args, timeout: float = 5.0) -> str:
    """
    Run an 'adb shell input <args>' command.
    Falls back to sendevent (no root needed) if INJECT_EVENTS permission is denied.
    
    Args:
        serial: ADB device serial (or None for default device)
        *input_args: Arguments to the `input` subcommand (e.g. "tap", "100", "200")
    """
    # Build ADB prefix args
    adb_prefix = ("-s", serial) if serial else ()

    # Strategy 1: Direct call
    try:
        return await _run_adb(*(adb_prefix + ("shell", "input") + input_args), timeout=timeout)
    except RuntimeError as e:
        err_str = str(e)
        if "INJECT_EVENTS" not in err_str and "SecurityException" not in err_str:
            raise

    # Strategy 2: Try granting INJECT_EVENTS permission, then retry direct call
    if not _inject_perms_granted:
        granted = await _try_grant_inject_permission(serial)
        if granted:
            try:
                return await _run_adb(*(adb_prefix + ("shell", "input") + input_args), timeout=timeout)
            except RuntimeError as e:
                err_str = str(e)
                if "INJECT_EVENTS" not in err_str and "SecurityException" not in err_str:
                    raise

    # Strategy 3: Fallback to sendevent (no root needed — works via input group)
    sendevent_ok = await _detect_sendevent(serial)
    if sendevent_ok:
        if input_args[0] == "keyevent":
            keycode = input_args[1]
            await _sendevent_key(serial, keycode)
            return ""
        elif input_args[0] == "text":
            text = input_args[1]
            for ch in text:
                await _sendevent_text_char(serial, ch)
                await asyncio.sleep(0.02)
            return ""
        elif input_args[0] == "tap":
            x, y = int(input_args[1]), int(input_args[2])
            await _sendevent_tap(serial, x, y)
            return ""
        elif input_args[0] == "swipe":
            x1, y1, x2, y2 = int(input_args[1]), int(input_args[2]), int(input_args[3]), int(input_args[4])
            duration_ms = int(input_args[5]) if len(input_args) > 5 else 300
            await _sendevent_swipe(serial, x1, y1, x2, y2, duration_ms)
            return ""

    # Strategy 4: Give up with helpful error
    raise RuntimeError(
        f"INJECT_EVENTS permission denied. This device does not allow ADB input injection.\n"
        f"Try: 1) Enable 'USB debugging (Security Settings)' in Developer Options\n"
        f"     2) Settings → Developer options → Allow screen overlays on settings"
    )


async def adb_available() -> bool:
    """Check if ADB is available and a device is connected."""
    try:
        out = await _run_adb("devices", timeout=3.0)
    except RuntimeError:
        return False
    lines = out.strip().split("\n")
    for line in lines[1:]:
        if "\tdevice" in line:
            return True
    return False


class ScriptExecutor:
    """
    Executes a script's actions in order.
    
    Action types supported:
    - tap: tap at (x, y), optionally using previous match result
    - swipe: swipe from (x,y) to (x2,y2)
    - long_press: long press at (x,y) for duration_ms
    - screenshot_match: match template on screen with retry + jump
    - wait: wait for wait_ms
    - push_key: press Android key
    - combo: perform key combo (select all, copy, paste, etc.)
    - fetch_api: HTTP call + save response to variable
    - variable: set/update/get variable
    - type_text: simulate keyboard typing character by character
    - jump: jump to another action by name
    - stop: stop script execution immediately
    - if: conditional branching (eq, ne, gt, lt, contains, etc.)
    - orientation: change device orientation (portrait/landscape/auto)
    - launch_app: launch an Android app by package name
    - kill_app: force-stop an Android app by package name
    """

    def __init__(self, mock_mode: bool = True):
        self.mock_mode = mock_mode
        self.variables: dict[str, str] = {}
        self.last_match_result: tuple[float, float] | None = None
        self.log_callback: Optional[Callable] = None
        self._stop_requested = False
        self._current_action_idx = 0
        self._serial: str | None = None  # ADB device serial

    async def _init_serial(self):
        """Discover and cache the ADB device serial."""
        if self._serial:
            return
        try:
            out = await _run_adb("devices")
            lines = out.strip().split("\n")
            for line in lines[1:]:
                if "\tdevice" in line:
                    self._serial = line.split("\t")[0]
                    break
        except RuntimeError:
            pass

    def _adb_args(self, *args) -> tuple:
        """Build ADB args with serial if known."""
        if self._serial:
            return ("-s", self._serial) + args
        return args

    def stop(self):
        """Request execution to stop after current action."""
        self._stop_requested = True

    def _log(self, level: str, message: str):
        if self.log_callback:
            self.log_callback(level, message)

    def _resolve_value(self, text: str) -> str:
        """Replace ${var.path.to.field} placeholders with variable values, supporting nested JSON access."""
        def _resolve_single(match):
            full_path = match.group(1)  # e.g. "randomuser.0.gender"
            parts = full_path.split(".")
            var_name = parts[0]          # "randomuser"
            access_path = parts[1:]      # ["0", "gender"]

            value = self.variables.get(var_name)
            if value is None:
                return match.group(0)  # keep original if variable not found

            # No sub-path → return raw value
            if not access_path:
                return str(value)

            # Try parsing JSON if it looks like JSON
            if isinstance(value, str) and value.strip().startswith(("{", "[")):
                try:
                    value = json.loads(value)
                except (json.JSONDecodeError, ValueError):
                    pass

            # Traverse into nested value
            for key in access_path:
                # Try numeric index for lists
                if isinstance(value, list):
                    try:
                        idx = int(key)
                        value = value[idx]
                        continue
                    except (ValueError, IndexError):
                        pass
                # Try dict key
                if isinstance(value, dict):
                    if key in value:
                        value = value[key]
                        continue
                    # also try numeric key (for numeric-like strings stored in dict)
                    try:
                        idx = int(key)
                        if idx in value:
                            value = value[idx]
                            continue
                    except (ValueError, TypeError):
                        pass
                # Can't traverse further
                return match.group(0)

            return str(value)

        return re.sub(r"\$\{([a-zA-Z_]\w*(?:\.[^.}]+)*)\}", _resolve_single, text)

    # ---- Android input (real via ADB, or mock) ----

    async def _tap(self, x: float, y: float):
        if self.mock_mode:
            self._log("info", f"  [mock] tap({x:.0f}, {y:.0f})")
            await asyncio.sleep(0.1)
        else:
            self._log("info", f"  👆 tap({x:.0f}, {y:.0f})")
            await _run_adb_input(self._serial, "tap", str(int(x)), str(int(y)))
            await asyncio.sleep(0.05)

    async def _swipe(self, x1, y1, x2, y2, duration_ms):
        if self.mock_mode:
            self._log("info", f"  [mock] swipe({x1:.0f},{y1:.0f} → {x2:.0f},{y2:.0f}) {duration_ms}ms")
            await asyncio.sleep(duration_ms / 1000 * 0.1)
        else:
            self._log("info", f"  👆 swipe({x1:.0f},{y1:.0f} → {x2:.0f},{y2:.0f}) {duration_ms}ms")
            await _run_adb_input(self._serial, "swipe",
                str(int(x1)), str(int(y1)), str(int(x2)), str(int(y2)), str(int(duration_ms)))
            await asyncio.sleep(duration_ms / 1000)

    async def _long_press(self, x, y, duration_ms):
        if self.mock_mode:
            self._log("info", f"  [mock] long_press({x:.0f}, {y:.0f}) {duration_ms}ms")
            await asyncio.sleep(duration_ms / 1000 * 0.1)
        else:
            self._log("info", f"  👆 long_press({x:.0f}, {y:.0f}) {duration_ms}ms")
            # Swipe from point to same point = long press
            await _run_adb_input(self._serial, "swipe",
                str(int(x)), str(int(y)), str(int(x)), str(int(y)), str(int(duration_ms)))
            await asyncio.sleep(duration_ms / 1000)

    async def _push_key(self, key_code: str):
        # Resolve keycode to canonical form
        if key_code.startswith("KEYCODE_"):
            resolved = key_code
        elif key_code.isdigit():
            # Numeric key code — pass directly to input keyevent (e.g. "66" = ENTER)
            resolved = key_code
        else:
            resolved = KEY_NAME_MAP.get(key_code.upper(), f"KEYCODE_{key_code.upper()}")
        if self.mock_mode:
            self._log("info", f"  [mock] keyevent {resolved}")
            await asyncio.sleep(0.05)
        else:
            self._log("info", f"  ⌨️  keyevent {resolved}")
            await _run_adb_input(self._serial, "keyevent", resolved)
            await asyncio.sleep(0.05)

    async def _combo_action(self, action: str):
        # Lookup combo keys
        keys = COMBO_KEYS.get(action, [f"KEYCODE_{action.upper()}"])
        if self.mock_mode:
            self._log("info", f"  [mock] combo: {action} → {keys}")
            await asyncio.sleep(0.1)
        else:
            self._log("info", f"  ⌨️  combo: {action} → {keys}")
            # For single-key combos (back, home, etc.), send normally
            if len(keys) == 1:
                await _run_adb_input(self._serial, "keyevent", keys[0])
                await asyncio.sleep(0.05)
                return

            # --- Multi-key combo ---
            # Strategy 1: `input keycombination` (native Android 7.0+, handles Ctrl+A etc.)
            try:
                adb_prefix = ("-s", self._serial) if self._serial else ()
                await _run_adb(*(adb_prefix + ("shell", "input", "keycombination") + tuple(keys)),
                              timeout=5.0)
                await asyncio.sleep(0.05)
                return
            except RuntimeError as e:
                self._log("warn", f"  keycombination failed: {e}")

            # Strategy 2: sendevent for hardware combos (volume+power etc.)
            #             Filters to keys that have a linux code mapping
            hw_keys = [k for k in keys if k in _KEYCODE_TO_LINUX]
            if hw_keys and len(hw_keys) == len(keys):
                try:
                    await _sendevent_combo(self._serial, hw_keys, hold_ms=500)
                    await asyncio.sleep(0.05)
                    return
                except RuntimeError as e:
                    self._log("warn", f"  sendevent failed: {e}")

            # Strategy 3: Last resort — sequential keyevents (won't hold keys but won't crash)
            self._log("warn", f"  ⚠️  falling back to sequential keyevents (combo may not work)")
            for i, key in enumerate(keys):
                await _run_adb_input(self._serial, "keyevent", key)
                if i < len(keys) - 1:
                    await asyncio.sleep(0.03)
            await asyncio.sleep(0.05)

    async def _capture_screenshot(self, save_path: str | None = None) -> str:
        """Capture a screenshot via ADB and return the local file path."""
        tmp_path = save_path or os.path.join(tempfile.gettempdir(), f"angulo_screen_{time.time():.0f}.png")
        if self.mock_mode:
            # In mock mode, create a dummy black image
            if _OPENCV_AVAILABLE:
                img = np.zeros((1920, 1080, 3), dtype=np.uint8)
                cv2.imwrite(tmp_path, img)
            else:
                # Create a minimal valid PNG
                import struct, zlib
                def _make_minimal_png(path):
                    sig = b'\x89PNG\r\n\x1a\n'
                    ihdr_data = struct.pack('>IIBBBBB', 1080, 1920, 8, 2, 0, 0, 0)
                    ihdr_crc = zlib.crc32(b'IHDR' + ihdr_data)
                    ihdr_chunk = struct.pack('>I', 13) + b'IHDR' + ihdr_data + struct.pack('>I', ihdr_crc)
                    # black IDAT
                    raw = b'\x00' * (1080 * 3)
                    compressed = zlib.compress(b''.join([raw] * 1920))
                    idat_crc = zlib.crc32(b'IDAT' + compressed)
                    idat_chunk = struct.pack('>I', len(compressed)) + b'IDAT' + compressed + struct.pack('>I', idat_crc)
                    iend_crc = zlib.crc32(b'IEND')
                    iend_chunk = struct.pack('>I', 0) + b'IEND' + struct.pack('>I', iend_crc)
                    with open(path, 'wb') as f:
                        f.write(sig + ihdr_chunk + idat_chunk + iend_chunk)
                _make_minimal_png(tmp_path)
            return tmp_path
        # Real mode: adb shell screencap
        adb_prefix = ("-s", self._serial) if self._serial else ()
        try:
            await _run_adb(*(adb_prefix + ("shell", "screencap", "-p", "/sdcard/angulo_tmp.png")), timeout=10.0)
            await _run_adb(*(adb_prefix + ("pull", "/sdcard/angulo_tmp.png", tmp_path)), timeout=10.0)
            # Cleanup remote temp
            try:
                await _run_adb(*(adb_prefix + ("shell", "rm", "/sdcard/angulo_tmp.png")), timeout=3.0)
            except Exception:
                pass
        except RuntimeError as e:
            raise RuntimeError(f"Failed to capture screenshot: {e}")
        return tmp_path

    async def _match_template_on_screen(self, template_path: str, threshold: float,
                                          region: tuple = None) -> tuple:
        """
        Match a template image against current screen.
        Returns (found: bool, x: float, y: float).
        x, y are the center coordinates of the match (in full-screen coords).

        If region=(rx, ry, rw, rh) is provided, only search that crop area.
        Returned coordinates are relative to the full screen, not the crop.
        """
        if not _OPENCV_AVAILABLE:
            self._log("warn", "  ⚠️ OpenCV not installed, cannot do real template matching. Install: pip install opencv-python numpy")
            if self.mock_mode:
                return (True, 540.0, 1200.0)
            return (False, 0, 0)

        # Resolve template file path
        template_full_path = template_path
        if not os.path.isabs(template_path):
            # template_path is like "templates/filename.png" — resolve from data/
            template_full_path = os.path.join("data", template_path)
        if not os.path.isfile(template_full_path):
            raise RuntimeError(f"Template file not found: {template_full_path}")

        # Capture screenshot
        screen_path = await self._capture_screenshot()

        try:
            # Read images
            screen = cv2.imread(screen_path)
            template = cv2.imread(template_full_path)

            if screen is None:
                raise RuntimeError(f"Failed to read screenshot from {screen_path}")
            if template is None:
                raise RuntimeError(f"Failed to read template from {template_full_path}")

            th, tw = template.shape[:2]
            sh, sw = screen.shape[:2]

            # Apply region crop if specified
            region_offset_x, region_offset_y = 0, 0
            if region is not None:
                rx, ry, rw, rh = region
                # Clamp to screen bounds
                rx = max(0, int(rx))
                ry = max(0, int(ry))
                rw = min(int(rw), sw - rx)
                rh = min(int(rh), sh - ry)
                if rw <= 0 or rh <= 0:
                    raise RuntimeError(f"Invalid match region: ({rx},{ry},{rw},{rh}) — not within screen {sw}x{sh}")
                screen = screen[ry:ry+rh, rx:rx+rw]
                region_offset_x, region_offset_y = rx, ry
                sh, sw = screen.shape[:2]
                self._log("info", f"  🔲 match region: x={rx} y={ry} w={rw} h={rh} (screen {region_offset_x+sw}x{region_offset_y+sh})")

            if tw > sw or th > sh:
                raise RuntimeError(f"Template ({tw}x{th}) is larger than search area ({sw}x{sh})")

            # Template matching
            result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

            self._log("info", f"  📊 match score: {max_val:.4f} (threshold: {threshold:.2f})")

            if max_val >= threshold:
                # Center of match — add region offset so coords are full-screen
                cx = region_offset_x + max_loc[0] + tw / 2.0
                cy = region_offset_y + max_loc[1] + th / 2.0
                return (True, float(cx), float(cy))
            else:
                return (False, 0.0, 0.0)
        finally:
            # Clean up screenshot temp file
            try:
                os.unlink(screen_path)
            except Exception:
                pass

    async def _screenshot_match(self, template_path: str, threshold: float,
                                  retry_count: int, retry_delay_ms: int,
                                  region: tuple = None) -> tuple:
        """Try to find template on screen. Returns (success, x, y)."""
        for attempt in range(retry_count):
            if self._stop_requested:
                return (False, 0, 0)
            if self.mock_mode:
                self._log("info", f"  [mock] match attempt {attempt+1}/{retry_count}: template='{template_path}' th={threshold}")
                if _OPENCV_AVAILABLE:
                    # Try real matching even in mock mode (but with dummy screenshot)
                    found, mx, my = await self._match_template_on_screen(template_path, threshold, region)
                    if found:
                        self.last_match_result = (mx, my)
                        return (True, mx, my)
                else:
                    self.last_match_result = (540.0, 1200.0)
                    self._log("info", f"  [mock] → FOUND (simulated)")
                    return (True, 540.0, 1200.0)
            else:
                self._log("info", f"  🔍 match attempt {attempt+1}/{retry_count}: template='{template_path}' th={threshold}")
                found, mx, my = await self._match_template_on_screen(template_path, threshold, region)
                if found:
                    self.last_match_result = (mx, my)
                    self._log("info", f"  ✅ match found at ({mx:.0f}, {my:.0f})")
                    return (True, mx, my)

            if attempt < retry_count - 1:
                self._log("info", f"  ⏳ retry in {retry_delay_ms}ms...")
                await asyncio.sleep(retry_delay_ms / 1000)
        return (False, 0, 0)

    async def _resolve_coords_from_template(self, action: dict) -> tuple:
        """
        For tap/swipe/long_press actions that have template_path set,
        resolve X/Y coordinates by matching template on screen.
        Returns (x, y) or (x, y, x2, y2) for swipe with two templates.

        If no template_path is set, returns the raw coords from action.
        """
        tpl = action.get("template_path", "")
        if not tpl:
            # No template — use raw coordinates
            if action.get("action_type") == "swipe":
                return (action.get("x", 0), action.get("y", 0),
                        action.get("x2", 0), action.get("y2", 0))
            return (action.get("x", 0), action.get("y", 0))

        threshold = action.get("match_threshold", 0.80)
        retry = action.get("retry_count", 1)
        retry_delay = action.get("retry_delay_ms", 1000)

        if action.get("action_type") == "swipe":
            # Swipe: match start point from template
            found, x1, y1 = await self._screenshot_match(tpl, threshold, retry, retry_delay)
            if not found:
                raise RuntimeError(f"Template '{tpl}' not found on screen for swipe start point")
            # For end point, use explicit x2/y2 or also from a second template
            tpl2 = action.get("template_path2", "")
            if tpl2:
                found2, x2, y2 = await self._screenshot_match(tpl2, threshold, retry, retry_delay)
                if not found2:
                    raise RuntimeError(f"Template '{tpl2}' not found on screen for swipe end point")
            else:
                x2 = action.get("x2", 0) or x1
                y2 = action.get("y2", 0) or y1
            return (x1, y1, x2, y2)
        else:
            # Tap or long_press: single point
            found, x, y = await self._screenshot_match(tpl, threshold, retry, retry_delay)
            if not found:
                raise RuntimeError(f"Template '{tpl}' not found on screen for {action.get('action_type')}")
            return (x, y)

    async def _fetch_api(self, url: str, method: str, headers: str, body: str) -> str:
        import httpx
        resolved_url = self._resolve_value(url)
        try:
            headers_dict = json.loads(headers) if headers else {}
        except json.JSONDecodeError:
            headers_dict = {}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                if method in ("GET", "DELETE"):
                    resp = await client.request(method, resolved_url, headers=headers_dict)
                else:
                    resolved_body = self._resolve_value(body or "{}")
                    resp = await client.request(method, resolved_url, headers=headers_dict, content=resolved_body)
                return resp.text
        except Exception as e:
            self._log("error", f"  API call failed: {e}")
            return ""

    async def _type_text(self, text: str, speed_ms: int):
        resolved = self._resolve_value(text)
        if self.mock_mode:
            self._log("info", f"  [mock] type text ({len(resolved)} chars, {speed_ms}ms/char)")
            await asyncio.sleep(len(resolved) * speed_ms / 1000 * 0.05)
        else:
            self._log("info", f"  ⌨️  type text: {len(resolved)} chars @ {speed_ms}ms/char")
            # ADB input text handles most ASCII characters
            # For complex/special chars, fall back to per-character keyevent
            safe_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .,!?@#$%&*()-_=+[]{}|;:'\"/<>`~")
            if all(ch in safe_chars for ch in resolved):
                # Fast path: send whole text
                await _run_adb_input(self._serial, "text", resolved)
                await asyncio.sleep(speed_ms / 1000 * len(resolved))
            else:
                for ch in resolved:
                    if ch == " ":
                        await _run_adb_input(self._serial, "keyevent", "KEYCODE_SPACE")
                    elif ch == "\n":
                        await _run_adb_input(self._serial, "keyevent", "KEYCODE_ENTER")
                    elif ch.isascii() and ch.isprintable():
                        await _run_adb_input(self._serial, "text", ch)
                    else:
                        # Unicode: broadcast via am broadcast
                        self._log("warn", f"  skipping non-ASCII char: {ch}")
                    await asyncio.sleep(speed_ms / 1000)

    # ---- New action types: jump, stop/kill, if, orientation, launch_app, kill_app ----

    async def _jump_to_action(self, jump_to: str, actions: list) -> int | None:
        """Resolve jump_to (action name) to its index in actions list. Returns None if not found."""
        if not jump_to:
            return None
        for i, a in enumerate(actions):
            if a.get("name") == jump_to:
                self._log("info", f"  🔀 Jumping to [{jump_to}] (action #{i + 1})")
                return i
        self._log("error", f"  Jump target [{jump_to}] not found")
        return None

    async def _if_condition(self, action: dict) -> tuple:
        """
        Evaluate an IF condition.
        Returns (jump_to: str or None,  whether the condition was true or false)
        Jump target is resolved outside.
        """
        var_name = action.get("condition_var", "")
        op = action.get("condition_op", "eq")
        compare_val = self._resolve_value(action.get("condition_value", ""))

        actual_val = self.variables.get(var_name, "")
        actual_val = self._resolve_value(actual_val)

        self._log("info", f"  IF condition: ${var_name} ({actual_val}) {op} {compare_val}")

        result = False
        if op == "eq":
            result = str(actual_val) == str(compare_val)
        elif op == "ne":
            result = str(actual_val) != str(compare_val)
        elif op == "gt":
            try:
                result = float(actual_val) > float(compare_val)
            except (ValueError, TypeError):
                result = False
        elif op == "lt":
            try:
                result = float(actual_val) < float(compare_val)
            except (ValueError, TypeError):
                result = False
        elif op == "ge":
            try:
                result = float(actual_val) >= float(compare_val)
            except (ValueError, TypeError):
                result = False
        elif op == "le":
            try:
                result = float(actual_val) <= float(compare_val)
            except (ValueError, TypeError):
                result = False
        elif op == "contains":
            result = compare_val in str(actual_val)
        elif op == "not_contains":
            result = compare_val not in str(actual_val)
        elif op == "empty":
            result = actual_val == "" or actual_val is None
        elif op == "not_empty":
            result = actual_val != "" and actual_val is not None
        else:
            self._log("warn", f"  unknown condition operator: {op}, treating as false")

        self._log("info", f"  IF result: {result}")
        return (action.get("jump_on_true", "") if result else action.get("jump_on_false", ""), result)

    async def _orientation(self, orientation: str):
        """Set device orientation via ADB."""
        # Map orientation values to Android settings
        orient_map = {
            "auto": "0",      # auto-rotate on
            "portrait": "0",  # settings put system user_rotation 0
            "landscape": "1",
            "reverse_portrait": "2",
            "reverse_landscape": "3",
        }
        # For "auto" we enable accelerometer rotation
        if orientation == "auto":
            if self.mock_mode:
                self._log("info", f"  [mock] orientation → auto (accelerometer)")
            else:
                self._log("info", f"  📱 orientation → auto")
                adb_prefix = ("-s", self._serial) if self._serial else ()
                await _run_adb(*(adb_prefix + ("shell", "settings", "put", "system", "accelerometer_rotation", "1")),
                              timeout=5.0)
                return

        rot_val = orient_map.get(orientation, "0")
        if self.mock_mode:
            self._log("info", f"  [mock] orientation → {orientation} (rotation {rot_val})")
        else:
            self._log("info", f"  📱 orientation → {orientation}")
            adb_prefix = ("-s", self._serial) if self._serial else ()
            # First disable accelerometer rotation, then set user rotation
            await _run_adb(*(adb_prefix + ("shell", "settings", "put", "system", "accelerometer_rotation", "0")),
                          timeout=5.0)
            await _run_adb(*(adb_prefix + ("shell", "settings", "put", "system", "user_rotation", rot_val)),
                          timeout=5.0)

    async def _launch_app(self, package: str):
        """Launch an Android app by package name via ADB."""
        resolved = self._resolve_value(package)
        if self.mock_mode:
            self._log("info", f"  [mock] launch_app: {resolved}")
            await asyncio.sleep(0.3)
        else:
            self._log("info", f"  🚀 launch_app: {resolved}")
            adb_prefix = ("-s", self._serial) if self._serial else ()
            # Use monkey to launch the app
            await _run_adb(*(adb_prefix + ("shell", "monkey", "-p", resolved, "-c", "android.intent.category.LAUNCHER", "1")),
                          timeout=10.0)
            await asyncio.sleep(1.0)  # wait for app to start

    async def _kill_app(self, package: str):
        """Kill/force-stop an Android app by package name via ADB."""
        resolved = self._resolve_value(package)
        if self.mock_mode:
            self._log("info", f"  [mock] kill_app: {resolved}")
            await asyncio.sleep(0.2)
        else:
            self._log("info", f"  🔪 kill_app: {resolved}")
            adb_prefix = ("-s", self._serial) if self._serial else ()
            await _run_adb(*(adb_prefix + ("shell", "am", "force-stop", resolved)),
                          timeout=10.0)
            await asyncio.sleep(0.3)

    async def _resolve_jump(self, jump_to: str, actions: list) -> int | None:
        """Resolve a jump target name to action index. Shared helper for all action types."""
        if not jump_to:
            return None
        for i, a in enumerate(actions):
            if a.get("name") == jump_to:
                return i
        return None

    # ---- Main executor ----

    async def execute(self, script: dict, log_cb: Callable | None = None) -> dict:
        """
        Execute all actions in a script. Returns summary dict.
        """
        self.log_callback = log_cb
        self._stop_requested = False
        self.variables = {}
        self.last_match_result = None

        # Initialize serial for real mode
        if not self.mock_mode:
            await self._init_serial()

        actions = script.get("actions", [])
        repeat = script.get("repeat_count", 1)
        delay_between = script.get("delay_between_ms", 1000) / 1000
        total_in_run = len(actions) * repeat

        success_count = 0
        fail_count = 0
        start_time = time.time()

        mode_tag = "[MOCK]" if self.mock_mode else "[REAL]"
        self._log("info", f"▶️  Script \"{script['name']}\" started {mode_tag}")
        self._log("info", f"📋 Total actions: {len(actions)}, Repeat: {repeat}x")

        for rep in range(repeat):
            if self._stop_requested:
                self._log("error", "⏹️ Execution stopped by user")
                break

            if repeat > 1:
                self._log("info", f"─── Repeat {rep + 1}/{repeat} ───")

            idx = 0
            while idx < len(actions):
                if self._stop_requested:
                    break

                action = actions[idx]
                action_name = action.get("name", f"action_{idx}")
                action_type = action.get("action_type", "wait")

                self._current_action_idx = idx
                self._log("info", f"⚡ [#{idx + 1}] {action_type} [{action_name}] executing...")

                # Wait before
                wait_before = action.get("wait_before_ms", 500) / 1000
                if wait_before > 0:
                    await asyncio.sleep(wait_before)

                jump_to = None
                ok = True
                err_msg = ""

                try:
                    if action_type == "tap":
                        if action.get("use_match_result") and self.last_match_result:
                            await self._tap(*self.last_match_result)
                        elif action.get("template_path") and action.get("x") is None and action.get("y") is None:
                            # No explicit coords → auto-detect via template matching
                            coords = await self._resolve_coords_from_template(action)
                            await self._tap(coords[0], coords[1])
                        else:
                            await self._tap(action.get("x", 0), action.get("y", 0))

                    elif action_type == "swipe":
                        if action.get("template_path") and action.get("x") is None and action.get("y") is None:
                            # No explicit coords → auto-detect via template matching
                            coords = await self._resolve_coords_from_template(action)
                            await self._swipe(
                                coords[0], coords[1], coords[2], coords[3],
                                action.get("duration_ms", 300),
                            )
                        else:
                            await self._swipe(
                                action.get("x", 0), action.get("y", 0),
                                action.get("x2", 0), action.get("y2", 0),
                                action.get("duration_ms", 300),
                            )

                    elif action_type == "long_press":
                        if action.get("template_path") and action.get("x") is None and action.get("y") is None:
                            # No explicit coords → auto-detect via template matching
                            coords = await self._resolve_coords_from_template(action)
                            await self._long_press(coords[0], coords[1],
                                action.get("duration_ms", 500),
                            )
                        else:
                            await self._long_press(
                                action.get("x", 0), action.get("y", 0),
                                action.get("duration_ms", 500),
                            )

                    elif action_type == "screenshot_match":
                        # Build region tuple if match region is configured
                        match_region = None
                        rx = action.get("match_region_x")
                        ry = action.get("match_region_y")
                        rw = action.get("match_region_w")
                        rh = action.get("match_region_h")
                        if rx is not None and ry is not None and rw is not None and rh is not None:
                            match_region = (rx, ry, rw, rh)
                        found, mx, my = await self._screenshot_match(
                            action.get("template_path", ""),
                            action.get("match_threshold", 0.80),
                            action.get("retry_count", 1),
                            action.get("retry_delay_ms", 1000),
                            match_region,
                        )
                        if found:
                            jump_to = action.get("jump_on_success", "")
                        else:
                            ok = False
                            err_msg = "Template not found after retries"
                            jump_to = action.get("jump_on_fail", "")

                    elif action_type == "wait":
                        wait_ms = action.get("wait_ms", 1000)
                        self._log("info", f"  waiting {wait_ms}ms...")
                        await asyncio.sleep(wait_ms / 1000)

                    elif action_type == "push_key":
                        await self._push_key(action.get("key_code", "HOME"))

                    elif action_type == "combo":
                        await self._combo_action(action.get("combo_action", "select_all"))

                    elif action_type == "fetch_api":
                        result = await self._fetch_api(
                            action.get("api_url", ""),
                            action.get("api_method", "GET"),
                            action.get("api_headers", "{}"),
                            action.get("api_body", ""),
                        )
                        save_var = action.get("api_save_to_var", "")
                        if save_var:
                            self.variables[save_var] = result
                            self._log("info", f"  saved response to ${save_var} ({len(result)} bytes)")

                    elif action_type == "variable":
                        vname = action.get("var_name", "")
                        vop = action.get("var_operation", "set")
                        vval = self._resolve_value(action.get("var_value", ""))
                        if vop == "set":
                            self.variables[vname] = vval
                            self._log("info", f"  set ${vname} = {vval}")
                        elif vop == "update":
                            self.variables[vname] = vval
                            self._log("info", f"  update ${vname} = {vval}")
                        elif vop == "get":
                            val = self.variables.get(vname, "")
                            self._log("info", f"  get ${vname} = {val}")

                    elif action_type == "type_text":
                        await self._type_text(
                            action.get("text_content", ""),
                            action.get("text_speed_ms", 50),
                        )

                    # ---- New action types ----
                    elif action_type == "jump":
                        jump_to = action.get("jump_to", "")
                        if jump_to:
                            target_idx = await self._resolve_jump(jump_to, actions)
                            if target_idx is not None:
                                idx = target_idx
                                self._log("success", f"✅ [#{idx + 1}] {action_type} [{action_name}]: jumped to [{jump_to}]")
                                continue
                            else:
                                ok = False
                                err_msg = f"Jump target [{jump_to}] not found"
                        else:
                            self._log("warn", f"  jump action without target, skipping")

                    elif action_type == "stop":
                        self._log("info", f"  ⏹️ stop action: stopping execution")
                        self._stop_requested = True
                        ok = True  # stop is intentional, not a failure

                    elif action_type == "if":
                        jump_target, result = await self._if_condition(action)
                        self._log("info", f"  IF result: {result}, jump_to: {jump_target or '(none)'}")
                        if jump_target:
                            target_idx = await self._resolve_jump(jump_target, actions)
                            if target_idx is not None:
                                idx = target_idx
                                self._log("success", f"✅ [#{idx + 1}] {action_type} [{action_name}]: jumped to [{jump_target}]")
                                continue
                            else:
                                ok = False
                                err_msg = f"IF jump target [{jump_target}] not found"

                    elif action_type == "orientation":
                        await self._orientation(action.get("orientation_value", "auto"))

                    elif action_type == "launch_app":
                        await self._launch_app(action.get("app_package", ""))

                    elif action_type == "kill_app":
                        await self._kill_app(action.get("app_package", ""))

                    else:
                        self._log("warn", f"  unknown action type: {action_type}")

                except Exception as e:
                    ok = False
                    err_msg = str(e)

                # Wait after
                wait_after = action.get("wait_after_ms", 500) / 1000
                if wait_after > 0:
                    await asyncio.sleep(wait_after)

                if ok:
                    success_count += 1
                    self._log("success", f"✅ [#{idx + 1}] {action_type} [{action_name}]: SUCCESS")
                else:
                    fail_count += 1
                    self._log("error", f"❌ [#{idx + 1}] {action_type} [{action_name}]: FAILED — {err_msg}")

                # ---- Jump logic ----
                if jump_to:
                    target_idx = None
                    for i, a in enumerate(actions):
                        if a.get("name") == jump_to:
                            target_idx = i
                            break
                    if target_idx is not None:
                        self._log("info", f"  🔀 Jumping to [{jump_to}] (action #{target_idx + 1})")
                        idx = target_idx
                        continue
                    elif ok:
                        self._log("info", f"  Jump target [{jump_to}] not found, continuing to next")
                    else:
                        self._log("error", f"  Jump target [{jump_to}] not found, stopping execution")
                        self._stop_requested = True
                        break

                idx += 1

                if idx < len(actions) and delay_between > 0:
                    await asyncio.sleep(delay_between)

        elapsed = time.time() - start_time
        status = "success" if not self._stop_requested else "stopped"
        self._log("info", "──────────────────────────────────────")
        self._log(status, f"✅ Execution {status} in {elapsed:.1f}s — {success_count} success, {fail_count} failed")

        return {
            "status": status,
            "success_count": success_count,
            "fail_count": fail_count,
            "total_actions": total_in_run,
            "duration_sec": round(elapsed, 1),
        }
