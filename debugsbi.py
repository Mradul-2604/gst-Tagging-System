import pdfplumber
import re

def clean(val):
    return re.sub(r'\s+', ' ', str(val)).strip() if val else ""

# ← change this to your actual SBI pdf filename
PDF_PATH = r"C:\Users\mridu\OneDrive\Desktop\gsttagger\bank-extractor\AccountStatement_07032026_183531.pdf"
PASSWORD = "MRADU26042005"

import pypdf, io

def unlock(path, pwd):
    with open(path, "rb") as f:
        data = f.read()
    reader = pypdf.PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        reader.decrypt(pwd)
    writer = pypdf.PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    out.seek(0)
    return out

unlocked = unlock(PDF_PATH, PASSWORD)

with pdfplumber.open(unlocked) as pdf:
    for page_num, page in enumerate(pdf.pages[:3]):
        print(f"\n========== PAGE {page_num+1} ==========")
        for s in [
            {"vertical_strategy": "lines",  "horizontal_strategy": "lines"},
            {"vertical_strategy": "lines",  "horizontal_strategy": "text"},
            {"vertical_strategy": "text",   "horizontal_strategy": "lines"},
            {"vertical_strategy": "text",   "horizontal_strategy": "text"},
        ]:
            tables = page.extract_tables(s)
            if not tables:
                continue
            score = sum(1 for r in tables[0] if r and any(
                re.match(r'^\d{2}[/\-\.]\d{2}[/\-\.]\d{2,4}', clean(c))
                for c in r[:4]
            ))
            if score > 0:
                print(f"Strategy: {s['vertical_strategy']}/{s['horizontal_strategy']} score={score}")
                for row in tables[0][:8]:
                    print([clean(c) for c in row])
                break