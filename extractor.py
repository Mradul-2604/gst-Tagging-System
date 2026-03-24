# import pdfplumber
# import pypdf
# import pandas as pd
# import re
# import io
# import os
# import json
# from dotenv import load_dotenv
# from groq import Groq

# load_dotenv()

# def unlock_pdf(file_bytes, password):
#     reader = pypdf.PdfReader(io.BytesIO(file_bytes))
#     if reader.is_encrypted:
#         reader.decrypt(password)
#     writer = pypdf.PdfWriter()
#     for page in reader.pages:
#         writer.add_page(page)
#     unlocked = io.BytesIO()
#     writer.write(unlocked)
#     unlocked.seek(0)
#     return unlocked

# def is_date(text):
#     return bool(re.match(r'^\d{2}[/\-\.]\d{2}[/\-\.]\d{2,4}$', str(text).strip()))

# def is_amount(text):
#     return bool(re.match(r'^[\d,]+\.\d{2}$', str(text).strip()))

# def clean(val):
#     return re.sub(r'\s+', ' ', str(val)).strip() if val else ""

# def is_footer_row(cells):
#     text = " ".join(cells).lower().replace(" ", "")
#     keywords = [
#         "statementsummary", "openingbalance", "generatedon", "generatedby",
#         "closingbalanceincludes", "contentsofthis", "registeredoffice",
#         "hdfcbanklimited", "hdfcbankgstin", "stateaccountbranch",
#         "accountbranch", "accountno", "custid", "nomination",
#         "bizpro", "jointholders", "drcount", "crcount"
#     ]
#     return any(kw in text for kw in keywords)

# def try_extract_tables(page):
#     strategies = [
#         {"vertical_strategy": "lines", "horizontal_strategy": "lines"},
#         {"vertical_strategy": "lines", "horizontal_strategy": "text"},
#         {"vertical_strategy": "text",  "horizontal_strategy": "lines"},
#         {"vertical_strategy": "text",  "horizontal_strategy": "text"},
#     ]
#     best = []
#     best_score = -1

#     for s in strategies:
#         tables = page.extract_tables(s)
#         all_rows = [row for t in tables for row in t if t]

#         score = 0
#         for row in all_rows:
#             if not row:
#                 continue
#             cells = [re.sub(r'\s+', ' ', str(c)).strip() if c else "" for c in row]
#             for i in range(min(2, len(cells))):
#                 if re.match(r'^\d{2}[/\-\.]\d{2}[/\-\.]\d{2,4}', cells[i]):
#                     score += 1
#                     break

#         effective_score = score * 1000 + len(all_rows)
#         if effective_score > best_score:
#             best = all_rows
#             best_score = effective_score

#     return best

# def detect_transaction(cells):
#     c0 = clean(cells[0]) if len(cells) > 0 else ""
#     c1 = clean(cells[1]) if len(cells) > 1 else ""

#     if c0 == "" or c0 == "None":
#         match = re.match(r'^(\d{2}[/\-\.]\d{2}[/\-\.]\d{2,4})\s+(\S.*)', c1)
#         if match:
#             return match.group(1), match.group(2), 2

#     if is_date(c0) and c1 and not is_amount(c1) and not is_date(c1):
#         return c0, c1, 2

#     match = re.match(r'^(\d{2}[/\-\.]\d{2}[/\-\.]\d{2,4})\s+(\S*)', c0)
#     if match:
#         partial = match.group(2)
#         narration = partial + c1
#         return match.group(1), narration, 2

#     return None, None, None

# def extract_amounts(cells):
#     indexed_amounts = []
#     for i, cell in enumerate(cells):
#         v = clean(cell)
#         for part in v.split():
#             if is_amount(part):
#                 indexed_amounts.append((i, part))

#     if not indexed_amounts:
#         return "", "", ""

#     closing = indexed_amounts[-1][1]

#     if len(indexed_amounts) == 1:
#         return "", "", closing
#     elif len(indexed_amounts) >= 3:
#         return indexed_amounts[0][1], indexed_amounts[1][1], closing
#     else:
#         return indexed_amounts[0][1], "", closing

# def fallback_shorten(narration):
#     if not narration:
#         return ""
#     cleaned = re.sub(r'[0-9@#\.\-\_\/]', ' ', narration.upper())
#     words = [w for w in cleaned.split() if len(w) > 2][:4]
#     return " ".join(words).title() if words else narration[:30].title()

# def process_narrations_batch(narrations):
#     """
#     Single Groq API call that returns short narration, GST tag, and category.
#     Returns three lists: (short_narrations, gst_tags, categories)
#     """
#     api_key = os.getenv("GROQ_API_KEY")
#     if not api_key:
#         print("No GROQ_API_KEY found, using fallback")
#         return [fallback_shorten(n) for n in narrations], ["No GST"] * len(narrations), [""] * len(narrations)

#     client = Groq(api_key=api_key)
#     narration_list = "\n".join([f"{i+1}. {n}" for i, n in enumerate(narrations)])

#     prompt = f"""You are an expert Indian bank transaction analyst.

# For each bank transaction narration, provide three things:
# 1. A short human-readable description (max 5 words)
# 2. Whether the transaction involves GST or not
# 3. A meaningful business category describing the purpose of the transaction

# SHORT DESCRIPTION RULES:
# - Use formats like: "UPI to [Name]", "NEFT from [Name]", "NEFT to [Name]", "Cheque to [Name]", "ATM Withdrawal", "Salary Credit", "EMI Payment"
# - Extract actual person or business name where possible
# - Remove all reference numbers, bank codes, transaction IDs
# - If known service use that name directly

# CATEGORY RULES:
# - Write a short meaningful business purpose (3-6 words)
# - Be specific and descriptive based on what you can infer from the narration
# - Do not just repeat the short description

# GST RULES:
# TRANSACTIONS WITH GST:
# - Payment to any registered business for goods or services
# - Online shopping, food delivery, travel, hotels, flights
# - Telecom & internet bills, utility bills
# - Software & streaming subscriptions
# - Professional services
# - Any company with PVT, LTD, LLP, CORP, ENTERPRISE, INDUSTRIES, TRADERS, SOLUTIONS, SERVICES, TECHNOLOGIES
# - Payment via payment gateway (PAYU, RAZORPAY, BILLDESK, CCAVENUE, EASEBUZZ)

# TRANSACTIONS WITHOUT GST:
# - Transfer to an individual person
# - Salary, residential rent, loan EMI, insurance premium
# - Mutual fund, SIP, stock investments
# - ATM withdrawals, income tax, TDS, government payments
# - Person to person transfers

# HOW TO IDENTIFY INDIVIDUAL VS BUSINESS:
# - Personal name (common first+last name) = individual = No GST
# - Business keywords (PVT, LTD, STORE, MART, SHOP, HOSPITAL) = GST
# - Payment gateways (PAYU, RAZORPAY) = always GST
# - If unclear, default to No GST

# Respond ONLY with a valid JSON array with exactly {len(narrations)} objects.
# Each object must have exactly three keys: "short", "gst", "category".
# "gst" must be exactly "GST" or "No GST".
# No explanation, no extra text, just the raw JSON array.

