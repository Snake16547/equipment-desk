from __future__ import annotations
import json, os, re, smtplib, ssl, tempfile, threading, time, secrets, hashlib
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

DATA_FILE = Path(os.getenv("DATA_FILE", "/data/equipment.json"))
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
SESSION_SECRET = os.getenv("SESSION_SECRET", "")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").lower() == "true"
APP_TITLE = os.getenv("APP_TITLE", "Equipment Desk")
APP_VERSION = os.getenv("APP_VERSION", "dev")

if len(SESSION_SECRET) < 32:
    raise RuntimeError("SESSION_SECRET must be at least 32 characters. Set it in .env.")
if not ADMIN_PASSWORD:
    raise RuntimeError("Set ADMIN_PASSWORD in .env before starting the application.")

app = FastAPI(title=APP_TITLE, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    SessionMiddleware, secret_key=SESSION_SECRET, session_cookie="equipment_admin",
    same_site="strict", https_only=COOKIE_SECURE, max_age=8 * 60 * 60
)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
db_lock = threading.RLock()
attempts = {}
RATE_WINDOW = 300
MAX_LOGIN_ATTEMPTS = 8

@app.get("/api/version")
def app_version():
    return {"version": APP_VERSION}

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def initial_db():
    return {
        "schema_version": 2,
        "people": [],
        "equipment": [],
        "loans": [],
        "activities": [],
        "settings": {
            "admin_password_hash": None,
            "smtp": {
                "host": "", "port": 587, "security": "starttls", "username": "",
                "password": "", "sender_name": "Equipment Desk", "sender_email": "",
                "recipients": []
            },
            "notifications": {
                "checkout": True, "checkin": True, "equipment_added": False,
                "equipment_updated": False, "equipment_deleted": False,
                "manual_adjustment": False
            },
        }
    }

def migrate_db(db):
    """Upgrade legacy databases without discarding loan history."""
    if db.get("schema_version", 1) < 2:
        db.setdefault("people", [])
        for item in db.get("equipment", []):
            if not str(item.get("category", "")).strip():
                item["category"] = "Uncategorized"
        db["schema_version"] = 2
        return True
    db.setdefault("people", [])
    return False

def read_db():
    with db_lock:
        if not DATA_FILE.exists():
            DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
            write_db(initial_db())
        try:
            db = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            if migrate_db(db):
                backup = DATA_FILE.with_name(DATA_FILE.name + ".v1-backup")
                if not backup.exists():
                    import shutil
                    shutil.copy2(DATA_FILE, backup)
                write_db(db)
            return db
        except (json.JSONDecodeError, OSError) as e:
            raise HTTPException(500, "The equipment data file could not be read. Restore a valid backup.") from e

def write_db(data):
    with db_lock:
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="equipment-", suffix=".tmp", dir=str(DATA_FILE.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, DATA_FILE)
            try:
                os.chmod(DATA_FILE, 0o600)
            except OSError:
                pass
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

def password_hash(password: str):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310000)
    import base64
    return base64.b64encode(salt + digest).decode()

def verify_hash(password, encoded):
    import base64, hmac
    try:
        raw = base64.b64decode(encoded)
        salt, expected = raw[:16], raw[16:]
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310000)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False

def is_admin(request: Request):
    return bool(request.session.get("admin"))

def require_admin(request: Request):
    if not is_admin(request):
        raise HTTPException(401, "Admin login required")
    return True

def clean_text(value, maxlen=120):
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    if not value or len(value) > maxlen:
        raise HTTPException(422, f"Please enter a value up to {maxlen} characters.")
    return value

def record_activity(db, kind, details):
    db["activities"].append({"id": secrets.token_hex(8), "type": kind, "timestamp": now(), **details})

