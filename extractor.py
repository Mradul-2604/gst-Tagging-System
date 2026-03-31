import pdfplumber
import pypdf
import pandas as pd
import re
import io
import os
import json
from difflib import SequenceMatcher
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def unlock_pdf(file_bytes, password):
    reader = pypdf.PdfReader(io.BytesIO(file_bytes))
    if reader.is_encrypted:
        reader.decrypt(password)
    writer = pypdf.PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    out.seek(0)
    return out

def clean(val):
    return re.sub(r'\s+', ' ', str(val)).strip() if val else ""

def is_date(text):
    return bool(re.match(r'^\d{2}[/\-\.]\d{2}[/\-\.]\d{2,4}$', str(text).strip()))

def is_amount(text):
    s = re.sub(r'[,\s]', '', str(text).strip())
    return bool(re.match(r'^\d+\.\d{2}$', s)) and s not in ('', '-')

def parse_amount(text):
    try:
        s = re.sub(r'[,\s₹$]', '', str(text)).strip()
        if not s or s == '-':
            return None
        return float(s)
    except:
        return None

def is_empty(val):
    return str(val or "").strip() in ("", "-", "None", "nil", "NIL")

def fallback_shorten(narration):
    if not narration:
        return "-"
    cleaned = re.sub(r'[0-9@#\.\-\_\/]', ' ', narration.upper())
    words = [w for w in cleaned.split() if len(w) > 2][:4]
    return " ".join(words).title() if words else narration[:30].title()

def detect_transfer_type(narration):
    text = re.sub(r'\s*\[(Dr|Cr)\]\s*$', '', str(narration or ""), flags=re.IGNORECASE).upper().strip()
    if re.search(r'\bNEFT\b', text):
        return "NEFT"
    if re.search(r'\bUPI\b', text):
        return "UPI"
    if re.search(r'\bIMPS\b', text):
        return "IMPS"
    if re.search(r'\bRTGS\b', text):
        return "RTGS"
    if re.search(r'\bACH\b|\bNACH\b', text):
        return "ACH"
    return ""

def merge_short_with_transfer(short_name, narration):
    short_name = str(short_name or "").strip()
    if not short_name:
        return smart_shorten(narration)
    if re.search(r'\([^)]*\)\s*$', short_name):
        return short_name

    transfer_type = detect_transfer_type(narration)
    if not transfer_type:
        return short_name

    if short_name.upper() in {"ATM WITHDRAWAL", "BANK CHARGES"}:
        return short_name

    return f"{short_name} ({transfer_type})"

