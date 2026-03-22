import xml.etree.ElementTree as ET
import io
import json
import base64
import hashlib
import re
import difflib
from flask import Blueprint, request, jsonify, current_app
from app.core.jwt_utils import require_role, get_current_user
from app.core.database import query_db, execute_db, row_to_dict, rows_to_dicts
import uuid
from datetime import datetime

invoices_bp = Blueprint("invoices", __name__)
NFE_NS = "http://www.portalfiscal.inf.br/nfe"

# Minimum fuzzy similarity ratio to accept a product match (0.0-1.0)
FUZZY_THRESHOLD = 0.6


# ─────────────────────────────────────────────
# OCR Cache helpers
# ─────────────────────────────────────────────

def _get_ocr_cache(pdf_hash):
    """Returns cached OCR result dict if found, else None."""
    row = query_db(
        "SELECT result_json FROM ocr_cache WHERE pdf_hash=?",
        [pdf_hash], one=True
    )
    if row:
        return json.loads(row["result_json"])
    return None


def _set_ocr_cache(pdf_hash, result_dict, source="openai"):
    """Stores OCR result in cache using upsert."""
    execute_db(
        """INSERT INTO ocr_cache (pdf_hash, result_json, source, created_at)
           VALUES (?, ?, ?, datetime('now'))
           ON CONFLICT(pdf_hash) DO UPDATE SET
               result_json=excluded.result_json,
               source=excluded.source,
               created_at=excluded.created_at""",
        [pdf_hash, json.dumps(result_dict), source]
    )


# ─────────────────────────────────────────────
# Validation helpers
# ─────────────────────────────────────────────

def _validate_cnpj(cnpj: str) -> bool:
    """
    Validates a Brazilian CNPJ using the official two-check-digit algorithm.
    Accepts formatted (XX.XXX.XXX/XXXX-XX) or raw (14 digits) strings.
    """
    cnpj = re.sub(r'\D', '', cnpj)
    if len(cnpj) != 14:
        return False
    if len(set(cnpj)) == 1:  # all same digit (e.g. 00000000000000) is invalid
        return False

    def _calc_digit(digits, weights):
        s = sum(int(d) * w for d, w in zip(digits, weights))
        remainder = s % 11
        return 0 if remainder < 2 else 11 - remainder

    w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    if _calc_digit(cnpj[:12], w1) != int(cnpj[12]):
        return False

    w2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    return _calc_digit(cnpj[:13], w2) == int(cnpj[13])


def _validate_ncm(ncm: str) -> bool:
    """Validates Brazilian NCM code: must be exactly 8 digits."""
    return len(re.sub(r'\D', '', ncm)) == 8


# ─────────────────────────────────────────────
# XML parser (NF-e SEFAZ)
# ─────────────────────────────────────────────

def parse_nfe_xml(xml_content):
    root = ET.fromstring(xml_content)
    ns = NFE_NS
    def find(el, tag):
        r = el.find(f"{{{ns}}}{tag}")
        return r.text if r is not None else None

    nfe = root.find(f".//{{{ns}}}infNFe")
    if nfe is None:
        raise ValueError("Estrutura XML NF-e inválida")

    ide = nfe.find(f"{{{ns}}}ide")
    emit = nfe.find(f"{{{ns}}}emit")

    invoice_number = find(ide, "nNF") or ""
    issue_date_raw = find(ide, "dEmi") or ""
    issue_date = issue_date_raw[:10] if issue_date_raw else None
    supplier_cnpj = find(emit, "CNPJ") or ""
    supplier_name = find(emit, "xNome") or ""

    items = []
    total_value = 0.0
    for det in nfe.findall(f"{{{ns}}}det"):
        prod = det.find(f"{{{ns}}}prod")
        if prod is not None:
            def fp(t): return find(prod, t)
            qty = float(fp("qCom") or 0)
            unit_price = float(fp("vUnCom") or 0)
            total_price = float(fp("vProd") or qty * unit_price)
            total_value += total_price
            items.append({
                "description": fp("xProd") or "",
                "ncm": fp("NCM") or "",
                "quantity": qty,
                "unit": fp("uCom") or "un",
                "unit_price": unit_price,
                "total_price": total_price,
            })

    return {"invoice_number": invoice_number, "supplier_cnpj": supplier_cnpj,
            "supplier_name": supplier_name, "issue_date": issue_date,
            "total_value": total_value, "items": items}


