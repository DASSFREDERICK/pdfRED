"""Health, document info and page previews — everything the UI needs before a run."""

from __future__ import annotations

import base64

import fitz
from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import Response

from utils import fail, open_pdf, read_upload

router = APIRouter(prefix="/api", tags=["Core"])

MAX_THUMBS = 60


@router.get("/health")
async def health():
    return {"status": "ok", "engine": f"PyMuPDF {fitz.version[0]}"}


@router.post("/info")
async def info(file: UploadFile = File(...), password: str = Form("")):
    """Metadata for the card readout. Never fails hard on an encrypted file —
    the UI needs to know it's encrypted so it can ask for a password."""
    data = await read_upload(file)
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception:
        fail("That file isn't a readable PDF. Try Repair PDF on it first.")

    locked = bool(doc.needs_pass)
    if locked and password:
        locked = not doc.authenticate(password)

    meta = doc.metadata or {}
    result = {
        "filename": file.filename,
        "size_bytes": len(data),
        "encrypted": bool(doc.needs_pass),
        "locked": locked,
        "pages": 0 if locked else doc.page_count,
        "title": (meta.get("title") or "").strip(),
        "author": (meta.get("author") or "").strip(),
        "producer": (meta.get("producer") or "").strip(),
        "has_text": False,
        "form_fields": 0,
    }
    if not locked and doc.page_count:
        page = doc[0]
        result["has_text"] = bool(page.get_text("text").strip())
        result["form_fields"] = sum(1 for _ in doc.pages() for _ in _.widgets()) if doc.is_form_pdf else 0
        rect = page.rect
        result["page_size"] = f"{rect.width / 72:.1f} x {rect.height / 72:.1f} in"
    doc.close()
    return result


@router.post("/preview")
async def preview(file: UploadFile = File(...), page: int = Form(1),
                  dpi: int = Form(150), password: str = Form("")):
    """Single page rendered to PNG for the live preview panel."""
    doc = open_pdf(await read_upload(file), password or None)
    try:
        index = max(1, min(page, doc.page_count)) - 1
        pix = doc[index].get_pixmap(dpi=max(36, min(dpi, 300)))
        return Response(content=pix.tobytes("png"), media_type="image/png")
    finally:
        doc.close()


@router.post("/thumbnails")
async def thumbnails(file: UploadFile = File(...), password: str = Form(""),
                     dpi: int = Form(36)):
    """Small data-URL thumbnails for the drag-to-reorder page organiser."""
    doc = open_pdf(await read_upload(file), password or None)
    try:
        pages = []
        for index in range(min(doc.page_count, MAX_THUMBS)):
            pix = doc[index].get_pixmap(dpi=max(20, min(dpi, 72)))
            encoded = base64.b64encode(pix.tobytes("png")).decode("ascii")
            pages.append({"page": index + 1, "src": f"data:image/png;base64,{encoded}"})
        return {
            "total": doc.page_count,
            "shown": len(pages),
            "truncated": doc.page_count > MAX_THUMBS,
            "pages": pages,
        }
    finally:
        doc.close()