def smart_shorten(narration):
    """
    Extract a clean human-readable party name from a raw bank narration.
    Strategy: skip leading noise/bank-code tokens, then STOP collecting at the
    first noise/city/ref token after the name begins.
    This way 'NEFTDR INDB UTKARSH KUMAR MUM LEWJUJ' → 'Utkarsh Kumar (NEFT)'
    because MUM (city code) terminates collection immediately.
    """
    if not narration:
        return "-"

    # Strip [Dr] / [Cr] suffix that Groq pipeline appends
    text = re.sub(r'\s*\[(Dr|Cr)\]\s*$', '', narration, flags=re.IGNORECASE).upper().strip()

    # ATM / cash withdrawal detection first
    if re.search(r'\bATM\b', text) or re.search(r'\bCASH WD\b|\bCASH WITHDRAWAL\b', text):
        return "ATM Withdrawal"

    # Detect transfer type from full string before we mangle it
    transfer_type = detect_transfer_type(text)

    # Complete stop-word set: ANYTHING that is not a person/company name fragment.
    # City codes are critical — they mark the END of the name in NEFT narrations.
    _STOP = {
        # Transfer type + direction combos
        "NEFTDR", "NEFTCR", "IMPSDR", "IMPSCR", "RTGSDR", "RTGSCR", "UPIDR", "UPICR",
        "ACHDR", "ACHCR", "NACHDR", "NACHCR",
        # Transfer types standalone
        "NEFT", "UPI", "IMPS", "RTGS", "ACH", "NACH", "ECS", "CHQ", "CHEQUE",
        # Direction
        "DR", "CR", "DB",
        # Known bank IFSC prefixes / abbreviations
        "INDB", "HDFC", "HDFCH", "SBIN", "ICIC", "ICICI", "AXIS", "UTIB",
        "KOTAK", "KKBK", "YESB", "YESBNK", "IDBI", "PNB", "PUNB", "BOI",
        "BOB", "BARB", "CANARA", "CNRB", "UNION", "UBIN", "UCO", "UCOB",
        "FEDERAL", "FDRL", "SCB", "SCBL", "CITI", "CITN", "HSBC", "HSBCH",
        "DBS", "DBSS", "RBL", "RATN", "INDUS", "INDU", "IDFCF", "IDFC",
        "AUSFB", "AUSF", "UJJIV", "UJJI", "FINO", "ESAF", "JAKA",
        # Channel / medium keywords
        "NETBAN", "NETBANK", "NETBANKING", "INB", "MB", "MOB", "MOBILE",
        "INTERNET", "BANKING", "ONLINE", "ATM",
        # City / location codes (VERY important — mark end-of-name in NEFT strings)
        "MUM", "MUMBAI", "BOM",
        "DEL", "DELHI", "NEWDELHI",
        "BLR", "BANG", "BANGALORE", "BENGALURU",
        "CHN", "MAD", "CHENNAI", "MADRAS",
        "HYD", "HYDERABAD",
        "PUN", "PUNE",
        "AHM", "AHMD", "AHMEDABAD",
        "KOL", "KOLKATA", "CALCUTTA",
        "GOA", "NCR", "NAVI",
        # Reference / transaction ID fragments
        "REF", "REFNO", "TXN", "TXNID", "UTR", "UTRNO", "TRAN", "TRANS",
        "PD", "TO", "BY", "FROM", "IN", "OUT",
        # Generic descriptor words
        "TRANSFER", "CREDIT", "DEBIT", "PAYMENT", "RECEIVED", "RECEIPT",
        "SALARY", "SAL", "ADVANCE", "FUND", "FUNDS",
    }

    def _is_stop(tok):
        """True if this token is noise/infrastructure, not a name fragment."""
        if tok in _STOP:
            return True
        if len(tok) <= 2:
            return True
        # Starts with NB → netbanking reference code (NBMUTD, NBZHZIU, NBEFIJIT…)
        if tok.startswith("NB") and len(tok) >= 4:
            return True
        # Zero vowels → pure bank/IFSC abbreviation
        vowels = sum(1 for c in tok if c in "AEIOU")
        if vowels == 0:
            return True
        # Has any digit → reference/account number fragment
        if any(c.isdigit() for c in tok):
            return True
        return False

    # Normalise to alpha only, then split
    alpha_text = re.sub(r'[^A-Z\s]', ' ', text)
    tokens = [t for t in alpha_text.split() if t]

    # Phase 1: skip all leading stop tokens (prefix noise)
    start = 0
    while start < len(tokens) and _is_stop(tokens[start]):
        start += 1

    # Phase 2: collect name tokens and STOP at the first stop token we hit
    name_tokens = []
    for tok in tokens[start:]:
        if _is_stop(tok):
            break          # city / channel / bank code marks the end of the name
        name_tokens.append(tok)

    if not name_tokens:
        # Last resort: pick longest non-tiny tokens from full set
        candidates = [t for t in tokens if len(t) >= 4 and not _is_stop(t)][:3]
        name_tokens = candidates if candidates else tokens[:3]

    name = " ".join(name_tokens[:5]).title()
    return f"{name} ({transfer_type})" if transfer_type else name

# ─────────────────────────────────────────────
# COLUMN DETECTION
# ─────────────────────────────────────────────

def detect_columns(rows):
    col_map = {}

    col_keywords = {
        "date":       ["value date", "txn date", "tran date", "transaction date", "posting date", "date"],
        "post_date":  ["post date", "instrument date"],
        "narration":  ["narration", "particular", "description", "details", "remarks", "transaction details"],
        "chq_ref":    ["chq", "ref", "cheque", "reference", "instrument no", "ref no", "chq/ref"],
        "withdrawal": ["withdrawal", "debit", "dr", "debit amount", "withdrawal amt",
                       "paid out", "amount dr", "withdrawals", "debit(₹)", "debit(rs)",
                       "₹ debit", "debit ₹", "debits"],
        "deposit":    ["deposit", "credit", "cr", "credit amount", "deposit amt",
                       "paid in", "amount cr", "deposits", "credit(₹)", "credit(rs)",
                       "₹ credit", "credit ₹", "credits"],
        "balance":    ["balance", "closing balance", "running balance"],
    }

    # Try header row detection
    for row in rows[:10]:
        if not row:
            continue
        cells = [re.sub(r'\s+', ' ', str(c or "")).strip().lower() for c in row]
        has_date  = any("date" in c for c in cells)
        has_money = any(
            any(kw in c for kw in ["debit", "credit", "withdrawal", "deposit", "amount", "balance"])
            for c in cells
        )
        if not (has_date and has_money):
            continue
        for ci, cell in enumerate(cells):
            for col_type, keywords in col_keywords.items():
                if col_type not in col_map and any(kw in cell for kw in keywords):
                    col_map[col_type] = ci
                    break
        if "date" in col_map:
            break

    # Auto-detect if header not found or amounts not detected
    if "date" not in col_map or ("withdrawal" not in col_map and "deposit" not in col_map):
        col_map = _autodetect_columns(rows)

    return col_map


