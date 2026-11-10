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

## Docker Hub deployment

1. Create a public Docker Hub repository `equipment-desk` and set the image name in `.env` as `EQUIPMENT_DESK_IMAGE=YOUR_DOCKERHUB_USERNAME/equipment-desk:0.2.0` (or replace it directly in `docker-compose.yml`).
2. `cp .env.example .env` and configure `ADMIN_PASSWORD`, `SESSION_SECRET` (generate with `openssl rand -hex 32`), and `COOKIE_SECURE=true` for HTTPS.
3. `mkdir -p data && sudo chown -R 10001:10001 data`
4. `docker compose pull && docker compose up -d`
5. Proxy port 8088 behind HTTPS. The container listens on port 8000.

To build locally instead: `docker build -t equipment-desk:local .`, then set `EQUIPMENT_DESK_IMAGE=equipment-desk:local` in `.env` and run `docker compose up -d` (no pull).

## Upgrade from v0.1.0

**Back up `data/` and `.env` before updating.** Stop the old container. Keep the existing `./data:/data` mount and use the same `.env`. On first database read, v1 data is migrated to schema v2; missing categories become `Uncategorized`. The app writes `equipment.json.v1-backup` once before migration. Verify the backup and category assignments in admin. Existing loans remain in the JSON file.

## Publishing on GitHub and Docker Hub

1. Push the project to a public GitHub repository named `equipment-desk`. Review `git status` to ensure `.env` and `data/` are excluded.
2. In Docker Hub create a public `equipment-desk` repository and a write-enabled access token.
3. GitHub repository → Settings → Secrets and variables → Actions: add **variable** `DOCKERHUB_USERNAME` and **secret** `DOCKERHUB_TOKEN`.
4. Run `python tests/test_smoke.py` locally (requires `pip install -r requirements.txt httpx`).
5. Commit changes, then `git tag v0.2.0 && git push origin v0.2.0`. The Actions workflow tests and publishes `0.2.0` and `latest` for linux/amd64 and linux/arm64.
6. GitHub → Settings → Pages → Deploy from a branch → `main` / `docs`. Replace `YOUR_GITHUB_USERNAME` in `docs/index.html`.
7. Create a GitHub Release using the existing `v0.2.0` tag.

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