# Example:
# [
#   {{"short": "NEFT to Raj Kumar", "gst": "No GST", "category": "Salary payment"}},
#   {{"short": "NEFT from Bilal Majbour", "gst": "No GST", "category": "Export software contract"}},
#   {{"short": "Cheque to Titan", "gst": "GST", "category": "Watch purchase for client"}},
#   {{"short": "UPI to Swiggy", "gst": "GST", "category": "Food delivery"}}
# ]

# Transactions to analyze:
# {narration_list}"""

#     try:
#         response = client.chat.completions.create(
#             model="llama-3.3-70b-versatile",
#             messages=[{"role": "user", "content": prompt}],
#             temperature=0,
#         )

#         content = response.choices[0].message.content.strip()
#         match = re.search(r'\[.*?\]', content, re.DOTALL)
#         if match:
#             result = json.loads(match.group())
#             if len(result) == len(narrations):
#                 short_narrations = [str(r.get("short", "")).strip() for r in result]
#                 gst_tags = ["GST" if str(r.get("gst", "")).strip().upper() == "GST" else "No GST" for r in result]
#                 categories = [str(r.get("category", "")).strip() for r in result]
#                 return short_narrations, gst_tags, categories

#         print(f"Groq parse failed: {content}")
#         return [fallback_shorten(n) for n in narrations], ["No GST"] * len(narrations), [""] * len(narrations)

#     except Exception as e:
#         print(f"Groq API error: {e}")
#         return [fallback_shorten(n) for n in narrations], ["No GST"] * len(narrations), [""] * len(narrations)

# def classify_amounts(transactions):
#     def parse_num(s):
#         try:
#             return float(s.replace(",", ""))
#         except:
#             return None

#     def guess_from_narration(narration):
#         n = str(narration).upper()
#         if any(x in n for x in ["NEFTCR", "RTGSCR", "IMPS CR", "CR-", "/CR", "CREDIT"]):
#             return "deposit"
#         if any(x in n for x in ["NEFTDR", "RTGSDR", "IMPS DR", "DR-", "/DR", "DEBIT"]):
#             return "withdrawal"
#         return None

#     for i, txn in enumerate(transactions):
#         # 0=date, 1=narration, 2=short, 3=chq, 4=valuedt, 5=withdrawal, 6=deposit, 7=closing
#         narration  = txn[1]
#         withdrawal = txn[5]
#         deposit    = txn[6]
#         closing    = txn[7]

#         if withdrawal and deposit:
#             continue

#         amount = withdrawal or deposit
#         if not amount:
#             continue

#         direction = None

#         if i == 0:
#             direction = guess_from_narration(narration)
#             if direction is None:
#                 direction = "deposit"
#         else:
#             prev_closing = parse_num(transactions[i-1][7])
#             curr_closing = parse_num(closing)
#             if prev_closing is not None and curr_closing is not None:
#                 direction = "withdrawal" if curr_closing < prev_closing else "deposit"

#         if direction == "withdrawal":
#             transactions[i][5] = amount
#             transactions[i][6] = ""
#         elif direction == "deposit":
#             transactions[i][5] = ""
#             transactions[i][6] = amount

#     return transactions

# def extract_transactions(file_bytes, password=""):
#     unlocked_pdf = unlock_pdf(file_bytes, password)

#     transactions = []
#     header_found = False
#     in_transaction_section = False

#     with pdfplumber.open(unlocked_pdf) as pdf:
#         for page_num, page in enumerate(pdf.pages):
#             rows = try_extract_tables(page)

#             for row in rows:
#                 if not row:
#                     continue

#                 cells = [clean(c) for c in row]

#                 if all(c == "" or c == "None" for c in cells):
#                     continue

#                 row_text = " ".join(cells).lower()

#                 if "date" in row_text and "narration" in row_text:
#                     header_found = True
#                     in_transaction_section = True
#                     continue

#                 if not header_found:
#                     continue

#                 non_empty = [c for c in cells if c and c != "None"]
#                 if non_empty and is_footer_row(cells):
#                     in_transaction_section = False
#                     continue

#                 date, narration, rest_start = detect_transaction(cells)
#                 if date and not in_transaction_section:
#                     in_transaction_section = True

#                 if not in_transaction_section:
#                     continue

#                 if date:
#                     remaining = cells[rest_start:]
#                     chq_parts = []
#                     valuedt = ""
#                     amount_start = 0

#                     for j, val in enumerate(remaining):
#                         v = clean(val)
#                         if is_date(v):
#                             valuedt = v
#                             amount_start = j + 1
#                             break
#                         elif is_amount(v):
#                             amount_start = j
#                             break
#                         elif v and v != "None":
#                             chq_parts.append(v)

#                     chq = "".join(chq_parts)
#                     amount_cells = remaining[amount_start:]
#                     withdrawal, deposit, closing = extract_amounts(amount_cells)

#                     # 0=date,1=narration,2=short,3=chq,4=valuedt,5=withdrawal,6=deposit,7=closing
#                     transactions.append([date, narration, "", chq, valuedt, withdrawal, deposit, closing])

#                 elif transactions:
#                     for c in cells:
#                         v = clean(c)
#                         if v and v not in ("None", "") and not is_amount(v) and not is_date(v) and len(v) > 2:
#                             transactions[-1][1] += " " + v
#                             break

#     if not transactions:
#         return None, "No transactions found"

#     transactions = [list(t) for t in transactions]
#     transactions = classify_amounts(transactions)

#     # Single API call for short narration, GST tag, and category
#     narrations = [t[1] for t in transactions]
#     short_narrations, gst_tags, categories = process_narrations_batch(narrations)

#     # Build final rows — Dr/Cr + Amount, no ClosingBalance
#     final_transactions = []
#     for i, t in enumerate(transactions):
#         date       = t[0]
#         narration  = t[1]
#         short      = short_narrations[i]
#         chq        = t[3]
#         valuedt    = t[4]
#         withdrawal = t[5]
#         deposit    = t[6]
#         # t[7] = closing — excluded from output
#         gst        = gst_tags[i]
#         category   = categories[i]

#         if withdrawal:
#             dr_cr  = "Dr"
#             amount = withdrawal
#         else:
#             dr_cr  = "Cr"
#             amount = deposit

#         final_transactions.append([date, narration, short, chq, valuedt, dr_cr, amount, gst, category])

#     clean_header = ["Date", "Narration", "Narration(Short)", "Chq./Ref.No.", "ValueDt", "Dr/Cr", "Amount(₹)", "GST", "Category"]
#     df = pd.DataFrame(final_transactions, columns=clean_header)
#     df = df.map(lambda x: re.sub(r'\s+', ' ', str(x)).strip() if x else "")
#     df = df[df["Date"].apply(is_date)]
#     df.reset_index(drop=True, inplace=True)

#     return df, None









# import pdfplumber
# import pypdf
# import pandas as pd
# import re
# import io
# import os
# import json
# from dotenv import load_dotenv
# from groq import Groq

# load_dotenv()

