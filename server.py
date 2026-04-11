import json
import os
import sqlite3
import csv
import io
import zipfile
import cgi
from datetime import datetime
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import xml.etree.ElementTree as ET
from io import BytesIO

try:
    from pypdf import PdfReader, PdfWriter
except Exception:
    PdfReader = None
    PdfWriter = None

BASE_DIR = Path(__file__).parent
PUBLIC_DIR = BASE_DIR / "public"
DB_PATH = BASE_DIR / "app.db"
TEMPLATES_DIR = BASE_DIR / "templates"
DOCS_DIR = BASE_DIR / "generated_docs"
UPLOADS_DIR = BASE_DIR / "uploads"
NAVIERA_TEMPLATES_PATH = TEMPLATES_DIR / "naviera_templates.json"
BANK_COVERS_PATH = TEMPLATES_DIR / "bank_covers.json"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referencia TEXT NOT NULL,
            naviera TEXT NOT NULL,
            bl TEXT NOT NULL,
            total REAL NOT NULL,
            fecha_recuperacion TEXT NOT NULL,
            estatus TEXT NOT NULL
        )
        """
    )
    cur.execute("PRAGMA table_info(records)")
    existing_cols = {row[1] for row in cur.fetchall()}
    if "pago_concepto" not in existing_cols:
        cur.execute("ALTER TABLE records ADD COLUMN pago_concepto TEXT")
    if "pago_confirmado_en" not in existing_cols:
        cur.execute("ALTER TABLE records ADD COLUMN pago_confirmado_en TEXT")
    if "generated_pdf_path" not in existing_cols:
        cur.execute("ALTER TABLE records ADD COLUMN generated_pdf_path TEXT")
    if "generated_pdf_at" not in existing_cols:
        cur.execute("ALTER TABLE records ADD COLUMN generated_pdf_at TEXT")
    doc_cols = [
        "bank_cover_path TEXT",
        "bank_cover_uploaded_at TEXT",
        "bank_cover_expires_at TEXT",
        "fiscal_path TEXT",
        "fiscal_uploaded_at TEXT",
        "fiscal_expires_at TEXT",
        "email_capture_path TEXT",
        "email_uploaded_at TEXT",
        "email_expires_at TEXT",
    ]
    for col_def in doc_cols:
        col_name = col_def.split()[0]
        if col_name not in existing_cols:
            cur.execute(f"ALTER TABLE records ADD COLUMN {col_def}")
    conn.commit()
    conn.close()


def init_templates():
    os.makedirs(TEMPLATES_DIR, exist_ok=True)
    if not NAVIERA_TEMPLATES_PATH.exists():
        NAVIERA_TEMPLATES_PATH.write_text(
            json.dumps(
                {
                    "MSC": "Estimados {{cliente}},\n\nPor medio de la presente se solicita atención del BL {{bl}}.\nReferencia: {{referencia}}\nTotal: {{total}}\nFecha: {{fecha}}\n",
                    "MAERSK": "Carta para {{cliente}}\nBL: {{bl}}\nReferencia: {{referencia}}\nTotal reclamado: {{total}}\nFecha: {{fecha}}\n",
                    "_default": "Carta dirigida a {{cliente}}\nBL {{bl}} / Ref {{referencia}}\nMonto {{total}}\nFecha {{fecha}}\n",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    if not BANK_COVERS_PATH.exists():
        BANK_COVERS_PATH.write_text(
            json.dumps(
                {
                    "BANCOMER": {"template": "Carátula bancaria BANCOMER\nCliente: {{cliente}}\nBL: {{bl}}\nTotal: {{total}}", "vigente": True},
                    "SANTANDER": {"template": "Carátula bancaria SANTANDER\nCliente: {{cliente}}\nBL: {{bl}}\nTotal: {{total}}", "vigente": True},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


def db_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _normalize_col_name(name):
    return (
        (name or "")
        .strip()
        .lower()
        .replace(" ", "_")
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
    )


def _extract_record_from_row(row):
    normalized = {_normalize_col_name(k): (v or "").strip() for k, v in row.items()}
    referencia = normalized.get("referencia", "")
    naviera = normalized.get("naviera", "")
    bl = normalized.get("bl", "")
    total = normalized.get("total", "0")
    fecha_recuperacion = normalized.get("fecha_recuperacion", "") or normalized.get("fecha", "")
    estatus = normalized.get("estatus", "") or "Pendiente"

    if not (referencia and naviera and bl):
        return None

    try:
        total_value = float(str(total).replace(",", "."))
    except ValueError:
        total_value = 0.0

    return {
        "referencia": referencia,
        "naviera": naviera,
        "bl": bl,
        "total": total_value,
        "fecha_recuperacion": fecha_recuperacion or datetime.utcnow().date().isoformat(),
        "estatus": estatus,
    }


def parse_csv_bytes(file_bytes):
    text = file_bytes.decode("utf-8-sig", errors="ignore")
    reader = csv.DictReader(io.StringIO(text))
    return list(reader)


def parse_xlsx_bytes(file_bytes):
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rows_data = []

    with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
        shared_strings = []
        if "xl/sharedStrings.xml" in zf.namelist():
            ss_root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in ss_root.findall("m:si", ns):
                parts = []
                for t in si.findall(".//m:t", ns):
                    parts.append(t.text or "")
                shared_strings.append("".join(parts))

        sheet_path = "xl/worksheets/sheet1.xml"
        if sheet_path not in zf.namelist():
            return rows_data

        sheet_root = ET.fromstring(zf.read(sheet_path))
        rows = sheet_root.findall(".//m:sheetData/m:row", ns)
        if not rows:
            return rows_data

        headers = []
        for c in rows[0].findall("m:c", ns):
            cell_type = c.attrib.get("t")
            v = c.find("m:v", ns)
            value = v.text if v is not None else ""
            if cell_type == "s" and value != "":
                value = shared_strings[int(value)]
            headers.append(value)

        for row in rows[1:]:
            values = []
            for c in row.findall("m:c", ns):
                cell_type = c.attrib.get("t")
                v = c.find("m:v", ns)
                value = v.text if v is not None else ""
                if cell_type == "s" and value != "":
                    value = shared_strings[int(value)]
                values.append(value)
            row_dict = {}
            for i, h in enumerate(headers):
                row_dict[h] = values[i] if i < len(values) else ""
            rows_data.append(row_dict)
    return rows_data


def _is_overdue(fecha_recuperacion):
    try:
        dt = datetime.strptime((fecha_recuperacion or "").strip(), "%Y-%m-%d").date()
        return dt < datetime.utcnow().date()
    except ValueError:
        return False


def _apply_pending_rule(conn):
    """
    Si la fecha de recuperación ya pasó y el estatus no es 'Pagado',
    entonces se marca como 'Pendiente'.
    """
    cur = conn.cursor()
    cur.execute("SELECT id, fecha_recuperacion, estatus FROM records")
    rows = cur.fetchall()
    updates = []
    for row in rows:
        estatus = (row["estatus"] or "").strip().lower()
        if _is_overdue(row["fecha_recuperacion"]) and estatus != "pagado":
            if estatus != "pendiente":
                updates.append((row["id"],))
    if updates:
        cur.executemany("UPDATE records SET estatus = 'Pendiente' WHERE id = ?", updates)
        conn.commit()


def _normalize_text(value):
    return "".join(ch.lower() if ch.isalnum() else " " for ch in (value or "")).strip()


def _flex_match(bl_value, concepto):
    bl = _normalize_text(bl_value).replace(" ", "")
    text = _normalize_text(concepto).replace(" ", "")
    if not bl or not text:
        return False
    if bl in text:
        return True
    # Coincidencia flexible: segmentos del BL (>=4 chars) dentro del concepto.
    for i in range(0, max(len(bl) - 3, 0)):
        segment = bl[i : i + 4]
        if segment and segment in text:
            return True
    return False


def _render_template(template_text, record):
    data = {
        "cliente": record.get("naviera", ""),
        "bl": record.get("bl", ""),
        "referencia": record.get("referencia", ""),
        "total": str(record.get("total", "")),
        "fecha": record.get("fecha_recuperacion", ""),
    }
    rendered = template_text
    for key, value in data.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", str(value))
    return rendered


def _escape_pdf_text(text):
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def create_simple_pdf(pages, output_path):
    """
    Genera un PDF simple (texto) sin dependencias externas.
    """
    objects = []
    kids = []
    page_size = "595 842"

    # 1: Catalog, 2: Pages
    objects.append("<< /Type /Catalog /Pages 2 0 R >>")
    objects.append("<< /Type /Pages /Kids [] /Count 0 >>")

    font_obj_id = 3
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    for page_text in pages:
        lines = (page_text or "").splitlines() or [""]
        content_lines = ["BT", "/F1 12 Tf", "50 790 Td", "14 TL"]
        for idx, line in enumerate(lines[:45]):
            safe_line = _escape_pdf_text(line)
            if idx == 0:
                content_lines.append(f"({safe_line}) Tj")
            else:
                content_lines.append(f"T* ({safe_line}) Tj")
        content_lines.append("ET")
        stream = "\n".join(content_lines).encode("latin-1", errors="replace")
        content_obj = f"<< /Length {len(stream)} >>\nstream\n{stream.decode('latin-1')}\nendstream"
        objects.append(content_obj)
        content_id = len(objects)

        page_obj = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_size}] "
            f"/Resources << /Font << /F1 {font_obj_id} 0 R >> >> /Contents {content_id} 0 R >>"
        )
        objects.append(page_obj)
        page_id = len(objects)
        kids.append(f"{page_id} 0 R")

    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"

    content = "%PDF-1.4\n"
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(content.encode("latin-1")))
        content += f"{i} 0 obj\n{obj}\nendobj\n"
    xref_pos = len(content.encode("latin-1"))
    content += f"xref\n0 {len(objects)+1}\n"
    content += "0000000000 65535 f \n"
    for off in offsets[1:]:
        content += f"{off:010d} 00000 n \n"
    content += f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF"

    with open(output_path, "wb") as f:
        f.write(content.encode("latin-1", errors="replace"))


def create_simple_pdf_bytes(text):
    temp_path = DOCS_DIR / f"_tmp_{int(datetime.utcnow().timestamp()*1000000)}.pdf"
    create_simple_pdf([text], temp_path)
    data = temp_path.read_bytes()
    temp_path.unlink(missing_ok=True)
    return data


def _jpeg_size(data):
    # Parser básico para obtener tamaño JPEG.
    i = 2
    while i < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3):
            h = int.from_bytes(data[i + 5 : i + 7], "big")
            w = int.from_bytes(data[i + 7 : i + 9], "big")
            return w, h
        length = int.from_bytes(data[i + 2 : i + 4], "big")
        i += 2 + length
    raise ValueError("No se pudo leer tamaño JPEG")


def jpeg_to_pdf_bytes(jpeg_bytes):
    width, height = _jpeg_size(jpeg_bytes)
    objects = []
    objects.append("<< /Type /Catalog /Pages 2 0 R >>")
    objects.append("<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] "
        "/Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>"
    )
    img_stream = (
        f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
        "/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
        f"/Length {len(jpeg_bytes)} >>\nstream\n"
    ).encode("latin-1") + jpeg_bytes + b"\nendstream"
    objects.append(img_stream)
    content = f"q\n{width} 0 0 {height} 0 0 cm\n/Im0 Do\nQ\n".encode("latin-1")
    content_obj = f"<< /Length {len(content)} >>\nstream\n".encode("latin-1") + content + b"endstream"
    objects.append(content_obj)

    pdf = b"%PDF-1.4\n"
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        if isinstance(obj, str):
            obj = obj.encode("latin-1")
        pdf += f"{i} 0 obj\n".encode("latin-1") + obj + b"\nendobj\n"
    xref_pos = len(pdf)
    pdf += f"xref\n0 {len(objects)+1}\n".encode("latin-1")
    pdf += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        pdf += f"{off:010d} 00000 n \n".encode("latin-1")
    pdf += f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF".encode(
        "latin-1"
    )
    return pdf


def _iso_now():
    return datetime.utcnow().isoformat()


def _expires_in_3_months():
    return (datetime.utcnow() + timedelta(days=90)).date().isoformat()


def _is_expired(iso_date):
    if not iso_date:
        return True
    try:
        return datetime.strptime(iso_date, "%Y-%m-%d").date() < datetime.utcnow().date()
    except ValueError:
        return True


class Handler(BaseHTTPRequestHandler):
    def _set_headers(self, status=200, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.end_headers()

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        return json.loads(body) if body else {}

    def _send_json(self, payload, status=200):
        self._set_headers(status=status, content_type="application/json")
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def _serve_static(self, filepath):
        full_path = PUBLIC_DIR / filepath
        if not full_path.exists() or not full_path.is_file():
            self._set_headers(404, "text/plain")
            self.wfile.write(b"Not found")
            return

        ext = full_path.suffix
        mime_types = {
            ".html": "text/html",
            ".css": "text/css",
            ".js": "application/javascript",
            ".json": "application/json",
        }
        content_type = mime_types.get(ext, "application/octet-stream")

        self._set_headers(200, content_type)
        with open(full_path, "rb") as f:
            self.wfile.write(f.read())

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            return self._serve_static("index.html")

        if path.startswith("/public/"):
            rel_path = path.replace("/public/", "", 1)
            return self._serve_static(rel_path)

        if path == "/api/records":
            params = parse_qs(parsed.query)
            naviera_filter = params.get("naviera", [""])[0].strip()
            conn = db_conn()
            _apply_pending_rule(conn)
            cur = conn.cursor()
            if naviera_filter:
                cur.execute(
                    "SELECT * FROM records WHERE naviera = ? ORDER BY id DESC",
                    (naviera_filter,),
                )
            else:
                cur.execute("SELECT * FROM records ORDER BY id DESC")
            records = [dict(row) for row in cur.fetchall()]
            conn.close()
            return self._send_json(records)

        if path == "/api/pending":
            conn = db_conn()
            _apply_pending_rule(conn)
            cur = conn.cursor()
            cur.execute(
                """
                SELECT * FROM records
                WHERE estatus = 'Pendiente'
                ORDER BY fecha_recuperacion ASC, id DESC
                """
            )
            pending = [dict(row) for row in cur.fetchall()]
            conn.close()
            return self._send_json(pending)

        if path == "/api/document-config":
            naviera_templates = json.loads(NAVIERA_TEMPLATES_PATH.read_text(encoding="utf-8"))
            bank_covers = json.loads(BANK_COVERS_PATH.read_text(encoding="utf-8"))
            return self._send_json(
                {
                    "navieras": [k for k in naviera_templates.keys() if k != "_default"],
                    "banks": [k for k, v in bank_covers.items() if v.get("vigente")],
                }
            )

        if path.startswith("/api/documents/download/"):
            record_id = path.split("/")[-1]
            conn = db_conn()
            cur = conn.cursor()
            cur.execute("SELECT generated_pdf_path FROM records WHERE id = ?", (int(record_id),))
            row = cur.fetchone()
            conn.close()
            if not row or not row["generated_pdf_path"]:
                self._set_headers(404, "text/plain")
                self.wfile.write(b"Documento no encontrado")
                return
            pdf_path = Path(row["generated_pdf_path"])
            if not pdf_path.exists():
                self._set_headers(404, "text/plain")
                self.wfile.write(b"Archivo no existe")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", f"attachment; filename={pdf_path.name}")
            self.end_headers()
            with open(pdf_path, "rb") as f:
                self.wfile.write(f.read())
            return

        self._set_headers(404, "text/plain")
        self.wfile.write(b"Not found")

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/api/login":
            data = self._read_json()
            username = data.get("username", "").strip()
            if not username:
                return self._send_json({"error": "Usuario requerido"}, status=400)
            return self._send_json(
                {
                    "message": "Login simulado exitoso",
                    "user": {"username": username, "login_at": datetime.utcnow().isoformat()},
                }
            )

        if path == "/api/records":
            data = self._read_json()
            required = ["referencia", "naviera", "bl", "total", "fecha_recuperacion", "estatus"]
            if any(not str(data.get(key, "")).strip() for key in required):
                return self._send_json({"error": "Todos los campos son obligatorios"}, status=400)

            conn = db_conn()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO records (referencia, naviera, bl, total, fecha_recuperacion, estatus)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    data["referencia"].strip(),
                    data["naviera"].strip(),
                    data["bl"].strip(),
                    float(data["total"]),
                    data["fecha_recuperacion"].strip(),
                    data["estatus"].strip(),
                ),
            )
            conn.commit()
            new_id = cur.lastrowid
            conn.close()
            return self._send_json({"message": "Registro creado", "id": new_id}, status=201)

        if path == "/api/import":
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": self.headers.get("Content-Type"),
                },
            )

            if "file" not in form:
                return self._send_json({"error": "Archivo no recibido"}, status=400)

            file_item = form["file"]
            filename = (file_item.filename or "").lower()
            file_bytes = file_item.file.read()

            try:
                if filename.endswith(".csv"):
                    parsed_rows = parse_csv_bytes(file_bytes)
                elif filename.endswith(".xlsx"):
                    parsed_rows = parse_xlsx_bytes(file_bytes)
                else:
                    return self._send_json(
                        {"error": "Formato no soportado. Usa CSV o XLSX."}, status=400
                    )
            except Exception:
                return self._send_json({"error": "No se pudo leer el archivo"}, status=400)

            conn = db_conn()
            cur = conn.cursor()
            cur.execute("SELECT referencia, naviera, bl FROM records")
            existing_keys = {
                (
                    (r["bl"] or "").strip().lower(),
                    (r["naviera"] or "").strip().lower(),
                    (r["referencia"] or "").strip().lower(),
                )
                for r in cur.fetchall()
            }

            seen_in_file = set()
            duplicates = []
            to_insert = []

            for row in parsed_rows:
                normalized = _extract_record_from_row(row)
                if not normalized:
                    continue

                key = (
                    normalized["bl"].strip().lower(),
                    normalized["naviera"].strip().lower(),
                    normalized["referencia"].strip().lower(),
                )

                if key in seen_in_file or key in existing_keys:
                    duplicates.append(
                        {
                            "referencia": normalized["referencia"],
                            "naviera": normalized["naviera"],
                            "bl": normalized["bl"],
                        }
                    )
                    continue

                seen_in_file.add(key)
                to_insert.append(normalized)

            if to_insert:
                cur.executemany(
                    """
                    INSERT INTO records (referencia, naviera, bl, total, fecha_recuperacion, estatus)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            r["referencia"],
                            r["naviera"],
                            r["bl"],
                            r["total"],
                            r["fecha_recuperacion"],
                            r["estatus"],
                        )
                        for r in to_insert
                    ],
                )
                conn.commit()
            conn.close()

            return self._send_json(
                {
                    "message": "Importación procesada",
                    "inserted": len(to_insert),
                    "duplicates": duplicates,
                },
                status=201,
            )

        if path == "/api/payments/validate":
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": self.headers.get("Content-Type"),
                },
            )
            if "file" not in form:
                return self._send_json({"error": "Archivo no recibido"}, status=400)

            file_item = form["file"]
            filename = (file_item.filename or "").lower()
            file_bytes = file_item.file.read()
            if not filename.endswith(".xlsx"):
                return self._send_json({"error": "Solo se soporta Excel .xlsx"}, status=400)

            try:
                parsed_rows = parse_xlsx_bytes(file_bytes)
            except Exception:
                return self._send_json({"error": "No se pudo leer el archivo Excel"}, status=400)

            concepts = []
            for row in parsed_rows:
                normalized = {_normalize_col_name(k): (v or "").strip() for k, v in row.items()}
                concepto = normalized.get("concepto", "")
                if concepto:
                    concepts.append(concepto)

            conn = db_conn()
            cur = conn.cursor()
            cur.execute("SELECT id, referencia, naviera, bl, estatus FROM records ORDER BY id DESC")
            records = [dict(r) for r in cur.fetchall()]
            conn.close()

            suggestions = []
            for concepto in concepts:
                matches = []
                for record in records:
                    if _flex_match(record.get("bl"), concepto):
                        matches.append(
                            {
                                "id": record["id"],
                                "referencia": record["referencia"],
                                "naviera": record["naviera"],
                                "bl": record["bl"],
                                "estatus": record["estatus"],
                            }
                        )
                if matches:
                    suggestions.append({"concepto": concepto, "matches": matches})

            return self._send_json(
                {
                    "message": "Validación procesada",
                    "concepts_found": len(concepts),
                    "suggestions": suggestions,
                }
            )

        if path == "/api/documents/generate":
            if PdfReader is None or PdfWriter is None:
                return self._send_json(
                    {"error": "Dependencia faltante: instala pypdf para generar PDFs reales"},
                    status=500,
                )
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": self.headers.get("Content-Type"),
                },
            )
            record_id = (form.getvalue("record_id") or "").strip()
            bank = (form.getvalue("bank") or "").strip().upper()
            if not record_id or not bank:
                return self._send_json({"error": "record_id y bank son requeridos"}, status=400)

            conn = db_conn()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, referencia, naviera, bl, total, fecha_recuperacion,
                       bank_cover_path, bank_cover_uploaded_at, bank_cover_expires_at,
                       fiscal_path, fiscal_uploaded_at, fiscal_expires_at,
                       email_capture_path, email_uploaded_at, email_expires_at
                FROM records WHERE id = ?
                """,
                (int(record_id),),
            )
            record = cur.fetchone()
            if not record:
                conn.close()
                return self._send_json({"error": "Registro no encontrado"}, status=404)

            record_data = dict(record)
            required_values = ["referencia", "naviera", "bl", "total", "fecha_recuperacion"]
            if any(not str(record_data.get(k, "")).strip() for k in required_values):
                conn.close()
                return self._send_json({"error": "Faltan datos clave del registro"}, status=400)

            naviera_templates = json.loads(NAVIERA_TEMPLATES_PATH.read_text(encoding="utf-8"))
            bank_covers = json.loads(BANK_COVERS_PATH.read_text(encoding="utf-8"))

            bank_cfg = bank_covers.get(bank)
            if not bank_cfg or not bank_cfg.get("vigente"):
                conn.close()
                return self._send_json({"error": "Carátula bancaria vigente no disponible"}, status=400)

            bank_cover_content = None
            bank_cover_path = record_data.get("bank_cover_path")
            bank_cover_uploaded_at = record_data.get("bank_cover_uploaded_at")
            bank_cover_expires_at = record_data.get("bank_cover_expires_at")
            if "bank_cover_file" in form and getattr(form["bank_cover_file"], "filename", None):
                bank_cover_item = form["bank_cover_file"]
                bank_cover_filename = bank_cover_item.filename or "caratula.pdf"
                bank_cover_content = bank_cover_item.file.read()
                if not bank_cover_content:
                    conn.close()
                    return self._send_json({"error": "Carátula bancaria vacía"}, status=400)
            elif bank_cover_path and Path(bank_cover_path).exists() and not _is_expired(bank_cover_expires_at):
                bank_cover_content = Path(bank_cover_path).read_bytes()
            else:
                conn.close()
                return self._send_json({"error": "Carátula bancaria vigente no disponible"}, status=400)

            fiscal_content = None
            fiscal_path = record_data.get("fiscal_path")
            fiscal_uploaded_at = record_data.get("fiscal_uploaded_at")
            fiscal_expires_at = record_data.get("fiscal_expires_at")
            if "fiscal_file" in form and getattr(form["fiscal_file"], "filename", None):
                fiscal_item = form["fiscal_file"]
                fiscal_filename = fiscal_item.filename or "constancia.pdf"
                fiscal_content = fiscal_item.file.read()
                if not fiscal_content:
                    conn.close()
                    return self._send_json({"error": "Constancia fiscal vacía"}, status=400)
            elif fiscal_path and Path(fiscal_path).exists() and not _is_expired(fiscal_expires_at):
                fiscal_content = Path(fiscal_path).read_bytes()
                fiscal_filename = Path(fiscal_path).name
            else:
                conn.close()
                return self._send_json({"error": "Constancia fiscal vigente no disponible"}, status=400)

            os.makedirs(UPLOADS_DIR, exist_ok=True)
            os.makedirs(DOCS_DIR, exist_ok=True)
            if "fiscal_file" in form and getattr(form["fiscal_file"], "filename", None):
                safe_fiscal_name = os.path.basename(fiscal_filename)
                fiscal_path = UPLOADS_DIR / f"fiscal_{record_id}_{int(datetime.utcnow().timestamp())}_{safe_fiscal_name}"
                with open(fiscal_path, "wb") as f:
                    f.write(fiscal_content)
                fiscal_uploaded_at = _iso_now()
                fiscal_expires_at = _expires_in_3_months()

            if "bank_cover_file" in form and getattr(form["bank_cover_file"], "filename", None):
                safe_bank_name = os.path.basename(bank_cover_filename)
                bank_cover_path = UPLOADS_DIR / f"bank_{record_id}_{int(datetime.utcnow().timestamp())}_{safe_bank_name}"
                with open(bank_cover_path, "wb") as f:
                    f.write(bank_cover_content)
                bank_cover_uploaded_at = _iso_now()
                bank_cover_expires_at = _expires_in_3_months()

            if _is_expired(bank_cover_expires_at):
                conn.close()
                return self._send_json({"error": "Carátula bancaria vencida"}, status=400)
            if _is_expired(fiscal_expires_at):
                conn.close()
                return self._send_json({"error": "Constancia fiscal vencida"}, status=400)

            email_pdf_bytes = None
            email_capture_path = record_data.get("email_capture_path")
            email_uploaded_at = record_data.get("email_uploaded_at")
            email_expires_at = record_data.get("email_expires_at")
            if "email_capture" in form and getattr(form["email_capture"], "filename", None):
                email_item = form["email_capture"]
                email_filename = email_item.filename or "captura_correo"
                email_bytes = email_item.file.read()
                safe_email_name = os.path.basename(email_filename)
                email_capture_path = UPLOADS_DIR / f"email_{record_id}_{int(datetime.utcnow().timestamp())}_{safe_email_name}"
                with open(email_capture_path, "wb") as f:
                    f.write(email_bytes)
                email_uploaded_at = _iso_now()
                email_expires_at = _expires_in_3_months()
                lower_name = safe_email_name.lower()
                if lower_name.endswith(".pdf"):
                    email_pdf_bytes = email_bytes
                elif lower_name.endswith(".jpg") or lower_name.endswith(".jpeg"):
                    email_pdf_bytes = jpeg_to_pdf_bytes(email_bytes)
                else:
                    conn.close()
                    return self._send_json(
                        {"error": "Captura de correo debe ser PDF o imagen JPG/JPEG"},
                        status=400,
                    )
            elif email_capture_path and Path(email_capture_path).exists() and not _is_expired(email_expires_at):
                email_bytes = Path(email_capture_path).read_bytes()
                if str(email_capture_path).lower().endswith(".pdf"):
                    email_pdf_bytes = email_bytes
                elif str(email_capture_path).lower().endswith(".jpg") or str(email_capture_path).lower().endswith(".jpeg"):
                    email_pdf_bytes = jpeg_to_pdf_bytes(email_bytes)

            naviera_key = record_data["naviera"].strip().upper()
            naviera_template = naviera_templates.get(naviera_key, naviera_templates.get("_default", ""))
            carta_text = _render_template(naviera_template, record_data)

            output_path = DOCS_DIR / f"registro_{record_id}_{int(datetime.utcnow().timestamp())}.pdf"
            writer = PdfWriter()

            # Página 1: carta generada.
            carta_pdf = create_simple_pdf_bytes(f"Carta a naviera\n\n{carta_text}")
            carta_reader = PdfReader(BytesIO(carta_pdf))
            writer.add_page(carta_reader.pages[0])

            # Página 2: carátula bancaria real (primera hoja del PDF cargado).
            bank_reader = PdfReader(BytesIO(bank_cover_content))
            writer.add_page(bank_reader.pages[0])

            # Página 3: captura opcional (PDF o imagen convertida a PDF).
            if email_pdf_bytes:
                email_reader = PdfReader(BytesIO(email_pdf_bytes))
                writer.add_page(email_reader.pages[0])

            # Página 4: constancia fiscal (solo primera hoja real del PDF).
            fiscal_reader = PdfReader(BytesIO(fiscal_content))
            writer.add_page(fiscal_reader.pages[0])

            with open(output_path, "wb") as f:
                writer.write(f)

            cur.execute(
                """
                UPDATE records
                SET generated_pdf_path = ?, generated_pdf_at = ?,
                    bank_cover_path = ?, bank_cover_uploaded_at = ?, bank_cover_expires_at = ?,
                    fiscal_path = ?, fiscal_uploaded_at = ?, fiscal_expires_at = ?,
                    email_capture_path = ?, email_uploaded_at = ?, email_expires_at = ?
                WHERE id = ?
                """,
                (
                    str(output_path),
                    _iso_now(),
                    str(bank_cover_path) if bank_cover_path else None,
                    bank_cover_uploaded_at,
                    bank_cover_expires_at,
                    str(fiscal_path) if fiscal_path else None,
                    fiscal_uploaded_at,
                    fiscal_expires_at,
                    str(email_capture_path) if email_capture_path else None,
                    email_uploaded_at,
                    email_expires_at,
                    int(record_id),
                ),
            )
            conn.commit()
            conn.close()

            return self._send_json(
                {
                    "message": "Documento generado",
                    "download_url": f"/api/documents/download/{record_id}",
                },
                status=201,
            )

        if path == "/api/payments/confirm":
            data = self._read_json()
            record_id = data.get("record_id")
            concepto = (data.get("concepto") or "").strip()
            if not record_id:
                return self._send_json({"error": "record_id es requerido"}, status=400)

            conn = db_conn()
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE records
                SET estatus = 'Pagado',
                    pago_concepto = ?,
                    pago_confirmado_en = ?
                WHERE id = ?
                """,
                (concepto, datetime.utcnow().isoformat(), int(record_id)),
            )
            conn.commit()
            updated = cur.rowcount
            conn.close()
            if not updated:
                return self._send_json({"error": "Registro no encontrado"}, status=404)
            return self._send_json({"message": "Pago confirmado y registro actualizado"})

        self._send_json({"error": "Ruta no encontrada"}, status=404)

    def do_PUT(self):
        path = urlparse(self.path).path
        if not path.startswith("/api/records/"):
            return self._send_json({"error": "Ruta no encontrada"}, status=404)

        record_id = path.split("/")[-1]
        data = self._read_json()
        required = ["referencia", "naviera", "bl", "total", "fecha_recuperacion", "estatus"]
        if any(not str(data.get(key, "")).strip() for key in required):
            return self._send_json({"error": "Todos los campos son obligatorios"}, status=400)

        conn = db_conn()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE records
            SET referencia = ?, naviera = ?, bl = ?, total = ?, fecha_recuperacion = ?, estatus = ?
            WHERE id = ?
            """,
            (
                data["referencia"].strip(),
                data["naviera"].strip(),
                data["bl"].strip(),
                float(data["total"]),
                data["fecha_recuperacion"].strip(),
                data["estatus"].strip(),
                int(record_id),
            ),
        )
        conn.commit()
        updated = cur.rowcount
        conn.close()
        if not updated:
            return self._send_json({"error": "Registro no encontrado"}, status=404)
        return self._send_json({"message": "Registro actualizado"})

    def do_DELETE(self):
        path = urlparse(self.path).path
        if not path.startswith("/api/records/"):
            return self._send_json({"error": "Ruta no encontrada"}, status=404)

        record_id = path.split("/")[-1]
        conn = db_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM records WHERE id = ?", (int(record_id),))
        conn.commit()
        deleted = cur.rowcount
        conn.close()

        if not deleted:
            return self._send_json({"error": "Registro no encontrado"}, status=404)
        return self._send_json({"message": "Registro eliminado"})


if __name__ == "__main__":
    os.makedirs(PUBLIC_DIR, exist_ok=True)
    os.makedirs(DOCS_DIR, exist_ok=True)
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    init_db()
    init_templates()
    port = 8000
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"Servidor iniciado en http://localhost:{port}")
    server.serve_forever()
