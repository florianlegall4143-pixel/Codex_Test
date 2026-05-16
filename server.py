from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import json
import mimetypes
import os
import secrets
import sqlite3
import time
import zipfile
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse
from xml.etree import ElementTree


ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "cmms.sqlite"
SECRET_PATH = DATA_DIR / ".secret"
STATIC_DIR = ROOT / "static"

SESSION_MAX_AGE = 60 * 60 * 10
ROLES = {"Admin", "Manager", "Technician"}
ASSET_FIELDS = [
    "asset_id",
    "name",
    "location",
    "category",
    "status",
    "description",
    "make",
    "model",
    "serial_number",
    "supplier",
    "purchase_date",
    "install_date",
    "warranty_expiry",
    "criticality",
    "notes",
]
REQUIRED_ASSET_FIELDS = ["asset_id", "name", "location", "category", "status"]


def ensure_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(exist_ok=True)
    STATIC_DIR.mkdir(exist_ok=True)


def load_secret() -> bytes:
    ensure_dirs()
    if not SECRET_PATH.exists():
        SECRET_PATH.write_text(secrets.token_hex(32), encoding="utf-8")
    return SECRET_PATH.read_text(encoding="utf-8").strip().encode("utf-8")


SECRET = load_secret()


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def now() -> int:
    return int(time.time())