def _autodetect_columns(rows):
    """Score each column statistically to detect date/narration/withdrawal/deposit/balance."""

    data_rows = [
        r for r in rows
        if r and any(
            re.match(r'^\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}', str(c or "").strip())
            for c in (r[:3] if len(r) >= 3 else r)
        )
    ]
    if not data_rows:
        return {}

    ncols = max(len(r) for r in data_rows)

    def _is_date(v):
        return bool(re.match(r'^\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}', str(v or "").strip()))

    def _is_amount(v):
        s = re.sub(r'[,\s₹$]', '', str(v or "")).strip()
        try:
            float(s)
            return bool(s) and s not in ("-",)
        except:
            return False

    date_cols   = []
    amount_cols = []
    text_cols   = []

    for ci in range(ncols):
        vals  = [r[ci] if ci < len(r) else None for r in data_rows]
        total = len(vals)

        date_score   = sum(1 for v in vals if _is_date(v))   / total
        amount_score = sum(1 for v in vals if _is_amount(v)) / total
        empty_score  = sum(1 for v in vals if is_empty(v))   / total
        text_score   = sum(
            1 for v in vals
            if v and not _is_date(v) and not _is_amount(v) and not is_empty(v)
        ) / total

        if date_score > 0.5:
            date_cols.append((ci, date_score))
        elif amount_score > 0.3:
            amount_cols.append((ci, amount_score, empty_score))
        elif text_score > 0.5:
            text_cols.append((ci, text_score))

    col_map = {}

    # First date col = primary date
    date_cols.sort(key=lambda x: x[0])
    if date_cols:
        col_map["date"] = date_cols[0][0]

    # Longest text col = narration, second = chq_ref
    if text_cols:
        def avg_len(ci):
            vals = [r[ci] if ci < len(r) else "" for r in data_rows]
            return sum(len(str(v or "")) for v in vals) / len(vals)
        text_cols.sort(key=lambda x: -avg_len(x[0]))
        col_map["narration"] = text_cols[0][0]
        if len(text_cols) > 1:
            col_map["chq_ref"] = text_cols[1][0]

    amount_cols.sort(key=lambda x: x[0])

    if len(amount_cols) >= 3:
        # Balance = lowest empty ratio (always has a value)
        balance_ci = sorted(amount_cols, key=lambda x: x[2])[0][0]
        col_map["balance"] = balance_ci
        remaining = [a for a in amount_cols if a[0] != balance_ci]

        if len(remaining) >= 2:
            best_pair, best_excl = None, -1
            for i in range(len(remaining)):
                for j in range(i + 1, len(remaining)):
                    ci, cj = remaining[i][0], remaining[j][0]
                    mutual = sum(
                        1 for r in data_rows
                        if (_is_amount(r[ci] if ci < len(r) else None) and is_empty(r[cj] if cj < len(r) else None))
                        or (is_empty(r[ci] if ci < len(r) else None) and _is_amount(r[cj] if cj < len(r) else None))
                    ) / len(data_rows)
                    if mutual > best_excl:
                        best_excl, best_pair = mutual, (ci, cj)
            if best_pair:
                col_map["withdrawal"] = min(best_pair)
                col_map["deposit"]    = max(best_pair)

    elif len(amount_cols) == 2:
        amount_cols.sort(key=lambda x: x[2])          # lowest empty = balance
        col_map["balance"]    = amount_cols[0][0]
        col_map["withdrawal"] = amount_cols[1][0]

    elif len(amount_cols) == 1:
        col_map["withdrawal"] = amount_cols[0][0]

    return col_map

# ─────────────────────────────────────────────
# ROW PARSING
# ─────────────────────────────────────────────

