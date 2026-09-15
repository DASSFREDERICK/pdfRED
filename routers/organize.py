"""Document manipulation and organisation."""

from __future__ import annotations

import fitz
from fastapi import APIRouter, File, Form, UploadFile

from utils import (fail, normalise_angle, open_pdf, parse_order, parse_pages,
                   pdf_response, read_upload, zip_response)

router = APIRouter(prefix="/api", tags=["Organize"])


@router.post("/merge")
async def merge_pdfs(files: list[UploadFile] = File(...), password: str = Form("")):
    """Combine files in the exact order the browser sent them."""
    if not files:
        fail("Add at least two PDFs to merge.")
    if len(files) < 2:
        fail("Merging needs at least two files.")

    merged = fitz.open()
    try:
        for upload in files:
            source = open_pdf(await read_upload(upload), password or None)
            try:
                merged.insert_pdf(source)
            finally:
                source.close()
        if merged.page_count == 0:
            fail("The merged document came out empty.")
        return pdf_response(merged, "merged.pdf")
    except Exception:
        merged.close()
        raise


@router.post("/split")
async def split_pdf(file: UploadFile = File(...), ranges: str = Form(""),
                    password: str = Form("")):
    """Blank ranges -> one PDF per page. '1-3,7,9-12' -> one PDF per range."""
    doc = open_pdf(await read_upload(file), password or None)
    try:
        entries: list[tuple[str, bytes]] = []
        if not ranges.strip():
            for index in range(doc.page_count):
                part = fitz.open()
                part.insert_pdf(doc, from_page=index, to_page=index)
                entries.append((f"page_{index + 1}.pdf", part.tobytes(garbage=3, deflate=True)))
                part.close()
        else:
            for chunk in [c.strip() for c in ranges.split(",") if c.strip()]:
                indices = parse_pages(chunk, doc.page_count, "Ranges")
                part = fitz.open()
                part.insert_pdf(doc, from_page=indices[0], to_page=indices[-1])
                name = f"pages_{indices[0] + 1}-{indices[-1] + 1}.pdf"
                entries.append((name, part.tobytes(garbage=3, deflate=True)))
                part.close()
        return zip_response(entries, "split_pages.zip")
    finally:
        doc.close()


@router.post("/extract-pages")
async def extract_pages(file: UploadFile = File(...), start_page: int = Form(...),
                        end_page: int = Form(...), password: str = Form("")):
    doc = open_pdf(await read_upload(file), password or None)
    total = doc.page_count
    try:
        if not 1 <= start_page <= total or not 1 <= end_page <= total:
            fail(f"Page range is outside the document. It has {total} pages.")
        if start_page > end_page:
            fail("The start page comes after the end page.")
        out = fitz.open()
        out.insert_pdf(doc, from_page=start_page - 1, to_page=end_page - 1)
        return pdf_response(out, "extracted.pdf")
    finally:
        doc.close()


@router.post("/remove-pages")
async def remove_pages(file: UploadFile = File(...), pages: str = Form(...),
                       password: str = Form("")):
    doc = open_pdf(await read_upload(file), password or None)
    try:
        targets = parse_pages(pages, doc.page_count, "Pages to remove")
        if len(targets) >= doc.page_count:
            fail("That would remove every page. Keep at least one.")
        doc.delete_pages(targets)
        return pdf_response(doc, "pages_removed.pdf", close=False)
    finally:
        doc.close()


@router.post("/organize-pages")
async def organize_pages(file: UploadFile = File(...), order: str = Form(...),
                         password: str = Form("")):
    """New page order as a comma list of original page numbers: 3,1,2.
    Pages left out are dropped; repeating a number duplicates that page."""
    doc = open_pdf(await read_upload(file), password or None)
    try:
        doc.select(parse_order(order, doc.page_count))
        return pdf_response(doc, "organized.pdf", close=False)
    finally:
        doc.close()


@router.post("/rotate")
async def rotate_pdf(file: UploadFile = File(...), angle: int = Form(90),
                     pages: str = Form(""), password: str = Form("")):
    """Blank pages field rotates every page."""
    doc = open_pdf(await read_upload(file), password or None)
    try:
        step = normalise_angle(angle)
        targets = (parse_pages(pages, doc.page_count, "Pages")
                   if pages.strip() else range(doc.page_count))
        for index in targets:
            page = doc[index]
            page.set_rotation((page.rotation + step) % 360)
        return pdf_response(doc, "rotated.pdf", close=False)
    finally:
        doc.close()


@router.post("/compress")
async def compress_pdf(file: UploadFile = File(...), level: str = Form("balanced"),
                       password: str = Form("")):
    """Recompress streams and optionally downsample images.
    Response carries X-Original-Size / X-Compressed-Size so the UI can report savings."""
    data = await read_upload(file)
    doc = open_pdf(data, password or None)
    presets = {"light": (0, 96), "balanced": (1, 144), "strong": (1, 96), "extreme": (1, 72)}
    if level not in presets:
        fail("Compression level must be light, balanced, strong or extreme.")
    downsample, target_dpi = presets[level]

    try:
        if downsample:
            _downsample_images(doc, target_dpi)
        out = doc.tobytes(garbage=4, deflate=True, deflate_images=True,
                          deflate_fonts=True, clean=True, use_objstms=1)
    finally:
        doc.close()

    # Never hand back something bigger than what came in.
    if len(out) >= len(data):
        out = data
    response = _pdf_bytes_response(out, "compressed.pdf")
    response.headers["X-Original-Size"] = str(len(data))
    response.headers["X-Compressed-Size"] = str(len(out))
    response.headers["Access-Control-Expose-Headers"] = "X-Original-Size, X-Compressed-Size"
    return response


@router.post("/repair")
async def repair_pdf(file: UploadFile = File(...)):
    """Rebuild a damaged file. MuPDF reconstructs the xref table on open."""
    data = await read_upload(file)
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception:
        fail("This file is too damaged to recover — no PDF structure could be found.")
    try:
        if doc.needs_pass:
            fail("Unlock the file first, then repair it.")
        if doc.page_count == 0:
            fail("No recoverable pages were found in this file.")
        rebuilt = fitz.open()
        rebuilt.insert_pdf(doc)
        return pdf_response(rebuilt, "repaired.pdf", garbage=4, clean=True, deflate=True)
    finally:
        doc.close()


# --------------------------------------------------------------------------- #
def _downsample_images(doc: fitz.Document, target_dpi: int) -> None:
    """PyMuPDF rewrites embedded images in place, keeping the filters and masks
    consistent — far safer than swapping raw streams by hand."""
    quality = {72: 55, 96: 65, 144: 75}.get(target_dpi, 70)
    try:
        doc.rewrite_images(dpi_threshold=target_dpi + 24, dpi_target=target_dpi,
                           quality=quality, lossy=True, lossless=True,
                           color=True, gray=True, bitonal=False)
    except Exception:
        pass  # image pass is best effort; stream compression below still applies
    try:
        doc.subset_fonts(fallback=False)
    except Exception:
        pass


def _pdf_bytes_response(data: bytes, filename: str):
    from utils import bytes_response
    return bytes_response(data, "application/pdf", filename, ".pdf")
