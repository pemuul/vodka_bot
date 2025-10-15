"""OCR helper that keeps EasyOCR in a dedicated long-lived subprocess."""

from __future__ import annotations

import atexit
import logging
import os
import queue
import threading
import time
import uuid
from multiprocessing import Process, Queue, get_context
from pathlib import Path
from typing import Any, Iterable

__all__ = ["extract_text", "release_reader", "OCRWorkerError"]

_DEFAULT_LANGUAGES: tuple[str, ...] = ("ru", "en")
_DEFAULT_TIMEOUT: float = float(os.getenv("OCR_WORKER_TIMEOUT", "25"))
_FALLBACK_LANG: str = os.getenv("OCR_FALLBACK_LANG", "rus+eng")
_WORKER_READY_TIMEOUT: float = float(os.getenv("OCR_WORKER_READY_TIMEOUT", "45"))

logger = logging.getLogger(__name__)


class OCRWorkerError(RuntimeError):
    """Raised when the OCR worker fails to return a successful result."""


def _ensure_sequence(value: Iterable[str] | None) -> tuple[str, ...]:
    if value is None:
        return _DEFAULT_LANGUAGES
    return tuple(value)


def _worker_main(
    request_queue: Queue,
    response_queue: Queue,
    languages: tuple[str, ...],
) -> None:
    """Worker entry point that hosts the EasyOCR reader."""

    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")
    os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

    try:
        import easyocr  # type: ignore
    except Exception as exc:  # pragma: no cover - environment-specific
        response_queue.put({
            "kind": "fatal",
            "error": f"EasyOCRImportError: {exc.__class__.__name__}: {exc}",
        })
        return

    try:  # pragma: no cover - defensive guard around torch optional dependency
        import torch  # type: ignore

        try:
            torch.set_num_threads(1)
        except Exception:
            pass
    except Exception:
        pass

    try:
        reader = easyocr.Reader(list(languages), gpu=False, verbose=False)
    except Exception as exc:  # pragma: no cover - environment-specific
        response_queue.put({
            "kind": "fatal",
            "error": f"EasyOCRError: {exc.__class__.__name__}: {exc}",
        })
        return

    response_queue.put({"kind": "ready"})

    while True:
        try:
            message = request_queue.get()
        except (EOFError, OSError):  # pragma: no cover - queue broke
            break

        if not isinstance(message, dict):
            continue

        kind = message.get("kind")
        if kind == "stop":
            break
        if kind != "ocr":
            continue

        job_id = message.get("job_id")
        image_path = message.get("path")
        if not isinstance(job_id, str) or not isinstance(image_path, str):
            response_queue.put(
                {
                    "kind": "result",
                    "job_id": job_id,
                    "success": False,
                    "error": "invalid job payload",
                }
            )
            continue

        try:
            lines = reader.readtext(image_path, detail=0)
            text = "\n".join(map(str, lines))
            response_queue.put(
                {
                    "kind": "result",
                    "job_id": job_id,
                    "success": True,
                    "text": text,
                }
            )
        except Exception as exc:  # pragma: no cover - native libs safety
            response_queue.put(
                {
                    "kind": "result",
                    "job_id": job_id,
                    "success": False,
                    "error": f"{exc.__class__.__name__}: {exc}",
                }
            )


