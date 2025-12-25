from aiogram import Router,  F
import asyncio
import json
import logging
import math
import os
import re
import threading
from aiogram.types import Message
import time
import random
import uuid
import multiprocessing as mp
import signal
import sys
import urllib.parse
from pathlib import Path
from typing import Any
from fns_api import get_receipt_by_qr
import queue

#from sql_mgt import sql_mgt.get_param, sql_mgt.set_param, sql_mgt.append_param_get_old
import sql_mgt
#from keys import ADMIN_ID_LIST
from heandlers import import_files, admin
from keyboards import admin_kb

import cv2
try:
    # Снижаем количество потоков в OpenCV, чтобы уменьшить количество арен glibc
    cv2.setNumThreads(1)
except Exception:
    pass

try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    psutil = None
from pyzbar.pyzbar import decode, ZBarSymbol
# optional ZXing libraries may provide more robust QR reading
# OCR helper based on Tesseract with Russian and English models
from ocr import extract_text, release_reader


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}



router = Router()
logger = logging.getLogger(__name__)
global_objects = None
UPLOAD_DIR_CHECKS = Path(__file__).resolve().parent.parent / "site_bot" / "static" / "uploads"
UPLOAD_DIR_CHECKS.mkdir(parents=True, exist_ok=True)
WECHAT_MODELS_DIR = Path(__file__).resolve().parent.parent / "wechat_qrcode"
_WECHAT_LOCK = threading.Lock()
_WECHAT_DETECTOR: Any | None = None
_WECHAT_INIT_FAILED = False
_OCR_FORCE_RELEASE = _env_flag("OCR_FORCE_RELEASE", default=False)
# По умолчанию запускаем OCR в отдельном процессе, чтобы после каждого чека
# память, занятая EasyOCR/PyTorch, гарантированно возвращалась системе.
_OCR_IN_SUBPROCESS = _env_flag("OCR_IN_SUBPROCESS", default=True)
_OCR_SUBPROCESS_TIMEOUT = int(os.getenv("OCR_SUBPROCESS_TIMEOUT", "45"))


def init_object(global_objects_inp):
    global global_objects

    global_objects = global_objects_inp
    import_files.init_object(global_objects_inp)
    admin.init_object(global_objects_inp)
    sql_mgt.init_object(global_objects_inp)


def _collect_memory_usage() -> dict[str, int] | None:
    """Return memory statistics for the current process in bytes."""

    if psutil is not None:
        try:
            process = psutil.Process()
            with process.oneshot():
                mem_info = process.memory_info()
            return {"rss": mem_info.rss, "vms": mem_info.vms}
        except Exception:
            logger.exception("[QR] Failed to query memory usage via psutil")

    try:
        import resource  # type: ignore

        usage = resource.getrusage(resource.RUSAGE_SELF)
        rss_bytes = usage.ru_maxrss
        if os.name != "nt":
            rss_bytes *= 1024
        return {"rss": int(rss_bytes)}
    except Exception:
        logger.exception("[QR] Failed to query memory usage via resource module")
    return None


def _format_bytes(num_bytes: int) -> str:
    if num_bytes <= 0:
        return "0.00 МБ"
    magnitude = math.log(num_bytes, 1024) if num_bytes else 0
    unit_index = max(0, min(int(magnitude), 3))
    units = ["Б", "КБ", "МБ", "ГБ"]
    scaled = num_bytes / (1024 ** unit_index)
    return f"{scaled:.2f} {units[unit_index]}"


def _log_memory_usage(context: str) -> None:
    stats = _collect_memory_usage()
    if not stats:
        return
    rss = _format_bytes(stats["rss"])
    vms = stats.get("vms")
    if vms is not None:
        logger.info("[QR] Memory usage (%s): RSS=%s, VMS=%s", context, rss, _format_bytes(vms))
    else:
        logger.info("[QR] Memory usage (%s): RSS=%s", context, rss)


def release_ocr_resources(force: bool = False) -> None:
    """Release cached OCR models to lower the process memory footprint."""

    if not force and not _OCR_FORCE_RELEASE:
        logger.debug("[QR] OCR ресурсы оставлены в памяти (force=%s)", force)
        return

    logger.info("[QR] Releasing OCR resources (before)")
    _log_memory_usage("before-release")
    try:
        release_reader()
    except Exception:
        logger.exception("[QR] Failed to release OCR resources")
    else:
        logger.info("[QR] OCR resources released")
    _log_memory_usage("after-release")


def _release_wechat_resources() -> None:
    """Сбросить кешированный WeChat-детектор и вернуть память ОС."""

    global _WECHAT_DETECTOR
    with _WECHAT_LOCK:
        _WECHAT_DETECTOR = None
    try:
        import ctypes

        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass


def _worker_log(token: str, message: str) -> None:
    """Append verbose debug information for the OCR subprocess."""

    logger.info("[OCR-WORKER][%s] %s", token, message)