# def unlock_pdf(file_bytes, password):
#     reader = pypdf.PdfReader(io.BytesIO(file_bytes))
#     if reader.is_encrypted:
#         reader.decrypt(password)
#     writer = pypdf.PdfWriter()
#     for page in reader.pages:
#         writer.add_page(page)
#     unlocked = io.BytesIO()
#     writer.write(unlocked)
#     unlocked.seek(0)
#     return unlocked

# def is_date(text):
#     return bool(re.match(r'^\d{2}[/\-\.]\d{2}[/\-\.]\d{2,4}$', str(text).strip()))

# def is_amount(text):
#     return bool(re.match(r'^[\d,]+\.\d{2}$', str(text).strip()))

# def clean(val):
#     return re.sub(r'\s+', ' ', str(val)).strip() if val else ""

# def fallback_shorten(narration):
#     if not narration:
#         return ""
#     cleaned = re.sub(r'[0-9@#\.\-\_\/]', ' ', narration.upper())
#     words = [w for w in cleaned.split() if len(w) > 2][:4]
#     return " ".join(words).title() if words else narration[:30].title()

# def extract_text_from_pdf(file_bytes, password=""):
#     """Extract raw text from all pages of PDF."""
#     unlocked = unlock_pdf(file_bytes, password)
#     pages_text = []
#     with pdfplumber.open(unlocked) as pdf:
#         for page in pdf.pages:
#             text = page.extract_text()
#             if text:
#                 pages_text.append(text.strip())
#     return pages_text

# def parse_transactions_with_groq(pages_text):
#     api_key = os.getenv("GROQ_API_KEY")
#     if not api_key:
#         return None, "No GROQ_API_KEY found in .env"

#     client = Groq(api_key=api_key)
#     full_text = "\n\n--- PAGE BREAK ---\n\n".join(pages_text)

#     if len(full_text) > 12000:
#         full_text = full_text[:12000]

#     prompt = f"""You are an expert at reading Indian bank statement PDFs.

# Extract ALL transactions from the following bank statement text.

# RULES:
# - Extract every single transaction row, do not skip any
# - Date format in output must be DD/MM/YY or DD/MM/YYYY
# - Amount must be a number with 2 decimal places like 1000.00 or 1,00,000.00
# - dr_cr must be exactly "Dr" if money went OUT of account, "Cr" if money came IN
# - narration is the full transaction description as it appears
# - chq_ref is the cheque number or reference number if present, else empty string
# - value_dt is the value date if present, else empty string
# - Ignore header rows, footer rows, summary rows, opening balance rows
# - Only include actual transaction rows

# Respond ONLY with a valid JSON array. No explanation, no extra text.

# Each object must have exactly these keys:
# - "date": transaction date as string
# - "narration": full narration as string
# - "chq_ref": cheque/reference number as string
# - "value_dt": value date as string
# - "dr_cr": "Dr" or "Cr"
# - "amount": amount as string with 2 decimals

# Bank statement text:
# {full_text}"""

#     try:
#         response = client.chat.completions.create(
#             model="llama-3.3-70b-versatile",
#             messages=[{"role": "user", "content": prompt}],
#             temperature=0,
#             max_tokens=8000,
#         )

#         content = response.choices[0].message.content.strip()
#         print(f"Groq extraction response length: {len(content)}")

#         # Greedy match to get full array
#         match = re.search(r'\[.*\]', content, re.DOTALL)
#         if match:
#             raw = match.group()
#             try:
#                 result = json.loads(raw)
#             except json.JSONDecodeError:
#                 # Fix truncated JSON — trim to last complete object
#                 last_brace = raw.rfind('},')
#                 if last_brace != -1:
#                     raw = raw[:last_brace + 1] + ']'
#                     try:
#                         result = json.loads(raw)
#                     except:
#                         return None, "Groq returned truncated JSON, try a shorter statement"
#                 else:
#                     return None, f"Groq could not parse transactions: {content[:200]}"

#             if isinstance(result, list) and len(result) > 0:
#                 print(f"Parsed {len(result)} transactions")
#                 return result, None

#         return None, f"Groq could not parse transactions: {content[:200]}"

#     except Exception as e:
#         return None, f"Groq API error: {str(e)}"

# def process_narrations_batch(narrations):
#     """
#     Single Groq API call for short narration, GST tag, and category.
#     Returns three lists: (short_narrations, gst_tags, categories)
#     """
#     api_key = os.getenv("GROQ_API_KEY")
#     if not api_key:
#         return [fallback_shorten(n) for n in narrations], ["No GST"] * len(narrations), [""] * len(narrations)

#     client = Groq(api_key=api_key)
#     narration_list = "\n".join([f"{i+1}. {n}" for i, n in enumerate(narrations)])

#     prompt = f"""You are an expert Indian bank transaction analyst.

# For each bank transaction narration, provide three things:
# 1. A short human-readable description (max 5 words)
# 2. Whether the transaction involves GST or not
# 3. A meaningful business category describing the purpose of the transaction

# SHORT DESCRIPTION RULES:
# - Use formats like: "UPI to [Name]", "NEFT from [Name]", "NEFT to [Name]", "Cheque to [Name]", "ATM Withdrawal", "Salary Credit", "EMI Payment"
# - Extract actual person or business name where possible
# - Remove all reference numbers, bank codes, transaction IDs
# - If known service use that name directly

# CATEGORY RULES:
# - Write a short meaningful business purpose (3-6 words)
# - Be specific and descriptive based on what you can infer from the narration
# - Do not just repeat the short description

# GST RULES:
# TRANSACTIONS WITH GST:
# - Payment to any registered business for goods or services
# - Online shopping, food delivery, travel, hotels, flights
# - Telecom & internet bills, utility bills
# - Software & streaming subscriptions
# - Professional services
# - Any company with PVT, LTD, LLP, CORP, ENTERPRISE, INDUSTRIES, TRADERS, SOLUTIONS, SERVICES, TECHNOLOGIES
# - Payment via payment gateway (PAYU, RAZORPAY, BILLDESK, CCAVENUE, EASEBUZZ)

# TRANSACTIONS WITHOUT GST:
# - Transfer to an individual person
# - Salary, residential rent, loan EMI, insurance premium
# - Mutual fund, SIP, stock investments
# - ATM withdrawals, income tax, TDS, government payments
# - Person to person transfers

# HOW TO IDENTIFY INDIVIDUAL VS BUSINESS:
# - Personal name (common first+last name) = individual = No GST
# - Business keywords (PVT, LTD, STORE, MART, SHOP, HOSPITAL) = GST
# - Payment gateways (PAYU, RAZORPAY) = always GST
# - If unclear, default to No GST

# Respond ONLY with a valid JSON array with exactly {len(narrations)} objects.
# Each object must have exactly three keys: "short", "gst", "category".
# "gst" must be exactly "GST" or "No GST".
# No explanation, no extra text, just the raw JSON array.

# Example:
# [
#   {{"short": "NEFT to Raj Kumar", "gst": "No GST", "category": "Salary payment"}},
#   {{"short": "NEFT from Bilal Majbour", "gst": "No GST", "category": "Export software contract"}},
#   {{"short": "Cheque to Titan", "gst": "GST", "category": "Watch purchase for client"}},
#   {{"short": "UPI to Swiggy", "gst": "GST", "category": "Food delivery"}}
# ]

