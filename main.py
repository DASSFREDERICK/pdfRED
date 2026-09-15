from fastapi import FastAPI, UploadFile, File, Request, Form
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
import fitz  # PyMuPDF
import uuid
import zipfile
import os

app = FastAPI(title="PDF Toolkit - Portfolio Edition")

templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(request, "index.html", {})

@app.post("/api/merge")
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

@app.post("/api/split")
async def split_pdf(file: UploadFile = File(...)):
    contents = await file.read()
    doc = fitz.open(stream=contents, filetype="pdf")
    
    zip_filename = f"split_pages_{uuid.uuid4().hex}.zip"
    
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

@app.post("/api/rotate")
async def rotate_pdf(file: UploadFile = File(...), angle: int = Form(90)):
    contents = await file.read()
    doc = fitz.open(stream=contents, filetype="pdf")
    
    for page in doc:
        page.set_rotation(page.rotation + angle)
        
    output_filename = f"rotated_{uuid.uuid4().hex}.pdf"
    doc.save(output_filename)
    doc.close()
    
    return FileResponse(output_filename, media_type="application/pdf", filename="rotated_output.pdf")

@app.post("/api/pdf-to-jpg")
async def pdf_to_jpg(file: UploadFile = File(...)):
    contents = await file.read()
    doc = fitz.open(stream=contents, filetype="pdf")
    
    zip_filename = f"images_{uuid.uuid4().hex}.zip"
    
    with zipfile.ZipFile(zip_filename, "w") as zf:
        for page_num in range(len(doc)):
            page = doc[page_num]
            pix = page.get_pixmap()
            img_filename = f"page_{page_num + 1}.jpg"
            pix.save(img_filename)
            
            zf.write(img_filename)
            os.remove(img_filename)
            
    doc.close()
    return FileResponse(zip_filename, media_type="application/zip", filename="pdf_images.zip")

@app.post("/api/remove-pages")
async def remove_pages(file: UploadFile = File(...), pages_to_remove: str = Form(...)):
    # pages_to_remove format example: "1,3,5" (1-based index)
    contents = await file.read()
    doc = fitz.open(stream=contents, filetype="pdf")
    
    # Convert string input to 0-based integer list and sort descending to avoid index shifting during deletion
    remove_indices = sorted([int(p.strip()) - 1 for p in pages_to_remove.split(",")], reverse=True)
    
    for idx in remove_indices:
        if 0 <= idx < len(doc):
            doc.delete_page(idx)
            
    output_filename = f"modified_{uuid.uuid4().hex}.pdf"
    doc.save(output_filename)
    doc.close()
    
    return FileResponse(output_filename, media_type="application/pdf", filename="pages_removed.pdf")

@app.post("/api/extract-pages")
async def extract_pages(file: UploadFile = File(...), start_page: int = Form(...), end_page: int = Form(...)):
    contents = await file.read()
    doc = fitz.open(stream=contents, filetype="pdf")
    
    new_doc = fitz.open()
    # PyMuPDF uses 0-based indexing, so adjust user input
    new_doc.insert_pdf(doc, from_page=start_page - 1, to_page=end_page - 1)
    
    output_filename = f"extracted_{uuid.uuid4().hex}.pdf"
    new_doc.save(output_filename)
    new_doc.close()
    doc.close()
    
    return FileResponse(output_filename, media_type="application/pdf", filename="extracted_pages.pdf")