"""
Core ADB communication layer.
All ADB subprocess calls go through `run_adb()` here.
"""
import asyncio


async def run_adb(*args, timeout: float = 5.0) -> str:
    """Run an ADB command asynchronously and return stdout. Raises RuntimeError on failure."""
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


async def adb_available() -> bool:
    """Check if ADB is available and a device is connected."""
    try:
        out = await run_adb("devices", timeout=3.0)
    except RuntimeError:
        return False
    lines = out.strip().split("\n")
    for line in lines[1:]:
        if "\tdevice" in line:
            return True
    return False


async def get_device_serial() -> str | None:
    """Discover and return the first connected ADB device serial."""
    try:
        out = await run_adb("devices")
        lines = out.strip().split("\n")
        for line in lines[1:]:
            if "\tdevice" in line:
                return line.split("\t")[0]
    except RuntimeError:
        pass
    return None
