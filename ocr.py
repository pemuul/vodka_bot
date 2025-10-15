"""Run EasyOCR in a dedicated worker process to keep memory bounded."""

from __future__ import annotations

import logging
import os
import time
from multiprocessing import get_context
from pathlib import Path
from typing import Iterable, Tuple

logger = logging.getLogger(__name__)

__all__ = ["extract_text", "release_reader", "OCRWorkerError"]

_DEFAULT_LANGUAGES: Tuple[str, ...] = tuple(
    filter(None, (lang.strip() for lang in os.getenv("OCR_LANGUAGES", "ru,en").split(",")))
) or ("ru", "en")
_FALLBACK_LANG: str = os.getenv("OCR_FALLBACK_LANG", "rus+eng")
_MAX_DIMENSION: int = int(os.getenv("OCR_MAX_DIMENSION", "1600"))
_DEFAULT_TIMEOUT: float = float(os.getenv("OCR_TIMEOUT", "35"))
_WORKER_START_TIMEOUT: float = float(os.getenv("OCR_WORKER_START_TIMEOUT", "25"))

try:  # pragma: no cover - psutil не обязателен в окружении тестов
    import psutil  # type: ignore

    _PROCESS = psutil.Process()
except Exception:  # pragma: no cover
    _PROCESS = None


class OCRWorkerError(RuntimeError):
    """Raised when the EasyOCR helper process fails."""


def _log_memory(label: str) -> None:
    if _PROCESS is None:
        return
    try:
        mem = _PROCESS.memory_info().rss / (1024 * 1024)
    except Exception:  # pragma: no cover - защитная проверка
        return
    logger.info("Использование памяти (%s): RSS=%.2f МБ", label, mem)


def _ensure_languages(languages: Iterable[str] | None) -> Tuple[str, ...]:
    if languages is None:
        return _DEFAULT_LANGUAGES
    langs = tuple(lang.strip() for lang in languages if lang and lang.strip())
    return langs or _DEFAULT_LANGUAGES


def _fallback_with_tesseract(path: Path, reason: str | None = None) -> str | None:
    """Попробовать распознать текст с помощью pytesseract."""

    try:
        import pytesseract  # type: ignore
    except Exception as exc:  # pragma: no cover - pytesseract опционален
        logger.warning(
            "EasyOCR failed (%s) и pytesseract недоступен: %s",
            reason or "unknown",
            exc,
        )
        return None

    try:
        import cv2  # type: ignore
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "EasyOCR failed (%s) и OpenCV недоступен для fallback: %s",
            reason or "unknown",
            exc,
        )
        return None

    image = cv2.imread(str(path))
    if image is None:
        logger.warning(
            "EasyOCR failed (%s); fallback не смог прочитать %s",
            reason or "unknown",
            path,
        )
        return None

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    try:
        text = pytesseract.image_to_string(gray, lang=_FALLBACK_LANG)
    except pytesseract.pytesseract.TesseractNotFoundError as exc:  # type: ignore[attr-defined]
        logger.warning(
            "EasyOCR failed (%s) и бинарник tesseract не найден: %s",
            reason or "unknown",
            exc,
        )
        return None
    except pytesseract.pytesseract.TesseractError as exc:  # type: ignore[attr-defined]
        logger.warning(
            "EasyOCR failed (%s); pytesseract вернул ошибку: %s",
            reason or "unknown",
            exc,
        )
        return None
    except Exception as exc:  # pragma: no cover - защита от нестандартных ошибок
        logger.warning(
            "EasyOCR failed (%s); непредвиденная ошибка pytesseract: %s",
            reason or "unknown",
            exc,
        )
        return None

    logger.info(
        "EasyOCR failed (%s); успешно использован pytesseract fallback для %s",
        reason or "unknown",
        path,
    )
    return text


def _load_image(path: Path, max_dimension: int):
    import cv2  # type: ignore

    image = cv2.imread(str(path))
    if image is None:
        raise RuntimeError("image not readable")

    if max_dimension > 0:
        height, width = image.shape[:2]
        max_dim = max(height, width)
        if max_dim > max_dimension:
            scale = max_dimension / float(max_dim)
            new_size = (max(int(width * scale), 1), max(int(height * scale), 1))
            image = cv2.resize(image, new_size, interpolation=cv2.INTER_AREA)

    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    return image


def _worker_main(conn, languages: Tuple[str, ...], max_dimension: int) -> None:
    import gc
    import signal

    try:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    except Exception:  # pragma: no cover - не критично
        pass

    try:
        from easyocr import Reader  # type: ignore
    except Exception as exc:  # pragma: no cover
        try:
            conn.send({"type": "fatal", "error": f"EasyOCRImportError: {exc}"})
        finally:
            conn.close()
        return

    try:
        reader = Reader(list(languages), gpu=False, verbose=False)
    except Exception as exc:  # pragma: no cover - ошибки загрузки весов
        try:
            conn.send({"type": "fatal", "error": f"EasyOCRError: {exc}"})
        finally:
            conn.close()
        return

    conn.send({"type": "ready"})

    while True:
        try:
            message = conn.recv()
        except EOFError:
            break

        if not isinstance(message, dict):
            continue

        command = message.get("cmd")
        if command == "shutdown":
            break
        if command != "process":
            continue

        path = Path(message.get("path", ""))
        if not path.exists():
            conn.send({"type": "result", "ok": False, "error": f"file not found: {path}"})
            continue

        try:
            image = _load_image(path, max_dimension)
            lines = reader.readtext(image, detail=0, paragraph=True)
            text = "\n".join(line for line in lines if line)
            conn.send({"type": "result", "ok": True, "text": text})
        except Exception as exc:  # pragma: no cover - ошибочные ситуации внутри EasyOCR
            conn.send({"type": "result", "ok": False, "error": str(exc)})
        finally:
            try:
                del image
            except Exception:
                pass
            gc.collect()

    try:
        conn.close()
    except Exception:  # pragma: no cover - завершение процесса
        pass


