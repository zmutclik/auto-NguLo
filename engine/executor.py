"""
Script Executor — walks through actions of a script and executes them.
Supports both real (ADB/uiautomator2) and mock mode for Termux dev.
"""
import asyncio
import json
import time
from typing import Callable, Optional

from database.connection import get_db


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
        self.variables: dict[str, str] = {}    # Runtime variables
        self.last_match_result: tuple[float, float] | None = None  # (x, y)
        self.log_callback: Optional[Callable] = None
        self._stop_requested = False
        self._current_action_idx = 0

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

    # ---- Android input mock/real ----

    async def _tap(self, x: float, y: float):
        if self.mock_mode:
            self._log("info", f"  [mock] tap({x:.0f}, {y:.0f})")
            await asyncio.sleep(0.1)
        else:
            self._log("info", f"  tap({x:.0f}, {y:.0f})")
            # TODO: real — adb shell input tap x y
            await asyncio.sleep(0.05)

    async def _swipe(self, x1, y1, x2, y2, duration_ms):
        if self.mock_mode:
            self._log("info", f"  [mock] swipe({x1:.0f},{y1:.0f} → {x2:.0f},{y2:.0f}) {duration_ms}ms")
            await asyncio.sleep(duration_ms / 1000 * 0.1)
        else:
            self._log("info", f"  swipe({x1:.0f},{y1:.0f} → {x2:.0f},{y2:.0f}) {duration_ms}ms")
            # TODO: real — adb shell input swipe x1 y1 x2 y2 duration
            await asyncio.sleep(duration_ms / 1000)

    async def _long_press(self, x, y, duration_ms):
        if self.mock_mode:
            self._log("info", f"  [mock] long_press({x:.0f}, {y:.0f}) {duration_ms}ms")
            await asyncio.sleep(duration_ms / 1000 * 0.1)
        else:
            self._log("info", f"  long_press({x:.0f}, {y:.0f}) {duration_ms}ms")
            # TODO: real — adb shell input swipe x y x y duration
            await asyncio.sleep(duration_ms / 1000)

    async def _push_key(self, key_code: str):
        if self.mock_mode:
            self._log("info", f"  [mock] keyevent {key_code}")
            await asyncio.sleep(0.05)
        else:
            self._log("info", f"  keyevent {key_code}")
            # TODO: real — adb shell input keyevent KEYCODE_{key_code}
            await asyncio.sleep(0.05)

    async def _combo_action(self, action: str):
        if self.mock_mode:
            self._log("info", f"  [mock] combo: {action}")
            await asyncio.sleep(0.1)
        else:
            self._log("info", f"  combo: {action}")
            # TODO: real — key combinations via input keyevent
            await asyncio.sleep(0.05)

    async def _screenshot_match(self, template_path: str, threshold: float,
                                  retry_count: int, retry_delay_ms: int) -> tuple[bool, float, float]:
        """Try to find template on screen. Returns (success, x, y)."""
        for attempt in range(retry_count):
            if self._stop_requested:
                return (False, 0, 0)
            if self.mock_mode:
                # Mock: 70% chance success on first try, 90% by retry 3
                success_chance = 0.7 + (attempt * 0.1)
                success = attempt > 2 or True  # Always succeed in mock after retries
                self._log("info", f"  [mock] match attempt {attempt+1}/{retry_count}: template='{template_path}' th={threshold} → {'FOUND' if success else 'NOT FOUND'}")
                if success:
                    self.last_match_result = (540.0, 1200.0)  # Mock center
                    return (True, 540.0, 1200.0)
                if attempt < retry_count - 1:
                    await asyncio.sleep(retry_delay_ms / 1000)
            else:
                # TODO: real — OpenCV template matching
                self._log("info", f"  match attempt {attempt+1}/{retry_count}: template='{template_path}' th={threshold}")
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
            await asyncio.sleep(len(resolved) * speed_ms / 1000 * 0.05)  # Faster in mock
        else:
            self._log("info", f"  type text: {len(resolved)} chars @ {speed_ms}ms/char")
            for ch in resolved:
                # TODO: real — adb shell input text (quoted) or per-character keyevent
                await asyncio.sleep(speed_ms / 1000)

    # ---- Main executor ----

    async def execute(self, script: dict, log_cb: Callable | None = None) -> dict:
        """
        Execute all actions in a script. Returns summary dict.
        `script` must contain keys: id, name, repeat_count, delay_between_ms, and nested `actions` list.
        """
        self.log_callback = log_cb
        self._stop_requested = False
        self.variables = {}
        self.last_match_result = None

        actions = script.get("actions", [])
        repeat = script.get("repeat_count", 1)
        delay_between = script.get("delay_between_ms", 1000) / 1000
        total_in_run = len(actions) * repeat

        success_count = 0
        fail_count = 0
        start_time = time.time()

        self._log("info", f"▶️  Script \"{script['name']}\" started")
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

                jump_to = None  # Override next index
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
                    # Find action index by name
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

                # Delay between actions
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
