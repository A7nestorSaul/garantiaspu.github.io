import json
import re
import sqlite3
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

ROOT = Path(__file__).parent
PUBLIC_DIR = ROOT / 'public'
DATA_DIR = ROOT / 'data'
DB_PATH = DATA_DIR / 'garantias.db'
DOCS_DIR = DATA_DIR / 'documents'
HOST = '0.0.0.0'
PORT = 3000
VALID_STATUS = {'Pendiente', 'En proceso', 'Recuperado', 'Pagado'}

DATA_DIR.mkdir(exist_ok=True)
DOCS_DIR.mkdir(exist_ok=True)


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referencia TEXT NOT NULL,
                naviera TEXT NOT NULL,
                bl TEXT NOT NULL,
                total REAL NOT NULL,
                fecha_recuperacion TEXT NOT NULL,
                estatus TEXT NOT NULL DEFAULT 'Pendiente',
                created_at TEXT NOT NULL
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS payment_validations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_id INTEGER NOT NULL,
                concepto TEXT NOT NULL,
                confirmed_at TEXT NOT NULL,
                FOREIGN KEY(record_id) REFERENCES records(id)
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS document_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS generated_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_id INTEGER NOT NULL,
                template_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(record_id) REFERENCES records(id),
                FOREIGN KEY(template_id) REFERENCES document_templates(id)
            )
            '''
        )


def db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def is_overdue(fecha_recuperacion):
    try:
        target = datetime.strptime(fecha_recuperacion, '%Y-%m-%d').date()
    except ValueError:
        return False
    return target < datetime.utcnow().date()


def is_due_soon(fecha_recuperacion, days=3):
    try:
        target = datetime.strptime(fecha_recuperacion, '%Y-%m-%d').date()
    except ValueError:
        return False
    delta = (target - datetime.utcnow().date()).days
    return 0 <= delta <= days


def apply_tracking_rule(conn, record):
    current_status = record['estatus']
    overdue = is_overdue(record['fecha_recuperacion'])
    should_mark_pending = overdue and current_status != 'Pagado'

    if should_mark_pending and current_status != 'Pendiente':
        conn.execute('UPDATE records SET estatus = ? WHERE id = ?', ('Pendiente', record['id']))
        record['estatus'] = 'Pendiente'

    record['is_overdue_pending'] = bool(overdue and record['estatus'] == 'Pendiente')
    return record


def fill_template(template_content, record):
    def replace(match):
        field = match.group(1).strip()
        return str(record.get(field, ''))

    return re.sub(r'{{\s*([^}]+)\s*}}', replace, template_content)


def create_simple_pdf(content, output_path):
    lines = content.splitlines() or ['']
    page_lines = lines[:45]
    stream_lines = ['BT', '/F1 11 Tf', '50 790 Td', '14 TL']
    for idx, line in enumerate(page_lines):
        safe_line = line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        if idx == 0:
            stream_lines.append(f'({safe_line}) Tj')
        else:
            stream_lines.append(f'T* ({safe_line}) Tj')
    stream_lines.append('ET')
    stream = '\n'.join(stream_lines).encode('latin-1', errors='replace')

    objects = []

    def add_object(obj_bytes):
        objects.append(obj_bytes)

    add_object(b'1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n')
    add_object(b'2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n')
    add_object(
        b'3 0 obj\n'
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] '
        b'/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\n'
        b'endobj\n'
    )
    add_object(b'4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n')
    add_object(f'5 0 obj\n<< /Length {len(stream)} >>\nstream\n'.encode('latin-1') + stream + b'\nendstream\nendobj\n')

    pdf = bytearray(b'%PDF-1.4\n')
    xref_positions = [0]
    for obj in objects:
        xref_positions.append(len(pdf))
        pdf.extend(obj)

    xref_start = len(pdf)
    pdf.extend(f'xref\n0 {len(xref_positions)}\n'.encode('latin-1'))
    pdf.extend(b'0000000000 65535 f \n')
    for pos in xref_positions[1:]:
        pdf.extend(f'{pos:010d} 00000 n \n'.encode('latin-1'))

    pdf.extend(
        (
            f'trailer\n<< /Size {len(xref_positions)} /Root 1 0 R >>\n'
            f'startxref\n{xref_start}\n%%EOF\n'
        ).encode('latin-1')
    )

    output_path.write_bytes(pdf)


class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC_DIR), **kwargs)

    def _send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        length = int(self.headers.get('Content-Length', 0))
        raw = self.rfile.read(length) if length > 0 else b'{}'
        return json.loads(raw.decode('utf-8'))

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == '/':
            self.path = '/login.html'
            return super().do_GET()

        if path == '/api/records':
            params = parse_qs(parsed.query)
            naviera = (params.get('naviera') or [''])[0].strip()

            with db_connection() as conn:
                if naviera:
                    rows = conn.execute(
                        'SELECT * FROM records WHERE naviera = ? ORDER BY id DESC',
                        (naviera,),
                    ).fetchall()
                else:
                    rows = conn.execute('SELECT * FROM records ORDER BY id DESC').fetchall()

                records = [apply_tracking_rule(conn, dict(row)) for row in rows]
            return self._send_json(records)

        if path == '/api/documents/templates':
            with db_connection() as conn:
                rows = conn.execute('SELECT * FROM document_templates ORDER BY id DESC').fetchall()
            return self._send_json([dict(row) for row in rows])

        if path == '/api/documents':
            with db_connection() as conn:
                rows = conn.execute(
                    '''
                    SELECT gd.id, gd.record_id, gd.template_id, gd.filename, gd.created_at,
                           r.referencia, r.bl, dt.name AS template_name
                    FROM generated_documents gd
                    JOIN records r ON r.id = gd.record_id
                    JOIN document_templates dt ON dt.id = gd.template_id
                    ORDER BY gd.id DESC
                    '''
                ).fetchall()
            return self._send_json([dict(row) for row in rows])

        if path == '/api/reminders':
            with db_connection() as conn:
                rows = conn.execute('SELECT * FROM records ORDER BY id DESC').fetchall()
                records = [apply_tracking_rule(conn, dict(row)) for row in rows]

            overdue_pending = [r for r in records if r['is_overdue_pending']]
            due_soon = [r for r in records if r['estatus'] != 'Pagado' and is_due_soon(r['fecha_recuperacion'])]
            return self._send_json(
                {
                    'overdue_pending_count': len(overdue_pending),
                    'due_soon_count': len(due_soon),
                    'overdue_pending': overdue_pending[:10],
                    'due_soon': due_soon[:10],
                }
            )

        if path.startswith('/files/'):
            filename = Path(path.replace('/files/', '', 1)).name
            file_path = DOCS_DIR / filename
            if not file_path.exists():
                return self.send_error(HTTPStatus.NOT_FOUND)
            content = file_path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header('Content-Type', 'application/pdf')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path

        if path == '/api/login':
            data = self._read_json_body()
            username = (data.get('username') or '').strip()
            password = data.get('password') or ''

            if not username or not password:
                return self._send_json(
                    {'message': 'Usuario y contraseña son obligatorios.'},
                    status=HTTPStatus.BAD_REQUEST,
                )

            return self._send_json({'message': 'Login exitoso (simulado).', 'user': {'username': username}})

        if path == '/api/records':
            data = self._read_json_body()
            error = self._validate_payload(data)
            if error:
                return self._send_json({'message': error}, status=HTTPStatus.BAD_REQUEST)

            with db_connection() as conn:
                status_to_store = data['estatus']
                if is_overdue(data['fecha_recuperacion']) and status_to_store != 'Pagado':
                    status_to_store = 'Pendiente'

                cursor = conn.execute(
                    '''
                    INSERT INTO records (referencia, naviera, bl, total, fecha_recuperacion, estatus, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        data['referencia'].strip(),
                        data['naviera'].strip(),
                        data['bl'].strip(),
                        float(data['total']),
                        data['fecha_recuperacion'],
                        status_to_store,
                        datetime.utcnow().isoformat(timespec='seconds'),
                    ),
                )
                record = conn.execute('SELECT * FROM records WHERE id = ?', (cursor.lastrowid,)).fetchone()
                normalized_record = apply_tracking_rule(conn, dict(record))

            return self._send_json(normalized_record, status=HTTPStatus.CREATED)

        if path == '/api/records/bulk':
            data = self._read_json_body()
            records = data.get('records') if isinstance(data, dict) else None
            if not isinstance(records, list) or not records:
                return self._send_json(
                    {'message': 'Debes enviar una lista de registros.'},
                    status=HTTPStatus.BAD_REQUEST,
                )

            inserted = []
            duplicates = []
            errors = []
            seen_in_file = {
                'referencia': set(),
                'naviera': set(),
                'bl': set(),
            }

            with db_connection() as conn:
                for index, record_data in enumerate(records, start=1):
                    error = self._validate_payload(record_data)
                    if error:
                        errors.append({'row': index, 'message': error})
                        continue

                    normalized = {
                        'referencia': str(record_data['referencia']).strip(),
                        'naviera': str(record_data['naviera']).strip(),
                        'bl': str(record_data['bl']).strip(),
                        'total': float(record_data['total']),
                        'fecha_recuperacion': record_data['fecha_recuperacion'],
                        'estatus': record_data['estatus'],
                    }
                    if is_overdue(normalized['fecha_recuperacion']) and normalized['estatus'] != 'Pagado':
                        normalized['estatus'] = 'Pendiente'

                    duplicate_fields = []
                    for field in ('bl', 'naviera', 'referencia'):
                        value = normalized[field]
                        if value in seen_in_file[field]:
                            duplicate_fields.append(field)

                    if not duplicate_fields:
                        db_dupe = conn.execute(
                            '''
                            SELECT
                                (bl = ?) AS by_bl,
                                (naviera = ?) AS by_naviera,
                                (referencia = ?) AS by_referencia
                            FROM records
                            WHERE bl = ? OR naviera = ? OR referencia = ?
                            LIMIT 1
                            ''',
                            (
                                normalized['bl'],
                                normalized['naviera'],
                                normalized['referencia'],
                                normalized['bl'],
                                normalized['naviera'],
                                normalized['referencia'],
                            ),
                        ).fetchone()

                        if db_dupe:
                            if db_dupe['by_bl']:
                                duplicate_fields.append('bl')
                            if db_dupe['by_naviera']:
                                duplicate_fields.append('naviera')
                            if db_dupe['by_referencia']:
                                duplicate_fields.append('referencia')

                    if duplicate_fields:
                        duplicates.append({'row': index, 'fields': duplicate_fields, 'record': normalized})
                        continue

                    cursor = conn.execute(
                        '''
                        INSERT INTO records (referencia, naviera, bl, total, fecha_recuperacion, estatus, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ''',
                        (
                            normalized['referencia'],
                            normalized['naviera'],
                            normalized['bl'],
                            normalized['total'],
                            normalized['fecha_recuperacion'],
                            normalized['estatus'],
                            datetime.utcnow().isoformat(timespec='seconds'),
                        ),
                    )
                    created = conn.execute('SELECT * FROM records WHERE id = ?', (cursor.lastrowid,)).fetchone()
                    inserted.append(apply_tracking_rule(conn, dict(created)))

                    seen_in_file['referencia'].add(normalized['referencia'])
                    seen_in_file['naviera'].add(normalized['naviera'])
                    seen_in_file['bl'].add(normalized['bl'])

            return self._send_json(
                {
                    'inserted': inserted,
                    'duplicates': duplicates,
                    'errors': errors,
                    'summary': {
                        'received': len(records),
                        'inserted': len(inserted),
                        'duplicates': len(duplicates),
                        'errors': len(errors),
                    },
                },
                status=HTTPStatus.OK,
            )

        if path == '/api/payments/suggestions':
            data = self._read_json_body()
            concepts = data.get('concepts') if isinstance(data, dict) else None
            if not isinstance(concepts, list) or not concepts:
                return self._send_json(
                    {'message': 'Debes enviar una lista de conceptos.'},
                    status=HTTPStatus.BAD_REQUEST,
                )

            with db_connection() as conn:
                rows = conn.execute('SELECT * FROM records ORDER BY id DESC').fetchall()
                records = [dict(row) for row in rows]

            suggestions = []
            for concept in concepts:
                concept_text = str(concept).strip()
                if not concept_text:
                    continue

                concept_lower = concept_text.lower()
                matches = []
                for record in records:
                    bl = str(record['bl']).strip()
                    bl_lower = bl.lower()
                    if bl_lower and (bl_lower in concept_lower or concept_lower in bl_lower):
                        match = {
                            'record_id': record['id'],
                            'referencia': record['referencia'],
                            'naviera': record['naviera'],
                            'bl': bl,
                            'estatus': record['estatus'],
                        }
                        matches.append(match)

                suggestions.append(
                    {
                        'concepto': concept_text,
                        'matches': matches,
                    }
                )

            return self._send_json({'suggestions': suggestions})

        if path == '/api/payments/confirm':
            data = self._read_json_body()
            try:
                record_id = int(data.get('record_id'))
            except (TypeError, ValueError):
                return self._send_json({'message': 'record_id inválido.'}, status=HTTPStatus.BAD_REQUEST)

            concepto = str(data.get('concepto') or '').strip()
            if not concepto:
                return self._send_json({'message': 'concepto es obligatorio.'}, status=HTTPStatus.BAD_REQUEST)

            with db_connection() as conn:
                record = conn.execute('SELECT * FROM records WHERE id = ?', (record_id,)).fetchone()
                if not record:
                    return self._send_json({'message': 'Registro no encontrado.'}, status=HTTPStatus.NOT_FOUND)

                conn.execute(
                    '''
                    INSERT INTO payment_validations (record_id, concepto, confirmed_at)
                    VALUES (?, ?, ?)
                    ''',
                    (record_id, concepto, datetime.utcnow().isoformat(timespec='seconds')),
                )
                conn.execute('UPDATE records SET estatus = ? WHERE id = ?', ('Pagado', record_id))
                updated = conn.execute('SELECT * FROM records WHERE id = ?', (record_id,)).fetchone()
                normalized_record = apply_tracking_rule(conn, dict(updated))

            return self._send_json(
                {
                    'message': 'Pago validado correctamente.',
                    'record': normalized_record,
                }
            )

        if path == '/api/documents/templates':
            data = self._read_json_body()
            name = str(data.get('name') or '').strip()
            content = str(data.get('content') or '').strip()
            if not name or not content:
                return self._send_json(
                    {'message': 'name y content son obligatorios.'},
                    status=HTTPStatus.BAD_REQUEST,
                )

            with db_connection() as conn:
                cursor = conn.execute(
                    '''
                    INSERT INTO document_templates (name, content, created_at)
                    VALUES (?, ?, ?)
                    ''',
                    (name, content, datetime.utcnow().isoformat(timespec='seconds')),
                )
                created = conn.execute('SELECT * FROM document_templates WHERE id = ?', (cursor.lastrowid,)).fetchone()

            return self._send_json(dict(created), status=HTTPStatus.CREATED)

        if path == '/api/documents/generate':
            data = self._read_json_body()
            try:
                record_id = int(data.get('record_id'))
                template_id = int(data.get('template_id'))
            except (TypeError, ValueError):
                return self._send_json(
                    {'message': 'record_id y template_id deben ser numéricos.'},
                    status=HTTPStatus.BAD_REQUEST,
                )

            with db_connection() as conn:
                record = conn.execute('SELECT * FROM records WHERE id = ?', (record_id,)).fetchone()
                template = conn.execute('SELECT * FROM document_templates WHERE id = ?', (template_id,)).fetchone()
                if not record or not template:
                    return self._send_json(
                        {'message': 'Registro o plantilla no encontrados.'},
                        status=HTTPStatus.NOT_FOUND,
                    )

                record_data = dict(record)
                filled_content = fill_template(template['content'], record_data)
                filename = f'doc_{record_id}_{template_id}_{uuid4().hex}.pdf'
                output_path = DOCS_DIR / filename
                create_simple_pdf(filled_content, output_path)

                cursor = conn.execute(
                    '''
                    INSERT INTO generated_documents (record_id, template_id, filename, created_at)
                    VALUES (?, ?, ?, ?)
                    ''',
                    (record_id, template_id, filename, datetime.utcnow().isoformat(timespec='seconds')),
                )
                created = conn.execute('SELECT * FROM generated_documents WHERE id = ?', (cursor.lastrowid,)).fetchone()

            return self._send_json(
                {
                    'message': 'Documento generado.',
                    'document': dict(created),
                    'file_url': f'/files/{filename}',
                }
            )

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_PUT(self):
        path = urlparse(self.path).path
        if not path.startswith('/api/records/'):
            return self.send_error(HTTPStatus.NOT_FOUND)

        try:
            record_id = int(path.split('/')[-1])
        except ValueError:
            return self._send_json({'message': 'ID inválido.'}, status=HTTPStatus.BAD_REQUEST)

        data = self._read_json_body()
        error = self._validate_payload(data)
        if error:
            return self._send_json({'message': error}, status=HTTPStatus.BAD_REQUEST)

        with db_connection() as conn:
            status_to_store = data['estatus']
            if is_overdue(data['fecha_recuperacion']) and status_to_store != 'Pagado':
                status_to_store = 'Pendiente'

            cursor = conn.execute(
                '''
                UPDATE records
                SET referencia = ?, naviera = ?, bl = ?, total = ?, fecha_recuperacion = ?, estatus = ?
                WHERE id = ?
                ''',
                (
                    data['referencia'].strip(),
                    data['naviera'].strip(),
                    data['bl'].strip(),
                    float(data['total']),
                    data['fecha_recuperacion'],
                    status_to_store,
                    record_id,
                ),
            )
            if cursor.rowcount == 0:
                return self._send_json({'message': 'Registro no encontrado.'}, status=HTTPStatus.NOT_FOUND)

            record = conn.execute('SELECT * FROM records WHERE id = ?', (record_id,)).fetchone()
            normalized_record = apply_tracking_rule(conn, dict(record))

        return self._send_json(normalized_record)

    def do_DELETE(self):
        path = urlparse(self.path).path
        if not path.startswith('/api/records/'):
            return self.send_error(HTTPStatus.NOT_FOUND)

        try:
            record_id = int(path.split('/')[-1])
        except ValueError:
            return self._send_json({'message': 'ID inválido.'}, status=HTTPStatus.BAD_REQUEST)

        with db_connection() as conn:
            cursor = conn.execute('DELETE FROM records WHERE id = ?', (record_id,))

        if cursor.rowcount == 0:
            return self._send_json({'message': 'Registro no encontrado.'}, status=HTTPStatus.NOT_FOUND)

        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    @staticmethod
    def _validate_payload(data):
        required = ['referencia', 'naviera', 'bl', 'total', 'fecha_recuperacion', 'estatus']
        if any(data.get(field) in (None, '') for field in required):
            return 'Todos los campos son obligatorios.'

        try:
            float(data.get('total'))
        except (TypeError, ValueError):
            return 'El total debe ser numérico.'

        if data.get('estatus') not in VALID_STATUS:
            return 'Estatus inválido.'

        return None


def main():
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print(f'Servidor activo en http://localhost:{PORT}')
    server.serve_forever()


if __name__ == '__main__':
    main()
