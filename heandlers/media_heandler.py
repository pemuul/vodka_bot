from aiogram import Router,  F
import asyncio
import logging
import math
import os
import threading
from aiogram.types import Message
import time
import random
import uuid
import multiprocessing as mp
import signal
import sys
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

    import os
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
    _worker_log(log_token, f"keywords:found={vodka}")
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
    decoded_objects = decode(gray, symbols=[ZBarSymbol.QRCODE])
    if decoded_objects:
        data = decoded_objects[0].data.decode("utf-8")
        logger.info("[QR] Found QR via pyzbar: %s", data)
        return data

    detector = cv2.QRCodeDetector()
    data, points, _ = detector.detectAndDecode(gray)
    if points is not None and data:
        decoded = data.strip()
        logger.info("[QR] Found QR via cv2.QRCodeDetector: %s", decoded)
        return decoded

    _log_memory_usage("detect_qr:post-basic")

    wechat_decoded = _decode_with_wechat(img)
    if wechat_decoded:
        return wechat_decoded

    _log_memory_usage("detect_qr:pre-enhanced")
    return _enhanced_qr(gray)


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
    logger.info("[OCR-TRACE] inline result vodka=%s", vodka)
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


def _decode_with_wechat(img) -> str | None:
    """Try to decode a QR code using the WeChat QR detector."""
    global _WECHAT_INIT_FAILED
    if _WECHAT_INIT_FAILED:
        return None

    with _WECHAT_LOCK:
        if _init_wechat_detector_locked() is None:
            return None

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
    for label, frame in rotations:
        for scale in scales:
            with _WECHAT_LOCK:
                detector = _init_wechat_detector_locked()
                if detector is None:
                    return None
                try:
                    detector.setScaleFactor(float(scale))
                except Exception:
                    pass
                try:
                    decoded, _points = detector.detectAndDecode(frame)
                except Exception:
                    decoded = []
            value = _first_wechat_result(decoded)
            if value:
                logger.info(
                    "[QR] Found QR via WeChat detector (%s, scaleFactor=%s): %s",
                    label,
                    scale,
                    value,
                )
                return value

        try:
            upscaled = cv2.resize(frame, None, fx=1.8, fy=1.8, interpolation=cv2.INTER_CUBIC)
        except Exception:
            continue
        with _WECHAT_LOCK:
            detector = _init_wechat_detector_locked()
            if detector is None:
                return None
            try:
                detector.setScaleFactor(1.0)
            except Exception:
                pass
            try:
                decoded, _points = detector.detectAndDecode(upscaled)
            except Exception:
                decoded = []
        value = _first_wechat_result(decoded)
        if value:
            logger.info(
                "[QR] Found QR via WeChat detector (upscaled %s): %s", label, value
            )
            return value

    return None


def _first_wechat_result(decoded) -> str | None:
    """Return the first non-empty decoded value as a stripped string."""
    if not decoded:
        return None
    if isinstance(decoded, (list, tuple)):
        for candidate in decoded:
            if candidate:
                return str(candidate).strip()
        return None
    return str(decoded).strip()


def _check_vodka_in_receipt(qr_data: str, keywords: list[str]) -> bool | None:
    """Call FNS service and search receipt items for configured products."""
    data = get_receipt_by_qr(qr_data)
    if not data:
        return None
    items = (
        data.get("items")
        or data.get("content", {}).get("items")
        or data.get("document", {}).get("receipt", {}).get("items", [])
    )
    for item in items:
        name = str(item.get("name", "")).casefold()
        if any(k in name for k in keywords):
            return True
    return False


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
    ocr_result: tuple[bool, str | None] | None = None
    final_status: str | None = None
    comment_text: str | None = None
    fns_result: str | None = None  # "success", "no_goods", "error"
    notify_messages = {
        "Подтверждён": "✅ Чек подтверждён",
        "Нет товара в чеке": "❌ Нет товара в чеке",
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
            vodka_found = await loop.run_in_executor(
                None, _check_vodka_in_receipt, qr_data, keywords
            )
        except Exception as exc:
            print(f"FNS check failed for receipt {receipt_id}: {exc}")
            vodka_found = None
        logger.info("[QR] Receipt %s FNS result: %s", receipt_id, vodka_found)
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
                    comment_text = (
                        "Бот: товар найден через распознавание изображения (ФНС недоступна)"
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
                    comment_text = (
                        "Бот: не удалось получить данные по QR и распознавание не подтвердило чек"
                    )
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
            await message.reply('Чек получен, идёт обработка...')
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