def _worker_log_memory(token: str, stage: str) -> None:
    """Log RSS/VMS information from inside the OCR subprocess."""

    rss = None
    vms = None
    try:
        import psutil  # type: ignore

        process = psutil.Process()
        with process.oneshot():
            info = process.memory_info()
        rss = info.rss
        vms = info.vms
    except Exception:
        try:
            import resource  # type: ignore

            usage = resource.getrusage(resource.RUSAGE_SELF)
            rss = usage.ru_maxrss * (1024 if os.name != "nt" else 1)
        except Exception:
            pass

    if rss is not None:
        if vms is not None:
            _worker_log(token, f"memory:{stage}:rss={rss} vms={vms}")
        else:
            _worker_log(token, f"memory:{stage}:rss={rss}")
    else:
        _worker_log(token, f"memory:{stage}:unavailable")


def _ocr_subprocess_init() -> None:
    """Инициализация подпроцесса OCR с ограничением потоков."""

    import logging
    import os
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[1]
    logger.info("[OCR-WORKER][init] chdir to %s", project_root)
    try:
        os.chdir(project_root)
    except Exception:
        logger.exception("[OCR-WORKER][init] failed to chdir", exc_info=True)
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
        logger.info("[OCR-WORKER][init] sys.path updated with %s", project_root)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
        force=True,
    )

    os.environ.setdefault("TORCH_NUM_THREADS", "1")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    logger.info("[OCR-WORKER][init] thread limits applied")
    try:
        import cv2 as _cv2  # type: ignore

        _cv2.setNumThreads(1)
    except Exception:
        logger.exception("[OCR-WORKER][init] failed to limit cv2 threads", exc_info=True)


def _ocr_worker_job(path: str, keywords: list[str], log_token: str) -> tuple[bool, str | None]:
    """Работаем в отдельном процессе: читаем текст и ищем ключевые слова."""

    from ocr import extract_text as _extract_text, release_reader as _release_reader

    _worker_log(log_token, "worker-enter")
    _worker_log(log_token, f"worker-start path={path}")
    _worker_log_memory(log_token, "start")

    if not keywords:
        _worker_log(log_token, "keywords-empty")
        return False, "ключевые слова не настроены"

    image_path = Path(path)
    if not image_path.exists():
        _worker_log(log_token, "image-missing")
        return False, "изображение не найдено"

    try:
        _worker_log(log_token, "extract-text:start")
        text = _extract_text(str(image_path))
        _worker_log(log_token, f"extract-text:done length={len(text)}")
        _worker_log(log_token, f"extract-text:excerpt={_log_excerpt(text)}")
        _worker_log_memory(log_token, "after-extract")
    except FileNotFoundError:
        _worker_log(log_token, "extract-text:error file-not-found")
        return False, "изображение не найдено"
    except ValueError:
        _worker_log(log_token, "extract-text:error unreadable")
        return False, "изображение не прочитано"
    finally:
        try:
            _release_reader()
        except Exception as cleanup_exc:
            _worker_log(log_token, f"release-reader:error {cleanup_exc}")
        else:
            _worker_log(log_token, "release-reader:done")
            _worker_log_memory(log_token, "after-release")

    lower = text.casefold()
    vodka = any(k in lower for k in keywords)
    if vodka:
        _worker_log(log_token, f"keywords:found={vodka}")
    else:
        try:
            _worker_log(log_token, "extract-text-fallback:start langs=ru,en")
            text_fb = _extract_text(str(image_path), languages=("ru", "en"))
            _worker_log(log_token, f"extract-text-fallback:done length={len(text_fb)}")
            _worker_log(log_token, f"extract-text-fallback:excerpt={_log_excerpt(text_fb)}")
            vodka = any(k in text_fb.casefold() for k in keywords)
            _worker_log(log_token, f"keywords:found={vodka} (fallback ru+en)")
        except Exception as exc:
            _worker_log(log_token, f"extract-text-fallback:error {exc}")
            pass
    if not vodka:
        _worker_log(log_token, "keywords:found=False")
    _worker_log_memory(log_token, "after-keywords")
    _worker_log(log_token, "worker-exit")
    return vodka, None


def _ocr_worker_entry(path: str, keywords: list[str], result_queue, log_token: str) -> None:
    """Точка входа подпроцесса OCR."""

    import traceback

    try:
        _ocr_subprocess_init()
        _worker_log(log_token, "subprocess:init-done")
        result = _ocr_worker_job(path, keywords, log_token)
    except Exception as exc:
        tb_short = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        tb_tail = "".join(traceback.format_exc(limit=2)).strip()
        _worker_log(log_token, f"exception: {tb_short}")
        _worker_log(log_token, tb_tail)
        result_queue.put(("error", f"ошибка OCR: {tb_short} | {tb_tail}"))
    else:
        _worker_log(log_token, "worker-success")
        result_queue.put(("ok", result))
    finally:
        _worker_log(log_token, "subprocess-exit")


