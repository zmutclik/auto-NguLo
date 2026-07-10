"""
Screenshot capture and template matching utilities.
Uses OpenCV if available, falls back to numpy + Pillow.
"""
import asyncio
import os
import tempfile
import time

try:
    import numpy as np
    _NUMPY_AVAILABLE = True
except ImportError:
    _NUMPY_AVAILABLE = False
    np = None  # type: ignore

try:
    import cv2
    _OPENCV_AVAILABLE = True
except ImportError:
    _OPENCV_AVAILABLE = False

try:
    from PIL import Image
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

if _PIL_AVAILABLE:
    try:
        from PIL import ImageFile
        ImageFile.LOAD_TRUNCATED_IMAGES = True
    except ImportError:
        pass

_TEMPLATE_MATCH_AVAILABLE = _OPENCV_AVAILABLE or (_NUMPY_AVAILABLE and _PIL_AVAILABLE)


def template_match_available() -> bool:
    """Return True if any image library is available for template matching."""
    return _TEMPLATE_MATCH_AVAILABLE


# ── Screenshot capture ──────────────────────────────────────────────

async def capture_screenshot(serial: str | None, mock_mode: bool = False,
                              save_path: str | None = None) -> str:
    """Capture a screenshot via ADB and return the local file path.
    
    Args:
        serial: ADB device serial, or None.
        mock_mode: If True, create a dummy black image instead of real capture.
        save_path: Optional explicit path to save the screenshot.
    """
    tmp_path = save_path or os.path.join(tempfile.gettempdir(), f"angulo_screen_{time.time():.0f}.png")

    if mock_mode:
        if _PIL_AVAILABLE:
            img = Image.new('RGB', (1080, 1920), color=(0, 0, 0))
            img.save(tmp_path, 'PNG')
        elif _OPENCV_AVAILABLE:
            img = np.zeros((1920, 1080, 3), dtype=np.uint8)
            cv2.imwrite(tmp_path, img)
        else:
            import struct, zlib
            def _make_minimal_png(path):
                sig = b'\x89PNG\r\n\x1a\n'
                ihdr_data = struct.pack('>IIBBBBB', 1080, 1920, 8, 2, 0, 0, 0)
                ihdr_crc = zlib.crc32(b'IHDR' + ihdr_data)
                ihdr_chunk = struct.pack('>I', 13) + b'IHDR' + ihdr_data + struct.pack('>I', ihdr_crc)
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
    from engine.adb import run_adb
    adb_prefix = ("-s", serial) if serial else ()
    try:
        await run_adb(*(adb_prefix + ("shell", "screencap", "-p", "/sdcard/angulo_tmp.png")), timeout=10.0)
        await run_adb(*(adb_prefix + ("pull", "/sdcard/angulo_tmp.png", tmp_path)), timeout=10.0)
        if os.path.isfile(tmp_path):
            file_size = os.path.getsize(tmp_path)
            if file_size < 1024:
                raise RuntimeError(f"Screenshot file too small ({file_size} bytes) — likely truncated")
        try:
            await run_adb(*(adb_prefix + ("shell", "rm", "/sdcard/angulo_tmp.png")), timeout=3.0)
        except Exception:
            pass
    except RuntimeError as e:
        raise RuntimeError(f"Failed to capture screenshot: {e}")
    return tmp_path


# ── Template matching ───────────────────────────────────────────────

def match_template_numpy(screen_path: str, template_path: str) -> tuple:
    """
    Pure numpy + Pillow template matching (TM_CCOEFF_NORMED).
    Returns (max_score: float, x: int, y: int) — top-left corner of best match.
    """
    screen_img = Image.open(screen_path).convert('L')
    template_img = Image.open(template_path).convert('L')

    screen = np.array(screen_img, dtype=np.float64)
    template = np.array(template_img, dtype=np.float64)

    th, tw = template.shape
    ih, iw = screen.shape

    rh = ih - th + 1
    rw = iw - tw + 1

    if rh <= 0 or rw <= 0:
        return (0.0, 0, 0)

    t_mean = template.mean()
    t_std = template.std()
    if t_std < 1e-10:
        return (0.0, 0, 0)
    t_norm = template - t_mean

    pad_h, pad_w = ih + th - 1, iw + tw - 1
    F_screen = np.fft.rfft2(screen, s=(pad_h, pad_w))
    F_template = np.fft.rfft2(t_norm[::-1, ::-1], s=(pad_h, pad_w))
    cross_corr = np.fft.irfft2(F_screen * F_template)

    numerator = cross_corr[th - 1: th - 1 + rh, tw - 1: tw - 1 + rw]

    integral = np.zeros((ih + 1, iw + 1))
    integral[1:, 1:] = screen.cumsum(axis=0).cumsum(axis=1)

    integral_sq = np.zeros((ih + 1, iw + 1))
    integral_sq[1:, 1:] = (screen ** 2).cumsum(axis=0).cumsum(axis=1)

    sums = (integral[th:, tw:] - integral[:rh, tw:]
            - integral[th:, :rw] + integral[:rh, :rw])
    sq_sums = (integral_sq[th:, tw:] - integral_sq[:rh, tw:]
               - integral_sq[th:, :rw] + integral_sq[:rh, :rw])

    n_pixels = th * tw
    means = sums / n_pixels
    vars_ = np.maximum(sq_sums / n_pixels - means ** 2, 0.0)
    stds = np.sqrt(vars_)

    denominator = t_std * stds * n_pixels
    valid = denominator > 1e-10

    result = np.zeros((rh, rw))
    result[valid] = numerator[valid] / denominator[valid]

    max_idx = np.argmax(result)
    max_y, max_x = divmod(max_idx, rw)
    return (float(result[max_y, max_x]), int(max_x), int(max_y))


