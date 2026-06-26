"""
Script Executor — walks through actions of a script and executes them.
Supports both real (ADB/uiautomator2) and mock mode for Termux dev.
"""
import asyncio
import json
import os
import time
import re
from typing import Callable, Optional

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
_device_rooted: bool | None = None
_device_su_path: str | None = None
_inject_perms_granted: bool = False

async def _detect_root() -> bool:
    """Detect if the connected Android device has root (su binary)."""
    global _device_rooted, _device_su_path
    if _device_rooted is not None:
        return _device_rooted
    # Try common su paths on Android
    for su_path in ("su", "/system/bin/su", "/system/xbin/su", "/sbin/su", "/su/bin/su"):
        try:
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    "adb", "shell", f"{su_path} -c 'id -u'",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                ),
                timeout=3.0,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=3.0)
            uid = stdout.decode("utf-8", errors="replace").strip()
            if uid == "0":
                _device_rooted = True
                _device_su_path = su_path
                return True
        except Exception:
            continue
    _device_rooted = False
    return False

async def _try_grant_inject_permission() -> bool:
    """Try to grant INJECT_EVENTS permission to the shell process via appops."""
    global _inject_perms_granted
    if _inject_perms_granted:
        return True
    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                "adb", "shell", "appops", "set", "com.android.shell", "INJECT_EVENTS", "allow",
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

async def _run_adb_input(serial: str | None, *input_args, timeout: float = 5.0) -> str:
    """
    Run an 'adb shell input <args>' command, automatically using su for root,
    and retrying with permission grant on SecurityException.
    
    Args:
        serial: ADB device serial (or None for default device)
        *input_args: Arguments to the `input` subcommand (e.g. "tap", "100", "200")
    """
    cmd_str = "input " + " ".join(str(a) for a in input_args)

    # Build ADB prefix args
    adb_prefix = ("-s", serial) if serial else ()

    # Strategy 1: Direct call (works on rooted Magisk devices, or devices with permissive SELinux)
    try:
        return await _run_adb(*(adb_prefix + ("shell", "input") + input_args), timeout=timeout)
    except RuntimeError as e:
        err_str = str(e)
        if "INJECT_EVENTS" not in err_str and "SecurityException" not in err_str:
            raise

    # Strategy 2: Try granting INJECT_EVENTS permission, then retry direct call
    if not _inject_perms_granted:
        granted = await _try_grant_inject_permission()
        if granted:
            try:
                return await _run_adb(*(adb_prefix + ("shell", "input") + input_args), timeout=timeout)
            except RuntimeError as e:
                err_str = str(e)
                if "INJECT_EVENTS" not in err_str and "SecurityException" not in err_str:
                    raise

    # Strategy 3: Use su (root) if available
    rooted = await _detect_root()
    if rooted and _device_su_path:
        su_cmd = f"{_device_su_path} -c '{cmd_str}'"
        return await _run_adb(*(adb_prefix + ("shell", su_cmd)), timeout=timeout)

    # Strategy 4: Give up with helpful error
    raise RuntimeError(
        f"INJECT_EVENTS permission denied. This device does not allow ADB input injection.\n"
        f"Try: 1) Root the device  2) Enable 'USB debugging (Security Settings)' in Developer Options  3) Use a device with Android < 10"
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
        """Replace ${var_name} placeholders with variable values."""
        result = text
        for name, val in self.variables.items():
            result = result.replace(f"${{{name}}}", str(val))
        return result

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
            for i, key in enumerate(keys):
                await _run_adb_input(self._serial, "keyevent", key)
                if i < len(keys) - 1:
                    await asyncio.sleep(0.03)
            await asyncio.sleep(0.05)

    async def _screenshot_match(self, template_path: str, threshold: float,
                                  retry_count: int, retry_delay_ms: int) -> tuple:
        """Try to find template on screen. Returns (success, x, y)."""
        for attempt in range(retry_count):
            if self._stop_requested:
                return (False, 0, 0)
            if self.mock_mode:
                success_chance = 0.7 + (attempt * 0.1)
                success = attempt > 2 or True
                self._log("info", f"  [mock] match attempt {attempt+1}/{retry_count}: template='{template_path}' th={threshold} → {'FOUND' if success else 'NOT FOUND'}")
                if success:
                    self.last_match_result = (540.0, 1200.0)
                    return (True, 540.0, 1200.0)
                if attempt < retry_count - 1:
                    await asyncio.sleep(retry_delay_ms / 1000)
            else:
                self._log("info", f"  🔍 match attempt {attempt+1}/{retry_count}: template='{template_path}' th={threshold}")
                # TODO: real OpenCV template matching via screencap + python-opencv
                await asyncio.sleep(retry_delay_ms / 1000)
        return (False, 0, 0)

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
                        else:
                            await self._tap(action.get("x", 0), action.get("y", 0))

                    elif action_type == "swipe":
                        await self._swipe(
                            action.get("x", 0), action.get("y", 0),
                            action.get("x2", 0), action.get("y2", 0),
                            action.get("duration_ms", 300),
                        )

                    elif action_type == "long_press":
                        await self._long_press(
                            action.get("x", 0), action.get("y", 0),
                            action.get("duration_ms", 500),
                        )

                    elif action_type == "screenshot_match":
                        found, mx, my = await self._screenshot_match(
                            action.get("template_path", ""),
                            action.get("match_threshold", 0.80),
                            action.get("retry_count", 1),
                            action.get("retry_delay_ms", 1000),
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
