"""OCR helper that runs EasyOCR in an isolated subprocess.

The EasyOCR models are quite heavy and tend to increase the memory usage of the
current process every time they are loaded.  To keep the main bot and receipt
worker lightweight we execute the recognition inside a short lived
``multiprocessing`` child that is terminated after the text is extracted.  This
ensures all allocations are reclaimed by the operating system once the child
exits.
"""

from __future__ import annotations

import multiprocessing as mp
from multiprocessing.connection import Connection
import os
from pathlib import Path
from typing import Sequence

__all__ = ["extract_text", "release_reader", "OCRWorkerError"]

_DEFAULT_LANGUAGES: tuple[str, ...] = ("ru", "en")
_DEFAULT_TIMEOUT: float = float(os.getenv("OCR_WORKER_TIMEOUT", "25"))


class OCRWorkerError(RuntimeError):
    """Raised when the OCR worker fails to return a successful result."""

def _run_worker(image_path: str, languages: Sequence[str], conn: Connection) -> None:
    """Worker entry point executed inside a spawned process."""

    try:
        import cv2  # Local import keeps the parent process light-weight
        import easyocr

        image = cv2.imread(image_path)
        if image is None:
            conn.send((False, "image not readable"))
            return

        reader = easyocr.Reader(list(languages), gpu=False, verbose=False)
        lines = reader.readtext(image, detail=0)
        conn.send((True, "\n".join(lines)))
    except Exception as exc:  # pragma: no cover - safety net for native libs
        conn.send((False, f"{exc.__class__.__name__}: {exc}"))
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _spawn_worker(image_path: str, timeout: float) -> tuple[bool, str]:
    ctx = mp.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    process = ctx.Process(
        target=_run_worker,
        args=(image_path, _DEFAULT_LANGUAGES, child_conn),
        name="easyocr-worker",
        daemon=True,
    )
    process.start()
    child_conn.close()

    try:
        if not parent_conn.poll(timeout):
            raise TimeoutError(f"timeout after {timeout} seconds")
        success, payload = parent_conn.recv()
    except EOFError as exc:  # Worker exited without writing a result
        success, payload = False, "worker finished without result"
        raise OCRWorkerError(payload) from exc
    finally:
        try:
            parent_conn.close()
        except Exception:
            pass
        process.join(timeout=1)
        if process.is_alive():
            process.terminate()
            process.join()

    return success, payload


def extract_text(image_path: str, timeout: float | None = None) -> str:
    """Extract text from *image_path* using EasyOCR inside an isolated worker."""

    timeout = timeout if timeout is not None else _DEFAULT_TIMEOUT
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")

    success, payload = _spawn_worker(str(path), timeout)
    if not success:
        raise OCRWorkerError(payload)
    return payload


def release_reader() -> None:  # pragma: no cover - kept for backward compat
    """No-op placeholder kept for compatibility with previous interface."""

    return None