# ─────────────────────────────────────────────
# Fuzzy product matching
# ─────────────────────────────────────────────

def _auto_match(description):
    """
    Finds best-matching product using:
    1. Barcode/SKU exact match for numeric descriptions
    2. LIKE search to build candidate pool
    3. difflib.SequenceMatcher to rank candidates

    Returns (product_id, confidence) tuple.
    confidence is 0.0-1.0.
    """
    if not description:
        return None, 0.0

    desc_lower = description.lower()

    # Try barcode/SKU exact match if description looks like a code
    numeric_desc = re.sub(r'\D', '', description)
    if len(numeric_desc) >= 8:
        row = query_db(
            "SELECT id FROM products WHERE (barcode=? OR sku=?) AND active=1 LIMIT 1",
            [numeric_desc, numeric_desc], one=True
        )
        if row:
            return row["id"], 1.0

    # Build candidate pool via LIKE on significant words
    words = [w for w in desc_lower.split() if len(w) > 3]
    if not words:
        return None, 0.0

    candidate_ids = set()
    for w in words[:5]:
        rows = query_db(
            "SELECT id FROM products WHERE name LIKE ? AND active=1 LIMIT 20",
            [f"%{w}%"]
        )
        for r in rows:
            candidate_ids.add(r["id"])

    if not candidate_ids:
        return None, 0.0

    # Fetch names for all candidates
    placeholders = ",".join("?" * len(candidate_ids))
    candidates = query_db(
        f"SELECT id, name FROM products WHERE id IN ({placeholders})",
        list(candidate_ids)
    )

    # Score each candidate with SequenceMatcher
    best_id = None
    best_ratio = 0.0
    for c in candidates:
        ratio = difflib.SequenceMatcher(
            None, desc_lower, c["name"].lower()
        ).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_id = c["id"]

    if best_ratio >= FUZZY_THRESHOLD:
        return best_id, round(best_ratio, 4)
    return None, 0.0


def _insert_invoice_items(inv_id, items):
    """Inserts invoice items with fuzzy auto-match and confidence score."""
    for item in items:
        matched_id, confidence = _auto_match(item.get("description", ""))
        execute_db(
            """INSERT INTO invoice_items
                   (id, invoice_id, product_id, description, ncm,
                    quantity, unit, unit_price, total_price, matched, match_confidence)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            [str(uuid.uuid4()), inv_id, matched_id,
             item.get("description", ""), item.get("ncm", ""),
             float(item.get("quantity", 0)), item.get("unit", "un"),
             float(item.get("unit_price", 0)), float(item.get("total_price", 0)),
             1 if matched_id else 0,
             confidence]
        )


# ─────────────────────────────────────────────
# PDF OCR — OpenAI GPT-4o
# ─────────────────────────────────────────────

def _parse_pdf_with_openai(pdf_bytes):
    """
    Sends PDF to OpenAI GPT-4o vision and extracts structured invoice data as JSON.
    """
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("Pacote 'openai' nao instalado. Execute: pip install openai")

    api_key = current_app.config.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY nao configurada. Defina a variavel de ambiente.")

    client = OpenAI(api_key=api_key)
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    prompt = """Voce e um especialista em leitura de notas fiscais brasileiras.
Analise este documento PDF e extraia as seguintes informacoes em formato JSON puro (sem markdown, sem explicacoes):

{
  "invoice_number": "numero da nota fiscal (NF ou NF-e)",
  "supplier_name": "nome/razao social do fornecedor/emitente",
  "supplier_cnpj": "CNPJ do fornecedor (somente numeros)",
  "issue_date": "data de emissao no formato YYYY-MM-DD",
  "total_value": 0.00,
  "items": [
    {
      "description": "descricao completa do produto/servico",
      "ncm": "codigo NCM se disponivel, senao vazio",
      "quantity": 0.00,
      "unit": "unidade de medida (un, kg, m, l, etc)",
      "unit_price": 0.00,
      "total_price": 0.00
    }
  ]
}

Regras:
- Extraia TODOS os itens/produtos da nota
- Se um campo nao estiver disponivel, use string vazia ou 0
- Valores numericos devem ser numeros (nao strings)
- A data deve estar no formato YYYY-MM-DD
- Retorne APENAS o JSON, sem texto adicional"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:application/pdf;base64,{pdf_b64}",
                            "detail": "high"
                        }
                    }
                ]
            }
        ],
        max_tokens=4096,
    )

    raw = response.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    return json.loads(raw)


