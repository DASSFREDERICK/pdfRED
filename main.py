"""
pdfRED — document processing console.

Run with:  uvicorn main:app --reload
Docs at :  http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from routers import convert, core, edit, organize, security
from utils import MAX_UPLOAD_MB

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pdfred")

app = FastAPI(
    title="pdfRED",
    description="A focused PDF toolkit: organise, convert, edit, secure and read documents.",
    version="2.0.0",
)

templates = Jinja2Templates(directory="templates")

app.include_router(core.router)
app.include_router(organize.router)
app.include_router(convert.router)
app.include_router(edit.router)
app.include_router(security.router)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(request, "index.html",
                                      {"max_upload_mb": MAX_UPLOAD_MB})


# --------------------------------------------------------------------------- #
# error shape the frontend expects: {"detail": "..."}
# --------------------------------------------------------------------------- #
@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(p) for p in first.get("loc", [])[1:]) or "input"
    return JSONResponse(status_code=400,
                        content={"detail": f"Check the '{field}' value: {first.get('msg', 'invalid')}"})


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    log.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500,
                        content={"detail": "Something broke on the server. Check the logs."})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=True)