def _run_ocr_subprocess(path: str, keywords: list[str]) -> tuple[bool, str | None]:
    """Запустить OCR в отдельном процессе и вернуть результат."""

    ctx = mp.get_context("spawn")
    result_queue = ctx.Queue()
    log_token = f"{Path(path).stem}:{uuid.uuid4().hex[:8]}"
    logger.info("[QR] OCR subprocess token: %s", log_token)
    process = ctx.Process(target=_ocr_worker_entry, args=(path, keywords, result_queue, log_token))
    process.start()
    logger.info("[OCR-SUBPROC][%s] started pid=%s", log_token, process.pid)

    try:
        process.join(_OCR_SUBPROCESS_TIMEOUT)
        if process.is_alive():
            logger.warning("[OCR-SUBPROC][%s] timeout exceeded, terminating", log_token)
            process.terminate()
            process.join()
            return False, "распознавание превысило лимит времени"

        exit_code = process.exitcode
        logger.info("[OCR-SUBPROC][%s] finished exit_code=%s", log_token, exit_code)

        try:
            status, payload = result_queue.get(timeout=5)
        except queue.Empty:
            if exit_code is None:
                return False, f"ошибка OCR: результат не получен от подпроцесса (token={log_token})"
            if exit_code < 0:
                sig_num = -exit_code
                try:
                    sig_name = signal.Signals(sig_num).name
                    reason = f"сигнал {sig_name}"
                except ValueError:
                    reason = f"сигнал {sig_num}"
            else:
                reason = f"код {exit_code}"
            return False, f"ошибка OCR: подпроцесс завершился ({reason}); token={log_token}"

        if status == "ok":
            vodka, error = payload
            logger.info("[OCR-SUBPROC][%s] result-ok vodka=%s error=%s", log_token, vodka, error)
            return vodka, error
        logger.warning("[OCR-SUBPROC][%s] result-error payload=%s", log_token, payload)
        return False, f"{payload}; token={log_token}"
    finally:
        try:
            result_queue.close()
        except Exception:
            pass
        try:
            result_queue.join_thread()
        except Exception:
            pass
        logger.info("[OCR-SUBPROC][%s] resources cleaned", log_token)


def _detect_qr(path: str) -> str | None:
    """Detect QR code, returning its payload if any."""
    logger.info("[QR] Starting detection for %s", path)
    _log_memory_usage("detect_qr:start")
    img = cv2.imread(path)
    if img is None:
        logger.warning("[QR] Failed to read image %s", path)
        return None

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    candidates: list[str] = []

    # 1) Сначала пробуем WeChat и собираем все варианты
    wechat_candidates = _decode_with_wechat(img)
    if wechat_candidates:
        candidates.extend(wechat_candidates)
        selected = _select_qr_candidate(wechat_candidates, accept_fallback=False)
        logger.info("[QR] WeChat candidates: %s; selected=%s", wechat_candidates, selected)
        if selected:
            return selected

    # 2) Базовый pyzbar
    decoded_objects = decode(gray, symbols=[ZBarSymbol.QRCODE])
    if decoded_objects:
        pyzbar_candidates = [obj.data.decode("utf-8") for obj in decoded_objects if obj.data]
        candidates.extend(pyzbar_candidates)
        selected = _select_qr_candidate(pyzbar_candidates, accept_fallback=False)
        logger.info("[QR] pyzbar candidates: %s; selected=%s", pyzbar_candidates, selected)
        if selected:
            return selected

    # 3) OpenCV detector (multi + single)
    detector = cv2.QRCodeDetector()
    detect_multi = getattr(detector, "detectAndDecodeMulti", None)
    if callable(detect_multi):
        try:
            multi_data, multi_points, _ = detector.detectAndDecodeMulti(gray)
        except Exception:
            multi_data, multi_points = [], None
        if multi_points is not None:
            cv_multi = [str(item).strip() for item in multi_data if item]
            candidates.extend(cv_multi)
            selected = _select_qr_candidate(cv_multi, accept_fallback=False)
            logger.info("[QR] cv2 detectAndDecodeMulti candidates: %s; selected=%s", cv_multi, selected)
            if selected:
                return selected
    try:
        data, points, _ = detector.detectAndDecode(gray)
    except Exception:
        data, points = None, None
    if points is not None and data:
        decoded = data.strip()
        candidates.append(decoded)
        selected = _select_qr_candidate([decoded], accept_fallback=False)
        logger.info("[QR] cv2.QRCodeDetector single candidate=%s; selected=%s", decoded, selected)
        if selected:
            return selected

    _log_memory_usage("detect_qr:post-basic")

    # 4) Усиленный проход + ZXing fallback
    _log_memory_usage("detect_qr:pre-enhanced")
    enhanced = _enhanced_qr(gray)
    if enhanced:
        candidates.append(enhanced)
        selected = _select_qr_candidate([enhanced], accept_fallback=False)
        logger.info("[QR] enhanced candidate=%s; selected=%s", enhanced, selected)
        if selected:
            return selected

    _log_memory_usage("detect_qr:after-enhanced")

    # 5) Финальный выбор: предпочитаем фискальные, иначе берём первый найденный
    final_choice = _select_qr_candidate(candidates, accept_fallback=True)
    if candidates:
        logger.info("[QR] Collected QR candidates (deduped): %s", list(dict.fromkeys(candidates)))
    if final_choice:
        if _looks_like_fns_qr(final_choice):
            logger.info("[QR] Selected fiscal candidate=%s", final_choice)
        else:
            logger.info("[QR] Selected non-fiscal candidate=%s (will be validated later)", final_choice)
    else:
        logger.info("[QR] QR not detected by any method")
    return final_choice