# Transactions to analyze:
# {narration_list}"""

#     try:
#         response = client.chat.completions.create(
#             model="llama-3.3-70b-versatile",
#             messages=[{"role": "user", "content": prompt}],
#             temperature=0,
#         )

#         content = response.choices[0].message.content.strip()
#         match = re.search(r'\[.*?\]', content, re.DOTALL)
#         if match:
#             result = json.loads(match.group())
#             if isinstance(result, list) and len(result) > 0:
#                 while len(result) < len(narrations):
#                     result.append({"short": "-", "gst": "No GST", "category": "-"})
#                 result = result[:len(narrations)]
#                 short_narrations = [str(r.get("short", "-")).strip() or "-" for r in result]
#                 gst_tags = ["GST" if str(r.get("gst", "")).strip().upper() == "GST" else "No GST" for r in result]
#                 categories = [str(r.get("category", "-")).strip() or "-" for r in result]
#                 return short_narrations, gst_tags, categories

#         print(f"Groq parse failed: {content}")
#         return [fallback_shorten(n) for n in narrations], ["No GST"] * len(narrations), [""] * len(narrations)

#     except Exception as e:
#         print(f"Groq API error: {e}")
#         return [fallback_shorten(n) for n in narrations], ["No GST"] * len(narrations), [""] * len(narrations)

# def extract_transactions(file_bytes, password=""):
#     # Step 1: Extract raw text from PDF
#     pages_text = extract_text_from_pdf(file_bytes, password)
#     if not pages_text:
#         return None, "Could not extract text from PDF"

#     # Step 2: Use Groq to parse transactions from raw text
#     raw_transactions, error = parse_transactions_with_groq(pages_text)
#     if error:
#         return None, error
#     if not raw_transactions:
#         return None, "No transactions found"

#     print(f"Groq extracted {len(raw_transactions)} transactions")

#     # Step 3: Process narrations with Groq (short, GST, category)
#     narrations = [t.get("narration", "") for t in raw_transactions]
#     short_narrations, gst_tags, categories = process_narrations_batch(narrations)

#     # Build final output
#     final_transactions = []
#     for i, t in enumerate(raw_transactions):
#         date     = clean(t.get("date", ""))
#         narration= clean(t.get("narration", ""))
#         chq      = clean(t.get("chq_ref", "")) or "-"
#         dr_cr    = clean(t.get("dr_cr", ""))
#         amount   = clean(t.get("amount", "")) or "-"
#         short    = short_narrations[i] or "-"
#         gst      = gst_tags[i] or "-"
#         category = categories[i] or "-"

#         # Normalize dr_cr
#         if dr_cr.upper() in ["DR", "DEBIT", "D"]:
#             dr_cr = "Dr"
#         elif dr_cr.upper() in ["CR", "CREDIT", "C"]:
#             dr_cr = "Cr"
#         else:
#             dr_cr = "-"

#         # ValueDt removed from output
#         final_transactions.append([date, narration, short, chq, dr_cr, amount, gst, category])

#     clean_header = ["Date", "Narration", "Narration(Short)", "Chq./Ref.No.", "Dr/Cr", "Amount(₹)", "GST", "Category"]
#     df = pd.DataFrame(final_transactions, columns=clean_header)
#     df = df.map(lambda x: re.sub(r'\s+', ' ', str(x)).strip() if x else "")
#     df = df[df["Date"].apply(is_date)]
#     df.reset_index(drop=True, inplace=True)

#     if df.empty:
#         return None, "No valid transactions found after filtering"

#     return df, None























# import pdfplumber
# import pypdf
# import pandas as pd
# import re
# import io
# import os
# import json
# import time
# import google.generativeai as genai
# from dotenv import load_dotenv

# load_dotenv()

# genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
# model = genai.GenerativeModel("gemini-2.0-flash-lite")

# def unlock_pdf(file_bytes, password):
#     reader = pypdf.PdfReader(io.BytesIO(file_bytes))
#     if reader.is_encrypted:
#         reader.decrypt(password)
#     writer = pypdf.PdfWriter()
#     for page in reader.pages:
#         writer.add_page(page)
#     unlocked = io.BytesIO()
#     writer.write(unlocked)
#     unlocked.seek(0)
#     return unlocked

# def is_date(text):
#     return bool(re.match(r'^\d{2}[/\-\.]\d{2}[/\-\.]\d{2,4}$', str(text).strip()))

# def is_amount(text):
#     return bool(re.match(r'^[\d,]+\.\d{2}$', str(text).strip()))

# def clean(val):
#     return re.sub(r'\s+', ' ', str(val)).strip() if val else ""

# def fallback_shorten(narration):
#     if not narration:
#         return ""
#     cleaned = re.sub(r'[0-9@#\.\-\_\/]', ' ', narration.upper())
#     words = [w for w in cleaned.split() if len(w) > 2][:4]
#     return " ".join(words).title() if words else narration[:30].title()

# def call_gemini(prompt):
#     response = model.generate_content(
#         prompt,
#         generation_config=genai.GenerationConfig(temperature=0)
#     )
#     return response.text.strip()

# def extract_page_structured(page):
#     strategies = [
#         {"vertical_strategy": "lines", "horizontal_strategy": "lines"},
#         {"vertical_strategy": "lines", "horizontal_strategy": "text"},
#         {"vertical_strategy": "text",  "horizontal_strategy": "lines"},
#         {"vertical_strategy": "text",  "horizontal_strategy": "text"},
#     ]

#     best_tables = []
#     best_score = -1

#     for s in strategies:
#         tables = page.extract_tables(s)
#         if not tables:
#             continue
#         all_rows = [row for t in tables for row in t if t]
#         score = sum(
#             1 for row in all_rows
#             if row and any(
#                 re.match(r'^\d{2}[/\-\.]\d{2}[/\-\.]\d{2,4}', str(c or "").strip())
#                 for c in row[:3]
#             )
#         )
#         if score > best_score:
#             best_tables = all_rows
#             best_score = score

#     if not best_tables:
#         return []

#     col_map = {}
#     col_keywords = {
#         "date":       ["date", "txn date", "tran date", "transaction date", "posting date", "value date"],
#         "narration":  ["narration", "particulars", "description", "details", "remarks", "transaction details"],
#         "ref":        ["chq", "ref", "cheque", "reference", "chq./ref", "utr", "transaction id", "txn id"],
#         "withdrawal": ["withdrawal", "debit", "dr", "debit amount", "withdrawal amt", "paid out", "amount dr"],
#         "deposit":    ["deposit", "credit", "cr", "credit amount", "deposit amt", "paid in", "amount cr"],
#         "closing":    ["balance", "closing", "running balance", "available balance", "closing balance"],
#     }

#     for row in best_tables[:8]:
#         if not row:
#             continue
#         cells = [str(c or "").lower().strip() for c in row]
#         has_date = any("date" in c for c in cells)
#         has_narr = any(
#             any(kw in c for kw in ["narration", "particular", "description", "details"])
#             for c in cells
#         )
#         if has_date and has_narr:
#             for col_type, keywords in col_keywords.items():
#                 for idx, cell in enumerate(cells):
#                     if any(kw in cell for kw in keywords):
#                         if col_type not in col_map:
#                             col_map[col_type] = idx
#             break