# ─────────────────────────────────────────────
# PDF OCR — Local fallback (PyPDF2 + regex)
# ─────────────────────────────────────────────

def _parse_pdf_local_fallback(pdf_bytes):
    """
    Fallback PDF parser using PyPDF2 text extraction + regex patterns for Brazilian NF-e.
    Used when OPENAI_API_KEY is not configured.
    Returns same dict structure as _parse_pdf_with_openai(), with _fallback=True.
    Item extraction is not reliable without AI; returns empty items list.
    """
    try:
        import PyPDF2
    except ImportError:
        raise RuntimeError("PyPDF2 nao instalado. Execute: pip install pypdf2")

    reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    # CNPJ pattern: XX.XXX.XXX/XXXX-XX
    cnpj_match = re.search(r'(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})', text)
    supplier_cnpj = re.sub(r'\D', '', cnpj_match.group(1)) if cnpj_match else ""

    # Total value: R$ X.XXX,XX
    total_value = 0.0
    total_match = re.search(r'R\$\s*([\d.,]+)', text)
    if total_match:
        raw = total_match.group(1).replace('.', '').replace(',', '.')
        try:
            total_value = float(raw)
        except ValueError:
            pass

    # Invoice number
    nf_match = re.search(
        r'(?:NF-?e?\s*n[º°o]?\s*|N[úu]mero\s*(?:da\s*NF)?[:\s]+)([\d.]+)',
        text, re.IGNORECASE
    )
    invoice_number = nf_match.group(1).replace('.', '') if nf_match else ""

    # Issue date: DD/MM/YYYY → YYYY-MM-DD
    issue_date = None
    date_match = re.search(r'(\d{2}/\d{2}/\d{4})', text)
    if date_match:
        parts = date_match.group(1).split('/')
        issue_date = f"{parts[2]}-{parts[1]}-{parts[0]}"

    # Supplier name
    name_match = re.search(
        r'(?:Raz[ãa]o\s*Social|Emitente)[:\s]+([^\n]+)',
        text, re.IGNORECASE
    )
    supplier_name = name_match.group(1).strip() if name_match else ""

    return {
        "invoice_number": invoice_number,
        "supplier_cnpj": supplier_cnpj,
        "supplier_name": supplier_name,
        "issue_date": issue_date,
        "total_value": total_value,
        "items": [],
        "_fallback": True,
    }


# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────