def _select_qr_candidate(candidates: list[str], accept_fallback: bool) -> str | None:
    """Choose the most plausible QR payload among candidates.

    Preference:
    1. Первое значение, похожее на фискальный QR (ключи t,s,fn,i,fp,n).
    2. При включённом accept_fallback — первое непустое значение.
    """
    seen = set()
    valids: list[str] = []
    others: list[str] = []
    for raw in candidates:
        if not raw:
            continue
        candidate = raw.strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        if _looks_like_fns_qr(candidate):
            valids.append(candidate)
        else:
            others.append(candidate)
    if valids:
        return valids[0]
    if accept_fallback and others:
        return others[0]
    return None


def _looks_like_fns_qr(payload: str) -> bool:
    """Heuristic: check that QR string contains fiscal params before sending to FNS."""
    if not payload:
        return False
    normalized = payload.strip()
    if "?" in normalized:
        normalized = normalized.split("?", 1)[1]
    parts = urllib.parse.parse_qs(normalized, keep_blank_values=True)
    required = ("t", "s", "fn", "i", "fp", "n")
    if not all(key in parts and parts[key] and parts[key][0].strip() for key in required):
        return False
    ts = parts["t"][0].strip()
    if not re.match(r"^\d{8}T\d{4}$", ts):
        return False
    amount_raw = parts["s"][0].replace(",", ".").strip()
    try:
        float(amount_raw)
    except Exception:
        return False
    for key in ("fn", "i", "fp", "n"):
        value = parts[key][0].strip()
        if not value.isdigit():
            return False
    return True


def _check_keywords_with_ocr(path: str, keywords: list[str]) -> tuple[bool, str | None]:
    """Use OCR to search for configured keywords inside receipt image."""

    logger.info("[OCR-TRACE] start path=%s keywords=%s", path, keywords)
    if not keywords:
        logger.info("[OCR-TRACE] keywords missing")
        return False, "ключевые слова не настроены"
    if not Path(path).exists():
        logger.info("[OCR-TRACE] image missing at path=%s", path)
        return False, "изображение не найдено"

    # Освобождаем ресурсы WeChat, чтобы освободить память перед EasyOCR
    _release_wechat_resources()
    _log_memory_usage("ocr:before-readtext")

    if _OCR_IN_SUBPROCESS:
        logger.info("[OCR-TRACE] invoking subprocess for OCR")
        vodka, error = _run_ocr_subprocess(path, keywords)
        _log_memory_usage("ocr:after-readtext")
        logger.info("[OCR-TRACE] subprocess result vodka=%s error=%s", vodka, error)
        return vodka, error

    # Этот путь используется только если отключён подпроцесс
    logger.info("[OCR-TRACE] running OCR inline")
    try:
        text = extract_text(path)
        logger.info("[OCR-TRACE] ocr-text length=%s excerpt=%s", len(text), _log_excerpt(text))
    except FileNotFoundError:
        logger.warning("[QR] OCR image missing: %s", path)
        return False, "изображение не найдено"
    except ValueError:
        logger.warning("[QR] OCR image not readable: %s", path)
        return False, "изображение не прочитано"
    except Exception:
        logger.exception("[QR] Unexpected OCR failure for %s", path)
        return False, "ошибка OCR"
    _log_memory_usage("ocr:after-readtext")

    lower = text.casefold()
    vodka = any(k in lower for k in keywords)
    if vodka:
        logger.info("[OCR-TRACE] inline result vodka=%s", vodka)
    else:
        try:
            logger.info("[OCR-TRACE] inline fallback OCR langs=ru,en start")
            text_fb = extract_text(path, languages=("ru", "en"))
            logger.info("[OCR-TRACE] inline fallback ocr-text length=%s excerpt=%s", len(text_fb), _log_excerpt(text_fb))
            vodka = any(k in text_fb.casefold() for k in keywords)
            logger.info("[OCR-TRACE] inline result vodka=%s (fallback ru+en)", vodka)
        except Exception:
            logger.exception("[QR] Inline OCR fallback failed for %s", path)
            logger.info("[OCR-TRACE] inline result vodka=%s (fallback exception)", vodka)
    return vodka, None