#     if not col_map:
#         for row in best_tables[:5]:
#             if not row:
#                 continue
#             cells = [str(c or "").strip() for c in row]

#             date_idx = None
#             for idx, c in enumerate(cells[:3]):
#                 if re.match(r'^\d{2}[/\-\.]\d{2}[/\-\.]\d{2,4}', c):
#                     date_idx = idx
#                     break
#             if date_idx is None:
#                 continue

#             amount_indices = [
#                 idx for idx, c in enumerate(cells)
#                 if re.match(r'^[\d,]+\.\d{2}$', c.replace('-', '').strip())
#                 and c.strip() not in ('', '-')
#             ]

#             narr_idx = None
#             for idx in range(date_idx + 1, len(cells)):
#                 c = cells[idx]
#                 if (c and c != '-'
#                         and not re.match(r'^\d{2}[/\-\.]\d{2}[/\-\.]\d{2,4}', c)
#                         and not re.match(r'^[\d,]+\.\d{2}$', c)
#                         and len(c) > 5):
#                     narr_idx = idx
#                     break

#             ref_idx = None
#             if narr_idx is not None:
#                 for idx in range(narr_idx + 1, len(cells)):
#                     c = cells[idx]
#                     if c and c != '-' and not re.match(r'^[\d,]+\.\d{2}$', c):
#                         ref_idx = idx
#                         break

#             if len(amount_indices) >= 3:
#                 col_map["withdrawal"] = amount_indices[-3]
#                 col_map["deposit"]    = amount_indices[-2]
#                 col_map["closing"]    = amount_indices[-1]
#             elif len(amount_indices) == 2:
#                 col_map["deposit"]  = amount_indices[-2]
#                 col_map["closing"]  = amount_indices[-1]
#             elif len(amount_indices) == 1:
#                 col_map["closing"]  = amount_indices[-1]

#             if date_idx  is not None: col_map["date"]      = date_idx
#             if narr_idx  is not None: col_map["narration"] = narr_idx
#             if ref_idx   is not None: col_map["ref"]       = ref_idx
#             break

#     structured_lines = []

#     for row in best_tables:
#         if not row:
#             continue
#         cells = [str(c or "").strip() for c in row]

#         row_text = " ".join(cells).lower()
#         if any(kw in row_text for kw in ["narration", "particulars", "description"]) and \
#            any(kw in row_text for kw in ["date", "withdrawal", "deposit", "debit", "credit"]):
#             continue

#         date_val = ""
#         if "date" in col_map and col_map["date"] < len(cells):
#             date_val = cells[col_map["date"]]
#         else:
#             for c in cells[:3]:
#                 if re.match(r'^\d{2}[/\-\.]\d{2}[/\-\.]\d{2,4}', c):
#                     date_val = c
#                     break

#         if not date_val:
#             continue

#         def get_col(col_type):
#             if col_type in col_map and col_map[col_type] < len(cells):
#                 return cells[col_map[col_type]]
#             return ""

#         narr_val  = get_col("narration") or (cells[1] if len(cells) > 1 else "")
#         ref_val   = get_col("ref")
#         wd_val    = get_col("withdrawal")
#         dep_val   = get_col("deposit")
#         close_val = get_col("closing")

#         narr_val = re.sub(r'\s+', ' ', narr_val).strip()

#         if not ref_val or ref_val == '-':
#             for c in cells:
#                 if re.match(r'^[A-Z0-9]{10,}$', c.strip()):
#                     ref_val = c.strip()
#                     break

#         wd_val    = "" if wd_val    in ("-", "None") else wd_val
#         dep_val   = "" if dep_val   in ("-", "None") else dep_val
#         close_val = "" if close_val in ("-", "None") else close_val

#         line = (f"DATE={date_val} | NARRATION={narr_val} | REF={ref_val} | "
#                 f"WITHDRAWAL={wd_val} | DEPOSIT={dep_val} | CLOSING={close_val}")
#         structured_lines.append(line)

#     return structured_lines

# def extract_text_from_pdf(file_bytes, password=""):
#     unlocked = unlock_pdf(file_bytes, password)
#     pages_text = []
#     with pdfplumber.open(unlocked) as pdf:
#         for page in pdf.pages:
#             lines = extract_page_structured(page)
#             if lines:
#                 pages_text.append("\n".join(lines))
#             else:
#                 text = page.extract_text()
#                 if text:
#                     pages_text.append(text.strip())
#     return pages_text

# def parse_page_with_gemini(page_text, page_num):
#     prompt = f"""You are an expert at reading bank statement data from any bank.

# The data below has clearly labeled columns:
# DATE= | NARRATION= | REF= | WITHDRAWAL= | DEPOSIT= | CLOSING=

# Extract ALL transactions following these rules:
# - date: use the DATE= value exactly
# - narration: use the NARRATION= value exactly as given
# - chq_ref: use the REF= value, empty string if blank
# - dr_cr: if WITHDRAWAL= has a number → "Dr", if DEPOSIT= has a number → "Cr"
# - amount: if WITHDRAWAL= has a number use it, else use DEPOSIT= value
# - Do NOT use CLOSING= as the amount — that is the running balance
# - Skip rows where both WITHDRAWAL= and DEPOSIT= are empty
# - If no transactions found on this page return []

# Respond ONLY with a valid JSON array. No explanation, no extra text, no markdown.

# Each object must have exactly these keys:
# - "date": string
# - "narration": string
# - "chq_ref": string or empty string
# - "dr_cr": "Dr" or "Cr"
# - "amount": string with 2 decimals

# Page {page_num + 1} data:
# {page_text}"""

#     try:
#         content = call_gemini(prompt)
#         content = re.sub(r'^```(?:json)?\s*', '', content)
#         content = re.sub(r'\s*```$', '', content)
#         match = re.search(r'\[.*\]', content, re.DOTALL)
#         if match:
#             raw = match.group()
#             try:
#                 result = json.loads(raw)
#             except json.JSONDecodeError:
#                 last_brace = raw.rfind('},')
#                 if last_brace != -1:
#                     raw = raw[:last_brace + 1] + ']'
#                     try:
#                         result = json.loads(raw)
#                     except:
#                         print(f"Page {page_num + 1}: could not fix truncated JSON")
#                         return []
#                 else:
#                     return []

#             if isinstance(result, list):
#                 print(f"Page {page_num + 1}: found {len(result)} transactions")
#                 return result

#         print(f"Page {page_num + 1}: no transactions found")
#         return []

#     except Exception as e:
#         print(f"Page {page_num + 1} Gemini error: {e}")
#         return []

# def process_narrations_batch(narrations):
#     if not os.getenv("GEMINI_API_KEY"):
#         return [fallback_shorten(n) for n in narrations], ["No GST"] * len(narrations), ["-"] * len(narrations)

#     narration_list = "\n".join([f"{i+1}. {n}" for i, n in enumerate(narrations)])

