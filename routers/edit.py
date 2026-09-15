"""Editing, annotation and form tools."""

from __future__ import annotations

import json

import fitz
from fastapi import APIRouter, File, Form, UploadFile

from utils import (IMAGE_EXTS, fail, hex_to_rgb, open_pdf, parse_pages,
                   pdf_response, read_upload)

router = APIRouter(prefix="/api", tags=["Edit"])

MARKUPS = {
    "highlight": "add_highlight_annot",
    "underline": "add_underline_annot",
    "strikeout": "add_strikeout_annot",
    "squiggly": "add_squiggly_annot",
}

SHAPES = ("rectangle", "circle", "line", "arrow")


@router.post("/replace-text")
async def replace_text(file: UploadFile = File(...), find: str = Form(...),
                       replace: str = Form(""), font_size: int = Form(0),
                       color: str = Form("#11151c"), match_case: bool = Form(True),
                       password: str = Form("")):
    """Redacts every occurrence and draws the replacement in the same spot.
    Works on machine-generated PDFs; scanned pages need OCR first."""
    if not find.strip():
        fail("Enter the text you want to replace.")
    doc = open_pdf(await read_upload(file), password or None)
    try:
        rgb = hex_to_rgb(color)
        flags = 0 if match_case else fitz.TEXT_IGNORECASE
        hits = 0
        for page in doc:
            rects = page.search_for(find, flags=flags) or []
            if not rects:
                continue
            hits += len(rects)
            for rect in rects:
                size = font_size or max(6, min(rect.height * 0.78, 36))
                page.add_redact_annot(rect, fill=(1, 1, 1))
                page.insert_textbox(rect + (0, -1, 40, 2), replace, fontsize=size,
                                    fontname="helv", color=rgb, align=0)
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        if hits == 0:
            fail(f"'{find}' wasn't found in this document.")
        return pdf_response(doc, "text_replaced.pdf", close=False)
    finally:
        doc.close()


@router.post("/add-text")
async def add_text(file: UploadFile = File(...), text: str = Form(...),
                   page: int = Form(1), x: float = Form(72), y: float = Form(72),
                   font_size: int = Form(14), color: str = Form("#11151c"),
                   bold: bool = Form(False), password: str = Form("")):
    if not text.strip():
        fail("Enter the text to add.")
    doc = open_pdf(await read_upload(file), password or None)
    try:
        target = _page(doc, page)
        rect = fitz.Rect(x, y, target.rect.x1 - 36, y + font_size * 2.4 + len(text) * 0.6)
        overflow = target.insert_textbox(rect, text, fontsize=font_size,
                                         fontname="hebo" if bold else "helv",
                                         color=hex_to_rgb(color), align=0)
        if overflow < 0:
            fail("The text doesn't fit at that position. Move it up or reduce the size.")
        return pdf_response(doc, "text_added.pdf", close=False)
    finally:
        doc.close()


@router.post("/add-shape")
async def add_shape(file: UploadFile = File(...), shape: str = Form("rectangle"),
                    page: int = Form(1), x: float = Form(72), y: float = Form(72),
                    width: float = Form(200), height: float = Form(120),
                    color: str = Form("#1b3b6f"), fill: str = Form(""),
                    line_width: float = Form(1.5), password: str = Form("")):
    if shape not in SHAPES:
        fail(f"Shape must be one of: {', '.join(SHAPES)}.")
    doc = open_pdf(await read_upload(file), password or None)
    try:
        target = _page(doc, page)
        rect = fitz.Rect(x, y, x + width, y + height)
        canvas = target.new_shape()
        if shape == "rectangle":
            canvas.draw_rect(rect)
        elif shape == "circle":
            canvas.draw_oval(rect)
        elif shape == "line":
            canvas.draw_line(rect.top_left, rect.bottom_right)
        else:
            canvas.draw_line(rect.top_left, rect.bottom_right)
            canvas.draw_line(rect.bottom_right, rect.bottom_right + (-12, -4))
            canvas.draw_line(rect.bottom_right, rect.bottom_right + (-4, -12))
        canvas.finish(color=hex_to_rgb(color), width=line_width,
                      fill=hex_to_rgb(fill) if fill.strip() else None)
        canvas.commit()
        return pdf_response(doc, "shape_added.pdf", close=False)
    finally:
        doc.close()