async def match_template_on_screen(serial: str | None, template_path: str,
                                     threshold: float, mock_mode: bool = False,
                                     region: tuple = None,
                                     log_fn=None) -> tuple:
    """
    Match a template image against current screen.
    Returns (found: bool, x: float, y: float).
    x, y are the center coordinates of the match (in full-screen coords).
    """
    def _log(level, msg):
        if log_fn:
            log_fn(level, msg)

    if not _TEMPLATE_MATCH_AVAILABLE:
        _log("warn", "  ⚠️ No image library available (install opencv-python or Pillow+numpy)")
        if mock_mode:
            return (True, 540.0, 1200.0)
        return (False, 0, 0)

    template_full_path = template_path
    if not os.path.isabs(template_path):
        template_full_path = os.path.join("data", template_path)
    if not os.path.isfile(template_full_path):
        raise RuntimeError(f"Template file not found: {template_full_path}")

    screen_path = await capture_screenshot(serial, mock_mode=mock_mode)

    try:
        if _OPENCV_AVAILABLE:
            screen = cv2.imread(screen_path)
            template = cv2.imread(template_full_path)
            if screen is None:
                if _PIL_AVAILABLE:
                    screen = np.array(Image.open(screen_path).convert('RGB'))[:, :, ::-1]
                    if screen is None or screen.size == 0:
                        raise RuntimeError(f"Failed to read screenshot from {screen_path}")
                else:
                    raise RuntimeError(f"Failed to read screenshot from {screen_path}")
            if template is None:
                if _PIL_AVAILABLE:
                    template = np.array(Image.open(template_full_path).convert('RGB'))[:, :, ::-1]
                    if template is None or template.size == 0:
                        raise RuntimeError(f"Failed to read template from {template_full_path}")
                else:
                    raise RuntimeError(f"Failed to read template from {template_full_path}")

            th, tw = template.shape[:2]
            sh, sw = screen.shape[:2]

            region_offset_x, region_offset_y = 0, 0
            if region is not None:
                rx, ry, rw_, rh_ = region
                rx = max(0, int(rx))
                ry = max(0, int(ry))
                rw_ = min(int(rw_), sw - rx)
                rh_ = min(int(rh_), sh - ry)
                if rw_ <= 0 or rh_ <= 0:
                    raise RuntimeError(f"Invalid match region: ({rx},{ry},{rw_},{rh_})")
                screen = screen[ry:ry + rh_, rx:rx + rw_]
                if template.shape[0] >= ry + rh_ and template.shape[1] >= rx + rw_:
                    template = template[ry:ry + rh_, rx:rx + rw_]
                    th, tw = template.shape[:2]
                region_offset_x, region_offset_y = rx, ry
                sh, sw = screen.shape[:2]
                _log("info", f"  🔲 match region: x={rx} y={ry} w={rw_} h={rh_} (template cropped to {tw}x{th})")

            if tw > sw or th > sh:
                raise RuntimeError(f"Template ({tw}x{th}) larger than search area ({sw}x{sh})")

            result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
            _log("info", f"  📊 match score: {max_val:.4f} (threshold: {threshold:.2f})")

            if max_val >= threshold:
                cx = region_offset_x + max_loc[0] + tw / 2.0
                cy = region_offset_y + max_loc[1] + th / 2.0
                return (True, float(cx), float(cy))
            return (False, 0.0, 0.0)

        else:
            # numpy + Pillow fallback
            screen_img = Image.open(screen_path)
            template_img = Image.open(template_full_path)
            tw, th = template_img.size

            sw, sh = screen_img.size
            region_offset_x, region_offset_y = 0, 0
            template_was_cropped = False

            if region is not None:
                rx, ry, rw_, rh_ = region
                rx = max(0, int(rx))
                ry = max(0, int(ry))
                rw_ = min(int(rw_), sw - rx)
                rh_ = min(int(rh_), sh - ry)
                if rw_ <= 0 or rh_ <= 0:
                    raise RuntimeError(f"Invalid match region: ({rx},{ry},{rw_},{rh_})")
                screen_img = screen_img.crop((rx, ry, rx + rw_, ry + rh_))
                if template_img.size[0] >= rx + rw_ and template_img.size[1] >= ry + rh_:
                    template_img = template_img.crop((rx, ry, rx + rw_, ry + rh_))
                    tw, th = template_img.size
                    template_was_cropped = True
                region_offset_x, region_offset_y = rx, ry
                _log("info", f"  🔲 match region: x={rx} y={ry} w={rw_} h={rh_} (template cropped to {tw}x{th})")

            if tw > screen_img.size[0] or th > screen_img.size[1]:
                raise RuntimeError(f"Template ({tw}x{th}) larger than search area")

            screen_img.save(screen_path)
            _tmp_tpl_path = None
            if template_was_cropped:
                tmp_tpl = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                template_img.save(tmp_tpl.name)
                template_full_path = tmp_tpl.name
                _tmp_tpl_path = template_full_path

            max_val, mx, my = match_template_numpy(screen_path, template_full_path)
            _log("info", f"  📊 match score: {max_val:.4f} (threshold: {threshold:.2f})")

            if _tmp_tpl_path:
                try:
                    os.unlink(_tmp_tpl_path)
                except Exception:
                    pass

            if max_val >= threshold:
                cx = region_offset_x + mx + tw / 2.0
                cy = region_offset_y + my + th / 2.0
                return (True, float(cx), float(cy))
            return (False, 0.0, 0.0)

    finally:
        try:
            os.unlink(screen_path)
        except Exception:
            pass
