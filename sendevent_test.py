#!/usr/bin/env python3
"""
sendevent_test.py — Test the sendevent ADB injection stack directly.
Run: python3 sendevent_test.py [serial]
"""
import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import the engine functions we want to test
from engine.executor import (
    _detect_sendevent, _sendevent_key, _sendevent_tap, _sendevent_swipe,
    _sendevent_text_char, _KEYCODE_TO_LINUX, _device_touch_event, _device_key_event,
    _device_max_x, _device_max_y, _sendevent_available, _run_adb_input,
)


async def main():
    serial = sys.argv[1] if len(sys.argv) > 1 else None
    if serial:
        print(f"📱 Target device: {serial}")
    else:
        print("📱 Target device: default (no -s flag)")

    # Step 1: Detect input devices
    print("\n" + "=" * 60)
    print("STEP 1: Detect input devices and sendevent availability")
    print("=" * 60)
    try:
        ok = await _detect_sendevent(serial)
        print(f"  sendevent available: {ok}")
        print(f"  _device_touch_event: {_device_touch_event}")
        print(f"  _device_key_event:   {_device_key_event}")
        print(f"  screen max:          {_device_max_x}x{_device_max_y}")
    except Exception as e:
        print(f"  ERROR: {e}")
        return

    if not ok:
        print("\n❌ sendevent NOT available — cannot test keys/taps")
        print("   Make sure the device has input group access for ADB shell")
        return

    # Step 2: Test KEYCODE_HOME
    print("\n" + "=" * 60)
    print("STEP 2: Test key event — KEYCODE_HOME")
    print("=" * 60)
    try:
        await _sendevent_key(serial, "KEYCODE_HOME")
        print("  ✅ KEYCODE_HOME sent successfully")
    except Exception as e:
        print(f"  ❌ FAILED: {e}")

    # Step 3: Test KEYCODE_BACK
    print("\n" + "=" * 60)
    print("STEP 3: Test key event — KEYCODE_BACK")
    print("=" * 60)
    try:
        await _sendevent_key(serial, "KEYCODE_BACK")
        print("  ✅ KEYCODE_BACK sent successfully")
    except Exception as e:
        print(f"  ❌ FAILED: {e}")

    # Step 4: Test KEYCODE_VOLUME_UP
    print("\n" + "=" * 60)
    print("STEP 4: Test key event — KEYCODE_VOLUME_UP")
    print("=" * 60)
    try:
        await _sendevent_key(serial, "KEYCODE_VOLUME_UP")
        print("  ✅ KEYCODE_VOLUME_UP sent successfully")
    except Exception as e:
        print(f"  ❌ FAILED: {e}")

    # Step 5: Test tap at center of screen
    print("\n" + "=" * 60)
    print("STEP 5: Test tap at center of screen")
    print("=" * 60)
    cx = _device_max_x // 2
    cy = _device_max_y // 2
    print(f"  Coordinates: ({cx}, {cy})")
    try:
        await _sendevent_tap(serial, cx, cy)
        print(f"  ✅ Tap at ({cx}, {cy}) sent successfully")
    except Exception as e:
        print(f"  ❌ FAILED: {e}")

    # Step 6: Check if 'adb shell input keyevent' works directly (no sendevent)
    print("\n" + "=" * 60)
    print("STEP 6: Test direct `adb shell input keyevent` (bypass sendevent)")
    print("=" * 60)
    try:
        await _run_adb_input(serial, "keyevent", "KEYCODE_HOME")
        print("  ✅ Direct input keyevent works")
    except RuntimeError as e:
        err = str(e)
        if "INJECT_EVENTS" in err or "SecurityException" in err:
            print(f"  ⚠️  INJECT_EVENTS permission denied (expected, falls back to sendevent)")
        else:
            print(f"  ❌ FAILED: {e}")

    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