@router.post("/add-image")
async def add_image(file: UploadFile = File(...), image: UploadFile = File(...),
                    page: int = Form(1), x: float = Form(72), y: float = Form(72),
                    width: float = Form(200), password: str = Form("")):
    blob = await read_upload(image, IMAGE_EXTS)
    doc = open_pdf(await read_upload(file), password or None)
    try:
        target = _page(doc, page)
        box = fitz.Rect(x, y, x + width, y + width)
        target.insert_image(box, stream=blob, overlay=True, keep_proportion=True)
        return pdf_response(doc, "image_added.pdf", close=False)
    finally:
        doc.close()


@router.post("/annotate")
async def annotate(file: UploadFile = File(...), search: str = Form(...),
                   style: str = Form("highlight"), color: str = Form("#f2c744"),
                   note: str = Form(""), password: str = Form("")):
    if style not in MARKUPS:
        fail(f"Markup style must be one of: {', '.join(MARKUPS)}.")
    if not search.strip():
        fail("Enter the words you want to mark up.")
    doc = open_pdf(await read_upload(file), password or None)
    try:
        rgb = hex_to_rgb(color, (0.95, 0.78, 0.27))
        hits = 0
        for page in doc:
            rects = page.search_for(search) or []
            for rect in rects:
                annot = getattr(page, MARKUPS[style])(rect)
                annot.set_colors(stroke=rgb)
                if note.strip():
                    annot.set_info(content=note)
                annot.update()
                hits += 1
        if hits == 0:
            fail(f"'{search}' wasn't found in this document.")
        return pdf_response(doc, "annotated.pdf", close=False)
    finally:
        doc.close()


@router.post("/sticky-note")
async def sticky_note(file: UploadFile = File(...), text: str = Form(...),
                      page: int = Form(1), x: float = Form(72), y: float = Form(72),
                      author: str = Form(""), password: str = Form("")):
    doc = open_pdf(await read_upload(file), password or None)
    try:
        target = _page(doc, page)
        annot = target.add_text_annot(fitz.Point(x, y), text, icon="Note")
        annot.set_info(title=author or "pdfRED", content=text)
        annot.update()
        return pdf_response(doc, "note_added.pdf", close=False)
    finally:
        doc.close()


@router.post("/form-fields")
async def form_fields(file: UploadFile = File(...), password: str = Form("")):
    """Lists every fillable field so you know what to send to /api/fill-form."""
    doc = open_pdf(await read_upload(file), password or None)
    try:
        fields = []
        for index, page in enumerate(doc):
            for widget in page.widgets():
                fields.append({
                    "page": index + 1,
                    "name": widget.field_name,
                    "type": widget.field_type_string,
                    "value": widget.field_value,
                    "options": list(widget.choice_values or []),
                })
        if not fields:
            fail("This PDF has no fillable form fields.")
        return {"count": len(fields), "fields": fields}
    finally:
        doc.close()