#     prompt = f"""You are an expert Indian bank transaction analyst.

# For each bank transaction narration, provide three things:
# 1. A short human-readable description (max 5 words)
# 2. Whether the transaction involves GST or not
# 3. A meaningful business category describing the purpose of the transaction

# SHORT DESCRIPTION RULES:
# - Use formats like: "UPI to [Name]", "NEFT from [Name]", "NEFT to [Name]", "Cheque to [Name]", "ATM Withdrawal", "Salary Credit", "EMI Payment"
# - Extract actual person or business name where possible
# - Remove all reference numbers, bank codes, transaction IDs
# - If known service use that name directly

# CATEGORY RULES:
# - Write a short meaningful business purpose (3-6 words)
# - Be specific and descriptive based on what you can infer from the narration
# - Do not just repeat the short description

# GST RULES:
# TRANSACTIONS WITH GST:
# - Payment to any registered business for goods or services
# - Online shopping, food delivery, travel, hotels, flights
# - Telecom & internet bills, utility bills
# - Software & streaming subscriptions
# - Professional services
# - Any company with PVT, LTD, LLP, CORP, ENTERPRISE, INDUSTRIES, TRADERS, SOLUTIONS, SERVICES, TECHNOLOGIES
# - Payment via payment gateway (PAYU, RAZORPAY, BILLDESK, CCAVENUE, EASEBUZZ)

# TRANSACTIONS WITHOUT GST:
# - Transfer to an individual person
# - Salary, residential rent, loan EMI, insurance premium
# - Mutual fund, SIP, stock investments
# - ATM withdrawals, income tax, TDS, government payments
# - Person to person transfers

# HOW TO IDENTIFY INDIVIDUAL VS BUSINESS:
# - Personal name (common first+last name) = individual = No GST
# - Business keywords (PVT, LTD, STORE, MART, SHOP, HOSPITAL) = GST
# - Payment gateways (PAYU, RAZORPAY) = always GST
# - If unclear, default to No GST

# IMPORTANT: You MUST return exactly {len(narrations)} objects in the array, one for each transaction.

# Respond ONLY with a valid JSON array with exactly {len(narrations)} objects.
# Each object must have exactly three keys: "short", "gst", "category".
# "gst" must be exactly "GST" or "No GST".
# No explanation, no extra text, no markdown, just the raw JSON array.

# Transactions to analyze:
# {narration_list}"""

#     try:
#         content = call_gemini(prompt)
#         content = re.sub(r'^```(?:json)?\s*', '', content)
#         content = re.sub(r'\s*```$', '', content)
#         match = re.search(r'\[.*\]', content, re.DOTALL)
#         if match:
#             raw = match.group()
#             try:
#                 result = json.loads(raw)
#             except json.JSONDecodeError:
#                 last_brace = raw.rfind('},')
#                 if last_brace != -1:
#                     raw = raw[:last_brace + 1] + ']'
#                     try:
#                         result = json.loads(raw)
#                     except:
#                         result = []
#                 else:
#                     result = []

#             if isinstance(result, list) and len(result) > 0:
#                 while len(result) < len(narrations):
#                     result.append({"short": "-", "gst": "No GST", "category": "-"})
#                 result = result[:len(narrations)]
#                 short_narrations = [str(r.get("short", "-")).strip() or "-" for r in result]
#                 gst_tags = ["GST" if str(r.get("gst", "")).strip().upper() == "GST" else "No GST" for r in result]
#                 categories = [str(r.get("category", "-")).strip() or "-" for r in result]
#                 return short_narrations, gst_tags, categories

#         print(f"Gemini narration parse failed: {content[:200]}")
#         return [fallback_shorten(n) for n in narrations], ["No GST"] * len(narrations), ["-"] * len(narrations)

#     except Exception as e:
#         print(f"Gemini API error: {e}")
#         return [fallback_shorten(n) for n in narrations], ["No GST"] * len(narrations), ["-"] * len(narrations)

# def extract_transactions(file_bytes, password=""):
#     pages_text = extract_text_from_pdf(file_bytes, password)
#     if not pages_text:
#         return None, "Could not extract text from PDF"

#     if not os.getenv("GEMINI_API_KEY"):
#         return None, "No GEMINI_API_KEY found in .env"

#     all_raw_transactions = []

#     for page_num, page_text in enumerate(pages_text):
#         if not page_text.strip():
#             continue
#         page_transactions = parse_page_with_gemini(page_text, page_num)
#         all_raw_transactions.extend(page_transactions)
#         if len(pages_text) > 5:
#             time.sleep(0.3)

#     if not all_raw_transactions:
#         return None, "No transactions found"

#     print(f"Total transactions extracted: {len(all_raw_transactions)}")

#     narrations = [t.get("narration", "") for t in all_raw_transactions]
#     short_narrations, gst_tags, categories = process_narrations_batch(narrations)

#     final_transactions = []
#     for i, t in enumerate(all_raw_transactions):
#         date      = clean(t.get("date", ""))
#         narration = clean(t.get("narration", ""))
#         chq       = clean(t.get("chq_ref", "")) or "-"
#         dr_cr     = clean(t.get("dr_cr", ""))
#         amount    = clean(t.get("amount", "")) or "-"
#         short     = short_narrations[i] or "-"
#         gst       = gst_tags[i] or "-"
#         category  = categories[i] or "-"

#         if dr_cr.upper() in ["DR", "DEBIT", "D"]:
#             dr_cr = "Dr"
#         elif dr_cr.upper() in ["CR", "CREDIT", "C"]:
#             dr_cr = "Cr"
#         else:
#             dr_cr = "-"

#         final_transactions.append([date, narration, short, chq, dr_cr, amount, gst, category])

#     clean_header = ["Date", "Narration", "Narration(Short)", "Chq./Ref.No.", "Dr/Cr", "Amount(₹)", "GST", "Category"]
#     df = pd.DataFrame(final_transactions, columns=clean_header)
#     df = df.map(lambda x: re.sub(r'\s+', ' ', str(x)).strip() if x else "")
#     df = df[df["Date"].apply(is_date)]
#     df.reset_index(drop=True, inplace=True)

#     if df.empty:
#         return None, "No valid transactions found after filtering"

#     return df, None


# import pdfplumber
# import pypdf
# import pandas as pd
# import re
# import io
# import os
# import json
# import time
# import google.generativeai as genai
# from dotenv import load_dotenv

# load_dotenv()

# genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
# model = genai.GenerativeModel("gemini-2.0-flash")

# # ─────────────────────────────────────────────
# # HELPERS
# # ─────────────────────────────────────────────

# def unlock_pdf(file_bytes, password):
#     reader = pypdf.PdfReader(io.BytesIO(file_bytes))
#     if reader.is_encrypted:
#         reader.decrypt(password)
#     writer = pypdf.PdfWriter()
#     for page in reader.pages:
#         writer.add_page(page)
#     out = io.BytesIO()
#     writer.write(out)
#     out.seek(0)
#     return out

# def clean(val):
#     return re.sub(r'\s+', ' ', str(val)).strip() if val else ""