def iso_now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return f"pbkdf2_sha256${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def check_password(password: str, stored: str) -> bool:
    try:
        algo, salt_b64, digest_b64 = stored.split("$", 2)
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def sign(value: str) -> str:
    sig = hmac.new(SECRET, value.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{value}.{sig}"


def unsign(value: str) -> str | None:
    if "." not in value:
        return None
    raw, sig = value.rsplit(".", 1)
    expected = hmac.new(SECRET, raw.encode("utf-8"), hashlib.sha256).hexdigest()
    return raw if hmac.compare_digest(sig, expected) else None


def init_db() -> None:
    ensure_dirs()
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                role TEXT NOT NULL CHECK(role IN ('Admin', 'Manager', 'Technician')),
                password_hash TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT DEFAULT '',
                archived INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                archived INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS statuses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                archived INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS criticalities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                archived INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                location_id INTEGER NOT NULL,
                category_id INTEGER NOT NULL,
                status_id INTEGER NOT NULL,
                criticality_id INTEGER,
                description TEXT DEFAULT '',
                make TEXT DEFAULT '',
                model TEXT DEFAULT '',
                serial_number TEXT DEFAULT '',
                supplier TEXT DEFAULT '',
                purchase_date TEXT DEFAULT '',
                install_date TEXT DEFAULT '',
                warranty_expiry TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                archived INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(location_id) REFERENCES locations(id),
                FOREIGN KEY(category_id) REFERENCES categories(id),
                FOREIGN KEY(status_id) REFERENCES statuses(id),
                FOREIGN KEY(criticality_id) REFERENCES criticalities(id)
            );

            CREATE TABLE IF NOT EXISTS attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_id INTEGER NOT NULL,
                kind TEXT NOT NULL DEFAULT 'document',
                original_name TEXT NOT NULL,
                stored_name TEXT NOT NULL,
                content_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(asset_id) REFERENCES assets(id) ON DELETE CASCADE
            );
            """
        )
        migrate_db(conn)
        seed(conn)


def migrate_db(conn: sqlite3.Connection) -> None:
    attachment_columns = {row["name"] for row in conn.execute("PRAGMA table_info(attachments)").fetchall()}
    if "kind" not in attachment_columns:
        conn.execute("ALTER TABLE attachments ADD COLUMN kind TEXT NOT NULL DEFAULT 'document'")


def seed(conn: sqlite3.Connection) -> None:
    stamp = iso_now()
    for name, email, role, password in [
        ("Admin", "admin@example.com", "Admin", "admin123"),
        ("Manager", "manager@example.com", "Manager", "manager123"),
        ("Technician", "technician@example.com", "Technician", "technician123"),
    ]:
        if not conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            conn.execute(
                "INSERT INTO users (name, email, role, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (name, email, role, hash_password(password), stamp, stamp),
            )
    for table, values in {
        "locations": ["Workshop", "Yard", "Office"],
        "categories": ["Plant", "Equipment", "Vehicle", "Tool", "Electrical", "Building", "Plumbing", "Safety", "Other"],
        "statuses": ["Active", "Inactive", "Under Repair", "Disposed"],
        "criticalities": ["Low", "Medium", "High", "Critical"],
    }.items():
        for value in values:
            conn.execute(
                f"INSERT OR IGNORE INTO {table} (name, created_at, updated_at) VALUES (?, ?, ?)",
                (value, stamp, stamp),
            )


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row else None


def list_rows(conn: sqlite3.Connection, table: str) -> list[dict]:
    rows = conn.execute(f"SELECT * FROM {table} WHERE archived = 0 ORDER BY name COLLATE NOCASE").fetchall()
    return [dict(row) for row in rows]


def lookup_id(conn: sqlite3.Connection, table: str, name: str, create: bool = False) -> int | None:
    if not name:
        return None
    row = conn.execute(f"SELECT id FROM {table} WHERE LOWER(name) = LOWER(?) AND archived = 0", (name.strip(),)).fetchone()
    if row:
        return int(row["id"])
    if not create:
        return None
    stamp = iso_now()
    cur = conn.execute(
        f"INSERT INTO {table} (name, created_at, updated_at) VALUES (?, ?, ?)",
        (name.strip(), stamp, stamp),
    )
    return int(cur.lastrowid)


def asset_payload(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    asset = dict(row)
    asset["location"] = row["location_name"]
    asset["category"] = row["category_name"]
    asset["status"] = row["status_name"]
    asset["criticality"] = row["criticality_name"] or ""
    asset["photo_url"] = f"/uploads/{quote(row['photo_stored_name'])}" if row["photo_stored_name"] else ""
    return asset


ASSET_SELECT = """
SELECT a.*, l.name AS location_name, c.name AS category_name, s.name AS status_name, cr.name AS criticality_name,
(
    SELECT stored_name
    FROM attachments
    WHERE asset_id = a.id AND kind = 'asset_photo'
    ORDER BY created_at DESC, id DESC
    LIMIT 1
) AS photo_stored_name
FROM assets a
JOIN locations l ON l.id = a.location_id
JOIN categories c ON c.id = a.category_id
JOIN statuses s ON s.id = a.status_id
LEFT JOIN criticalities cr ON cr.id = a.criticality_id
"""


def parse_csv(text: str) -> list[dict]:
    sample = text[:2048]
    dialect = csv.Sniffer().sniff(sample) if "," in sample or "\t" in sample else csv.excel
    reader = csv.DictReader(text.splitlines(), dialect=dialect)
    return [{(k or "").strip().lower(): (v or "").strip() for k, v in row.items()} for row in reader]


def parse_xlsx(data: bytes) -> list[dict]:
    tmp = DATA_DIR / f"import-{secrets.token_hex(8)}.xlsx"
    tmp.write_bytes(data)
    try:
        with zipfile.ZipFile(tmp) as zf:
            shared = []
            if "xl/sharedStrings.xml" in zf.namelist():
                root = ElementTree.fromstring(zf.read("xl/sharedStrings.xml"))
                ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                for item in root.findall("x:si", ns):
                    shared.append("".join(t.text or "" for t in item.findall(".//x:t", ns)))
            sheet_name = next(name for name in zf.namelist() if name.startswith("xl/worksheets/sheet"))
            root = ElementTree.fromstring(zf.read(sheet_name))
            ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            rows = []
            for row in root.findall(".//x:row", ns):
                values = []
                for cell in row.findall("x:c", ns):
                    value = cell.find("x:v", ns)
                    text = value.text if value is not None else ""
                    if cell.attrib.get("t") == "s" and text:
                        text = shared[int(text)]
                    values.append(text.strip())
                rows.append(values)
            if not rows:
                return []
            headers = [h.strip().lower() for h in rows[0]]
            return [dict(zip(headers, [v.strip() for v in values])) for values in rows[1:]]
    finally:
        tmp.unlink(missing_ok=True)


def validate_import_rows(conn: sqlite3.Connection, rows: list[dict]) -> tuple[list[dict], list[dict]]:
    existing = {row["asset_id"].lower() for row in conn.execute("SELECT asset_id FROM assets").fetchall()}
    seen = set()
    valid, invalid = [], []
    for idx, row in enumerate(rows, start=2):
        clean = {field: (row.get(field) or "").strip() for field in ASSET_FIELDS}
        errors = []
        for field in REQUIRED_ASSET_FIELDS:
            if not clean[field]:
                errors.append(f"Missing {field}")
        key = clean["asset_id"].lower()
        if key and key in existing:
            errors.append("Asset ID already exists")
        if key and key in seen:
            errors.append("Duplicate asset ID in import")
        seen.add(key)
        target = invalid if errors else valid
        entry = {"row": idx, "errors": errors, **clean}
        target.append(entry)
    return valid, invalid


class App(BaseHTTPRequestHandler):
    server_version = "FLE-CMMS/0.1"

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def send_json(self, data, status: int = 200, headers: dict | None = None) -> None:
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, content_type: str | None = None) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def current_user(self) -> dict | None:
        jar = cookies.SimpleCookie(self.headers.get("Cookie"))
        session = jar.get("session")
        if not session:
            return None
        raw = unsign(session.value)
        if not raw:
            return None
        try:
            user_id, expires = raw.split(":", 1)
            if int(expires) < now():
                return None
        except ValueError:
            return None
        with db() as conn:
            row = conn.execute("SELECT id, name, email, role FROM users WHERE id = ? AND active = 1", (user_id,)).fetchone()
            return row_to_dict(row)

    def require_user(self) -> dict | None:
        user = self.current_user()
        if not user:
            self.send_json({"error": "Authentication required"}, 401)
            return None
        return user

    def require_admin(self) -> dict | None:
        user = self.require_user()
        if user and user["role"] != "Admin":
            self.send_json({"error": "Admin role required"}, 403)
            return None
        return user

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/" or path == "/login":
            self.send_file(STATIC_DIR / "index.html", "text/html")
            return
        if path.startswith("/static/"):
            self.send_file(STATIC_DIR / path.removeprefix("/static/"))
            return
        if path.startswith("/uploads/"):
            self.send_file(UPLOAD_DIR / unquote(path.removeprefix("/uploads/")))
            return
        if path.startswith("/api/"):
            self.handle_api_get(path, parse_qs(urlparse(self.path).query))
            return
        self.send_file(STATIC_DIR / "index.html", "text/html")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            self.handle_api_post(path)
            return
        self.send_error(404)

    def do_PUT(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            self.handle_api_put(path)
            return
        self.send_error(404)

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            self.handle_api_delete(path)
            return
        self.send_error(404)

    def handle_api_get(self, path: str, query: dict) -> None:
        if path == "/api/me":
            self.send_json({"user": self.current_user()})
            return
        user = self.require_user()
        if not user:
            return
        with db() as conn:
            if path == "/api/bootstrap":
                self.send_json({
                    "user": user,
                    "locations": list_rows(conn, "locations"),
                    "categories": list_rows(conn, "categories"),
                    "statuses": list_rows(conn, "statuses"),
                    "criticalities": list_rows(conn, "criticalities"),
                })
                return
            if path == "/api/dashboard":
                counts = {
                    "assets": conn.execute("SELECT COUNT(*) n FROM assets WHERE archived = 0").fetchone()["n"],
                    "locations": conn.execute("SELECT COUNT(*) n FROM locations WHERE archived = 0").fetchone()["n"],
                    "under_repair": conn.execute(
                        "SELECT COUNT(*) n FROM assets a JOIN statuses s ON s.id = a.status_id WHERE a.archived = 0 AND s.name = 'Under Repair'"
                    ).fetchone()["n"],
                    "disposed": conn.execute(
                        "SELECT COUNT(*) n FROM assets a JOIN statuses s ON s.id = a.status_id WHERE a.archived = 0 AND s.name = 'Disposed'"
                    ).fetchone()["n"],
                }
                self.send_json(counts)
                return
            if path == "/api/assets":
                self.list_assets(conn, query)
                return
            if path == "/api/assets/export":
                self.export_assets(conn, query)
                return
            if path.startswith("/api/assets/"):
                asset_id = int(path.split("/")[3])
                row = conn.execute(ASSET_SELECT + " WHERE a.id = ?", (asset_id,)).fetchone()
                if not row:
                    self.send_json({"error": "Asset not found"}, 404)
                    return
                attachments = conn.execute(
                    "SELECT * FROM attachments WHERE asset_id = ? AND kind = 'document' ORDER BY created_at DESC",
                    (asset_id,),
                ).fetchall()
                data = asset_payload(conn, row)
                data["attachments"] = [dict(a) for a in attachments]
                self.send_json(data)
                return
            for endpoint, table in [("/api/locations", "locations"), ("/api/categories", "categories"), ("/api/statuses", "statuses"), ("/api/criticalities", "criticalities")]:
                if path == endpoint:
                    self.send_json(list_rows(conn, table))
                    return
        self.send_error(404)

    def list_assets(self, conn: sqlite3.Connection, query: dict) -> None:
        clauses = ["a.archived = 0"]
        params = []
        search = (query.get("search", [""])[0] or "").strip()
        if search:
            clauses.append("(LOWER(a.asset_id) LIKE ? OR LOWER(a.name) LIKE ? OR LOWER(a.serial_number) LIKE ?)")
            like = f"%{search.lower()}%"
            params += [like, like, like]
        for key, column in {"location": "l.name", "category": "c.name", "status": "s.name"}.items():
            value = (query.get(key, [""])[0] or "").strip()
            if value:
                clauses.append(f"{column} = ?")
                params.append(value)
        sort = query.get("sort", ["asset_id"])[0]
        allowed = {"asset_id": "a.asset_id", "name": "a.name", "location": "l.name", "category": "c.name", "status": "s.name", "updated_at": "a.updated_at"}
        order = allowed.get(sort, "a.asset_id")
        rows = conn.execute(ASSET_SELECT + f" WHERE {' AND '.join(clauses)} ORDER BY {order} COLLATE NOCASE", params).fetchall()
        self.send_json([asset_payload(conn, row) for row in rows])

    def export_assets(self, conn: sqlite3.Connection, query: dict) -> None:
        rows = conn.execute(ASSET_SELECT + " WHERE a.archived = 0 ORDER BY a.asset_id COLLATE NOCASE").fetchall()
        out = []
        for row in rows:
            asset = asset_payload(conn, row)
            out.append({field: asset.get(field, "") for field in ASSET_FIELDS})
        text = csv_text(out, ASSET_FIELDS)
        body = text.encode("utf-8-sig")
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", 'attachment; filename="assets.csv"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_api_post(self, path: str) -> None:
        if path == "/api/login":
            payload = self.read_json()
            with db() as conn:
                row = conn.execute("SELECT * FROM users WHERE LOWER(email) = LOWER(?) AND active = 1", (payload.get("email", ""),)).fetchone()
            if not row or not check_password(payload.get("password", ""), row["password_hash"]):
                self.send_json({"error": "Invalid email or password"}, 401)
                return
            raw = f"{row['id']}:{now() + SESSION_MAX_AGE}"
            header = f"session={sign(raw)}; HttpOnly; Path=/; SameSite=Lax; Max-Age={SESSION_MAX_AGE}"
            self.send_json({"user": {"id": row["id"], "name": row["name"], "email": row["email"], "role": row["role"]}}, headers={"Set-Cookie": header})
            return
        if path == "/api/logout":
            self.send_json({"ok": True}, headers={"Set-Cookie": "session=; HttpOnly; Path=/; Max-Age=0"})
            return
        user = self.require_user()
        if not user:
            return
        with db() as conn:
            if path == "/api/assets":
                self.save_asset(conn, self.read_json())
                return
            if path == "/api/imports/assets/preview":
                self.preview_import(conn, self.read_json())
                return
            if path == "/api/imports/assets/commit":
                valid, invalid = validate_import_rows(conn, self.read_json().get("rows", []))
                if invalid:
                    self.send_json({"error": "Import contains invalid rows", "invalid": invalid}, 400)
                    return
                for row in valid:
                    self.save_asset_record(conn, row, create_lookups=True)
                self.send_json({"created": len(valid)})
                return
            if path.startswith("/api/assets/") and path.endswith("/attachments"):
                asset_id = int(path.split("/")[3])
                self.save_attachment(conn, asset_id, self.read_json(), kind="document")
                return
            if path.startswith("/api/assets/") and path.endswith("/photo"):
                asset_id = int(path.split("/")[3])
                self.save_attachment(conn, asset_id, self.read_json(), kind="asset_photo")
                return
            for endpoint, table in [("/api/locations", "locations"), ("/api/categories", "categories"), ("/api/statuses", "statuses"), ("/api/criticalities", "criticalities")]:
                if path == endpoint:
                    if not self.require_admin():
                        return
                    payload = self.read_json()
                    stamp = iso_now()
                    try:
                        cur = conn.execute(f"INSERT INTO {table} (name, description, created_at, updated_at) VALUES (?, ?, ?, ?)", (payload.get("name", "").strip(), payload.get("description", ""), stamp, stamp))
                        self.send_json({"id": cur.lastrowid}, 201)
                    except sqlite3.IntegrityError:
                        self.send_json({"error": "Name already exists"}, 400)
                    return
        self.send_error(404)

    def handle_api_put(self, path: str) -> None:
        user = self.require_user()
        if not user:
            return
        with db() as conn:
            if path.startswith("/api/assets/"):
                asset_id = int(path.split("/")[3])
                self.save_asset(conn, self.read_json(), asset_id)
                return
            for prefix, table in [("/api/locations/", "locations"), ("/api/categories/", "categories"), ("/api/statuses/", "statuses"), ("/api/criticalities/", "criticalities")]:
                if path.startswith(prefix):
                    if not self.require_admin():
                        return
                    item_id = int(path.removeprefix(prefix))
                    payload = self.read_json()
                    try:
                        conn.execute(f"UPDATE {table} SET name = ?, description = COALESCE(?, description), updated_at = ? WHERE id = ?", (payload.get("name", "").strip(), payload.get("description"), iso_now(), item_id))
                        self.send_json({"ok": True})
                    except sqlite3.IntegrityError:
                        self.send_json({"error": "Name already exists"}, 400)
                    return
        self.send_error(404)

    def handle_api_delete(self, path: str) -> None:
        user = self.require_user()
        if not user:
            return
        with db() as conn:
            if path.startswith("/api/assets/") and "/attachments/" in path:
                parts = path.split("/")
                attachment_id = int(parts[5])
                row = conn.execute("SELECT stored_name FROM attachments WHERE id = ?", (attachment_id,)).fetchone()
                if row:
                    (UPLOAD_DIR / row["stored_name"]).unlink(missing_ok=True)
                conn.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
                self.send_json({"ok": True})
                return
            if path.startswith("/api/assets/"):
                asset_id = int(path.split("/")[3])
                conn.execute("UPDATE assets SET archived = 1, updated_at = ? WHERE id = ?", (iso_now(), asset_id))
                self.send_json({"ok": True})
                return
            for prefix, table in [("/api/locations/", "locations"), ("/api/categories/", "categories"), ("/api/statuses/", "statuses"), ("/api/criticalities/", "criticalities")]:
                if path.startswith(prefix):
                    if not self.require_admin():
                        return
                    item_id = int(path.removeprefix(prefix))
                    conn.execute(f"UPDATE {table} SET archived = 1, updated_at = ? WHERE id = ?", (iso_now(), item_id))
                    self.send_json({"ok": True})
                    return
        self.send_error(404)

    def save_asset(self, conn: sqlite3.Connection, payload: dict, asset_pk: int | None = None) -> None:
        clean = {field: (payload.get(field) or "").strip() for field in ASSET_FIELDS}
        missing = [field for field in REQUIRED_ASSET_FIELDS if not clean[field]]
        if missing:
            self.send_json({"error": f"Missing required fields: {', '.join(missing)}"}, 400)
            return
        try:
            result_id = self.save_asset_record(conn, clean, asset_pk=asset_pk, create_lookups=False)
            self.send_json({"id": result_id})
        except ValueError as exc:
            self.send_json({"error": str(exc)}, 400)
        except sqlite3.IntegrityError:
            self.send_json({"error": "Asset ID already exists"}, 400)

    def save_asset_record(self, conn: sqlite3.Connection, data: dict, asset_pk: int | None = None, create_lookups: bool = False) -> int:
        location_id = lookup_id(conn, "locations", data["location"], create_lookups)
        category_id = lookup_id(conn, "categories", data["category"], create_lookups)
        status_id = lookup_id(conn, "statuses", data["status"], create_lookups)
        criticality_id = lookup_id(conn, "criticalities", data.get("criticality", ""), create_lookups) if data.get("criticality") else None
        if not location_id:
            raise ValueError("Unknown location")
        if not category_id:
            raise ValueError("Unknown category")
        if not status_id:
            raise ValueError("Unknown status")
        stamp = iso_now()
        values = (
            data["asset_id"], data["name"], location_id, category_id, status_id, criticality_id,
            data.get("description", ""), data.get("make", ""), data.get("model", ""), data.get("serial_number", ""),
            data.get("supplier", ""), data.get("purchase_date", ""), data.get("install_date", ""),
            data.get("warranty_expiry", ""), data.get("notes", ""), stamp,
        )
        if asset_pk:
            conn.execute(
                """
                UPDATE assets SET asset_id=?, name=?, location_id=?, category_id=?, status_id=?, criticality_id=?,
                description=?, make=?, model=?, serial_number=?, supplier=?, purchase_date=?, install_date=?,
                warranty_expiry=?, notes=?, updated_at=? WHERE id=?
                """,
                values + (asset_pk,),
            )
            return asset_pk
        cur = conn.execute(
            """
            INSERT INTO assets (asset_id, name, location_id, category_id, status_id, criticality_id,
            description, make, model, serial_number, supplier, purchase_date, install_date,
            warranty_expiry, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values[:-1] + (stamp, stamp),
        )
        return int(cur.lastrowid)

    def save_attachment(self, conn: sqlite3.Connection, asset_id: int, payload: dict, kind: str) -> None:
        row = conn.execute("SELECT id FROM assets WHERE id = ? AND archived = 0", (asset_id,)).fetchone()
        if not row:
            self.send_json({"error": "Asset not found"}, 404)
            return
        name = Path(payload.get("name", "attachment")).name
        content_type = payload.get("content_type") or "application/octet-stream"
        if kind == "asset_photo" and not content_type.startswith("image/"):
            self.send_json({"error": "Asset picture must be an image file"}, 400)
            return
        data = base64.b64decode(payload.get("data", ""))
        stored = f"{asset_id}-{secrets.token_hex(10)}-{name}"
        if kind == "asset_photo":
            previous = conn.execute(
                "SELECT stored_name FROM attachments WHERE asset_id = ? AND kind = 'asset_photo'",
                (asset_id,),
            ).fetchall()
            for item in previous:
                (UPLOAD_DIR / item["stored_name"]).unlink(missing_ok=True)
            conn.execute("DELETE FROM attachments WHERE asset_id = ? AND kind = 'asset_photo'", (asset_id,))
        (UPLOAD_DIR / stored).write_bytes(data)
        cur = conn.execute(
            "INSERT INTO attachments (asset_id, kind, original_name, stored_name, content_type, size_bytes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (asset_id, kind, name, stored, content_type, len(data), iso_now()),
        )
        self.send_json({"id": cur.lastrowid, "stored_name": stored, "photo_url": f"/uploads/{quote(stored)}"}, 201)

    def preview_import(self, conn: sqlite3.Connection, payload: dict) -> None:
        name = payload.get("name", "")
        raw = base64.b64decode(payload.get("data", ""))
        try:
            if name.lower().endswith(".xlsx"):
                rows = parse_xlsx(raw)
            else:
                rows = parse_csv(raw.decode("utf-8-sig"))
            valid, invalid = validate_import_rows(conn, rows)
            self.send_json({"valid": valid, "invalid": invalid, "total": len(rows)})
        except Exception as exc:
            self.send_json({"error": f"Could not parse file: {exc}"}, 400)


def csv_text(rows: list[dict], fields: list[str]) -> str:
    from io import StringIO

    out = StringIO()
    writer = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def main() -> None:
    init_db()
    host, port = "localhost", 8000
    print(f"FLE CMMS Asset Database running at http://{host}:{port}")
    print("Login: admin@example.com / admin123")
    ThreadingHTTPServer((host, port), App).serve_forever()


if __name__ == "__main__":
    main()
