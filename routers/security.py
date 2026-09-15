"""Passwords, watermarks, page numbers and signatures."""

from __future__ import annotations

import datetime
import io

import fitz
from fastapi import APIRouter, File, Form, UploadFile

from utils import (IMAGE_EXTS, fail, hex_to_rgb, open_pdf, pdf_response,
                   read_upload, require_module)

router = APIRouter(prefix="/api", tags=["Security"])

POSITIONS = ("top-left", "top-center", "top-right",
             "bottom-left", "bottom-center", "bottom-right")


@router.post("/protect")
async def protect_pdf(file: UploadFile = File(...), user_password: str = Form(...),
                      owner_password: str = Form(""), allow_printing: bool = Form(True),
                      allow_copying: bool = Form(False), password: str = Form("")):
    if len(user_password) < 4:
        fail("Use a password of at least 4 characters.")
    doc = open_pdf(await read_upload(file), password or None)

    permissions = fitz.PDF_PERM_ACCESSIBILITY
    if allow_printing:
        permissions |= fitz.PDF_PERM_PRINT | fitz.PDF_PERM_PRINT_HQ
    if allow_copying:
        permissions |= fitz.PDF_PERM_COPY
    return pdf_response(doc, "protected.pdf", close=False,
                        encryption=fitz.PDF_ENCRYPT_AES_256,
                        owner_pw=owner_password or user_password,
                        user_pw=user_password,
                        permissions=permissions)


@router.post("/unlock")
async def unlock_pdf(file: UploadFile = File(...), password: str = Form("")):
    data = await read_upload(file)
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        if doc.needs_pass and not doc.authenticate(password):
            fail("That password didn't open the file.", 401)
        if not doc.needs_pass and not doc.is_encrypted:
            fail("This PDF isn't protected — nothing to unlock.")
        return pdf_response(doc, "unlocked.pdf", close=False,
                            encryption=fitz.PDF_ENCRYPT_NONE)
    finally:
        doc.close()


@router.post("/watermark")
async def watermark_pdf(file: UploadFile = File(...), text: str = Form(""),
                        image: UploadFile | None = File(None),
                        opacity: float = Form(0.25), angle: int = Form(45),
                        font_size: int = Form(48), color: str = Form("#c4102f"),
                        scale: float = Form(0.6), password: str = Form("")):
    """Text or image, tiled across the centre of every page."""
    if not text.strip() and (image is None or not image.filename):
        fail("Add watermark text or an image.")
    opacity = min(max(opacity, 0.02), 1.0)

    stamp = None
    if image is not None and image.filename:
        stamp = _with_opacity(await read_upload(image, IMAGE_EXTS), opacity)

    doc = open_pdf(await read_upload(file), password or None)
    try:
        rgb = hex_to_rgb(color, (0.77, 0.06, 0.18))
        for page in doc:
            rect = page.rect
            if stamp is not None:
                width = rect.width * min(max(scale, 0.05), 1.0)
                height = width  # keep_proportion trims the box to the real aspect
                left = rect.x0 + (rect.width - width) / 2
                top = rect.y0 + (rect.height - height) / 2
                box = fitz.Rect(left, top, left + width, top + height)
                page.insert_image(box, stream=stamp, overlay=True, rotate=_snap(angle),
                                  keep_proportion=True)
            if text.strip():
                page.insert_text(
                    fitz.Point(rect.width * 0.5 - font_size * len(text) * 0.22,
                               rect.height * 0.55),
                    text, fontsize=font_size, fontname="hebo", color=rgb,
                    fill_opacity=opacity, rotate=_snap(angle), overlay=True)
        return pdf_response(doc, "watermarked.pdf", close=False)
    finally:
        doc.close()


@router.post("/page-numbers")
async def page_numbers(file: UploadFile = File(...), position: str = Form("bottom-center"),
                       start_at: int = Form(1), template: str = Form("{n}"),
                       font_size: int = Form(10), skip_first: bool = Form(False),
                       color: str = Form("#11151c"), password: str = Form("")):
    """Template supports {n} for the number and {total} for the page count."""
    if position not in POSITIONS:
        fail(f"Position must be one of: {', '.join(POSITIONS)}.")
    doc = open_pdf(await read_upload(file), password or None)
    try:
        rgb = hex_to_rgb(color)
        total = doc.page_count - (1 if skip_first else 0)
        number = start_at
        for index, page in enumerate(doc):
            if skip_first and index == 0:
                continue
            try:
                label = template.format(n=number, total=total)
            except (KeyError, IndexError):
                fail("Format can only use {n} and {total}.")
            width = fitz.get_text_length(label, fontname="helv", fontsize=font_size)
            page.insert_text(_anchor(page.rect, position, width, font_size), label,
                             fontsize=font_size, fontname="helv", color=rgb, overlay=True)
            number += 1
        return pdf_response(doc, "numbered.pdf", close=False)
    finally:
        doc.close()


@router.post("/sign")
async def sign_pdf(file: UploadFile = File(...), signature: UploadFile = File(...),
                   page: int = Form(1), x: float = Form(72), y: float = Form(600),
                   width: float = Form(160), name: str = Form(""),
                   stamp_date: bool = Form(True), password: str = Form("")):
    """Places a signature image and an optional name/date caption.
    This is a visible signature, not a cryptographic one — for a certified
    digital signature, sign the output with pyHanko or Acrobat."""
    stamp = await read_upload(signature, IMAGE_EXTS)
    doc = open_pdf(await read_upload(file), password or None)
    try:
        if not 1 <= page <= doc.page_count:
            fail(f"Page {page} is out of range. This document has {doc.page_count} pages.")
        target = doc[page - 1]
        height = width * 0.4
        box = fitz.Rect(x, y, x + width, y + height)
        if not fitz.Rect(target.rect).contains(box.top_left):
            fail("The signature position falls outside the page.")
        target.insert_image(box, stream=stamp, overlay=True, keep_proportion=True)
        caption = " · ".join(filter(None, [
            name.strip(),
            datetime.date.today().isoformat() if stamp_date else ""
        ]))
        if caption:
            target.insert_text(fitz.Point(x, y + height + 12), caption,
                               fontsize=8, fontname="helv", color=(0.35, 0.39, 0.45))
        return pdf_response(doc, "signed.pdf", close=False)
    finally:
        doc.close()


# --------------------------------------------------------------------------- #
def _snap(angle: int) -> int:
    """PyMuPDF text/image rotation accepts multiples of 90 only."""
    return min((0, 90, 180, 270), key=lambda a: abs(a - (angle % 360)))


def _anchor(rect: fitz.Rect, position: str, text_width: float, size: int) -> fitz.Point:
    pad = 28
    vertical, horizontal = position.split("-")
    y = pad + size if vertical == "top" else rect.height - pad
    if horizontal == "left":
        x = pad
    elif horizontal == "right":
        x = rect.width - pad - text_width
    else:
        x = (rect.width - text_width) / 2
    return fitz.Point(x, y)


def _with_opacity(blob: bytes, opacity: float) -> bytes:
    """Bake the alpha into the image — insert_image has no opacity argument."""
    require_module("PIL", "pip install Pillow")
    from PIL import Image as PILImage

    try:
        image = PILImage.open(io.BytesIO(blob)).convert("RGBA")
    except Exception:
        fail("That watermark image could not be read.")
    alpha = image.getchannel("A").point(lambda v: int(v * opacity))
    image.putalpha(alpha)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
