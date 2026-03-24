from flask import Flask, request, send_file, render_template, jsonify
import xlsxwriter
from extractor import extract_transactions
import pandas as pd
import io
import os

app = Flask(__name__)

# ── Excel styling ─────────────────────────────────────────────

def style_sheet(workbook, sheet_name, headers, rows):
    # All columns narrow + wrap_text on everything — matches the reference format
    col_widths = {
        "Date": 12, "Narration": 52, "Narration(Short)": 26,
        "Chq./Ref.No.": 24, "Dr/Cr": 8, "Amount(₹)": 15,
        "Category": 28, "GST": 14, "GST Notes": 36,
    }
    B = {"border": 1, "border_color": "#DDE1EA", "text_wrap": True, "valign": "top"}

    def mf(d): return workbook.add_format({**B, **d})

    hdr = workbook.add_format({
        "bold":True,"font_name":"Arial","font_size":10,"font_color":"#FFFFFF",
        "bg_color":"#1B3A6B","align":"center","valign":"vcenter","text_wrap":True,
        "border":1,"border_color":"#DDE1EA"
    })

    fmts = {}
    for even in (True, False):
        bg = "#EEF1F8" if even else "#FFFFFF"
        k = "e" if even else "o"
        fmts[f"{k}_base"]  = mf({"font_name":"Arial","font_size":9.5,"bg_color":bg})
        fmts[f"{k}_bold"]  = mf({"font_name":"Arial","font_size":9.5,"bg_color":bg,"bold":True})
        fmts[f"{k}_muted"] = mf({"font_name":"Arial","font_size":9,"bg_color":bg,"font_color":"#7A8699"})
        fmts[f"{k}_amt"]   = mf({"font_name":"Courier New","font_size":9.5,"bg_color":bg,"align":"right"})
        fmts[f"{k}_dr"]    = mf({"font_name":"Arial","font_size":9.5,"bg_color":bg,"align":"center"})
        fmts[f"{k}_cr"]    = mf({"font_name":"Arial","font_size":9.5,"bg_color":bg,"align":"center"})
        fmts[f"{k}_itc"]   = mf({"font_name":"Arial","font_size":9.5,"bg_color":bg,"align":"center"})
        fmts[f"{k}_zero"]  = mf({"font_name":"Arial","font_size":9.5,"bg_color":bg,"align":"center"})
        fmts[f"{k}_nogst"] = mf({"font_name":"Arial","font_size":9.5,"bg_color":bg,"align":"center"})

    ws = workbook.add_worksheet(sheet_name)

    # Set all column widths first
    for ci, h in enumerate(headers):
        ws.set_column(ci, ci, col_widths.get(h, 15))

    # Header row
    ws.set_row(0, 30)
    for ci, h in enumerate(headers):
        ws.write(0, ci, h, hdr)

    # Data rows — height based on longest cell content in that row
    narr_w  = col_widths.get("Narration", 30)
    short_w = col_widths.get("Narration(Short)", 18)
    cat_w   = col_widths.get("Category", 22)
    note_w  = col_widths.get("GST Notes", 22)

    h_idx = {h: i for i, h in enumerate(headers)}

    for ri, row in enumerate(rows):
        k = "e" if (ri + 2) % 2 == 0 else "o"

        # Calculate row height from wrapping columns
        def lines(val, w): return max(1, -(-len(str(val)) // w))
        max_lines = 1
        for col_key, w in [("Narration", narr_w), ("Narration(Short)", short_w),
                            ("Category", cat_w), ("GST Notes", note_w)]:
            if col_key in h_idx:
                v = row[h_idx[col_key]] if h_idx[col_key] < len(row) else ""
                max_lines = max(max_lines, lines(v, w))
        ws.set_row(ri + 1, max(15, max_lines * 15))

        for ci, val in enumerate(row):
            h = headers[ci] if ci < len(headers) else ""
            if   h in ("Narration", "Category"):  ws.write(ri+1, ci, val, fmts[f"{k}_base"])
            elif h == "Narration(Short)":          ws.write(ri+1, ci, val, fmts[f"{k}_bold"])
            elif h == "GST Notes":                 ws.write(ri+1, ci, val, fmts[f"{k}_muted"])
            elif h == "Amount(₹)":                 ws.write(ri+1, ci, val, fmts[f"{k}_amt"])
            elif h == "Dr/Cr":
                ws.write(ri+1, ci, val, fmts[f"{k}_dr"] if val=="Dr" else fmts[f"{k}_cr"] if val=="Cr" else fmts[f"{k}_base"])
            elif h == "GST":
                gf = {"ITC Eligible": f"{k}_itc", "Zero Rated": f"{k}_zero", "No GST": f"{k}_nogst"}
                ws.write(ri+1, ci, val, fmts.get(gf.get(val,""), fmts[f"{k}_base"]))
            else:
                ws.write(ri+1, ci, val, fmts[f"{k}_base"])

    ws.freeze_panes(1, 0)


# ── Routes ────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/extract_multi", methods=["POST"])
def extract_multi():
    files     = request.files.getlist("pdfs")
    passwords = request.form.getlist("passwords")

    if not files:
        return jsonify({"error": "No files uploaded"}), 400

    results = []
    all_dfs = []

    for i, file in enumerate(files):
        password   = passwords[i] if i < len(passwords) else ""
        file_bytes = file.read()
        df, error  = extract_transactions(file_bytes, password)
        if error:
            return jsonify({"error": f"{file.filename}: {error}"}), 400
        results.append({
            "filename": file.filename,
            "columns":  df.columns.tolist(),
            "rows":     df.to_dict(orient="records")
        })
        all_dfs.append(df)

    merged_df = pd.concat(all_dfs, ignore_index=True)
    try:
        merged_df["_date_sort"] = pd.to_datetime(
            merged_df["Date"], format="%d/%m/%Y", dayfirst=True, errors="coerce"
        )
        merged_df = merged_df.sort_values("_date_sort").drop(columns=["_date_sort"])
    except Exception:
        pass
    merged_df.reset_index(drop=True, inplace=True)

    return jsonify({
        "files":  results,
        "merged": {
            "columns": merged_df.columns.tolist(),
            "rows":    merged_df.to_dict(orient="records")
        }
    })

@app.route("/download_excel_multi", methods=["POST"])
def download_excel_multi():
    data   = request.get_json()
    mode   = data.get("mode", "merged")
    output = io.BytesIO()
    wb     = xlsxwriter.Workbook(output, {"in_memory": True})

    if mode == "merged":
        style_sheet(wb, "GST Transactions", data["headers"], data["rows"])
    else:
        for sheet in data["sheets"]:
            name = sheet["name"][:31]
            for ch in ['\\', '/', ':', '*', '?', '[', ']']:
                name = name.replace(ch, "_")
            style_sheet(wb, name, sheet["headers"], sheet["rows"])

    wb.close()
    output.seek(0)
    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="transactions.xlsx"
    )

@app.route("/extract_json", methods=["POST"])
def extract_json():
    if "pdf" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    file      = request.files["pdf"]
    password  = request.form.get("password", "")
    df, error = extract_transactions(file.read(), password)
    if error:
        return jsonify({"error": error}), 400
    return jsonify({"columns": df.columns.tolist(), "rows": df.to_dict(orient="records")})

@app.route("/download_excel", methods=["POST"])
def download_excel():
    data   = request.get_json()
    output = io.BytesIO()
    wb     = xlsxwriter.Workbook(output, {"in_memory": True})
    style_sheet(wb, "Transactions", data["headers"], data["rows"])
    wb.close()
    output.seek(0)
    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="transactions.xlsx"
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)