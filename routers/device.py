"""Device info router — get real device information via ADB."""
import asyncio
import re
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/device", tags=["device"])

ADB_CMD = "adb"

# ---- Request Schemas ----
class ADBPairRequest(BaseModel):
    ip: str = Field(..., pattern=r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(:\d{1,5})?$")
    port: int = Field(default=5555, ge=1, le=65535)
    pairing_code: str = Field(..., min_length=6, max_length=6)

class ADBConnectRequest(BaseModel):
    ip: str = Field(..., pattern=r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(:\d{1,5})?$")
    port: int = Field(default=5555, ge=1, le=65535)



async def _run_cmd(*args, timeout: float = 10.0, capture_stderr: bool = True) -> str | None:
    """
    Run a shell command async, return stdout as string,
    or None on failure / timeout.
    """
    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE if capture_stderr else asyncio.subprocess.DEVNULL,
            ),
            timeout=timeout,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        result = stdout.decode("utf-8", errors="replace").strip()
        if capture_stderr:
            stderr_text = stderr.decode("utf-8", errors="replace").strip()
            if stderr_text:
                result += ("\n" + stderr_text if result else stderr_text)
        return result
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


# ==================== ADB Devices ====================

@router.get("/devices")
async def list_devices():
    """
    List all ADB devices (both USB and wireless).
    Returns list of {serial, status, type}.
    """
    output = await _run_cmd(ADB_CMD, "devices", "-l")
    devices = []
    if output:
        for line in output.split("\n")[1:]:
            line = line.strip()
            if not line or "List of devices" in line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                serial = parts[0]
                status = parts[1]
                # Determine type: usb or wireless
                dev_type = "wireless" if (":" in serial and "." in serial) else "usb"
                # Extract model if available
                model = ""
                for p in parts[2:]:
                    if p.startswith("model:"):
                        model = p.replace("model:", "")
                        break
                devices.append({
                    "serial": serial,
                    "status": status,
                    "type": dev_type,
                    "model": model,
                })
    return {"devices": devices, "count": len(devices)}


# ==================== ADB Pair ====================

@router.post("/pair")
async def pair_device(req: ADBPairRequest):
    """
    Pair with a wireless debugging device using pairing code.
    Uses: adb pair <ip>:<port> <pairing_code>
    """
    target = f"{req.ip}:{req.port}"
    output = await _run_cmd(ADB_CMD, "pair", target, req.pairing_code, timeout=15.0)
    if output is None:
        raise HTTPException(status_code=500, detail="ADB command failed (is adb installed?)")
    # Check for success indicators
    if "successfully paired" in output.lower() or "success" in output.lower():
        return {"success": True, "message": f"Successfully paired with {target}", "detail": output}
    elif "already" in output.lower():
        return {"success": True, "message": f"Already paired with {target}", "detail": output}
    else:
        raise HTTPException(status_code=400, detail=output.strip() or "Pairing failed")


# ==================== ADB Connect ====================

@router.post("/connect")
async def connect_device(req: ADBConnectRequest):
    """
    Connect to a device via TCP/IP.
    Uses: adb connect <ip>:<port>
    """
    target = f"{req.ip}:{req.port}"
    output = await _run_cmd(ADB_CMD, "connect", target, timeout=15.0)
    if output is None:
        raise HTTPException(status_code=500, detail="ADB command failed (is adb installed?)")
    # Check for success
    if "connected" in output.lower() or "already connected" in output.lower():
        return {"success": True, "message": f"Connected to {target}", "detail": output}
    elif "failed" in output.lower() or "unable" in output.lower():
        raise HTTPException(status_code=400, detail=output.strip() or "Connection failed")
    else:
        return {"success": True, "message": f"Result: {output.strip()}", "detail": output}


# ==================== ADB Disconnect ====================

@router.delete("/disconnect/{target}")
async def disconnect_device(target: str):
    """
    Disconnect a remote ADB device.
    target can be 'all' or '<ip>:<port>'.
    Uses: adb disconnect <target>
    """
    if target == "all":
        output = await _run_cmd(ADB_CMD, "disconnect")
    else:
        output = await _run_cmd(ADB_CMD, "disconnect", target)
    if output is None:
        raise HTTPException(status_code=500, detail="ADB command failed (is adb installed?)")
    return {"success": True, "message": f"Disconnected {target}", "detail": output.strip()}


# ==================== Get ADB Server Info ====================

@router.get("/adb-info")
async def adb_info():
    """Get ADB version and server status."""
    version = await _run_cmd(ADB_CMD, "version")
    server_status = await _run_cmd(ADB_CMD, "get-state")
    devices_output = await _run_cmd(ADB_CMD, "devices")
    device_count = 0
    if devices_output:
        for line in devices_output.split("\n")[1:]:
            if line.strip() and "\t" in line:
                device_count += 1
    return {
        "version": version or "unknown",
        "server_state": server_status or "unknown",
        "connected_devices": device_count,
    }