def _enhanced_qr(gray):
    """Attempt to decode difficult QR codes by rotating, scaling,
    thresholding, and using optional ZXing-based readers."""
    logger.info("[QR] Entering enhanced QR detection")
    _log_memory_usage("enhanced:entry")
    detector = cv2.QRCodeDetector()
    rotate_codes = [None, cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180, cv2.ROTATE_90_COUNTERCLOCKWISE]
    for rc in rotate_codes:
        img = gray if rc is None else cv2.rotate(gray, rc)
        up = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_LINEAR)
        for processed in (
            up,
            cv2.adaptiveThreshold(
                up, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 2
            ),
        ):
            decoded = decode(processed, symbols=[ZBarSymbol.QRCODE])
            if decoded:
                data = decoded[0].data.decode("utf-8")
                logger.info("[QR] Enhanced pyzbar success (rotation=%s): %s", rc, data)
                return data
            data, points, _ = detector.detectAndDecode(processed)
            if points is not None and data:
                decoded = data.strip()
                logger.info("[QR] Enhanced cv2 detector success (rotation=%s): %s", rc, decoded)
                return decoded
        _log_memory_usage(f"enhanced:after-rotation-{rc}")
    try:
        import zxingcpp  # type: ignore
        logger.info("[QR] Trying ZXingCPP reader")
        results = zxingcpp.read_barcodes(gray)
        if results:
            data = results[0].text
            logger.info("[QR] ZXingCPP success: %s", data)
            return data
    except Exception:
        pass
    try:
        from pyzxing import BarCodeReader  # type: ignore
        logger.info("[QR] Trying pyzxing reader")
        reader = BarCodeReader()
        res = reader.decode_array(gray)
        if res and 'parsed' in res[0]:
            data = res[0]['parsed']
            logger.info("[QR] pyzxing success: %s", data)
            return data
    except Exception:
        logger.exception("[QR] pyzxing reader failed")
        pass
    _log_memory_usage("enhanced:exit")
    logger.info("[QR] QR not detected by any method")
    return None


def _init_wechat_detector_locked() -> Any | None:
    """Initialize and cache the WeChat QR detector inside the lock."""
    global _WECHAT_DETECTOR, _WECHAT_INIT_FAILED
    if _WECHAT_INIT_FAILED:
        return None
    if _WECHAT_DETECTOR is not None:
        return _WECHAT_DETECTOR
    ctor = getattr(cv2, "wechat_qrcode_WeChatQRCode", None)
    if ctor is None:
        logger.info("[QR] OpenCV contrib module 'wechat_qrcode' is not available")
        _WECHAT_INIT_FAILED = True
        return None
    models = {
        "detect.prototxt": WECHAT_MODELS_DIR / "detect.prototxt",
        "detect.caffemodel": WECHAT_MODELS_DIR / "detect.caffemodel",
        "sr.prototxt": WECHAT_MODELS_DIR / "sr.prototxt",
        "sr.caffemodel": WECHAT_MODELS_DIR / "sr.caffemodel",
    }
    missing = [name for name, path in models.items() if not path.exists()]
    if missing:
        logger.warning("[QR] Missing WeChat QR models: %s", ", ".join(missing))
        _WECHAT_INIT_FAILED = True
        return None
    try:
        _WECHAT_DETECTOR = ctor(
            str(models["detect.prototxt"]),
            str(models["detect.caffemodel"]),
            str(models["sr.prototxt"]),
            str(models["sr.caffemodel"]),
        )
    except Exception as exc:  # pragma: no cover - OpenCV specific failures
        logger.warning("[QR] Failed to initialize WeChat QR detector: %s", exc)
        _WECHAT_INIT_FAILED = True
        return None
    return _WECHAT_DETECTOR


def _decode_with_wechat(img) -> list[str]:
    """Try to decode QR codes using the WeChat QR detector, returning all hits."""
    global _WECHAT_INIT_FAILED
    if _WECHAT_INIT_FAILED:
        return []

    with _WECHAT_LOCK:
        if _init_wechat_detector_locked() is None:
            return []

    rotations = [("original", img)]
    for rc, label in (
        (cv2.ROTATE_90_CLOCKWISE, "rot90"),
        (cv2.ROTATE_180, "rot180"),
        (cv2.ROTATE_90_COUNTERCLOCKWISE, "rot270"),
    ):
        try:
            rotations.append((label, cv2.rotate(img, rc)))
        except Exception:
            continue

    scales = (1.0, 1.3, 1.6, 2.0)
    candidates: list[str] = []
    for label, frame in rotations:
        for scale in scales:
            with _WECHAT_LOCK:
                detector = _init_wechat_detector_locked()
                if detector is None:
                    return []
                try:
                    detector.setScaleFactor(float(scale))
                except Exception:
                    pass
                try:
                    decoded, _points = detector.detectAndDecode(frame)
                except Exception:
                    decoded = []
            candidates.extend(_collect_wechat_results(decoded))

        try:
            upscaled = cv2.resize(frame, None, fx=1.8, fy=1.8, interpolation=cv2.INTER_CUBIC)
        except Exception:
            continue
        with _WECHAT_LOCK:
            detector = _init_wechat_detector_locked()
            if detector is None:
                return []
            try:
                detector.setScaleFactor(1.0)
            except Exception:
                pass
            try:
                decoded, _points = detector.detectAndDecode(upscaled)
            except Exception:
                decoded = []
        candidates.extend(_collect_wechat_results(decoded))

    if candidates:
        logger.info("[QR] WeChat collected candidates: %s", candidates)
    return candidates