def send_notification(db, event, subject, lines):
    settings = db.get("settings", {})
    if not settings.get("notifications", {}).get(event):
        return
    smtp = settings.get("smtp", {})
    recipients = [x.strip() for x in smtp.get("recipients", []) if x.strip()]
    if not smtp.get("host") or not smtp.get("sender_email") or not recipients:
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f'{smtp.get("sender_name") or "Equipment Desk"} <{smtp["sender_email"]}>'
    msg["To"] = ", ".join(recipients)
    msg.set_content("\n".join(lines))
    security = smtp.get("security", "starttls")
    port = int(smtp.get("port") or 587)
    try:
        if security == "ssl":
            server = smtplib.SMTP_SSL(smtp["host"], port, timeout=12, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(smtp["host"], port, timeout=12)
        with server:
            server.ehlo()
            if security == "starttls":
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
            if smtp.get("username"):
                server.login(smtp["username"], smtp.get("password", ""))
            server.send_message(msg)
    except Exception as exc:
        # Email failures must not undo a recorded checkout/return.
        print(f"SMTP notification failed: {type(exc).__name__}: {exc}", flush=True)

class Person(BaseModel):
    first_name: str = Field(min_length=1, max_length=60)
    last_name: str = Field(min_length=1, max_length=60)
    phone: str = Field(min_length=5, max_length=40)
    project: str = Field(default="", max_length=120)

class CheckoutItem(BaseModel):
    equipment_id: str
    quantity: int = Field(ge=1, le=500)

class CheckoutRequest(Person):
    items: list[CheckoutItem] = Field(min_length=1, max_length=50)

class ReturnRequest(Person):
    loan_ids: list[str] = Field(min_length=1, max_length=100)

class EquipmentInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=80)
    tracking: str = Field(pattern="^(individual|quantity)$")
    total_quantity: int = Field(ge=1, le=10000)
    notes: str = Field(default="", max_length=500)

class SavedPersonInput(Person):
    pass

class ManualReturnItem(BaseModel):
    loan_id: str
    quantity: int = Field(ge=1, le=10000)

class ManualReturnRequest(BaseModel):
    items: list[ManualReturnItem] = Field(min_length=1, max_length=100)

class ManualCheckoutRequest(CheckoutRequest):
    pass

class SMTPInput(BaseModel):
    host: str = Field(default="", max_length=255)
    port: int = Field(default=587, ge=1, le=65535)
    security: str = Field(pattern="^(none|starttls|ssl)$")
    username: str = Field(default="", max_length=255)
    password: str = Field(default="", max_length=500)
    sender_name: str = Field(default="Equipment Desk", max_length=120)
    sender_email: str = Field(default="", max_length=255)
    recipients: list[str] = Field(default_factory=list, max_length=30)

class AdminSettings(BaseModel):
    smtp: SMTPInput
    notifications: dict[str, bool]

class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=200)

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet, noimageindex"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    return response

@app.get("/")
def kiosk():
    return FileResponse("app/static/index.html")

@app.get("/admin")
def admin_page():
    return FileResponse("app/static/admin.html")

@app.get("/robots.txt")
def robots():
    return Response("User-agent: *\nDisallow: /\n", media_type="text/plain")

@app.get("/api/public/inventory")
def public_inventory():
    db = read_db()
    available = []
    for e in db["equipment"]:
        checked = sum(x["quantity_out"] - x["quantity_returned"] for x in db["loans"] if x["equipment_id"] == e["id"] and x["status"] == "out")
        available.append({
            "id": e["id"], "name": e["name"], "category": e.get("category", "Uncategorized"),
            "tracking": e["tracking"], "available": max(0, e["total_quantity"] - checked),
            "total": e["total_quantity"]
        })
    return available

@app.get("/api/public/people")
def public_people():
    db = read_db()
    # Phone numbers are not published to anonymous visitors.
    return [{"id": x["id"], "first_name": x["first_name"], "last_name": x["last_name"]}
            for x in db["people"]]

@app.post("/api/public/people/{person_id}/details")
def public_person_details(person_id: str):
    # A public kiosk cannot keep saved phone numbers secret from a determined user.
    # This convenience endpoint deliberately reveals details only after selection.
    db = read_db()
    person = next((x for x in db["people"] if x["id"] == person_id), None)
    if not person:
        raise HTTPException(404, "Saved person not found")
    return {k: person.get(k, "") for k in ("first_name", "last_name", "phone", "project")}