class _EasyOCRManager:
    """Manage a dedicated EasyOCR subprocess and route jobs to it."""

    def __init__(self, languages: Iterable[str] | None = None) -> None:
        self._languages = _ensure_sequence(languages)
        self._ctx = get_context("spawn")
        self._request_queue: Queue | None = None
        self._response_queue: Queue | None = None
        self._process: Process | None = None
        self._lock = threading.Lock()
        atexit.register(self.close)

    # ------------------------------------------------------------------ utils
    def _terminate_process(self) -> None:
        process = self._process
        request_queue = self._request_queue
        response_queue = self._response_queue

        self._process = None
        self._request_queue = None
        self._response_queue = None

        if request_queue is not None:
            try:
                request_queue.put_nowait({"kind": "stop"})
            except Exception:
                pass
            try:
                request_queue.cancel_join_thread()
            except Exception:
                pass
            try:
                request_queue.close()
            except Exception:
                pass

        if process is not None:
            process.join(timeout=5)
            if process.is_alive():  # pragma: no cover - defensive
                process.terminate()
                process.join(timeout=5)

        if response_queue is not None:
            try:
                response_queue.cancel_join_thread()
            except Exception:
                pass
            try:
                response_queue.close()
            except Exception:
                pass

    def close(self) -> None:
        with self._lock:
            self._terminate_process()

    # ----------------------------------------------------------------- startup
    def _start_worker(self) -> None:
        if self._process is not None and self._process.is_alive():
            return

        self._terminate_process()

        self._request_queue = self._ctx.Queue()
        self._response_queue = self._ctx.Queue()
        self._process = self._ctx.Process(
            target=_worker_main,
            args=(self._request_queue, self._response_queue, self._languages),
            daemon=True,
        )
        self._process.start()

        if not self._await_ready():
            raise OCRWorkerError("failed to start EasyOCR worker")

    def _await_ready(self) -> bool:
        if self._response_queue is None:
            return False

        deadline = time.monotonic() + _WORKER_READY_TIMEOUT
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._terminate_process()
                return False
            try:
                message = self._response_queue.get(timeout=remaining)
            except queue.Empty:
                continue

            if not isinstance(message, dict):
                continue

            kind = message.get("kind")
            if kind == "ready":
                return True
            if kind == "fatal":
                self._terminate_process()
                error_text = message.get("error", "worker failed to start")
                raise OCRWorkerError(error_text)

    # ------------------------------------------------------------------ public
    def run(self, image_path: str, timeout: float) -> tuple[bool, str]:
        with self._lock:
            self._start_worker()
            if self._request_queue is None or self._response_queue is None:
                raise OCRWorkerError("EasyOCR worker queues unavailable")

            job_id = uuid.uuid4().hex
            self._request_queue.put({"kind": "ocr", "job_id": job_id, "path": image_path})

            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._handle_failure("timeout waiting for worker response")
                    raise TimeoutError(f"timeout after {timeout} seconds")

                try:
                    message: dict[str, Any] = self._response_queue.get(timeout=remaining)
                except queue.Empty:
                    if self._process is None or not self._process.is_alive():
                        self._handle_failure("worker exited unexpectedly")
                        raise OCRWorkerError("EasyOCR worker exited unexpectedly")
                    continue

                kind = message.get("kind")
                if kind == "result":
                    if message.get("job_id") != job_id:
                        logger.debug(
                            "Ignoring OCR result for stale job %s (expected %s)",
                            message.get("job_id"),
                            job_id,
                        )
                        continue
                    success = bool(message.get("success"))
                    payload = message.get("text") if success else message.get("error", "")
                    return success, str(payload or "")

                if kind == "fatal":
                    error_text = message.get("error", "EasyOCR worker failure")
                    self._handle_failure(error_text)
                    raise OCRWorkerError(error_text)

                if kind == "ready":  # stray handshake after restart
                    continue

    def _handle_failure(self, reason: str) -> None:
        logger.warning("Restarting EasyOCR worker: %s", reason)
        self._terminate_process()


_manager = _EasyOCRManager()


def _fallback_with_tesseract(path: Path, reason: str | None = None) -> str | None:
    """Attempt to extract text with pytesseract if EasyOCR is unavailable."""

    try:
        import pytesseract  # type: ignore
    except Exception as exc:  # pragma: no cover - environment specific
        logger.warning(
            "EasyOCR worker failed (%s) and pytesseract is not available: %s",
            reason or "unknown reason",
            exc,
        )
        return None

    try:
        import cv2  # type: ignore
    except Exception as exc:  # pragma: no cover - OpenCV should be present
        logger.warning(
            "EasyOCR worker failed (%s) and OpenCV is unavailable for fallback: %s",
            reason or "unknown reason",
            exc,
        )
        return None

    image = cv2.imread(str(path))
    if image is None:
        logger.warning(
            "EasyOCR worker failed (%s) and fallback image load failed for %s",
            reason or "unknown reason",
            path,
        )
        return None

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    try:
        text = pytesseract.image_to_string(gray, lang=_FALLBACK_LANG)
    except pytesseract.pytesseract.TesseractNotFoundError as exc:  # type: ignore[attr-defined]
        logger.warning(
            "EasyOCR worker failed (%s) and Tesseract binary is missing: %s",
            reason or "unknown reason",
            exc,
        )
        return None
    except pytesseract.pytesseract.TesseractError as exc:  # type: ignore[attr-defined]
        logger.warning(
            "EasyOCR worker failed (%s); pytesseract returned an error: %s",
            reason or "unknown reason",
            exc,
        )
        return None
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.warning(
            "EasyOCR worker failed (%s); unexpected pytesseract error: %s",
            reason or "unknown reason",
            exc,
        )
        return None

    logger.info(
        "EasyOCR worker failed (%s); successfully used pytesseract fallback for %s",
        reason or "unknown reason",
        path,
    )
    return text


def extract_text(image_path: str, timeout: float | None = None) -> str:
    """Extract text from *image_path* using the managed EasyOCR worker."""

    timeout = timeout if timeout is not None else _DEFAULT_TIMEOUT
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")

    try:
        success, payload = _manager.run(str(path), timeout)
    except TimeoutError:
        fallback_text = _fallback_with_tesseract(path, "timeout")
        if fallback_text is not None:
            return fallback_text
        raise
    except OCRWorkerError as exc:
        fallback_text = _fallback_with_tesseract(path, str(exc))
        if fallback_text is not None:
            return fallback_text
        raise

    if success:
        return payload

    fallback_text = _fallback_with_tesseract(path, payload)
    if fallback_text is not None:
        return fallback_text

    raise OCRWorkerError(payload)


def release_reader() -> None:  # pragma: no cover - kept for backward compat
    """No-op placeholder kept for compatibility with previous interface."""

    return None