def _collect_wechat_results(decoded) -> list[str]:
    """Normalize WeChat output (str or list) to a list of unique strings."""
    if not decoded:
        return []
    if isinstance(decoded, (list, tuple)):
        return [str(candidate).strip() for candidate in decoded if str(candidate).strip()]
    value = str(decoded).strip()
    return [value] if value else []


def _log_excerpt(text: str, limit: int = 400) -> str:
    """Return a sanitized excerpt of OCR text for logs."""
    if text is None:
        return "<none>"
    safe = text.replace("\n", "\\n").replace("\r", "\\r")
    if len(safe) > limit:
        return f"{safe[:limit]}… (truncated, total={len(safe)})"
    return safe


def _truncate_payload(payload: object, limit: int = 1500) -> str:
    """Serialize payload objects for logging without flooding the console."""

    try:
        if isinstance(payload, str):
            text = payload
        else:
            text = json.dumps(payload, ensure_ascii=False, default=str)
    except Exception:
        text = repr(payload)
    if len(text) > limit:
        return f"{text[:limit]}… (truncated)"
    return text


def _format_money_value(value: object) -> str:
    """Return a readable representation for monetary values."""

    if value in (None, ""):
        return ""
    try:
        amount = float(value)
    except Exception:
        return str(value)
    if math.isfinite(amount):
        rounded = round(amount, 2)
        text = f"{rounded:.2f}₽"
        int_amount = int(round(amount))
        if abs(amount - int_amount) < 1e-6 and int_amount % 100 == 0 and int_amount:
            text = f"{int_amount / 100:.2f}₽ ({int_amount} коп.)"
        return text
    return str(value)


def _format_receipt_items(items: list[dict]) -> str:
    """Return a readable summary for items inside an FNS receipt."""

    summary = []
    for item in items:
        name = str(item.get("name", "")).strip() or "<без названия>"
        quantity = item.get("quantity") or item.get("qty") or 0
        price = item.get("price")
        total = item.get("sum")
        if price is None and total is not None and quantity:
            try:
                price = float(total) / float(quantity)
            except Exception:
                price = None
        parts = [name]
        try:
            qty_val = float(quantity)
            parts.append(f"x{qty_val:g}")
        except Exception:
            if quantity:
                parts.append(f"x{quantity}")
        if price is not None:
            parts.append(f"цена={_format_money_value(price)}")
        if total is not None:
            parts.append(f"сумма={_format_money_value(total)}")
        summary.append("; ".join(parts))
    return ", ".join(summary) if summary else "<товары отсутствуют>"


def _format_error_text(error: str | None, limit: int = 400) -> str | None:
    """Shorten error messages so they fit into logs and comments."""

    if not error:
        return None
    text = error.strip()
    if len(text) > limit:
        return f"{text[:limit]}…"
    return text


def _check_vodka_in_receipt(
    qr_data: str, keywords: list[str], receipt_id: int | None = None
) -> tuple[bool | None, str | None]:
    """Call FNS service and search receipt items for configured products."""

    data, error_text = get_receipt_by_qr(qr_data)
    error_text = _format_error_text(error_text)

    if data is None:
        if receipt_id is not None:
            if error_text:
                logger.warning(
                    "[QR] Receipt %s FNS ticket не получен: %s",
                    receipt_id,
                    error_text,
                )
            else:
                logger.info(
                    "[QR] Receipt %s FNS ticket отсутствует или не получен",
                    receipt_id,
                )
        return None, error_text

    if receipt_id is not None:
        logger.info(
            "[QR] Receipt %s FNS ticket payload: %s",
            receipt_id,
            _truncate_payload(data),
        )

    raw_items = (
        data.get("items")
        or data.get("content", {}).get("items")
        or data.get("document", {}).get("receipt", {}).get("items", [])
        or []
    )

    if not isinstance(raw_items, (list, tuple)):
        raw_items = [raw_items]

    items = [item for item in raw_items if isinstance(item, dict)]

    if receipt_id is not None:
        logger.info(
            "[QR] Receipt %s FNS items: %s",
            receipt_id,
            _format_receipt_items(items),
        )

    for item in items:
        name = str(item.get("name", "")).casefold()
        if any(k in name for k in keywords):
            return True, None
    return False, None