@router.post("/fill-form")
async def fill_form(file: UploadFile = File(...), values: str = Form(...),
                    flatten: bool = Form(False), password: str = Form("")):
    """values is JSON: {"full_name": "Frederick", "agree": true}"""
    try:
        payload = json.loads(values)
    except json.JSONDecodeError:
        fail('Values must be JSON, for example {"full_name": "Frederick"}')
    if not isinstance(payload, dict):
        fail('Values must be a JSON object, for example {"full_name": "Frederick"}')

    doc = open_pdf(await read_upload(file), password or None)
    try:
        filled, unknown = 0, set(payload.keys())
        for page in doc:
            for widget in page.widgets():
                if widget.field_name not in payload:
                    continue
                unknown.discard(widget.field_name)
                value = payload[widget.field_name]
                if widget.field_type == fitz.PDF_WIDGET_TYPE_CHECKBOX:
                    widget.field_value = bool(value)
                else:
                    widget.field_value = str(value)
                widget.update()
                filled += 1
        if filled == 0:
            fail("None of those field names exist in this PDF. Run 'Inspect form fields' first.")
        if flatten:
            doc = _flatten(doc)
        response = pdf_response(doc, "form_filled.pdf", close=False)
        response.headers["X-Fields-Filled"] = str(filled)
        if unknown:
            response.headers["X-Fields-Unknown"] = ",".join(sorted(unknown))[:200]
        response.headers["Access-Control-Expose-Headers"] = "X-Fields-Filled, X-Fields-Unknown"
        return response
    finally:
        doc.close()


@router.post("/add-form-field")
async def add_form_field(file: UploadFile = File(...), name: str = Form(...),
                         field_type: str = Form("text"), page: int = Form(1),
                         x: float = Form(72), y: float = Form(72),
                         width: float = Form(200), height: float = Form(24),
                         password: str = Form("")):
    kinds = {
        "text": fitz.PDF_WIDGET_TYPE_TEXT,
        "checkbox": fitz.PDF_WIDGET_TYPE_CHECKBOX,
        "radio": fitz.PDF_WIDGET_TYPE_RADIOBUTTON,
    }
    if field_type not in kinds:
        fail("Field type must be text, checkbox or radio.")
    if not name.strip():
        fail("Give the field a name.")

    doc = open_pdf(await read_upload(file), password or None)
    try:
        target = _page(doc, page)
        widget = fitz.Widget()
        widget.field_name = name.strip()
        widget.field_type = kinds[field_type]
        widget.rect = fitz.Rect(x, y, x + width, y + height)
        widget.border_color = (0.36, 0.40, 0.45)
        widget.fill_color = (0.98, 0.98, 0.99)
        if field_type == "text":
            widget.field_value = ""
            widget.text_fontsize = 11
        else:
            widget.field_value = False
        target.add_widget(widget)
        return pdf_response(doc, "field_added.pdf", close=False)
    finally:
        doc.close()


@router.post("/flatten")
async def flatten_pdf(file: UploadFile = File(...), password: str = Form("")):
    """Bakes form values and annotations into the page content."""
    doc = open_pdf(await read_upload(file), password or None)
    try:
        return pdf_response(_flatten(doc), "flattened.pdf", close=False)
    finally:
        doc.close()


@router.post("/redact")
async def redact(file: UploadFile = File(...), search: str = Form(...),
                 pages: str = Form(""), password: str = Form("")):
    """Permanently removes the matching text, not just covers it."""
    if not search.strip():
        fail("Enter the text to redact.")
    doc = open_pdf(await read_upload(file), password or None)
    try:
        targets = (parse_pages(pages, doc.page_count, "Pages")
                   if pages.strip() else range(doc.page_count))
        hits = 0
        for index in targets:
            page = doc[index]
            for rect in page.search_for(search) or []:
                page.add_redact_annot(rect, fill=(0, 0, 0))
                hits += 1
            page.apply_redactions()
        if hits == 0:
            fail(f"'{search}' wasn't found in the selected pages.")
        return pdf_response(doc, "redacted.pdf", close=False)
    finally:
        doc.close()


# --------------------------------------------------------------------------- #
def _page(doc: fitz.Document, number: int) -> fitz.Page:
    if not 1 <= number <= doc.page_count:
        fail(f"Page {number} is out of range. This document has {doc.page_count} pages.")
    return doc[number - 1]


def _flatten(doc: fitz.Document) -> fitz.Document:
    """Render each page to a vector-preserving copy with annotations burnt in."""
    out = fitz.open()
    for page in doc:
        new_page = out.new_page(width=page.rect.width, height=page.rect.height)
        pix = page.get_pixmap(dpi=200, annots=True)
        new_page.insert_image(new_page.rect, stream=pix.tobytes("png"))
    return out