@app.post("/api/public/checkout")
def checkout(body: CheckoutRequest):
    return perform_checkout(body, "kiosk")

def perform_checkout(body: CheckoutRequest, actor: str):
    with db_lock:
        db = read_db()
        first, last = clean_text(body.first_name, 60), clean_text(body.last_name, 60)
        phone = clean_text(body.phone, 40)
        person = {"first_name": first, "last_name": last, "phone": phone, "project": (body.project or "").strip()[:120]}
        requested = {}
        for item in body.items:
            requested[item.equipment_id] = requested.get(item.equipment_id, 0) + item.quantity
        created = []
        for eid, qty in requested.items():
            equipment = next((e for e in db["equipment"] if e["id"] == eid), None)
            if not equipment:
                raise HTTPException(404, "An equipment item could not be found. Refresh and try again.")
            if equipment["tracking"] == "individual" and qty != 1:
                raise HTTPException(422, f'{equipment["name"]} is tracked individually. Select one at a time.')
            checked = sum(x["quantity_out"] - x["quantity_returned"] for x in db["loans"] if x["equipment_id"] == eid and x["status"] == "out")
            if qty > equipment["total_quantity"] - checked:
                raise HTTPException(409, f'Not enough available: {equipment["name"]}. Refresh and try again.')
            loan = {
                "id": secrets.token_hex(8), "equipment_id": eid, "equipment_name": equipment["name"],
                "quantity_out": qty, "quantity_returned": 0, "status": "out",
                **person, "checkout_at": now(), "return_at": None
            }
            db["loans"].append(loan)
            created.append(loan)
        record_activity(db, "admin_checkout" if actor == "admin" else "checkout", {"actor": actor, "person": f"{first} {last}", "phone": phone, "project": person["project"],
                                         "items": [{"name": x["equipment_name"], "quantity": x["quantity_out"]} for x in created]})
        write_db(db)
        send_notification(db, "checkout", "Equipment checked out", [
            f"Person: {first} {last}", f"Phone: {phone}", f"Project: {person['project'] or '-'}",
            f"Time: {created[0]['checkout_at']}", "Items:",
            *[f"- {x['equipment_name']} x{x['quantity_out']}" for x in created]
        ])
        return {"ok": True, "message": "Checkout recorded. Thank you!"}

@app.post("/api/public/returns/search")
def return_search(body: Person):
    db = read_db()
    first, last = clean_text(body.first_name, 60), clean_text(body.last_name, 60)
    phone = re.sub(r"\D", "", body.phone or "")
    matches = []
    for loan in db["loans"]:
        if loan["status"] == "out" and loan["first_name"].casefold() == first.casefold() and loan["last_name"].casefold() == last.casefold() and re.sub(r"\D", "", loan["phone"]) == phone:
            matches.append({"loan_id": loan["id"], "equipment_name": loan["equipment_name"],
                            "quantity_out": loan["quantity_out"], "quantity_returned": loan["quantity_returned"],
                            "remaining": loan["quantity_out"] - loan["quantity_returned"]})
    return matches

@app.post("/api/public/returns")
def return_items(body: ReturnRequest):
    with db_lock:
        db = read_db()
        first, last = clean_text(body.first_name, 60), clean_text(body.last_name, 60)
        phone = re.sub(r"\D", "", body.phone or "")
        selected = []
        for loan_id in set(body.loan_ids):
            loan = next((x for x in db["loans"] if x["id"] == loan_id and x["status"] == "out"), None)
            if loan and loan["first_name"].casefold() == first.casefold() and loan["last_name"].casefold() == last.casefold() and re.sub(r"\D", "", loan["phone"]) == phone:
                selected.append(loan)
        if not selected:
            raise HTTPException(404, "No matching outstanding equipment was found.")
        returned = []
        for loan in selected:
            previous_returned = loan["quantity_returned"]
            loan["quantity_returned"] = loan["quantity_out"]
            loan["status"] = "returned"
            loan["return_at"] = now()
            returned.append({"name": loan["equipment_name"], "quantity": loan["quantity_out"] - previous_returned})
        record_activity(db, "checkin", {"person": f"{first} {last}", "phone": body.phone, "items": returned})
        write_db(db)
        send_notification(db, "checkin", "Equipment returned", [
            f"Person: {first} {last}", f"Phone: {body.phone}", f"Time: {now()}", "Items:",
            *[f"- {x['name']} x{x['quantity']}" for x in returned]
        ])
        return {"ok": True, "message": "Return recorded. Thank you!"}