async def process_receipt(dest: Path, chat_id: int, msg_id: int, receipt_id: int):
    loop = asyncio.get_running_loop()
    keywords_raw = await sql_mgt.get_param(0, 'product_keywords') or ''
    keywords = [k.strip().casefold() for k in keywords_raw.split(';') if k.strip()]

    logger.info("[QR] Processing receipt %s from %s", receipt_id, dest)
    qr_data = await loop.run_in_executor(
        global_objects.ocr_pool,
        _detect_qr,
        str(dest),
    )
    if qr_data:
        logger.info("[QR] Receipt %s QR detected: %s", receipt_id, qr_data)
    else:
        logger.info("[QR] Receipt %s QR not detected", receipt_id)
    raw_qr_data = qr_data
    if qr_data and not _looks_like_fns_qr(qr_data):
        logger.info("[QR] Receipt %s QR looks non-fiscal, skipping FNS duplicate check/FNS call: %s", receipt_id, qr_data)
        qr_data = None
    ocr_result: tuple[bool, str | None] | None = None
    final_status: str | None = None
    comment_text: str | None = None
    fns_result: str | None = None  # "success", "no_goods", "error"
    fns_error_text: str | None = None
    notify_messages = {
        "Подтверждён": "✅ Чек подтверждён",
        "Чек уже загружен": "❌ Чек уже загружен",
        "Нет товара в чеке": "❌ В чеке не найден нужный товар",
    }
    use_vision = False
    if qr_data:
        existing = await sql_mgt.find_receipt_by_qr(qr_data)
        logger.info("[QR] Receipt %s checking duplicate status: %s", receipt_id, existing)
        if existing and existing != receipt_id:
            await sql_mgt.update_receipt_qr(receipt_id, qr_data)
            comment_text = "Бот: чек с таким QR уже загружен"
            await sql_mgt.update_receipt_status(
                receipt_id,
                "Чек уже загружен",
                comment=comment_text,
            )
            await global_objects.bot.send_message(
                chat_id,
                "❌ Чек уже загружен",
                reply_to_message_id=msg_id,
            )
            return
        await sql_mgt.update_receipt_qr(receipt_id, qr_data)
        try:
            vodka_found, fns_error_text = await loop.run_in_executor(
                None, _check_vodka_in_receipt, qr_data, keywords, receipt_id
            )
        except Exception as exc:
            logger.exception(
                "[QR] FNS check failed for receipt %s with QR %s",
                receipt_id,
                qr_data,
            )
            vodka_found = None
            fns_error_text = _format_error_text(
                f"{exc.__class__.__name__}: {exc}"
            )
        logger.info("[QR] Receipt %s FNS result: %s", receipt_id, vodka_found)
        if fns_error_text:
            logger.info(
                "[QR] Receipt %s FNS error detail: %s", receipt_id, fns_error_text
            )
        if vodka_found is None:
            fns_result = "error"
            use_vision = True
        elif vodka_found:
            fns_result = "success"
            final_status = "Подтверждён"
            comment_text = "Бот: товар найден в данных по QR"
        else:
            fns_result = "no_goods"
            final_status = "Нет товара в чеке"
            comment_text = "Бот: товар не найден в данных по QR"
    else:
        use_vision = True

    if use_vision:
        if ocr_result is None:
            ocr_result = await loop.run_in_executor(
                global_objects.ocr_pool,
                _check_keywords_with_ocr,
                str(dest),
                keywords,
            )
        vodka_by_vision, vision_error = ocr_result
        logger.info(
            "[QR] Receipt %s OCR fallback result: vodka_by_vision=%s error=%s",
            receipt_id,
            vodka_by_vision,
            vision_error,
        )
        if vodka_by_vision:
            final_status = "Подтверждён"
            if qr_data:
                if fns_result == "error":
                    detail = "ФНС недоступна"
                    if fns_error_text:
                        detail = f"ФНС недоступна: {fns_error_text}"
                    comment_text = (
                        "Бот: товар найден через распознавание изображения "
                        f"({detail})"
                    )
                else:
                    comment_text = "Бот: товар найден через распознавание изображения"
            else:
                comment_text = (
                    "Бот: товар найден через распознавание изображения (QR не распознан)"
                )
        else:
            final_status = "Ошибка"
            if vision_error == "изображение не прочитано":
                comment_text = "Бот: не удалось прочитать изображение чека"
            elif vision_error == "ключевые слова не настроены":
                comment_text = "Бот: не настроены ключевые слова для проверки чека"
            elif isinstance(vision_error, str) and vision_error.startswith("ошибка OCR"):
                comment_text = f"Бот: {vision_error}"
            elif vision_error:
                comment_text = f"Бот: {vision_error}"
            else:
                if not qr_data:
                    comment_text = (
                        "Бот: QR-код не распознан и распознавание не подтвердило чек"
                    )
                elif fns_result == "error":
                    base = "Бот: не удалось получить данные по QR"
                    if fns_error_text:
                        base = f"{base} ({fns_error_text})"
                    comment_text = f"{base} и распознавание не подтвердило чек"
                else:
                    comment_text = "Бот: распознавание не подтвердило чек"

    if final_status is None:
        final_status = "Ошибка"
    if comment_text is None:
        comment_text = f"Бот: автоматическая обработка завершилась со статусом \"{final_status}\""

    logger.info(
        "[QR] Receipt %s final status: %s (comment=%s)",
        receipt_id,
        final_status,
        comment_text,
    )
    await sql_mgt.update_receipt_status(receipt_id, final_status, comment=comment_text)

    user_message = notify_messages.get(final_status)
    if user_message:
        await global_objects.bot.send_message(
            chat_id,
            user_message,
            reply_to_message_id=msg_id,
        )


