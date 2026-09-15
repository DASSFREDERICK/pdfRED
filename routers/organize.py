from fastapi import APIRouter, UploadFile, File, Form
from fastapi.responses import FileResponse
import fitz  # PyMuPDF
import uuid
import zipfile
import os

router = APIRouter(prefix="/api", tags=["Organize"])

@router.post("/merge")
async def merge_pdfs(files: list[UploadFile] = File(...)):
    merged_doc = fitz.open()
    for file in files:
        contents = await file.read()
        doc = fitz.open(stream=contents, filetype="pdf")
        merged_doc.insert_pdf(doc)
        
    output_filename = f"merged_{uuid.uuid4().hex}.pdf"
    merged_doc.save(output_filename)
    merged_doc.close()
    return FileResponse(output_filename, media_type="application/pdf", filename="merged_output.pdf")

@router.post("/split")
async def split_pdf(file: UploadFile = File(...)):
    contents = await file.read()
    doc = fitz.open(stream=contents, filetype="pdf")
    zip_filename = f"split_{uuid.uuid4().hex}.zip"
    
    with zipfile.ZipFile(zip_filename, "w") as zf:
        for page_num in range(len(doc)):
            new_doc = fitz.open()
            new_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
            page_filename = f"page_{page_num + 1}.pdf"
            new_doc.save(page_filename)
            new_doc.close()
            zf.write(page_filename)
            os.remove(page_filename)
            
    doc.close()
    return FileResponse(zip_filename, media_type="application/zip", filename="split_pages.zip")

@router.post("/rotate")
async def rotate_pdf(file: UploadFile = File(...), angle: int = Form(90)):
    contents = await file.read()
    doc = fitz.open(stream=contents, filetype="pdf")
    
    for page in doc:
        page.set_rotation(page.rotation + angle)
        
    output_filename = f"rotated_{uuid.uuid4().hex}.pdf"
    doc.save(output_filename)
    doc.close()
    return FileResponse(output_filename, media_type="application/pdf", filename="rotated_output.pdf")