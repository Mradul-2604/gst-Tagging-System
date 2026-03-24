import pdfplumber
import pypdf
import io

password = "300132996"  # change this

with open(r"C:\Users\mridu\OneDrive\Desktop\gsttagger\bank-extractor\Acct Statement_2367_07032026_23.17.44.pdf", "rb") as f:
    file_bytes = f.read()

reader = pypdf.PdfReader(io.BytesIO(file_bytes))
reader.decrypt(password)
writer = pypdf.PdfWriter()
for page in reader.pages:
    writer.add_page(page)
unlocked = io.BytesIO()
writer.write(unlocked)
unlocked.seek(0)

with pdfplumber.open(unlocked) as pdf:
    page = pdf.pages[1]  # page 2
    print("=== PAGE 2 RAW TEXT ===")
    print(page.extract_text())
    print("\n=== PAGE 2 ALL STRATEGIES ===")
    for s in [
        {"vertical_strategy": "lines", "horizontal_strategy": "lines"},
        {"vertical_strategy": "lines", "horizontal_strategy": "text"},
        {"vertical_strategy": "text",  "horizontal_strategy": "lines"},
        {"vertical_strategy": "text",  "horizontal_strategy": "text"},
    ]:
        tables = page.extract_tables(s)
        total = sum(len(t) for t in tables)
        print(f"\nStrategy {s} → {total} rows")
        for t in tables:
            for row in t[:5]:  # print first 5 rows of each table
                print(f"  {row}")