@router.message(F.photo)
async def set_photo(message: Message) -> None:
    await sql_mgt.set_param(message.chat.id, 'DELETE_LAST_MESSAGE', 'yes')

    is_get_check = await sql_mgt.get_param(message.chat.id, 'GET_CHECK')
    if is_get_check == str(True):
        if await sql_mgt.is_user_blocked(message.chat.id):
            await message.reply('Вы заблокированы и не можете участвовать в розыгрыше')
            return
        photo = message.photo[-1]
        try:
            photo_file = await global_objects.bot.download(photo.file_id)
            fname = f"{uuid.uuid4().hex}.jpg"
            dest = UPLOAD_DIR_CHECKS / fname
            with dest.open("wb") as f:
                f.write(photo_file.getvalue())

            web_path = f"/static/uploads/{fname}"
            draw_id = await sql_mgt.get_active_draw_id()
            receipt_id = await sql_mgt.add_receipt(
                web_path,
                message.chat.id,
                "В авто обработке",
                message_id=message.message_id,
                draw_id=draw_id,
            )
            await sql_mgt.enqueue_receipt_ocr(receipt_id)
            await message.reply(
                'Чек загружен и находится в статусе Проверка. Как проверка будет пройдена, мы вам сообщим.'
            )
            return
        except Exception:
            await message.reply('Ошибка при обработке чека. Попробуйте ещё раз.')
            return
    
    if not message.chat.id in global_objects.admin_list:
        await message.answer("Миленько, но что с этим делать, я не знаю) (если вы не админ)")
        return
    
    except_message_name = await sql_mgt.get_param(message.chat.id, 'EXCEPT_MESSAGE')
    if except_message_name == 'EDIT_MEDIA':
        await add_admin_media(message)
        return

    await import_files.set_new_image(message)


async def add_admin_media(message: Message, type_file:str = 'image'):
    if type_file == 'image':
        #image_name = await import_files.dowland_image(message)
        media_name = message.photo[-1].file_id + ' photo'
    elif type_file == 'video':
        #image_name = await import_files.dowland_video(message)
        media_name = message.video.file_id + ' video'
    elif type_file == 'video_file':
        media_name = message.document.file_id + ' video'

    last_path_id = await sql_mgt.get_param(message.chat.id, 'LAST_PATH_ID')
    last_message_id = await sql_mgt.get_param(message.chat.id, 'LAST_MESSAGE_ID')

    # чтобы у нас число сообщений отображалось корректно и они не попадали все разом
    delay = random.uniform(0.2, 1)
    time.sleep(delay)

    new_media_list_str = await sql_mgt.append_param_get_old(message.chat.id, 'NEW_MEDIA_LIST', media_name)

    if new_media_list_str:
        new_media_list = new_media_list_str.split(',')
    else:
        new_media_list = []

    message_text = f'Отправте фото или видео, которые будут добавлены!\nЗагружено медиа: {len(new_media_list)}'

    try:
        await global_objects.bot.edit_message_text(
            text=message_text,
            chat_id=message.chat.id,
            message_id=int(last_message_id),
            reply_markup=admin_kb.import_media_kb(last_path_id),
        )
    except Exception:
        pass
    #await callback.message.edit_text(f'Отправте фото, которые будут добавлены!\nЗагружено фото: {}', reply_markup=admin_kb.import_media_kb(callback_data.path_id), parse_mode=ParseMode.HTML)
    

@router.message(F.video)
async def set_video(message: Message) -> None:
    await sql_mgt.set_param(message.chat.id, 'DELETE_LAST_MESSAGE', 'yes')

    if not message.chat.id in global_objects.admin_list:
        await message.answer("Миленько, но что с этим делать, я не знаю) (если вы не админ)")
        return   

    except_message_name = await sql_mgt.get_param(message.chat.id, 'EXCEPT_MESSAGE')
    if except_message_name == 'EDIT_MEDIA':
        await add_admin_media(message, type_file='video')
        return

    await global_objects.bot.send_message(message.from_user.id, f"У видео id:\n{message.video.file_id}", reply_to_message_id=message.message_id)



async def set_video_file(message: Message) -> None:
    await sql_mgt.set_param(message.chat.id, 'DELETE_LAST_MESSAGE', 'yes')

    if not message.chat.id in global_objects.admin_list:
        await message.answer("Миленько, но что с этим делать, я не знаю) (если вы не админ)")
        return   

    except_message_name = await sql_mgt.get_param(message.chat.id, 'EXCEPT_MESSAGE')
    if except_message_name == 'EDIT_MEDIA':
        await add_admin_media(message, type_file='video_file')
        return

    await global_objects.bot.send_message(message.from_user.id, f"У видео id:\n{message.document.file_id}", reply_to_message_id=message.message_id)