def parse_rows_to_transactions(rows, col_map):
    transactions = []

    def gcol(cells, key):
        idx = col_map.get(key)
        if idx is not None and idx < len(cells):
            v = clean(cells[idx])
            return "" if v in ("-", "None") else v
        return ""

    for row in rows:
        if not row:
            continue
        cells    = [clean(c) for c in row]
        row_text = " ".join(cells).lower()

        # Skip header rows
        if any(kw in row_text for kw in ["narration", "particulars", "description"]) and \
           any(kw in row_text for kw in ["date", "withdrawal", "deposit", "debit", "credit"]):
            continue

        # Get date
        date_val = gcol(cells, "date")
        if not date_val:
            for c in cells[:3]:
                if re.match(r'^\d{2}[/\-\.]\d{2}[/\-\.]\d{2,4}', c):
                    date_val = c
                    break

        # ── Continuation row: no date → append narration to last transaction ──
        if not date_val or not is_date(date_val):
            if transactions:
                narr_idx = col_map.get("narration")
                if narr_idx is not None and narr_idx < len(cells):
                    extra = clean(cells[narr_idx])
                else:
                    extra = max(cells, key=lambda c: len(c)) if cells else ""
                if extra and extra not in ("-", "None"):
                    transactions[-1]["narration"] = (transactions[-1]["narration"] + " " + extra).strip()
            continue

        narr_val = gcol(cells, "narration") or (cells[1] if len(cells) > 1 else "")
        narr_val = re.sub(r'\s+', ' ', narr_val).strip()
        ref_val  = gcol(cells, "chq_ref") or gcol(cells, "ref")
        wd_val   = gcol(cells, "withdrawal")
        dep_val  = gcol(cells, "deposit")

        if not ref_val:
            for c in cells:
                if re.match(r'^[A-Z0-9]{10,}$', c):
                    ref_val = c
                    break

        # Positional fallback ONLY when col_map has no amount columns at all
        if not wd_val and not dep_val and "withdrawal" not in col_map and "deposit" not in col_map:
            amt_cells = [(i, c) for i, c in enumerate(cells) if is_amount(c)]
            if len(amt_cells) >= 3:
                wd_val  = amt_cells[-3][1]
                dep_val = amt_cells[-2][1]
            elif len(amt_cells) == 2:
                wd_val  = amt_cells[-2][1]
            elif len(amt_cells) == 1:
                dep_val = amt_cells[-1][1]

        wd_num  = parse_amount(wd_val)
        dep_num = parse_amount(dep_val)

        if wd_num and wd_num > 0:
            dr_cr  = "Dr"
            amount = wd_val
        elif dep_num and dep_num > 0:
            dr_cr  = "Cr"
            amount = dep_val
        else:
            # FIX: last transaction — if only one amount col and no Dr/Cr split,
            # use balance delta from previous row to determine direction
            continue

        transactions.append({
            "date":      date_val,
            "narration": narr_val or "-",
            "chq_ref":   ref_val  or "-",
            "dr_cr":     dr_cr,
            "amount":    amount,
        })

    return transactions

# ─────────────────────────────────────────────
# PDF EXTRACTION
# ─────────────────────────────────────────────

def extract_transactions_from_pdf(file_bytes, password=""):
    unlocked = unlock_pdf(file_bytes, password)
    all_transactions = []
    last_good_col_map = {}

    with pdfplumber.open(unlocked) as pdf:
        for page_num, page in enumerate(pdf.pages):

            best_rows  = []
            best_score = -1

            for s in [
                {"vertical_strategy": "lines",  "horizontal_strategy": "lines"},
                {"vertical_strategy": "lines",  "horizontal_strategy": "text"},
                {"vertical_strategy": "text",   "horizontal_strategy": "lines"},
                {"vertical_strategy": "text",   "horizontal_strategy": "text"},
            ]:
                tables = page.extract_tables(s)
                if not tables:
                    continue
                for table in tables:
                    if not table:
                        continue
                    t_rows = [r for r in table if r]
                    score  = sum(
                        1 for r in t_rows if any(
                            re.match(r'^\d{2}[/\-\.]\d{2}[/\-\.]\d{2,4}', clean(c))
                            for c in r[:3]
                        )
                    )
                    if score > best_score:
                        best_rows, best_score = t_rows, score

            if best_score <= 0:
                print(f"Page {page_num + 1}: no transaction table found")
                continue

            col_map = detect_columns(best_rows)

            if not col_map:
                col_map = last_good_col_map
            elif "withdrawal" in col_map or "deposit" in col_map:
                last_good_col_map = col_map
            else:
                col_map = last_good_col_map or col_map

            if not col_map:
                print(f"Page {page_num + 1}: could not detect columns, skipping")
                continue

            txns = parse_rows_to_transactions(best_rows, col_map)
            all_transactions.extend(txns)
            print(f"Page {page_num + 1}: extracted {len(txns)} transactions, col_map={col_map}")

    return all_transactions

# ─────────────────────────────────────────────
# GROQ ENRICHMENT
# ─────────────────────────────────────────────

CHUNK = 40  # transactions per Groq call

def enrich_narrations(narrations_with_drcr):
    """
    narrations_with_drcr: list of strings like "WDL TFR UPI/DR/... [Dr]"
    Returns: shorts, gst_tags, categories, gst_notes, is_salary
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or not narrations_with_drcr:
        n = len(narrations_with_drcr)
        return ([smart_shorten(x) for x in narrations_with_drcr],
                [""] * n, ["-"] * n, [""] * n, [False] * n)

    client   = Groq(api_key=api_key)
    all_shorts, all_gst, all_cats, all_notes, all_sal = [], [], [], [], []

    for start in range(0, len(narrations_with_drcr), CHUNK):
        chunk = narrations_with_drcr[start:start + CHUNK]
        narr_list = "\n".join([f"{i+1}. {n}" for i, n in enumerate(chunk)])

        prompt = f"""You are an expert Indian bank transaction analyst.

