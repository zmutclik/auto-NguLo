"""
Script Executor — walks through actions of a script and executes them.
Supports both real (ADB/uiautomator2) and mock mode for Termux dev.

Architecture (refactored):
  engine/adb.py            → ADB communication layer
  engine/input_injector.py → sendevent fallback, key mappings, run_adb_input()
  engine/vision.py         → screenshot capture & template matching
  engine/variables.py      → global variable store (load/save)
  engine/keyboard_cache.py → keyboard mapping cache from DB
  engine/executor.py       → ScriptExecutor class (this file — dispatch + orchestration)
"""
import asyncio
import json
import re
import time
from typing import Callable, Optional

from engine.adb import run_adb, get_device_serial
from engine.input_injector import (
    COMBO_KEYS, KEY_NAME_MAP, KEYCODE_TO_LINUX,
    run_adb_input, sendevent_combo,
)
from engine.vision import (
    template_match_available,
    match_template_on_screen,
)
from engine.variables import load_global_vars, save_global_vars
from engine.keyboard_cache import load_keyboard_mapping


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
    - call_script: call another script, wait for it to finish, then continue
    - goto_script: transfer execution to another script (stop current, start target)
    - toast: show a toast message on the device screen
    """

    def __init__(self, mock_mode: bool = True):
        self.mock_mode = mock_mode
        self.variables: dict[str, str] = {}
        self.last_match_result: tuple[float, float] | None = None
        self.log_callback: Optional[Callable] = None
        self.script_loader: Optional[Callable] = None  # async (script_name) -> script_dict
        self._stop_requested = False
        self._current_action_idx = 0
        self._serial: str | None = None  # ADB device serial

    async def _init_serial(self):
        """Discover and cache the ADB device serial."""
        if self._serial:
            return
        self._serial = await get_device_serial()

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

    # ── Variable resolution ─────────────────────────────────────────

    def _resolve_value(self, text: str) -> str:
        """Replace ${var.path.to.field} placeholders with variable values, supporting nested JSON access."""
        def _resolve_single(match):
            full_path = match.group(1)
            parts = full_path.split(".")
            var_name = parts[0]
            access_path = parts[1:]

            value = self.variables.get(var_name)
            if value is None:
                return match.group(0)

            if not access_path:
                return str(value)

            if isinstance(value, str) and value.strip().startswith(("{", "[")):
                try:
                    value = json.loads(value)
                except (json.JSONDecodeError, ValueError):
                    pass

            for key in access_path:
                if isinstance(value, list):
                    try:
                        value = value[int(key)]
                        continue
                    except (ValueError, IndexError):
                        pass
                if isinstance(value, dict):
                    if key in value:
                        value = value[key]
                        continue
                    try:
                        if int(key) in value:
                            value = value[int(key)]
                            continue
                    except (ValueError, TypeError):
                        pass
                return match.group(0)

            return str(value)

        return re.sub(r"\$\{([a-zA-Z_]\w*(?:\.[^.}]+)*)\}", _resolve_single, text)

    def _eval_expr(self, value: str) -> str:
        """Safely evaluate a simple arithmetic expression string (e.g. '0+1', '5*2-3')."""
        stripped = value.strip()
        if not stripped:
            return value
        if re.fullmatch(r"[\d\s\+\-\*\/\%\(\)\.eE]+", stripped):
            try:
                result = eval(stripped, {"__builtins__": {}}, {})  # noqa: S307
                if isinstance(result, float) and result.is_integer():
                    return str(int(result))
                return str(result)
            except Exception:
                pass
        return value

    # ── Android input (real via ADB, or mock) ────────────────────────

    async def _tap(self, x: float, y: float):
        if self.mock_mode:
            self._log("info", f"  [mock] tap({x:.0f}, {y:.0f})")
            await asyncio.sleep(0.1)
        else:
            self._log("info", f"  👆 tap({x:.0f}, {y:.0f})")
            await run_adb_input(self._serial, "tap", str(int(x)), str(int(y)))
            await asyncio.sleep(0.05)

    async def _swipe(self, x1, y1, x2, y2, duration_ms):
        if self.mock_mode:
            self._log("info", f"  [mock] swipe({x1:.0f},{y1:.0f} → {x2:.0f},{y2:.0f}) {duration_ms}ms")
            await asyncio.sleep(duration_ms / 1000 * 0.1)
        else:
            self._log("info", f"  👆 swipe({x1:.0f},{y1:.0f} → {x2:.0f},{y2:.0f}) {duration_ms}ms")
            await run_adb_input(self._serial, "swipe",
                str(int(x1)), str(int(y1)), str(int(x2)), str(int(y2)), str(int(duration_ms)))
            await asyncio.sleep(duration_ms / 1000)

    async def _long_press(self, x, y, duration_ms):
        if self.mock_mode:
            self._log("info", f"  [mock] long_press({x:.0f}, {y:.0f}) {duration_ms}ms")
            await asyncio.sleep(duration_ms / 1000 * 0.1)
        else:
            self._log("info", f"  👆 long_press({x:.0f}, {y:.0f}) {duration_ms}ms")
            end_x = int(x) + 1
            await run_adb_input(self._serial, "swipe",
                str(int(x)), str(int(y)), str(end_x), str(int(y)), str(int(duration_ms)))
            await asyncio.sleep(duration_ms / 1000)

    async def _push_key(self, key_code: str):
        if key_code.startswith("KEYCODE_"):
            resolved = key_code
        elif key_code.isdigit():
            resolved = key_code
        else:
            resolved = KEY_NAME_MAP.get(key_code.upper(), f"KEYCODE_{key_code.upper()}")
        if self.mock_mode:
            self._log("info", f"  [mock] keyevent {resolved}")
            await asyncio.sleep(0.05)
        else:
            self._log("info", f"  ⌨️  keyevent {resolved}")
            await run_adb_input(self._serial, "keyevent", resolved)
            await asyncio.sleep(0.05)

    async def _combo_action(self, action: str):
        keys = COMBO_KEYS.get(action, [f"KEYCODE_{action.upper()}"])
        if self.mock_mode:
            self._log("info", f"  [mock] combo: {action} → {keys}")
            await asyncio.sleep(0.1)
        else:
            self._log("info", f"  ⌨️  combo: {action} → {keys}")
            if len(keys) == 1:
                await run_adb_input(self._serial, "keyevent", keys[0])
                await asyncio.sleep(0.05)
                return

            # Strategy 1: `input keycombination` (native Android 7.0+)
            try:
                adb_prefix = ("-s", self._serial) if self._serial else ()
                await run_adb(*(adb_prefix + ("shell", "input", "keycombination") + tuple(keys)),
                              timeout=5.0)
                await asyncio.sleep(0.05)
                return
            except RuntimeError as e:
                self._log("warn", f"  keycombination failed: {e}")

            # Strategy 2: sendevent for hardware combos
            hw_keys = [k for k in keys if k in KEYCODE_TO_LINUX]
            if hw_keys and len(hw_keys) == len(keys):
                try:
                    await sendevent_combo(self._serial, hw_keys, hold_ms=500)
                    await asyncio.sleep(0.05)
                    return
                except RuntimeError as e:
                    self._log("warn", f"  sendevent failed: {e}")

            # Strategy 3: sequential fallback
            self._log("warn", f"  ⚠️  falling back to sequential keyevents (combo may not work)")
            for i, key in enumerate(keys):
                await run_adb_input(self._serial, "keyevent", key)
                if i < len(keys) - 1:
                    await asyncio.sleep(0.03)
            await asyncio.sleep(0.05)

    async def _type_text(self, text: str, speed_ms: int, keyboard_mapping_id: int | None = None):
        """
        Type text on the device.
        If keyboard_mapping_id is set: tap each character using mapped coordinates.
        Otherwise: ADB input text (legacy).
        """
        resolved = self._resolve_value(text)
        delay_per_char = speed_ms / 1000.0

        # Keyboard mapping tap mode
        if keyboard_mapping_id is not None and keyboard_mapping_id > 0:
            keys_map = await load_keyboard_mapping(keyboard_mapping_id, log_fn=self._log)
            if not keys_map:
                self._log("warn", f"  ⌨️  Keyboard mapping #{keyboard_mapping_id} is empty, no keys defined")
                return

            if self.mock_mode:
                self._log("info", f"  [mock] type_text via keyboard map #{keyboard_mapping_id}: {len(resolved)} chars, {speed_ms}ms/char")
                for ch in resolved:
                    coord = keys_map.get(ch)
                    if coord:
                        self._log("info", f"  [mock]   tap '{ch}' → ({coord['x']:.0f}, {coord['y']:.0f})")
                    else:
                        upp = ch.upper()
                        coord = keys_map.get(upp)
                        if coord:
                            self._log("info", f"  [mock]   tap upper '{upp}' (for '{ch}') → ({coord['x']:.0f}, {coord['y']:.0f})")
                        else:
                            self._log("warn", f"  [mock]   SKIP '{ch}' (not mapped)")
                await asyncio.sleep(len(resolved) * delay_per_char * 0.05)
                return

            self._log("info", f"  ⌨️  type_text via keyboard map #{keyboard_mapping_id}: {len(resolved)} chars @ {speed_ms}ms/char")
            skipped = 0
            for ch in resolved:
                if self._stop_requested:
                    return
                coord = keys_map.get(ch)
                if not coord:
                    upp = ch.upper()
                    coord = keys_map.get(upp)
                    if coord:
                        self._log("info", f"  ⌨️   tapping upper '{upp}' for '{ch}'")
                if coord:
                    await self._tap(coord["x"], coord["y"])
                else:
                    self._log("warn", f"  ⌨️   SKIP '{ch}' — not mapped in keyboard layout #{keyboard_mapping_id}")
                    skipped += 1
                if delay_per_char > 0:
                    await asyncio.sleep(delay_per_char)
            if skipped:
                self._log("warn", f"  ⌨️   {skipped} character(s) skipped (not mapped)")
            return

        # Legacy ADB input text mode
        if self.mock_mode:
            self._log("info", f"  [mock] type text ({len(resolved)} chars, {speed_ms}ms/char)")
            for ch in resolved:
                if ch == "\n":
                    self._log("info", "  [mock]   keyevent ENTER")
                else:
                    self._log("info", f"  [mock]   input text '{ch}'")
            await asyncio.sleep(len(resolved) * delay_per_char * 0.05)
        else:
            self._log("info", f"  ⌨️  type text: {len(resolved)} chars @ {speed_ms}ms/char")
            for ch in resolved:
                if self._stop_requested:
                    return
                if ch == "\n":
                    await run_adb_input(self._serial, "keyevent", "KEYCODE_ENTER")
                elif ch == " ":
                    await run_adb_input(self._serial, "keyevent", "KEYCODE_SPACE")
                elif ch in ('"', "'", "\\", "`", "$", "&", "|", ";", "(", ")", "{", "}", "<", ">", "~", "#", "!", "*"):
                    await run_adb_input(self._serial, "text", f"\\{ch}")
                elif ch.isascii() and ch.isprintable():
                    await run_adb_input(self._serial, "text", ch)
                else:
                    self._log("warn", f"  ⌨️  skipping non-ASCII char: {repr(ch)}")
                if delay_per_char > 0:
                    await asyncio.sleep(delay_per_char)

    # ── Screenshot / template matching ───────────────────────────────

    async def _screenshot_match(self, template_path: str, threshold: float,
                                  retry_count: int, retry_delay_ms: int,
                                  region: tuple = None) -> tuple:
        """Try to find template on screen. Returns (success, x, y)."""
        for attempt in range(retry_count):
            if self._stop_requested:
                return (False, 0, 0)
            if self.mock_mode:
                self._log("info", f"  [mock] match attempt {attempt+1}/{retry_count}: template='{template_path}' th={threshold}")
                if template_match_available():
                    found, mx, my = await match_template_on_screen(
                        self._serial, template_path, threshold,
                        mock_mode=self.mock_mode, region=region, log_fn=self._log,
                    )
                    if found:
                        self.last_match_result = (mx, my)
                        return (True, mx, my)
                else:
                    self.last_match_result = (540.0, 1200.0)
                    self._log("info", f"  [mock] → FOUND (simulated)")
                    return (True, 540.0, 1200.0)
            else:
                self._log("info", f"  🔍 match attempt {attempt+1}/{retry_count}: template='{template_path}' th={threshold}")
                found, mx, my = await match_template_on_screen(
                    self._serial, template_path, threshold,
                    mock_mode=False, region=region, log_fn=self._log,
                )
                if found:
                    self.last_match_result = (mx, my)
                    self._log("info", f"  ✅ match found at ({mx:.0f}, {my:.0f})")
                    return (True, mx, my)

            if attempt < retry_count - 1:
                self._log("info", f"  ⏳ retry in {retry_delay_ms}ms...")
                await asyncio.sleep(retry_delay_ms / 1000)
        return (False, 0, 0)

    async def _resolve_coords_from_template(self, action: dict) -> tuple:
        """Resolve X/Y coordinates by matching template on screen, or return raw coords."""
        tpl = action.get("template_path", "")
        if not tpl:
            if action.get("action_type") == "swipe":
                return (action.get("x", 0), action.get("y", 0),
                        action.get("x2", 0), action.get("y2", 0))
            return (action.get("x", 0), action.get("y", 0))

        threshold = action.get("match_threshold", 0.80)
        retry = action.get("retry_count", 1)
        retry_delay = action.get("retry_delay_ms", 1000)

        if action.get("action_type") == "swipe":
            found, x1, y1 = await self._screenshot_match(tpl, threshold, retry, retry_delay)
            if not found:
                raise RuntimeError(f"Template '{tpl}' not found on screen for swipe start point")
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
            found, x, y = await self._screenshot_match(tpl, threshold, retry, retry_delay)
            if not found:
                raise RuntimeError(f"Template '{tpl}' not found on screen for {action.get('action_type')}")
            return (x, y)

    # ── API, orientation, apps, SMS, toast ───────────────────────────

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

    async def _orientation(self, orientation: str):
        if orientation == "auto":
            if self.mock_mode:
                self._log("info", "  [mock] orientation → auto (accelerometer)")
            else:
                self._log("info", "  📱 orientation → auto")
                adb_prefix = ("-s", self._serial) if self._serial else ()
                await run_adb(*(adb_prefix + ("shell", "settings", "put", "system", "accelerometer_rotation", "1")),
                              timeout=5.0)
                return

        orient_map = {"portrait": "0", "landscape": "1", "reverse_portrait": "2", "reverse_landscape": "3"}
        rot_val = orient_map.get(orientation, "0")
        if self.mock_mode:
            self._log("info", f"  [mock] orientation → {orientation} (rotation {rot_val})")
        else:
            self._log("info", f"  📱 orientation → {orientation}")
            adb_prefix = ("-s", self._serial) if self._serial else ()
            await run_adb(*(adb_prefix + ("shell", "settings", "put", "system", "accelerometer_rotation", "0")),
                          timeout=5.0)
            await run_adb(*(adb_prefix + ("shell", "settings", "put", "system", "user_rotation", rot_val)),
                          timeout=5.0)

    async def _launch_app(self, package: str):
        resolved = self._resolve_value(package)
        if self.mock_mode:
            self._log("info", f"  [mock] launch_app: {resolved}")
            await asyncio.sleep(0.3)
        else:
            self._log("info", f"  🚀 launch_app: {resolved}")
            adb_prefix = ("-s", self._serial) if self._serial else ()
            await run_adb(*(adb_prefix + ("shell", "monkey", "-p", resolved, "-c", "android.intent.category.LAUNCHER", "1")),
                          timeout=10.0)
            await asyncio.sleep(1.0)

    async def _kill_app(self, package: str):
        resolved = self._resolve_value(package)
        if self.mock_mode:
            self._log("info", f"  [mock] kill_app: {resolved}")
            await asyncio.sleep(0.2)
        else:
            self._log("info", f"  🔪 kill_app: {resolved}")
            adb_prefix = ("-s", self._serial) if self._serial else ()
            await run_adb(*(adb_prefix + ("shell", "am", "force-stop", resolved)),
                          timeout=10.0)
            await asyncio.sleep(0.3)

    async def _toast(self, message: str, duration: str = "short"):
        resolved_msg = self._resolve_value(message)
        dur_param = "1" if duration == "long" else "0"
        if self.mock_mode:
            self._log("info", f"  [mock] toast ({duration}): {resolved_msg}")
            await asyncio.sleep(0.1)
            return

        self._log("info", f"  💬 toast ({duration}): {resolved_msg}")
        escaped = resolved_msg.replace("'", "\\'")
        adb_prefix = ("-s", self._serial) if self._serial else ()

        for strat_args in [
            ("shell", "am", "broadcast",
             "-a", "com.android.systemui.action.show_toast",
             "--es", "android.intent.extra.TEXT", escaped,
             "--ei", "android.intent.extra.DURATION", dur_param),
            ("shell", "am", "broadcast",
             "-n", "com.termux.api/.ToastReceiver",
             "--es", "text", escaped,
             "--ez", "long", "true" if duration == "long" else "false"),
        ]:
            try:
                await run_adb(*(adb_prefix + strat_args), timeout=4.0)
                await asyncio.sleep(0.15)
                return
            except RuntimeError:
                pass

        # Strategy 3: notification
        try:
            await run_adb(*(adb_prefix + (
                "shell", "cmd", "notification", "post",
                "-S", "bigtext", "-t", "Auto-NguLo", "toast", resolved_msg,
            )), timeout=4.0)
            await asyncio.sleep(1.5 if duration == "short" else 3.5)
            try:
                await run_adb(*(adb_prefix + ("shell", "cmd", "notification", "cancel", "toast")), timeout=3.0)
            except RuntimeError:
                pass
            return
        except RuntimeError:
            pass

        self._log("warn", f"  ⚠️  Toast not supported on this device (logged only): {resolved_msg}")

    async def _read_latest_sms(self, save_var: str = "last_sms", sms_type: str = "inbox", sms_limit: int = 1):
        if self.mock_mode:
            dummy = json.dumps({
                "count": 1,
                "messages": [{
                    "address": "08123456789",
                    "body": "[mock] Ini SMS terakhir untuk testing",
                    "date": str(int(time.time() * 1000)),
                }]
            }, ensure_ascii=False)
            self.variables[save_var] = dummy
            self._log("info", f"  📩 [mock] SMS saved to ${save_var}")
            return

        self._log("info", f"  📩 Reading latest SMS ({sms_type}, limit={sms_limit})...")
        uri_map = {"inbox": "content://sms/inbox", "sent": "content://sms/sent",
                    "draft": "content://sms/draft", "all": "content://sms"}
        uri = uri_map.get(sms_type, "content://sms/inbox")

        try:
            raw = await run_adb(
                *self._adb_args(
                    "shell", "content", "query",
                    "--uri", uri,
                    "--projection", "address,body,date",
                    "--sort", "date DESC",
                    "--limit", str(sms_limit),
                ),
                timeout=10.0,
            )
            messages = []
            if raw:
                for row_line in raw.split("\n"):
                    row_line = row_line.strip()
                    if not row_line or not row_line.startswith("Row:"):
                        continue
                    msg = {}
                    body_part = row_line.split(" ", 2)[-1] if len(row_line.split(" ", 2)) > 2 else row_line
                    for part in body_part.split(", "):
                        part = part.strip()
                        if "=" in part:
                            key, val = part.split("=", 1)
                            msg[key.strip()] = val
                    if msg:
                        messages.append(msg)

            result = json.dumps({"count": len(messages), "messages": messages}, ensure_ascii=False)
            self.variables[save_var] = result
            preview = messages[0].get("body", "")[:60] if messages else "(kosong)"
            self._log("success", f"  📩 SMS saved to ${save_var}: {len(messages)} message(s) — {preview}")
        except RuntimeError as e:
            self._log("error", f"  ❌ Failed to read SMS: {e}")
            self.variables[save_var] = json.dumps({"count": 0, "messages": [], "error": str(e)})
            raise

    # ── call_script / goto_script ────────────────────────────────────

    async def _call_script(self, target_script_name: str) -> bool:
        if not self.script_loader:
            self._log("error", "  ❌ script_loader not set — cannot call another script")
            return False

        try:
            target_script = await self.script_loader(target_script_name)
        except Exception as e:
            self._log("error", f"  ❌ Failed to load script [{target_script_name}]: {e}")
            return False

        if not target_script or not target_script.get("actions"):
            self._log("error", f"  ❌ Script [{target_script_name}] not found or has no actions")
            return False

        target_name = target_script.get("name", target_script_name)
        actions = target_script["actions"]
        self._log("info", f"  📞 Calling script [{target_name}] with {len(actions)} action(s)...")

        saved_stop = self._stop_requested
        self._stop_requested = False

        idx = 0
        while idx < len(actions):
            if self._stop_requested:
                self._log("info", f"  ⏹️ Called script [{target_name}] stopped")
                self._stop_requested = saved_stop
                return False

            action = actions[idx]
            action_name = action.get("name", f"action_{idx}")
            action_type = action.get("action_type", "wait")

            if action.get("enabled", 1) == 0 or action.get("enabled") is False:
                self._log("info", f"  ⏭️ [{target_name}] [#{idx + 1}] {action_type} [{action_name}] SKIPPED (disabled)")
                idx += 1
                continue

            self._log("info", f"  📞 [{target_name}] ⚡ [#{idx + 1}] {action_type} [{action_name}]")

            wait_before = action.get("wait_before_ms", 500) / 1000
            if wait_before > 0:
                await asyncio.sleep(wait_before)

            try:
                ok, jump_to, err_msg = await self._execute_single_action(action, actions)
            except Exception as e:
                ok, jump_to, err_msg = False, None, str(e)

            wait_after = action.get("wait_after_ms", 500) / 1000
            if wait_after > 0:
                await asyncio.sleep(wait_after)

            if ok:
                self._log("success", f"  📞 [{target_name}] ✅ [#{idx + 1}] {action_type} [{action_name}]")
            else:
                self._log("error", f"  📞 [{target_name}] ❌ [#{idx + 1}] {action_type} [{action_name}]: {err_msg}")
                if target_script.get("stop_on_failure"):
                    self._stop_requested = saved_stop
                    return False

            if jump_to:
                target_idx = await self._resolve_jump(jump_to, actions)
                if target_idx is not None:
                    idx = target_idx
                    continue
                elif not ok:
                    self._stop_requested = saved_stop
                    return False

            idx += 1

        self._log("success", f"  📞 Called script [{target_name}] completed successfully")
        self._stop_requested = saved_stop
        return True

    async def _if_condition(self, action: dict) -> tuple:
        var_name = action.get("condition_var", "")
        op = action.get("condition_op", "eq")
        compare_val = self._resolve_value(action.get("condition_value", ""))

        actual_val = self.variables.get(var_name, "")
        actual_val = self._resolve_value(actual_val)

        self._log("info", f"  IF condition: ${var_name} ({actual_val}) {op} {compare_val}")

        if op == "eq":
            result = str(actual_val) == str(compare_val)
        elif op == "ne":
            result = str(actual_val) != str(compare_val)
        elif op in ("gt", "lt", "ge", "le"):
            try:
                a, b = float(actual_val), float(compare_val)
                result = (op == "gt" and a > b) or (op == "lt" and a < b) or (op == "ge" and a >= b) or (op == "le" and a <= b)
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
            result = False

        self._log("info", f"  IF result: {result}")
        return (action.get("jump_on_true", "") if result else action.get("jump_on_false", ""), result)

    async def _resolve_jump(self, jump_to: str, actions: list) -> int | None:
        if not jump_to:
            return None
        for i, a in enumerate(actions):
            if a.get("name") == jump_to:
                return i
        return None

    # ── Single action dispatcher ─────────────────────────────────────

    async def _execute_single_action(self, action: dict, actions: list) -> tuple:
        """Returns (ok: bool, jump_to: str | None, err_msg: str)."""
        action_type = action.get("action_type", "wait")
        jump_to = None
        ok = True
        err_msg = ""

        try:
            if action_type == "tap":
                if action.get("use_match_result") and self.last_match_result:
                    await self._tap(*self.last_match_result)
                elif action.get("template_path") and action.get("x") is None and action.get("y") is None:
                    coords = await self._resolve_coords_from_template(action)
                    await self._tap(coords[0], coords[1])
                else:
                    await self._tap(action.get("x", 0), action.get("y", 0))

            elif action_type == "swipe":
                if action.get("template_path") and action.get("x") is None and action.get("y") is None:
                    coords = await self._resolve_coords_from_template(action)
                    await self._swipe(coords[0], coords[1], coords[2], coords[3], action.get("duration_ms", 300))
                else:
                    await self._swipe(action.get("x", 0), action.get("y", 0),
                                      action.get("x2", 0), action.get("y2", 0),
                                      action.get("duration_ms", 300))

            elif action_type == "long_press":
                if action.get("template_path") and action.get("x") is None and action.get("y") is None:
                    coords = await self._resolve_coords_from_template(action)
                    await self._long_press(coords[0], coords[1], action.get("duration_ms", 500))
                else:
                    await self._long_press(action.get("x", 0), action.get("y", 0), action.get("duration_ms", 500))

            elif action_type == "screenshot_match":
                match_region = None
                rx, ry = action.get("match_region_x"), action.get("match_region_y")
                rw, rh = action.get("match_region_w"), action.get("match_region_h")
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
                await asyncio.sleep(action.get("wait_ms", 1000) / 1000)

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
                vval = self._eval_expr(vval)
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
                    action.get("keyboard_mapping_id"),
                )

            elif action_type == "jump":
                jump_to = action.get("jump_to", "")
                if not jump_to:
                    self._log("warn", "  jump action without target, skipping")

            elif action_type == "stop":
                self._stop_requested = True

            elif action_type == "if":
                jump_target, result = await self._if_condition(action)
                self._log("info", f"  IF result: {result}, jump_to: {jump_target or '(none)'}")
                if jump_target:
                    jump_to = jump_target

            elif action_type == "orientation":
                await self._orientation(action.get("orientation_value", "auto"))

            elif action_type == "launch_app":
                await self._launch_app(action.get("app_package", ""))

            elif action_type == "kill_app":
                await self._kill_app(action.get("app_package", ""))

            elif action_type == "read_sms":
                await self._read_latest_sms(
                    save_var=action.get("var_name", "last_sms"),
                    sms_type=action.get("sms_type", "inbox"),
                    sms_limit=int(action.get("sms_limit", "1")),
                )

            elif action_type == "call_script":
                target_name = action.get("call_script_name", "").strip()
                if target_name:
                    ok = await self._call_script(target_name)
                    if not ok:
                        err_msg = f"Call script [{target_name}] failed"
                else:
                    ok = False
                    err_msg = "call_script_name not set"

            elif action_type == "goto_script":
                target_name = action.get("goto_script_name", "").strip()
                if target_name:
                    self._log("info", f"  🔀 goto_script: transferring to script [{target_name}]")
                    self._goto_target = target_name
                    self._stop_requested = True
                else:
                    ok = False
                    err_msg = "goto_script_name not set"

            elif action_type == "toast":
                await self._toast(
                    action.get("toast_message", ""),
                    action.get("toast_duration", "short"),
                )

            else:
                self._log("warn", f"  unknown action type: {action_type}")

        except Exception as e:
            ok = False
            err_msg = str(e)

        return ok, jump_to, err_msg

    # ── Main executor ────────────────────────────────────────────────

    async def execute(self, script: dict, log_cb: Callable | None = None,
                       inherit_variables: dict | None = None) -> dict:
        """
        Execute all actions in a script. Returns summary dict.
        Supports goto_script: if _goto_target is set, returns a special
        result dict with _goto_target so the router can restart execution
        on the target script.
        """
        self.log_callback = log_cb
        self._stop_requested = False
        self._goto_target = None
        self.variables = load_global_vars()
        if inherit_variables is not None:
            self.variables.update(inherit_variables)
        self.last_match_result = None

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

                if action.get("enabled", 1) == 0 or action.get("enabled") is False:
                    self._log("info", f"⏭️ [#{idx + 1}] {action_type} [{action_name}] SKIPPED (disabled)")
                    idx += 1
                    continue

                self._current_action_idx = idx
                self._log("info", f"⚡ [#{idx + 1}] {action_type} [{action_name}] executing...")

                wait_before = action.get("wait_before_ms", 500) / 1000
                if wait_before > 0:
                    await asyncio.sleep(wait_before)

                ok, jump_to, err_msg = await self._execute_single_action(action, actions)

                if self._goto_target is not None:
                    self._log("success", f"✅ [#{idx + 1}] {action_type} [{action_name}]: SUCCESS")
                    success_count += 1
                    self._log("info", f"  🔀 goto_script → [{self._goto_target}]")
                    break

                # Handle jump action
                if action_type == "jump" and jump_to:
                    target_idx = await self._resolve_jump(jump_to, actions)
                    if target_idx is not None:
                        idx = target_idx
                        self._log("success", f"✅ [#{idx + 1}] {action_type} [{action_name}]: jumped to [{jump_to}]")
                        continue
                    else:
                        ok = False
                        err_msg = f"Jump target [{jump_to}] not found"

                # Handle if action
                if action_type == "if" and jump_to:
                    target_idx = await self._resolve_jump(jump_to, actions)
                    if target_idx is not None:
                        idx = target_idx
                        self._log("success", f"✅ [#{idx + 1}] {action_type} [{action_name}]: jumped to [{jump_to}]")
                        continue
                    else:
                        ok = False
                        err_msg = f"IF jump target [{jump_to}] not found"

                wait_after = action.get("wait_after_ms", 500) / 1000
                if wait_after > 0:
                    await asyncio.sleep(wait_after)

                if ok:
                    success_count += 1
                    self._log("success", f"✅ [#{idx + 1}] {action_type} [{action_name}]: SUCCESS")
                else:
                    fail_count += 1
                    self._log("error", f"❌ [#{idx + 1}] {action_type} [{action_name}]: FAILED — {err_msg}")

                # Jump logic (from screenshot_match, etc.)
                if jump_to and action_type not in ("jump", "if"):
                    target_idx = await self._resolve_jump(jump_to, actions)
                    if target_idx is not None:
                        self._log("info", f"  🔀 Jumping to [{jump_to}] (action #{target_idx + 1})")
                        idx = target_idx
                        continue
                    else:
                        self._log("error", f"  Jump target [{jump_to}] not found, stopping execution")
                        self._stop_requested = True
                        break

                if not ok:
                    self._log("error", "⏹️ Stopping execution due to failure (no jump_on_fail set)")
                    self._stop_requested = True
                    break

                idx += 1

                if idx < len(actions) and delay_between > 0:
                    await asyncio.sleep(delay_between)

            if self._goto_target is not None:
                break

        elapsed = time.time() - start_time
        if self._goto_target is not None:
            status = "success"
        elif self._stop_requested:
            status = "stopped"
        else:
            status = "success"
        self._log("info", "──────────────────────────────────────")
        self._log(status, f"✅ Execution {status} in {elapsed:.1f}s — {success_count} success, {fail_count} failed")

        result = {
            "status": status,
            "success_count": success_count,
            "fail_count": fail_count,
            "total_actions": total_in_run,
            "duration_sec": round(elapsed, 1),
        }

        if self._goto_target is not None:
            result["_goto_target"] = self._goto_target

        save_global_vars(self.variables)
        self._log("info", f"💾 Variables saved ({len(self.variables)} var)")

        return result