class _WorkerHandle:
    def __init__(self) -> None:
        self._ctx = get_context("spawn")
        self._proc = None
        self._conn = None
        self._languages = _ensure_languages(None)

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.is_alive()

    def ensure_started(self) -> None:
        if self.alive and self._conn is not None:
            return

        self.stop(force=True)

        parent_conn, child_conn = self._ctx.Pipe()
        proc = self._ctx.Process(
            target=_worker_main,
            args=(child_conn, self._languages, _MAX_DIMENSION),
            name="easyocr-worker",
        )
        proc.daemon = True
        proc.start()
        child_conn.close()

        self._proc = proc
        self._conn = parent_conn

        if not parent_conn.poll(_WORKER_START_TIMEOUT):
            self.stop(force=True)
            raise OCRWorkerError("EasyOCR worker не ответил на запуск")

        message = parent_conn.recv()
        if not isinstance(message, dict) or message.get("type") != "ready":
            error = message.get("error") if isinstance(message, dict) else "unknown"
            self.stop(force=True)
            raise OCRWorkerError(f"EasyOCR worker не запустился: {error}")

    def stop(self, force: bool = False) -> None:
        if self._conn is not None:
            try:
                if not force and self.alive:
                    self._conn.send({"cmd": "shutdown"})
            except Exception:
                pass
            try:
                self._conn.close()
            except Exception:
                pass
            finally:
                self._conn = None

        if self._proc is not None:
            try:
                self._proc.join(timeout=5)
            except Exception:
                pass
            if self._proc.is_alive():
                try:
                    self._proc.terminate()
                except Exception:
                    pass
                try:
                    self._proc.join(timeout=5)
                except Exception:
                    pass
            self._proc = None

    def restart(self) -> None:
        self.stop(force=True)
        self.ensure_started()

    def request(self, path: Path, timeout: float | None) -> dict:
        if self._conn is None:
            raise OCRWorkerError("EasyOCR worker недоступен")

        effective_timeout = timeout if timeout is not None else _DEFAULT_TIMEOUT

        try:
            self._conn.send({"cmd": "process", "path": str(path)})
        except (BrokenPipeError, EOFError):
            self.restart()
            raise OCRWorkerError("EasyOCR worker разорвал соединение")

        deadline = time.monotonic() + effective_timeout

        while True:
            if self._conn is None:
                raise OCRWorkerError("EasyOCR worker недоступен")

            if not self.alive:
                exit_code = self._proc.exitcode if self._proc else None
                self.restart()
                raise OCRWorkerError(f"EasyOCR worker завершился (exitcode={exit_code})")

            remaining = max(deadline - time.monotonic(), 0.0)

            if remaining <= 0:
                self.restart()
                raise TimeoutError(f"OCR worker timeout after {effective_timeout} секунд")

            try:
                ready = self._conn.poll(remaining)
            except (OSError, EOFError):
                ready = False
                exit_code = self._proc.exitcode if self._proc else None
                self.restart()
                raise OCRWorkerError(f"EasyOCR worker завершился (exitcode={exit_code})")

            if ready:
                try:
                    message = self._conn.recv()
                except EOFError:
                    exit_code = self._proc.exitcode if self._proc else None
                    self.restart()
                    raise OCRWorkerError(f"EasyOCR worker завершился (exitcode={exit_code})")

                if not isinstance(message, dict):
                    continue

                msg_type = message.get("type")
                if msg_type == "result":
                    return message
                if msg_type == "fatal":
                    error = message.get("error", "unknown")
                    self.restart()
                    raise OCRWorkerError(error)

                continue


_WORKER = _WorkerHandle()


def _run_via_worker(path: Path, timeout: float | None) -> str:
    try:
        _WORKER.ensure_started()
    except OCRWorkerError:
        raise
    except Exception as exc:  # pragma: no cover - непредвиденные ошибки запуска
        raise OCRWorkerError(f"Не удалось запустить EasyOCR worker: {exc}") from exc

    try:
        message = _WORKER.request(path, timeout)
    except TimeoutError:
        raise
    except OCRWorkerError:
        raise

    if message.get("ok"):
        return message.get("text", "")

    error = message.get("error", "unknown error")
    raise OCRWorkerError(error)


def extract_text(image_path: str, timeout: float | None = None) -> str:
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")

    _log_memory("ocr:before-worker")
    try:
        text = _run_via_worker(path, timeout)
    except TimeoutError:
        raise
    except OCRWorkerError as exc:
        fallback = _fallback_with_tesseract(path, str(exc))
        if fallback is not None:
            return fallback
        raise
    finally:
        _log_memory("ocr:after-worker")

    if text.strip():
        return text

    fallback = _fallback_with_tesseract(path, "empty EasyOCR result")
    if fallback is not None:
        return fallback

    return text


def release_reader() -> None:
    """Освободить фонового воркера, если он запущен."""

    _WORKER.stop()