@app.post("/api/admin/login")
def login(request: Request, response: Response, body: dict):
    with db_lock:
        ip = request.client.host if request.client else "unknown"
        current = [t for t in attempts.get(ip, []) if time.time() - t < RATE_WINDOW]
        if len(current) >= MAX_LOGIN_ATTEMPTS:
            raise HTTPException(429, "Too many login attempts. Try again in five minutes.")
        password = str(body.get("password", ""))
        db = read_db()
        stored_hash = db["settings"].get("admin_password_hash")
        valid = verify_hash(password, stored_hash) if stored_hash else secrets.compare_digest(password, ADMIN_PASSWORD)
        if not valid:
            current.append(time.time())
            attempts[ip] = current
            raise HTTPException(401, "Incorrect password.")
        attempts.pop(ip, None)
        request.session["admin"] = True
        if not stored_hash:
            db["settings"]["admin_password_hash"] = password_hash(ADMIN_PASSWORD)
            write_db(db)
        return {"ok": True}

@app.post("/api/admin/logout")
def logout(request: Request, _=Depends(require_admin)):
    request.session.clear()
    return {"ok": True}

@app.get("/api/admin/me")
def admin_me(request: Request):
    return {"authenticated": is_admin(request)}

@app.get("/api/admin/data")
def admin_data(_=Depends(require_admin)):
    db = read_db()
    # Never return SMTP password in ordinary dashboard data.
    safe_settings = json.loads(json.dumps(db["settings"]))
    safe_settings.get("smtp", {}).pop("password", None)
    equipment = []
    for e in db["equipment"]:
        checked = sum(x["quantity_out"] - x["quantity_returned"] for x in db["loans"] if x["equipment_id"] == e["id"] and x["status"] == "out")
        equipment.append({**e, "available": e["total_quantity"] - checked, "checked_out": checked})
    return {"equipment": equipment, "loans": db["loans"], "activities": list(reversed(db["activities"])),
            "settings": safe_settings, "people": db["people"]}

@app.post("/api/admin/equipment")
def add_equipment(body: EquipmentInput, _=Depends(require_admin)):
    with db_lock:
        db = read_db()
        item = {"id": "EQ-" + secrets.token_hex(4).upper(), **body.model_dump()}
        item["category"] = clean_text(item["category"], 80)
        if item["tracking"] == "individual" and item["total_quantity"] != 1:
            raise HTTPException(422, "Individual equipment entries must have quantity 1. Create one entry per item.")
        db["equipment"].append(item)
        record_activity(db, "equipment_added", {"equipment": item["name"], "quantity": item["total_quantity"]})
        write_db(db)
        send_notification(db, "equipment_added", "Equipment added", [f"Equipment: {item['name']}", f"Quantity: {item['total_quantity']}"])
        return item

@app.put("/api/admin/equipment/{eid}")
def update_equipment(eid: str, body: EquipmentInput, _=Depends(require_admin)):
    with db_lock:
        db = read_db()
        item = next((e for e in db["equipment"] if e["id"] == eid), None)
        if not item:
            raise HTTPException(404, "Equipment not found.")
        checked = sum(x["quantity_out"] - x["quantity_returned"] for x in db["loans"] if x["equipment_id"] == eid and x["status"] == "out")
        if body.total_quantity < checked:
            raise HTTPException(409, f"Quantity cannot be lower than the {checked} currently checked out.")
        if body.tracking == "individual" and body.total_quantity != 1:
            raise HTTPException(422, "Individual equipment entries must have quantity 1.")
        item.update(body.model_dump())
        item["category"] = clean_text(item["category"], 80)
        record_activity(db, "equipment_updated", {"equipment": item["name"]})
        write_db(db)
        send_notification(db, "equipment_updated", "Equipment updated", [f"Equipment: {item['name']}"])
        return item

