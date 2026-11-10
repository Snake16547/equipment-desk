# Equipment Desk v0.2.0 (beta)

A minimal self-hosted equipment checkout and check-in kiosk. FastAPI backend, plain HTML/CSS/JS frontend, one readable JSON database.

## Features

- Public checkout and return kiosk; no user account required.
- Category-first equipment browsing; category required when adding/editing equipment.
- Admin-managed regular borrowers, selectable in the kiosk; visitors can still enter details manually.
- Admin-assisted checkout and partial/full returns.
- Individually tracked equipment and quantity-based stock.
- Password-protected `/admin`, SMTP notifications, activity CSV and full JSON export.
- Noindex headers and robots.txt (not access control).

## Storage and security

- All data and SMTP credentials are in `data/equipment.json`. Restrict filesystem access; encrypt backups. Do not publish real data or `.env`.
- **Privacy warning:** the public saved-people picker reveals borrower names, and the selection API supplies their saved phone numbers. Do not enable predefined people for a public internet-facing deployment without additional kiosk access control. A private LAN, VPN, or reverse-proxy access restriction is recommended.
- Anyone knowing a borrower's name and phone can look up and return loans. This is convenience identification, not authentication.
- Admin endpoints require login. Use HTTPS. Do not publish port 8088 unprotected on the public internet.
- Run exactly one container and one Uvicorn worker. JSON file locking is in-process only.
- Existing SMTP credentials remain in the JSON backup. No overdue warnings are shown.
- This is a beta: validate your deployment and security before public production use.

## Local development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt httpx
cp .env.example .env
# edit .env
set -a && . ./.env && set +a
uvicorn app.main:app --reload
```
