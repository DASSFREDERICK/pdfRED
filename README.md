# pdfRED

FastAPI + PyMuPDF document processing console. 32 tools across four groups,
plus four support endpoints (health, info, preview, thumbnails).

No external binaries, no API keys, no outbound calls except the one you ask for
when converting a URL to PDF.

## Quick start

    pip install -r requirements.txt
    uvicorn main:app --reload

Open http://127.0.0.1:8000 — API reference at /docs.

If you're on Windows and want the full walkthrough, see below.

## Windows setup, step by step

### 1. Install Python

1. Download the latest installer from the [official Python website](https://www.python.org/downloads/).
2. Run the installer.
   **Critical:** check the box at the bottom that says **"Add python.exe to PATH"** before clicking **Install Now**.
3. Verify the install by opening Command Prompt (`cmd`) and running:

   ```
   python --version
   ```

### 2. Navigate to the project folder

1. Open Command Prompt.
2. `cd` into your `pdfRED` folder — the one containing `main.py` and `requirements.txt`:

   ```
   cd C:\Users\<you>\OneDrive\Documents\pdfRED
   ```

### 3. Install dependencies

1. Install the core requirements:

   ```
   pip install -r requirements.txt
   ```

2. (Optional) If you want PDF to Word, Excel, PowerPoint or Markdown, install their extras too:

   ```
   pip install pymupdf4llm pdf2docx openpyxl python-pptx
   ```

### 4. Verify the project layout

FastAPI and Jinja2 expect this structure:

    pdfRED/
    ├── main.py
    ├── utils.py
    ├── requirements.txt
    ├── routers/
    │   ├── core.py
    │   ├── organize.py
    │   ├── convert.py
    │   ├── edit.py
    │   └── security.py
    └── templates/
        └── index.html

### 5. Start the server

With your terminal open inside the `pdfRED` folder:

```
python -m uvicorn main:app --reload
```

Wait for the log lines confirming the server started (Uvicorn will print the
address it's listening on).

### 6. Open and use the console

1. Open your browser — Firefox, Chrome, Edge, whatever you like.
2. Go to `http://127.0.0.1:8000`.
3. The console loads immediately. The engine indicator top-right turns green
   once it confirms the PyMuPDF engine is up, and you can start processing
   documents straight away.

## Layout

    main.py                 app, router wiring, error handlers
    utils.py                uploads, temp files, responses, page parsing
    routers/core.py         health, info, preview, thumbnails
    routers/organize.py     merge, split, extract, remove, organise, rotate, compress, repair
    routers/convert.py      pdf to image/text/markdown/word/excel/pptx, images and html to pdf
    routers/edit.py         replace text, add text/shape/image, markup, notes, forms, redact, flatten
    routers/security.py     protect, unlock, watermark, page numbers, sign
    templates/index.html    single-page frontend, cards built from a JS registry

## Optional packages

Everything runs on the core requirements. Four conversions want an extra package
and return a 501 naming the install command if it is missing.

| Tool              | Needs                     |
|-------------------|---------------------------|
| PDF to Markdown   | `pip install pymupdf4llm` |
| PDF to Word       | `pip install pdf2docx`    |
| PDF to Excel      | `pip install openpyxl`    |
| PDF to PowerPoint | `pip install python-pptx` |

## Environment variables

    PDFRED_MAX_UPLOAD_MB   upload ceiling, default 100

## Notes

- Sign PDF places a visible signature image. For a certified cryptographic
  signature, sign the output with pyHanko or Acrobat.
- Replace text, redact and markup need a real text layer; they will not find
  anything on a scanned page.