@app.delete("/api/admin/equipment/{eid}")
def delete_equipment(eid: str, _=Depends(require_admin)):
    with db_lock:
        db = read_db()
        item = next((e for e in db["equipment"] if e["id"] == eid), None)
        if not item:
            raise HTTPException(404, "Equipment not found.")
        if any(x["equipment_id"] == eid and x["status"] == "out" for x in db["loans"]):
            raise HTTPException(409, "Cannot delete equipment while any quantity is checked out.")
        db["equipment"].remove(item)
        record_activity(db, "equipment_deleted", {"equipment": item["name"]})
        write_db(db)
        send_notification(db, "equipment_deleted", "Equipment deleted", [f"Equipment: {item['name']}"])
        return {"ok": True}

@app.put("/api/admin/settings")
def save_settings(body: AdminSettings, _=Depends(require_admin)):
    with db_lock:
        db = read_db()
        old_password = db["settings"]["smtp"].get("password", "")
        smtp = body.smtp.model_dump()
        if not smtp["password"]:
            smtp["password"] = old_password
        smtp["recipients"] = [x.strip() for x in smtp["recipients"] if x.strip()]
        db["settings"]["smtp"] = smtp
        db["settings"]["notifications"] = body.notifications
        write_db(db)
        return {"ok": True}

@app.post("/api/admin/test-email")
def test_email(_=Depends(require_admin)):
    db = read_db()
    smtp = db["settings"]["smtp"]
    if not smtp.get("host") or not smtp.get("sender_email") or not smtp.get("recipients"):
        raise HTTPException(422, "Configure SMTP host, sender address and at least one recipient first.")
    # Test is sent regardless of event notification toggles.
    test_db = json.loads(json.dumps(db))
    test_db["settings"]["notifications"]["checkout"] = True
    send_notification(test_db, "checkout", "Equipment Desk – SMTP test", ["This is a test email from Equipment Desk."])
    return {"ok": True, "message": "Test email queued for delivery. Check the application log if it does not arrive."}

@app.post("/api/admin/password")
def change_password(body: PasswordChange, request: Request, _=Depends(require_admin)):
    with db_lock:
        db = read_db()
        stored_hash = db["settings"].get("admin_password_hash")
        valid = verify_hash(body.current_password, stored_hash) if stored_hash else secrets.compare_digest(body.current_password, ADMIN_PASSWORD)
        if not valid:
            raise HTTPException(401, "Current password is incorrect.")
        db["settings"]["admin_password_hash"] = password_hash(body.new_password)
        write_db(db)
        request.session.clear()
        request.session["admin"] = True
        return {"ok": True}

@app.get("/api/admin/export/json")
def export_json(_=Depends(require_admin)):
    return FileResponse(DATA_FILE, media_type="application/json", filename="equipment-desk-backup.json")