Each narration ends with [Dr] (money OUT) or [Cr] (money IN).

Return exactly {len(chunk)} JSON objects — one per narration.

FIELDS:
- short: human-readable label, max 8 words
  * Format: "FULL NAME (NEFT)" or "FULL NAME (UPI)" or "Company Name (IMPS)" etc.
  * Keep COMPLETE name — never truncate. E.g. "TASLIMA BIBI (NEFT)", "UTKARSH KUMAR (NEFT)", "TITAN COMPANY LIMITED"
  * For ATM: "ATM Withdrawal"
  * For bank charges: "Bank Charges"

- gst: ITC eligibility — choose ONE of:
    * "No GST"       — ONLY for clear salary-to-individual payments
    * "Zero Rated"   — ONLY for very clear export / foreign receipt cases
    * "ITC Eligible" — use ONLY if the narration itself makes business GST eligibility obvious beyond doubt
    * ""             — default for insurance, business payments, subscriptions, vendors, loan EMI, mutual fund, personal transfers, and all uncertain cases
    * Be conservative: if there is any doubt, leave gst as ""

- gst_notes: one short sentence explaining gst decision
  * Salary: "Salary Payment (Outside GST Scope)"
    * Export: "Export of Service - Zero Rated"
  * Blank if gst is ""

- category: specific real-world purpose, max 8 words
  * [Dr] to individual person name → "Salary Payment"
  * [Dr] to business → actual purpose e.g. "Food Order", "Cloud Services", "Insurance Premium"
  * [Cr] from individual → "Payment Received from Individual"
  * [Cr] from business → "Business Receipt" or specific purpose
  * Never use "Personal Transfer" — always infer the real purpose

IMPORTANT GST RULE:
- If is_salary is true, gst should usually be "No GST"
- If is_salary is false, prefer gst="" and gst_notes="" unless export/foreign receipt is extremely clear
- For insurance, vendors, business expenses, software tools, subscriptions, bank charges, loan EMI, investments, and ambiguous business receipts: keep gst blank

- is_salary: boolean
  * true ONLY if: transaction is [Dr] AND recipient is a real human name (2-3 words, no company suffix)
  * false for ALL [Cr] transactions — money coming IN is NEVER salary you pay
  * false for businesses, brands, banks, insurance companies
  * Examples: "UTKARSH KUMAR [Dr]"=true, "TANAY ME [Cr]"=false, "HARSHIL [Cr]"=false, "DOMINOS [Dr]"=false

Respond ONLY with a raw JSON array, no markdown, no explanation.
Each object: {{"short":"...","gst":"...","gst_notes":"...","category":"...","is_salary":true/false}}

