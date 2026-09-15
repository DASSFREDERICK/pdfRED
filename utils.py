"""
pdfRED — shared helpers.

Everything that touches the filesystem goes through here so that:
  * temp files always get a unique name (no cross-request collisions)
  * temp files are always deleted after the response has been streamed
  * bad input produces a clean 400 with a readable message instead of a 500
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import zipfile
from typing import Iterable, Sequence

import fitz  # PyMuPDF
from fastapi import HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

MAX_UPLOAD_MB = int(os.getenv("PDFRED_MAX_UPLOAD_MB", "100"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif")


# --------------------------------------------------------------------------- #
# errors
# --------------------------------------------------------------------------- #
def fail(message: str, code: int = 400) -> None:
    """Raise a clean HTTP error. FastAPI renders it as {"detail": message}."""
    raise HTTPException(status_code=code, detail=message)


# --------------------------------------------------------------------------- #
# uploads
# --------------------------------------------------------------------------- #
async def read_upload(file: UploadFile | None, exts: Sequence[str] = (".pdf",)) -> bytes:
    if file is None or not file.filename:
        fail("Add a file first.")
    name = file.filename.lower()
    if exts and not name.endswith(tuple(exts)):
        fail(f"{file.filename} isn't a supported file type. Accepted: {', '.join(exts)}.")
    data = await file.read()
    if not data:
        fail(f"{file.filename} is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        fail(f"{file.filename} is larger than the {MAX_UPLOAD_MB} MB limit.")
    return data


def open_pdf(data: bytes, password: str | None = None) -> fitz.Document:
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception:
        fail("That file isn't a readable PDF. Try Repair PDF on it first.")
    if doc.needs_pass:
        if not password or not doc.authenticate(password):
            doc.close()
            fail("This PDF is password protected. Enter the password to continue.", 401)
    if doc.page_count == 0:
        doc.close()
        fail("This PDF has no pages.")
    return doc


async def open_upload(file: UploadFile, password: str | None = None) -> fitz.Document:
    return open_pdf(await read_upload(file), password)


# --------------------------------------------------------------------------- #
# temp files + responses
# --------------------------------------------------------------------------- #
def temp_path(suffix: str) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="pdfred_")
    os.close(fd)
    return path


def cleanup(*paths: str) -> None:
    for path in paths:
        try:
            if path and os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            elif path and os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


def file_response(path: str, media_type: str, filename: str, *extra_cleanup: str):
    return FileResponse(
        path,
        media_type=media_type,
        filename=filename,
        background=BackgroundTask(cleanup, path, *extra_cleanup),
    )


def pdf_response(doc: fitz.Document, filename: str, close: bool = True, **save_opts):
    opts = dict(garbage=3, deflate=True)
    opts.update(save_opts)
    path = temp_path(".pdf")
    try:
        doc.save(path, **opts)
    except Exception as exc:
        cleanup(path)
        fail(f"Could not write the output PDF: {exc}")
    finally:
        if close:
            doc.close()
    return file_response(path, "application/pdf", filename)


def bytes_response(data: bytes, media_type: str, filename: str, suffix: str = ""):
    path = temp_path(suffix or os.path.splitext(filename)[1] or ".bin")
    with open(path, "wb") as fh:
        fh.write(data)
    return file_response(path, media_type, filename)


def zip_response(entries: Iterable[tuple[str, bytes]], filename: str):
    """entries: (name_inside_zip, raw_bytes). Written straight into the archive,
    so no per-page temp files and no filename collisions between requests."""
    path = temp_path(".zip")
    count = 0
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, blob in entries:
            zf.writestr(name, blob)
            count += 1
    if count == 0:
        cleanup(path)
        fail("Nothing to package — the operation produced no files.")
    return file_response(path, "application/zip", filename)


# --------------------------------------------------------------------------- #
# page selections
# --------------------------------------------------------------------------- #
_RANGE = re.compile(r"^\s*(\d+)\s*(?:[-–]\s*(\d+)\s*)?$")


def parse_pages(spec: str, total: int, label: str = "Pages") -> list[int]:
    """'1,3,5-8' -> sorted unique 0-based indices. Raises 400 on anything invalid."""
    if not spec or not spec.strip():
        fail(f"{label} is required, for example 1,3,5-8.")
    out: set[int] = set()
    for chunk in spec.split(","):
        if not chunk.strip():
            continue
        m = _RANGE.match(chunk)
        if not m:
            fail(f"'{chunk.strip()}' isn't a valid page or range. Use numbers like 1,3,5-8.")
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else start
        if start > end:
            fail(f"Range {start}-{end} runs backwards.")
        for page in range(start, end + 1):
            if not 1 <= page <= total:
                fail(f"Page {page} is out of range. This document has {total} pages.")
            out.add(page - 1)
    if not out:
        fail(f"{label} is required, for example 1,3,5-8.")
    return sorted(out)


def parse_order(spec: str, total: int) -> list[int]:
    """'3,1,2' -> [2,0,1]. Order matters and duplicates are allowed (page copies)."""
    if not spec or not spec.strip():
        fail("Provide the new page order, for example 3,1,2.")
    out: list[int] = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if not chunk.isdigit():
            fail(f"'{chunk}' isn't a page number.")
        page = int(chunk)
        if not 1 <= page <= total:
            fail(f"Page {page} is out of range. This document has {total} pages.")
        out.append(page - 1)
    if not out:
        fail("The new page order is empty.")
    return out


def normalise_angle(angle: int) -> int:
    if angle % 90 != 0:
        fail("Rotation must be 90, 180 or 270 degrees.")
    return angle % 360


def hex_to_rgb(value: str, default=(0, 0, 0)) -> tuple[float, float, float]:
    if not value:
        return default
    value = value.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    if len(value) != 6:
        return default
    try:
        return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore
    except ValueError:
        return default


# --------------------------------------------------------------------------- #
# optional python packages
# --------------------------------------------------------------------------- #
def require_module(name: str, install_hint: str):
    try:
        return __import__(name)
    except ImportError:
        fail(f"This feature needs the '{name}' package. Install it with: {install_hint}", 501)