@invoices_bp.route("/", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def list_invoices():
    q = "SELECT * FROM invoices"
    args = []
    if request.args.get("status"):
        q += " WHERE status=?"; args.append(request.args["status"])
    q += " ORDER BY created_at DESC"
    rows = query_db(q, args)
    result = []
    for row in rows:
        d = dict(row)
        d["items"] = rows_to_dicts(query_db("SELECT * FROM invoice_items WHERE invoice_id=?", [d["id"]]))
        result.append(d)
    return jsonify(result)


@invoices_bp.route("/<invoice_id>", methods=["GET"])
@require_role("admin", "manager", "operator", "buyer")
def get_invoice(invoice_id):
    row = query_db("SELECT * FROM invoices WHERE id=?", [invoice_id], one=True)
    if not row: return jsonify({"error": "Not found"}), 404
    d = dict(row)
    d["items"] = rows_to_dicts(query_db("SELECT * FROM invoice_items WHERE invoice_id=?", [invoice_id]))
    # Re-attach validation warnings if CNPJ was flagged invalid
    d["validation_warnings"] = []
    if not d.get("cnpj_valid", 1):
        d["validation_warnings"].append(f"CNPJ possivelmente inválido: {d.get('supplier_cnpj', '')}")
    return jsonify(d)


@invoices_bp.route("/import-xml", methods=["POST"])
@require_role("admin", "buyer")
def import_xml():
    if "file" in request.files:
        xml_content = request.files["file"].read().decode("utf-8", errors="replace")
    else:
        data = request.get_json() or {}
        xml_content = data.get("xml_content", "")
    if not xml_content:
        return jsonify({"error": "Nenhum conteúdo XML"}), 400
    try:
        data = parse_nfe_xml(xml_content)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    # Validate CNPJ and NCM
    validation_warnings = []
    cnpj = data.get("supplier_cnpj", "")
    cnpj_valid = _validate_cnpj(cnpj) if cnpj else True
    if cnpj and not cnpj_valid:
        validation_warnings.append(f"CNPJ possivelmente inválido: {cnpj}")
    for item in data.get("items", []):
        ncm = item.get("ncm", "")
        if ncm and not _validate_ncm(ncm):
            validation_warnings.append(
                f"NCM inválido para '{item.get('description', '')}': {ncm}"
            )

    inv_id = str(uuid.uuid4())
    execute_db(
        """INSERT INTO invoices
               (id, invoice_number, supplier_cnpj, supplier_name, issue_date,
                total_value, xml_content, cnpj_valid)
           VALUES (?,?,?,?,?,?,?,?)""",
        [inv_id, data["invoice_number"], data["supplier_cnpj"], data["supplier_name"],
         data["issue_date"], data["total_value"], xml_content, 1 if cnpj_valid else 0]
    )

    _insert_invoice_items(inv_id, data["items"])

    d = dict(query_db("SELECT * FROM invoices WHERE id=?", [inv_id], one=True))
    d["items"] = rows_to_dicts(query_db("SELECT * FROM invoice_items WHERE invoice_id=?", [inv_id]))
    d["validation_warnings"] = validation_warnings
    return jsonify(d), 201


@invoices_bp.route("/import-pdf", methods=["POST"])
@require_role("admin", "buyer")
def import_pdf():
    if "file" not in request.files:
        return jsonify({"error": "Nenhum arquivo PDF enviado"}), 400

    f = request.files["file"]
    if not f.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Arquivo deve ser um PDF"}), 400

    pdf_bytes = f.read()
    if not pdf_bytes:
        return jsonify({"error": "Arquivo PDF vazio"}), 400

    # Check OCR cache first
    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
    cached = _get_ocr_cache(pdf_hash)
    ocr_source = "cache"

    if cached:
        data = cached
    else:
        api_key = current_app.config.get("OPENAI_API_KEY", "")
        if api_key:
            try:
                data = _parse_pdf_with_openai(pdf_bytes)
                ocr_source = "openai"
                _set_ocr_cache(pdf_hash, data, source="openai")
            except Exception as e:
                try:
                    data = _parse_pdf_local_fallback(pdf_bytes)
                    ocr_source = "local"
                    _set_ocr_cache(pdf_hash, data, source="local")
                except Exception:
                    if isinstance(e, RuntimeError):
                        return jsonify({"error": str(e)}), 503
                    if isinstance(e, (json.JSONDecodeError, KeyError)):
                        return jsonify({"error": f"Nao foi possivel interpretar a resposta da IA: {str(e)}"}), 422
                    return jsonify({"error": f"Erro ao processar PDF: {str(e)}"}), 500
        else:
            try:
                data = _parse_pdf_local_fallback(pdf_bytes)
                ocr_source = "local"
                _set_ocr_cache(pdf_hash, data, source="local")
            except Exception as e:
                return jsonify({"error": f"Erro no fallback local: {str(e)}"}), 500

    # Allow import even with empty items when using fallback
    if not data.get("items") and not data.get("_fallback"):
        return jsonify({"error": "Nenhum item encontrado na nota fiscal"}), 422

    # Validate CNPJ and NCM
    validation_warnings = []
    if ocr_source == "cache":
        validation_warnings = []  # warnings were already stored on first import

    cnpj = data.get("supplier_cnpj", "")
    cnpj_valid = _validate_cnpj(cnpj) if cnpj else True
    if cnpj and not cnpj_valid:
        validation_warnings.append(f"CNPJ possivelmente inválido: {cnpj}")
    for item in data.get("items", []):
        ncm = item.get("ncm", "")
        if ncm and not _validate_ncm(ncm):
            validation_warnings.append(
                f"NCM inválido para '{item.get('description', '')}': {ncm}"
            )

    inv_id = str(uuid.uuid4())
    execute_db(
        """INSERT INTO invoices
               (id, invoice_number, supplier_cnpj, supplier_name, issue_date,
                total_value, xml_content, cnpj_valid)
           VALUES (?,?,?,?,?,?,?,?)""",
        [inv_id,
         data.get("invoice_number", ""),
         data.get("supplier_cnpj", ""),
         data.get("supplier_name", ""),
         data.get("issue_date"),
         float(data.get("total_value", 0)),
         f"[PDF:{ocr_source}] {f.filename}",
         1 if cnpj_valid else 0]
    )

    _insert_invoice_items(inv_id, data.get("items", []))

    d = dict(query_db("SELECT * FROM invoices WHERE id=?", [inv_id], one=True))
    d["items"] = rows_to_dicts(query_db("SELECT * FROM invoice_items WHERE invoice_id=?", [inv_id]))
    d["ocr_source"] = ocr_source
    d["validation_warnings"] = validation_warnings
    return jsonify(d), 201


@invoices_bp.route("/<invoice_id>/process", methods=["POST"])
@require_role("admin", "manager")
def process_invoice(invoice_id):
    current = get_current_user()
    data = request.get_json() or {}
    invoice = row_to_dict(query_db("SELECT * FROM invoices WHERE id=?", [invoice_id], one=True))
    if not invoice: return jsonify({"error": "Not found"}), 404

    for mapping in data.get("item_mappings", []):
        item = row_to_dict(query_db("SELECT * FROM invoice_items WHERE id=?", [mapping["item_id"]], one=True))
        if not item or not mapping.get("product_id"): continue
        execute_db("UPDATE invoice_items SET product_id=?, matched=1 WHERE id=?",
                   [mapping["product_id"], mapping["item_id"]])
        mid = str(uuid.uuid4())
        qty = float(item["quantity"])
        execute_db(
            """INSERT INTO movements (id, product_id, type, quantity, unit_cost, user_id, invoice_number, observation)
               VALUES (?,?,?,?,?,?,?,?)""",
            [mid, mapping["product_id"], "entry", qty, item["unit_price"],
             current.get("id"), invoice["invoice_number"],
             f"Importado via NF-e {invoice['invoice_number']}"]
        )
        execute_db("UPDATE products SET stock=stock+? WHERE id=?", [qty, mapping["product_id"]])

    execute_db("UPDATE invoices SET status='processed' WHERE id=?", [invoice_id])
    return jsonify(row_to_dict(query_db("SELECT * FROM invoices WHERE id=?", [invoice_id], one=True)))


@invoices_bp.route("/<invoice_id>/reverse", methods=["POST"])
@require_role("admin")
def reverse_invoice(invoice_id):
    """
    Reverses a processed invoice:
    - Finds all entry movements linked to this invoice number
    - Creates negative adjustment movements for each
    - Decrements product stock accordingly
    - Sets invoice status to 'reversed'
    """
    current = get_current_user()
    invoice = row_to_dict(
        query_db("SELECT * FROM invoices WHERE id=?", [invoice_id], one=True)
    )
    if not invoice:
        return jsonify({"error": "Nota não encontrada"}), 404
    if invoice["status"] != "processed":
        return jsonify({"error": "Apenas notas com status 'processed' podem ser estornadas"}), 400

    inv_number = invoice["invoice_number"]

    entries = rows_to_dicts(
        query_db(
            "SELECT * FROM movements WHERE invoice_number=? AND type='entry'",
            [inv_number]
        )
    )

    if not entries:
        return jsonify({"error": "Nenhuma movimentação de entrada encontrada para esta nota"}), 400

    for entry in entries:
        mid = str(uuid.uuid4())
        qty = float(entry["quantity"])
        execute_db(
            """INSERT INTO movements
                   (id, product_id, type, quantity, unit_cost, user_id,
                    invoice_number, observation)
               VALUES (?,?,?,?,?,?,?,?)""",
            [mid, entry["product_id"], "adjustment", -qty,
             entry.get("unit_cost", 0), current.get("id"),
             inv_number,
             f"Estorno NF-e {inv_number}"]
        )
        execute_db(
            "UPDATE products SET stock=stock-? WHERE id=?",
            [qty, entry["product_id"]]
        )

    execute_db("UPDATE invoices SET status='reversed' WHERE id=?", [invoice_id])

    return jsonify(
        row_to_dict(query_db("SELECT * FROM invoices WHERE id=?", [invoice_id], one=True))
    )
