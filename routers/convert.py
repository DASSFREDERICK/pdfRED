from fastapi import APIRouter, UploadFile, File
from fastapi.responses import FileResponse
import fitz
import uuid
import zipfile
import os

router = APIRouter(prefix="/api", tags=["Convert"])

@router.post("/pdf-to-jpg")
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