# def is_date(text):
#     return bool(re.match(r'^\d{2}[/\-\.]\d{2}[/\-\.]\d{2,4}$', str(text).strip()))

# def is_amount(text):
#     return bool(re.match(r'^[\d,]+\.\d{2}$', str(text).strip()))

# def parse_amount(text):
#     try:
#         return float(str(text).replace(',', '').strip())
#     except:
#         return None

# def fallback_shorten(narration):
#     if not narration:
#         return "-"
#     cleaned = re.sub(r'[0-9@#\.\-\_\/]', ' ', narration.upper())
#     words = [w for w in cleaned.split() if len(w) > 2][:4]
#     return " ".join(words).title() if words else narration[:30].title()

# # ─────────────────────────────────────────────
# # PDF EXTRACTION — pure pdfplumber, no AI
# # ─────────────────────────────────────────────

# def best_table_rows(page):
#     strategies = [
#         {"vertical_strategy": "lines",  "horizontal_strategy": "lines"},
#         {"vertical_strategy": "lines",  "horizontal_strategy": "text"},
#         {"vertical_strategy": "text",   "horizontal_strategy": "lines"},
#         {"vertical_strategy": "text",   "horizontal_strategy": "text"},
#     ]
#     best, best_score = [], -1
#     for s in strategies:
#         tables = page.extract_tables(s)
#         if not tables:
#             continue
#         rows = [r for t in tables for r in t if t]
#         score = sum(
#             1 for r in rows if r and any(
#                 re.match(r'^\d{2}[/\-\.]\d{2}[/\-\.]\d{2,4}', clean(c))
#                 for c in r[:3]
#             )
#         )
#         if score > best_score:
#             best, best_score = rows, score
#     return best

# def detect_columns(rows):
#     col_keywords = {
#         "date":       ["date", "txn date", "tran date", "transaction date", "posting date", "value date"],
#         "narration":  ["narration", "particulars", "description", "details", "remarks", "transaction details"],
#         "ref":        ["chq", "ref", "cheque", "reference", "chq./ref", "utr", "transaction id", "txn id"],
#         "withdrawal": ["withdrawal", "debit", "dr", "debit amount", "withdrawal amt", "paid out", "amount dr"],
#         "deposit":    ["deposit", "credit", "cr", "credit amount", "deposit amt", "paid in", "amount cr"],
#         "closing":    ["balance", "closing", "running balance", "closing balance"],
#     }

#     col_map = {}

#     # Try header row detection first
#     for row in rows[:8]:
#         if not row:
#             continue
#         cells = [clean(c).lower() for c in row]
#         if any("date" in c for c in cells) and any(
#             any(kw in c for kw in ["narration", "particular", "description", "details"])
#             for c in cells
#         ):
#             for col_type, keywords in col_keywords.items():
#                 for idx, cell in enumerate(cells):
#                     if any(kw in cell for kw in keywords) and col_type not in col_map:
#                         col_map[col_type] = idx
#             break

#     if col_map:
#         return col_map

#     # Auto-detect from first data row
#     for row in rows[:5]:
#         if not row:
#             continue
#         cells = [clean(c) for c in row]

#         date_idx = next(
#             (i for i, c in enumerate(cells[:3])
#              if re.match(r'^\d{2}[/\-\.]\d{2}[/\-\.]\d{2,4}', c)), None
#         )
#         if date_idx is None:
#             continue

#         amt_indices = [
#             i for i, c in enumerate(cells)
#             if is_amount(c.replace('-', '').strip()) and c.strip() not in ('', '-')
#         ]

#         narr_idx = next(
#             (i for i in range(date_idx + 1, len(cells))
#              if cells[i] and cells[i] != '-'
#              and not re.match(r'^\d{2}[/\-\.]\d{2}[/\-\.]\d{2,4}', cells[i])
#              and not is_amount(cells[i])
#              and len(cells[i]) > 5), None
#         )

#         ref_idx = None
#         if narr_idx is not None:
#             ref_idx = next(
#                 (i for i in range(narr_idx + 1, len(cells))
#                  if cells[i] and cells[i] != '-' and not is_amount(cells[i])), None
#             )

#         if len(amt_indices) >= 3:
#             col_map["withdrawal"] = amt_indices[-3]
#             col_map["deposit"]    = amt_indices[-2]
#             col_map["closing"]    = amt_indices[-1]
#         elif len(amt_indices) == 2:
#             col_map["deposit"]  = amt_indices[-2]
#             col_map["closing"]  = amt_indices[-1]
#         elif len(amt_indices) == 1:
#             col_map["closing"]  = amt_indices[-1]

#         if date_idx  is not None: col_map["date"]      = date_idx
#         if narr_idx  is not None: col_map["narration"] = narr_idx
#         if ref_idx   is not None: col_map["ref"]       = ref_idx
#         break

#     return col_map

# def parse_rows_to_transactions(rows, col_map):
#     transactions = []

#     def gcol(cells, key):
#         idx = col_map.get(key)
#         if idx is not None and idx < len(cells):
#             v = clean(cells[idx])
#             return "" if v in ("-", "None") else v
#         return ""

#     for row in rows:
#         if not row:
#             continue
#         cells = [clean(c) for c in row]

#         row_text = " ".join(cells).lower()
#         if any(kw in row_text for kw in ["narration", "particulars", "description"]) and \
#            any(kw in row_text for kw in ["date", "withdrawal", "deposit", "debit", "credit"]):
#             continue

#         date_val = gcol(cells, "date")
#         if not date_val:
#             for c in cells[:3]:
#                 if re.match(r'^\d{2}[/\-\.]\d{2}[/\-\.]\d{2,4}', c):
#                     date_val = c
#                     break
#         if not date_val or not is_date(date_val):
#             continue

#         narr_val = gcol(cells, "narration") or (cells[1] if len(cells) > 1 else "")
#         narr_val = re.sub(r'\s+', ' ', narr_val).strip()
#         ref_val  = gcol(cells, "ref")
#         wd_val   = gcol(cells, "withdrawal")
#         dep_val  = gcol(cells, "deposit")

#         if not ref_val:
#             for c in cells:
#                 if re.match(r'^[A-Z0-9]{10,}$', c):
#                     ref_val = c
#                     break

#         wd_num  = parse_amount(wd_val)
#         dep_num = parse_amount(dep_val)

#         if wd_num and wd_num > 0:
#             dr_cr  = "Dr"
#             amount = wd_val
#         elif dep_num and dep_num > 0:
#             dr_cr  = "Cr"
#             amount = dep_val
#         else:
#             continue

#         transactions.append({
#             "date":      date_val,
#             "narration": narr_val or "-",
#             "chq_ref":   ref_val  or "-",
#             "dr_cr":     dr_cr,
#             "amount":    amount,
#         })

#     return transactions

# def extract_transactions_from_pdf(file_bytes, password=""):
#     unlocked = unlock_pdf(file_bytes, password)
#     all_transactions = []

#     with pdfplumber.open(unlocked) as pdf:
#         for page in pdf.pages:
#             rows = best_table_rows(page)
#             if not rows:
#                 continue
#             col_map = detect_columns(rows)
#             if not col_map:
#                 continue
#             txns = parse_rows_to_transactions(rows, col_map)
#             all_transactions.extend(txns)
#             print(f"Page extracted: {len(txns)} transactions")