@app.get("/api/admin/export/csv")
def export_csv(_=Depends(require_admin)):
    import csv, io
    db = read_db()
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["activity_id", "timestamp", "type", "person", "phone", "project", "equipment", "quantity"])
    for a in db["activities"]:
        items = a.get("items") or [{"name": a.get("equipment", ""), "quantity": a.get("quantity", "")}]
        for item in items:
            writer.writerow([a.get("id"), a.get("timestamp"), a.get("type"), a.get("person"), a.get("phone"),
                             a.get("project"), item.get("name", ""), item.get("quantity", "")])
    from fastapi.responses import Response
    return Response(out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="equipment-desk-activity.csv"'})

@app.post("/api/admin/adjust/{eid}")
def adjust_quantity(eid: str, body: dict, _=Depends(require_admin)):
    with db_lock:
        db = read_db()
        item = next((e for e in db["equipment"] if e["id"] == eid), None)
        if not item:
            raise HTTPException(404, "Equipment not found.")
        quantity = int(body.get("total_quantity", -1))
        checked = sum(x["quantity_out"] - x["quantity_returned"] for x in db["loans"] if x["equipment_id"] == eid and x["status"] == "out")
        if quantity < max(1, checked) or quantity > 10000:
            raise HTTPException(422, "Quantity must be at least the amount currently checked out.")
        item["total_quantity"] = quantity
        record_activity(db, "manual_adjustment", {"equipment": item["name"], "quantity": quantity, "note": str(body.get("note", ""))[:250]})
        write_db(db)
        send_notification(db, "manual_adjustment", "Inventory adjusted", [f"Equipment: {item['name']}", f"New total: {quantity}", f"Note: {body.get('note','')}"])
        return {"ok": True}


@app.post("/api/admin/people")
def add_person(body: SavedPersonInput, _=Depends(require_admin)):
    with db_lock:
        db = read_db()
        person = {"id": "P-" + secrets.token_hex(5), **body.model_dump()}
        person["first_name"] = clean_text(person["first_name"], 60)
        person["last_name"] = clean_text(person["last_name"], 60)
        person["phone"] = clean_text(person["phone"], 40)
        db["people"].append(person)
        record_activity(db, "person_added", {"person": person["first_name"] + " " + person["last_name"]})
        write_db(db)
        return person

@app.put("/api/admin/people/{pid}")
def update_person(pid: str, body: SavedPersonInput, _=Depends(require_admin)):
    with db_lock:
        db = read_db()
        person = next((p for p in db["people"] if p["id"] == pid), None)
        if not person:
            raise HTTPException(404, "Person not found")
        person.update(body.model_dump())
        for key, limit in (("first_name", 60), ("last_name", 60), ("phone", 40)):
            person[key] = clean_text(person[key], limit)
        record_activity(db, "person_updated", {"person": person["first_name"] + " " + person["last_name"]})
        write_db(db)
        return person

@app.delete("/api/admin/people/{pid}")
def delete_person(pid: str, _=Depends(require_admin)):
    with db_lock:
        db = read_db()
        person = next((p for p in db["people"] if p["id"] == pid), None)
        if not person:
            raise HTTPException(404, "Person not found")
        db["people"].remove(person)
        record_activity(db, "person_deleted", {"person": person["first_name"] + " " + person["last_name"]})
        write_db(db)
        return {"ok": True}

@app.post("/api/admin/checkout")
def admin_checkout(body: ManualCheckoutRequest, _=Depends(require_admin)):
    return perform_checkout(CheckoutRequest(**body.model_dump()), "admin")

@app.post("/api/admin/returns")
def admin_returns(body: ManualReturnRequest, _=Depends(require_admin)):
    with db_lock:
        db = read_db()
        requested = {}
        for item in body.items:
            requested[item.loan_id] = requested.get(item.loan_id, 0) + item.quantity
        selected = []
        for loan_id, qty in requested.items():
            loan = next((x for x in db["loans"] if x["id"] == loan_id and x["status"] == "out"), None)
            if not loan:
                raise HTTPException(404, "An outstanding loan could not be found")
            remaining = loan["quantity_out"] - loan["quantity_returned"]
            if qty > remaining:
                raise HTTPException(409, "Return quantity exceeds outstanding quantity")
            selected.append((loan, qty))
        returned = []
        for loan, qty in selected:
            loan["quantity_returned"] += qty
            if loan["quantity_returned"] == loan["quantity_out"]:
                loan["status"] = "returned"
                loan["return_at"] = now()
            returned.append({"name": loan["equipment_name"], "quantity": qty})
        record_activity(db, "admin_checkin", {"actor": "admin", "items": returned,
                        "note": "Manual return recorded by administrator"})
        write_db(db)
        send_notification(db, "checkin", "Equipment returned by administrator", [
            "Manual return", *[f"- {x['name']} x{x['quantity']}" for x in returned]])
        return {"ok": True, "message": "Manual return recorded"}
