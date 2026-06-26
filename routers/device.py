"""Device info router — get real device information via ADB."""
import asyncio
import re
from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/device", tags=["device"])

ADB_CMD = "adb"


async def _run_cmd(*args, timeout: float = 5.0) -> str | None:
    """
    Run a shell command async, return stdout as string,
    or None on failure / timeout.
    """
    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            ),
            timeout=timeout,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return stdout.decode("utf-8", errors="replace").strip()
    except (asyncio.TimeoutError, FileNotFoundError, OSError, AttributeError):
        return None


@router.get("/info")
async def device_info(request: Request):
    """
    Get real device information.
    Returns JSON with device, resolution, adb_status, server_url,
    android_version, uiautomator2_version.
    """
    info: dict = {
        "device": "Unknown",
        "resolution": "\u2014",
        "adb_status": "disconnected",
        "server_url": str(request.base_url).rstrip("/"),
        "android_version": "\u2014",
        "uiautomator2_version": "\u2014",
    }

    # 1. ADB devices — check connection & device name
    adb_devices = await _run_cmd(ADB_CMD, "devices")
    if adb_devices:
        lines = adb_devices.strip().split("\n")
        for line in lines[1:]:
            if "\tdevice" in line or "\t" in line:
                serial = line.split("\t")[0]

                # --- Device model ---
                model = await _run_cmd(ADB_CMD, "-s", serial, "shell", "getprop", "ro.product.model")
                if not model:
                    brand = await _run_cmd(ADB_CMD, "-s", serial, "shell", "getprop", "ro.product.brand")
                    name = await _run_cmd(ADB_CMD, "-s", serial, "shell", "getprop", "ro.product.marketname")
                    if brand and name:
                        model = f"{brand.capitalize()} {name}"
                    elif brand:
                        model = brand.capitalize()
                    elif name:
                        model = name
                if model:
                    info["device"] = model

                info["adb_status"] = "connected"

                # --- Resolution (wm size) ---
                size = await _run_cmd(ADB_CMD, "-s", serial, "shell", "wm", "size")
                if size:
                    match = re.search(r"(\d+)\s*[×x]\s*(\d+)", size)
                    if match:
                        info["resolution"] = f"{match.group(1)} × {match.group(2)}"

                # --- Android version + API level ---
                version = await _run_cmd(ADB_CMD, "-s", serial, "shell", "getprop", "ro.build.version.release")
                sdk = await _run_cmd(ADB_CMD, "-s", serial, "shell", "getprop", "ro.build.version.sdk")
                if version:
                    info["android_version"] = version
                if sdk:
                    info["android_version"] += f" (API {sdk})"

                break  # first connected device

    # 2. uiautomator2 version (from pip, not ADB)
    u2ver = await _run_cmd("pip", "show", "uiautomator2")
    if u2ver:
        ver_match = re.search(r"Version:\s*(\S+)", u2ver)
        if ver_match:
            info["uiautomator2_version"] = f"v{ver_match.group(1)}"
    else:
        u2ver2 = await _run_cmd(
            "python3", "-c",
            "import uiautomator2; print(uiautomator2.__version__)"
        )
        if u2ver2:
            info["uiautomator2_version"] = f"v{u2ver2.strip()}"

    return info