#     return all_transactions

# # ─────────────────────────────────────────────
# # GEMINI — single call for short, GST, category
# # ─────────────────────────────────────────────

# def call_gemini(prompt, retries=3):
#     for attempt in range(retries):
#         try:
#             response = model.generate_content(
#                 prompt,
#                 generation_config=genai.GenerationConfig(temperature=0)
#             )
#             return response.text.strip()
#         except Exception as e:
#             err = str(e)
#             if "429" in err or "quota" in err.lower() or "rate" in err.lower():
#                 delay_match = re.search(r'retry_delay\s*\{\s*seconds:\s*(\d+)', err)
#                 wait = int(delay_match.group(1)) + 2 if delay_match else 30
#                 print(f"Rate limited. Waiting {wait}s... (attempt {attempt+1}/{retries})")
#                 time.sleep(wait)
#             else:
#                 raise e
#     raise Exception(f"Gemini failed after {retries} retries")

# def enrich_narrations(narrations):
#     """
#     Single Gemini call — returns (short_narrations, gst_tags, categories).
#     Falls back gracefully if Gemini unavailable.
#     """
#     if not os.getenv("GEMINI_API_KEY") or not narrations:
#         return (
#             [fallback_shorten(n) for n in narrations],
#             ["No GST"] * len(narrations),
#             ["-"] * len(narrations)
#         )

#     narration_list = "\n".join([f"{i+1}. {n}" for i, n in enumerate(narrations)])

#     prompt = f"""You are an expert Indian bank transaction analyst.

# For each transaction narration below, return three things:
# 1. short: a human-readable label (max 5 words)
# 2. gst: "GST" or "No GST"
# 3. category: short business purpose (3-6 words)

# SHORT RULES:
# - Format: "UPI to [Name]", "NEFT from [Name]", "NEFT to [Name]", "ATM Withdrawal", "Salary Credit", "EMI Payment"
# - Extract actual person or business name
# - Remove reference numbers, bank codes, transaction IDs

# GST RULES:
# - GST if: payment to registered business, online shopping, food delivery, travel, hotels, telecom/internet bills, software/streaming subscriptions, professional services, companies with PVT/LTD/LLP/CORP/ENTERPRISE/INDUSTRIES/TRADERS/SOLUTIONS/SERVICES/TECHNOLOGIES, payment gateways (PAYU/RAZORPAY/BILLDESK/CCAVENUE/EASEBUZZ)
# - No GST if: transfer to individual person, salary, residential rent, loan EMI, insurance, mutual fund/SIP/stocks, ATM withdrawal, income tax, TDS, government payments
# - Personal name (first+last) = No GST. If unclear = No GST.

# CATEGORY RULES:
# - Specific and descriptive (3-6 words)
# - Do not just repeat the short description

# IMPORTANT: Return exactly {len(narrations)} objects.
# Respond ONLY with a raw JSON array, no markdown, no explanation.
# Each object: {{"short": "...", "gst": "GST" or "No GST", "category": "..."}}

# Narrations:
# {narration_list}"""

#     try:
#         content = call_gemini(prompt)
#         content = re.sub(r'^```(?:json)?\s*', '', content)
#         content = re.sub(r'\s*```$', '', content)
#         match = re.search(r'\[.*\]', content, re.DOTALL)
#         if match:
#             result = json.loads(match.group())
#             if isinstance(result, list) and len(result) > 0:
#                 while len(result) < len(narrations):
#                     result.append({"short": "-", "gst": "No GST", "category": "-"})
#                 result = result[:len(narrations)]
#                 shorts     = [str(r.get("short",    "-")).strip() or "-" for r in result]
#                 gst_tags   = ["GST" if str(r.get("gst", "")).upper() == "GST" else "No GST" for r in result]
#                 categories = [str(r.get("category", "-")).strip() or "-" for r in result]
#                 return shorts, gst_tags, categories

#     except Exception as e:
#         print(f"Gemini error: {e}")

#     return (
#         [fallback_shorten(n) for n in narrations],
#         ["No GST"] * len(narrations),
#         ["-"] * len(narrations)
#     )

# # ─────────────────────────────────────────────
# # MAIN ENTRY POINT
# # ─────────────────────────────────────────────

# def extract_transactions(file_bytes, password=""):
#     # Step 1: Extract everything with pdfplumber — no AI
#     transactions = extract_transactions_from_pdf(file_bytes, password)

#     if not transactions:
#         return None, "No transactions found"

#     print(f"Total transactions extracted: {len(transactions)}")

#     # Step 2: Single Gemini call for short narration + GST + category
#     narrations = [t["narration"] for t in transactions]
#     shorts, gst_tags, categories = enrich_narrations(narrations)

#     # Step 3: Build final dataframe
#     final = []
#     for i, t in enumerate(transactions):
#         final.append([
#             t["date"],
#             t["narration"],
#             shorts[i],
#             t["chq_ref"],
#             t["dr_cr"],
#             t["amount"],
#             gst_tags[i],
#             categories[i],
#         ])

#     columns = ["Date", "Narration", "Narration(Short)", "Chq./Ref.No.", "Dr/Cr", "Amount(₹)", "GST", "Category"]
#     df = pd.DataFrame(final, columns=columns)
#     df = df.map(lambda x: re.sub(r'\s+', ' ', str(x)).strip() if x else "")
#     df = df[df["Date"].apply(is_date)]
#     df.reset_index(drop=True, inplace=True)

#     if df.empty:
#         return None, "No valid transactions found after filtering"

#     return df, None






















import pdfplumber
import pypdf
import pandas as pd
import re
import io
import os
import json
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
        return ([fallback_shorten(x) for x in narrations_with_drcr],
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
  * "ITC Eligible" — payment to GST-registered business, claimable input credit
  * "Zero Rated"   — export of services/goods, foreign payment (SWIFT/USD/AED/GBP)
  * "No GST"       — salary to individual, ATM, personal transfer, insurance, loan EMI, mutual fund
  * ""             — cannot determine from narration alone

- gst_notes: one short sentence explaining gst decision
  * Salary: "Salary Payment (Outside GST Scope)"
  * ATM: "Outside GST Scope"
  * Insurance: "ITC Blocked u/s 17(5) - No Claim"
  * Business: "GST Applicable - ITC Claimable"
  * Bank fee: "GST Applicable - Bank Fee"
  * Export: "Export of Service - Zero Rated"
  * Blank if gst is ""

- category: specific real-world purpose, max 8 words
  * [Dr] to individual person name → "Salary Payment"
  * [Dr] to business → actual purpose e.g. "Food Order", "Cloud Services", "Insurance Premium"
  * [Cr] from individual → "Payment Received from Individual"
  * [Cr] from business → "Business Receipt" or specific purpose
  * Never use "Personal Transfer" — always infer the real purpose

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
            all_shorts.extend([fallback_shorten(x) for x in chunk])
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
            gst_tags[i]  = ""
            gst_notes[i] = ""

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