Narrations:
{narr_list}"""

        try:
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=10000,
            )
            content = resp.choices[0].message.content.strip()
            match   = re.search(r'\[.*\]', content, re.DOTALL)
            result  = []
            if match:
                raw = match.group()
                try:
                    result = json.loads(raw)
                except json.JSONDecodeError:
                    last = raw.rfind('},')
                    if last != -1:
                        try:
                            result = json.loads(raw[:last + 1] + ']')
                        except:
                            pass

            # Pad if Groq returned fewer
            while len(result) < len(chunk):
                result.append({"short": "-", "gst": "", "gst_notes": "", "category": "-", "is_salary": False})
            result = result[:len(chunk)]

            all_shorts.extend([str(r.get("short",    "-")).strip() or "-" for r in result])
            all_gst   .extend([str(r.get("gst",       "")).strip()        for r in result])
            all_cats  .extend([str(r.get("category",  "-")).strip() or "-" for r in result])
            all_notes .extend([str(r.get("gst_notes", "")).strip()        for r in result])
            all_sal   .extend([bool(r.get("is_salary", False))            for r in result])

        except Exception as e:
            print(f"Groq error on chunk {start}: {e}")
            n = len(chunk)
            all_shorts.extend([smart_shorten(x) for x in chunk])
            all_gst   .extend([""] * n)
            all_cats  .extend(["-"] * n)
            all_notes .extend([""] * n)
            all_sal   .extend([False] * n)

    return all_shorts, all_gst, all_cats, all_notes, all_sal

# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────

def extract_transactions(file_bytes, password=""):
    transactions = extract_transactions_from_pdf(file_bytes, password)

    if not transactions:
        return None, "No transactions found"

    print(f"Total transactions extracted: {len(transactions)}")

    # Build narrations with [Dr]/[Cr] tag for Groq context
    narrations_with_drcr = [
        f"{t['narration']} [{t.get('dr_cr', '?')}]"
        for t in transactions
    ]

    shorts, gst_tags, categories, gst_notes, is_salary = enrich_narrations(narrations_with_drcr)

    # ── Hardcoded overrides ──────────────────────────────────────
    export_contractors = ["bilalmajbour", "bilal majbour", "bilal majbur"]

    for i, t in enumerate(transactions):
        narr_lower = t["narration"].lower()

        if any(name in narr_lower for name in export_contractors):
            gst_tags[i]   = "Zero Rated"
            gst_notes[i]  = "Export of Service - UAE"
            categories[i] = "Export Software Contract (UAE, USD)"

        elif is_salary[i] and t.get("dr_cr") == "Dr":
            gst_tags[i]   = "No GST"
            gst_notes[i]  = "Salary Payment (Outside GST Scope)"
            categories[i] = "Salary Payment"

        else:
            # Don't wipe Groq's decision — only clear if Groq returned something wrong
            # Leave gst_tags[i] and gst_notes[i] as Groq returned them
            pass

    # ── Build final dataframe ────────────────────────────────────
    final = []
    for i, t in enumerate(transactions):
        final.append([
            t["date"],
            t["narration"],
            shorts[i],
            t["chq_ref"],
            t["dr_cr"],
            t["amount"],
            categories[i],
            gst_tags[i],
            gst_notes[i],
        ])

    columns = ["Date", "Narration", "Narration(Short)", "Chq./Ref.No.",
               "Dr/Cr", "Amount(₹)", "Category", "GST", "GST Notes"]
    df = pd.DataFrame(final, columns=columns)
    df = df.map(lambda x: re.sub(r'\s+', ' ', str(x)).strip() if x else "")
    df = df[df["Date"].apply(is_date)]
    df.reset_index(drop=True, inplace=True)

    if df.empty:
        return None, "No valid transactions found after filtering"

    return df, None

# ─────────────────────────────────────────────
# EXCEL MEMORY — PARTY RULES
# ─────────────────────────────────────────────

def clean_party_name(name):
    """Normalize narration/party text into a stable identity for matching."""
    if not name:
        return ""
    result = str(name).upper()

    # Drop IDs, punctuation-heavy fragments and bracketed transfer info.
    result = re.sub(r'\([^)]*\)', ' ', result)
    result = re.sub(r'[^A-Z\s]', ' ', result)
    result = re.sub(r'\s+', ' ', result).strip()

    stop_words = {
        "UPI", "NEFT", "IMPS", "RTGS", "ACH", "CHQ", "CHEQUE", "REF", "REFNO",
        "TRANSFER", "PAYMENT", "RECEIVED", "RECEIPT", "CREDIT", "DEBIT",
        "NETBANK", "NETBANKING", "INB", "MB", "MOB", "INSTA", "BY", "TO", "FROM",
        "THE", "AND", "BANK", "PVT", "LTD", "LIMITED", "PRIVATE", "INDIA", "MUM", "DELHI",
    }

    tokens = [t for t in result.split() if len(t) > 1 and t not in stop_words]
    return " ".join(tokens[:8]).strip()


def fuzzy_score(a, b):
    """Hybrid similarity score using sequence ratio + token overlap."""
    a, b = a.lower().strip(), b.lower().strip()
    if not a or not b:
        return 0

    if a in b or b in a:
        return 96

    seq_score = int(SequenceMatcher(None, a, b).ratio() * 100)

    ta = set(a.split())
    tb = set(b.split())
    token_score = 0
    if ta and tb:
        token_score = int((len(ta & tb) / max(1, min(len(ta), len(tb)))) * 100)

    return max(seq_score, token_score)


def normalize_date_key(text):
    s = str(text or "").strip()
    if not s:
        return ""
    m = re.match(r'^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})$', s)
    if not m:
        return s
    d, mo, y = m.groups()
    if len(y) == 2:
        y = "20" + y
    return f"{int(d):02d}/{int(mo):02d}/{y}"


def normalize_amount_key(text):
    v = parse_amount(text)
    if v is None:
        return ""
    return f"{v:.2f}"


def normalize_drcr_key(text):
    s = str(text or "").strip().upper()
    if s.startswith("D"):
        return "DR"
    if s.startswith("C"):
        return "CR"
    return s


def load_party_rules(excel_bytes):
    """
    Read a previously tagged Excel file and build a party → tags lookup.
    Returns dict: { cleaned_party_name: {Category, GST, GST Notes} }
    """
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(excel_bytes), data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return {}

        # Find header row
        header = None
        header_idx = 0
        for i, row in enumerate(rows[:5]):
            row_lower = [str(c or "").lower() for c in row]
            if any("narration" in c or "party" in c for c in row_lower):
                header = row_lower
                header_idx = i
                break

        if not header:
            return {}

        # Find column indexes
        def find_col(keywords):
            for j, h in enumerate(header):
                if any(kw in h for kw in keywords):
                    return j
            return None

        short_col = find_col(["short", "party"])
        cat_col   = find_col(["category"])
        gst_col   = find_col(["gst mark", "gst"])
        note_col  = find_col(["gst note", "notes"])

        if short_col is None or cat_col is None:
            return {}

        rules = {}
        txn_rules = {}
        amt_dr_candidates = {}

        date_col = find_col(["date", "txn date", "value date"]) 
        drcr_col = find_col(["dr/cr", "dr cr", "debit/credit", "debit credit"]) 
        amt_col = find_col(["amount", "amount(₹)", "amount rs", "amount inr"]) 

        for row in rows[header_idx + 1:]:
            party = str(row[short_col] or "").strip()
            cat   = str(row[cat_col]   or "").strip() if cat_col is not None else ""
            gst   = str(row[gst_col]   or "").strip() if gst_col is not None else ""
            note  = str(row[note_col]  or "").strip() if note_col is not None else ""

            if not party or not cat or cat in ("-", "None"):
                continue

            key = clean_party_name(party)
            if key:
                rules[key] = {"Category": cat, "GST": gst, "GST Notes": note}

            # Transaction signature memory: (Date, Dr/Cr, Amount) -> tags
            if date_col is not None and drcr_col is not None and amt_col is not None:
                date_key = normalize_date_key(row[date_col] if date_col < len(row) else "")
                drcr_key = normalize_drcr_key(row[drcr_col] if drcr_col < len(row) else "")
                amt_key = normalize_amount_key(row[amt_col] if amt_col < len(row) else "")
                if date_key and drcr_key and amt_key:
                    tags_obj = {
                        "Category": cat,
                        "GST": gst,
                        "GST Notes": note,
                        "Narration(Short)": party,
                    }
                    txn_rules[(date_key, drcr_key, amt_key)] = tags_obj

                    # Date-agnostic fallback key for next months.
                    amt_dr_key = (drcr_key, amt_key)
                    amt_dr_candidates.setdefault(amt_dr_key, []).append(tags_obj)

        # Keep only unambiguous (Dr/Cr, Amount) mappings.
        amt_dr_rules = {}
        for key, arr in amt_dr_candidates.items():
            uniq = {
                (
                    str(x.get("Category", "")).strip(),
                    str(x.get("GST", "")).strip(),
                    str(x.get("GST Notes", "")).strip(),
                    str(x.get("Narration(Short)", "")).strip(),
                )
                for x in arr
            }
            if len(uniq) == 1:
                c, g, n, s = next(iter(uniq))
                amt_dr_rules[key] = {
                    "Category": c,
                    "GST": g,
                    "GST Notes": n,
                    "Narration(Short)": s,
                }

        print(
            f"Loaded {len(rules)} party rules, {len(txn_rules)} txn rules, "
            f"{len(amt_dr_rules)} amt-dr rules from Excel"
        )
        return {"party_rules": rules, "txn_rules": txn_rules, "amt_dr_rules": amt_dr_rules}

    except Exception as e:
        print(f"load_party_rules error: {e}")
        return {"party_rules": {}, "txn_rules": {}, "amt_dr_rules": {}}


def match_party(party_name, party_rules, threshold=68):
    """
    Find best matching party from rules.
    Returns tags dict if match found above threshold, else None.
    Priority:
      1. Exact match on cleaned name
      2. One contains the other
      3. Fuzzy score above threshold
    """
    if not party_name or not party_rules:
        return None

    cleaned = clean_party_name(party_name)
    if not cleaned:
        return None

    best_score = 0
    best_match = None

    for known_party, tags in party_rules.items():
        # Exact match
        if cleaned == known_party:
            return tags

        # Substring match
        if cleaned in known_party or known_party in cleaned:
            score = 92
        else:
            score = fuzzy_score(cleaned, known_party)

        if score > best_score:
            best_score = score
            best_match = known_party

    if best_score >= threshold and best_match:
        print(f"  Matched '{party_name}' → '{best_match}' (score={best_score})")
        return party_rules[best_match]

    return None


def extract_transactions_with_memory(file_bytes, password="", excel_bytes=None):
    """
    Enhanced extraction that uses previous Excel to pre-fill known parties.
    Falls back to Groq only for unrecognised transactions.
    """
    transactions = extract_transactions_from_pdf(file_bytes, password)

    if not transactions:
        return None, "No transactions found"

    print(f"Total transactions extracted: {len(transactions)}")

    # Load party rules from previous Excel (if provided)
    memory_rules = load_party_rules(excel_bytes) if excel_bytes else {"party_rules": {}, "txn_rules": {}, "amt_dr_rules": {}}
    party_rules = memory_rules.get("party_rules", {})
    txn_rules = memory_rules.get("txn_rules", {})
    amt_dr_rules = memory_rules.get("amt_dr_rules", {})

    # Separate matched vs unmatched
    matched_indices = {}   # index → tags from Excel
    groq_indices    = []   # indices that need Groq

    for i, t in enumerate(transactions):
        # 1) Month-independent party match first.
        party = t.get("narration_short") or t["narration"]
        tags = match_party(party, party_rules)
        if tags and tags.get("Category") and tags["Category"] not in ("-", ""):
            matched_indices[i] = tags
            continue

        # 2) Exact same-transaction match when date also aligns.
        sig = (
            normalize_date_key(t.get("date")),
            normalize_drcr_key(t.get("dr_cr")),
            normalize_amount_key(t.get("amount")),
        )

        sig_tags = txn_rules.get(sig)
        if sig_tags and sig_tags.get("Category") and sig_tags["Category"] not in ("-", ""):
            matched_indices[i] = sig_tags
            continue

        # 3) Date-agnostic fallback: (Dr/Cr, Amount) only if mapping is unique.
        amt_dr_key = (sig[1], sig[2])
        amt_dr_tags = amt_dr_rules.get(amt_dr_key)
        if amt_dr_tags and amt_dr_tags.get("Category") and amt_dr_tags["Category"] not in ("-", ""):
            matched_indices[i] = amt_dr_tags
            continue

        groq_indices.append(i)

    print(f"  Excel matched: {len(matched_indices)} | Groq needed: {len(groq_indices)}")

    # Run Groq only on unmatched
    groq_narrations = [
        f"{transactions[i]['narration']} [{transactions[i].get('dr_cr', '?')}]"
        for i in groq_indices
    ]

    shorts_all    = [""] * len(transactions)
    gst_all       = [""] * len(transactions)
    cats_all      = [""] * len(transactions)
    notes_all     = [""] * len(transactions)
    salary_all    = [False] * len(transactions)

    # Fill matched from Excel
    for i, tags in matched_indices.items():
        if tags.get("Narration(Short)"):
            shorts_all[i] = merge_short_with_transfer(tags.get("Narration(Short)"), transactions[i]["narration"])
        else:
            shorts_all[i] = smart_shorten(transactions[i]["narration"])
        cats_all[i]   = tags.get("Category", "")
        gst_all[i]    = tags.get("GST", "")
        notes_all[i]  = tags.get("GST Notes", "")
        salary_all[i] = "salary" in tags.get("Category", "").lower()

    # Fill Groq results
    if groq_narrations:
        g_shorts, g_gst, g_cats, g_notes, g_sal = enrich_narrations(groq_narrations)
        for pos, i in enumerate(groq_indices):
            shorts_all[i]  = g_shorts[pos]
            gst_all[i]     = g_gst[pos]
            cats_all[i]    = g_cats[pos]
            notes_all[i]   = g_notes[pos]
            salary_all[i]  = g_sal[pos]

    # Hardcoded overrides
    export_contractors = ["bilalmajbour", "bilal majbour", "bilal majbur"]

    for i, t in enumerate(transactions):
        narr_lower = t["narration"].lower()
        if any(name in narr_lower for name in export_contractors):
            gst_all[i]  = "Zero Rated"
            notes_all[i] = "Export of Service - UAE"
            cats_all[i]  = "Export Software Contract (UAE, USD)"
        elif salary_all[i] and t.get("dr_cr") == "Dr":
            gst_all[i]  = "No GST"
            notes_all[i] = "Salary Payment (Outside GST Scope)"
            cats_all[i]  = "Salary Payment"

    # Build final dataframe
    final = []
    for i, t in enumerate(transactions):
        final.append([
            t["date"], t["narration"], shorts_all[i],
            t["chq_ref"], t["dr_cr"], t["amount"],
            cats_all[i], gst_all[i], notes_all[i],
        ])

    columns = ["Date", "Narration", "Narration(Short)", "Chq./Ref.No.",
               "Dr/Cr", "Amount(₹)", "Category", "GST", "GST Notes"]
    df = pd.DataFrame(final, columns=columns)
    df = df.map(lambda x: re.sub(r'\s+', ' ', str(x)).strip() if x else "")
    df = df[df["Date"].apply(is_date)]
    df.reset_index(drop=True, inplace=True)

    if df.empty:
        return None, "No valid transactions found after filtering"

    return df, None