<div align="center">

# 📦 Equipment Desk

**A simple, self-hosted equipment checkout system.**

Track cameras, batteries, microphones, cables, tools, and other shared gear without spreadsheets, accounts for every borrower, or a complicated database server.

[![Docker Hub](https://img.shields.io/badge/Docker%20Hub-Image-2496ED?logo=docker&logoColor=white)](https://hub.docker.com/r/snake16547/equipment-desk)
[![GitHub Release](https://img.shields.io/github/v/release/Snake16547/equipment-desk?include_prereleases)](https://github.com/Snake16547/equipment-desk/releases)
[![License](https://img.shields.io/github/license/Snake16547/equipment-desk)](LICENSE)

**[Quick start](#-quick-start-with-docker-compose) · [Features](#-features) · [Configuration](#%EF%B8%8F-configuration) · [Updates](#-updating) · [Security](#-security-and-privacy)**

</div>

> **Beta software.** Test with a backup before using it for important inventory. The public kiosk is intended for a trusted team or a restricted network, not unrestricted internet access.

## ✨ Features

- **Fast checkout and return:** Borrowers can check out equipment or return it without creating accounts.
- **Category-first browsing:** Browse categories before choosing gear, avoiding endless equipment lists.
- **Saved people:** Admins can predefine regular borrowers; occasional users can still enter their details manually.
- **Admin-assisted actions:** Staff can record checkouts and full or partial returns on behalf of borrowers.
- **Equipment tracking:** Supports individually tracked items and quantity-based inventory.
- **Admin dashboard:** Manage equipment, people, inventory, and settings behind an admin password.
- **Activity history and exports:** Export activity as CSV and the complete database as JSON.
- **Optional email notifications:** Configure SMTP in the admin interface.
- **Minimal infrastructure:** FastAPI, vanilla HTML/CSS/JavaScript, and a single readable JSON database. No separate SQL server required.
- **Docker-ready:** Prebuilt images for `linux/amd64` and `linux/arm64`.

## 🚀 Quick start with Docker Compose

**Requirements:** Docker Engine with the Compose plugin (or a Docker-compatible manager such as Dockge), and an available host port `8088`.

### 1. Create a folder

```bash
mkdir -p equipment-desk/data
cd equipment-desk
```

### 2. Create `compose.yaml`

```yaml
services:
  equipment-desk:
    image: snake16547/equipment-desk:0.2.2
    container_name: equipment-desk
    restart: unless-stopped
    ports:
      - "8088:8000"
    env_file:
      - .env
    environment:
      DATA_FILE: /data/equipment.json
    volumes:
      - ./data:/data
    read_only: true
    tmpfs:
      - /tmp:size=32m,mode=1777
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
```

> **Version pinning:** `0.2.2` is the first published image from the current release process. Use a specific version for predictable updates instead of `latest`. Verify the tag exists on [Docker Hub](https://hub.docker.com/r/snake16547/equipment-desk/tags).

### 3. Create `.env`

Create a file named `.env` next to `compose.yaml`:

```dotenv
ADMIN_PASSWORD=choose-a-long-unique-admin-password
SESSION_SECRET=replace-with-a-random-secret
APP_TITLE=Equipment Desk
COOKIE_SECURE=true
```

Generate a strong session secret:

```bash
openssl rand -hex 32
```

Paste the generated value after `SESSION_SECRET=`. **Do not commit your real `.env` file to GitHub.**

`COOKIE_SECURE=true` requires access through **HTTPS** for the admin session cookie. For a temporary, trusted local-network HTTP test only, use `COOKIE_SECURE=false`. Do not disable it for an internet-facing deployment.

### 4. Prepare persistent storage

The container runs as user ID `10001`. Give it access to the database directory:

```bash
sudo chown -R 10001:10001 data
sudo chmod 750 data
```

### 5. Start Equipment Desk

```bash
docker compose pull
docker compose up -d
```

Open:

- **Kiosk:** `http://YOUR-SERVER-IP:8088/`
- **Admin:** `http://YOUR-SERVER-IP:8088/admin`

Use your `ADMIN_PASSWORD` to log in. For normal use, put Equipment Desk behind an HTTPS reverse proxy and preferably restrict access to a private network or VPN.

### 6. Add your first equipment

1. Open `/admin` and sign in.
2. Add equipment with a **required category** and its quantity or individual tracking information.
3. Optionally add frequently used borrowers under **People**.
4. Return to the kiosk and try a checkout and return with test equipment.
5. Optionally configure SMTP notifications in the admin settings.

**That's it.** The database is created in `./data/equipment.json` on first use.

## 🐳 Dockge installation

If you already use [Dockge](https://github.com/louislam/dockge), create a new stack named `equipment-desk`, paste the Compose configuration above, and add the `.env` variables in the stack directory. Ensure a persistent `data` folder is mounted as `./data:/data` and writable by UID `10001`. Deploy the stack, then open the kiosk and admin URLs.

**Already running an older version?** Follow [Updating](#-updating) instead of creating a second stack with the same container name or port.

## ⚙️ Configuration

| Variable | Required | Description |
| --- | --- | --- |
| `ADMIN_PASSWORD` | Yes | Password for the admin interface. Use a unique, strong value. |
| `SESSION_SECRET` | Yes | Secret used for admin sessions. Generate with `openssl rand -hex 32`. |
| `APP_TITLE` | No | Display name, default `Equipment Desk`. |
| `COOKIE_SECURE` | Recommended | `true` for HTTPS; `false` only for trusted local HTTP testing. |
| `DATA_FILE` | No | Database location inside the container; the Compose example sets `/data/equipment.json`. |

SMTP settings are managed through the admin interface and saved in the database. **The database also contains borrower details and potentially SMTP credentials**, so handle it as sensitive data.

### Reverse proxy and ports

The application listens on **port `8000` inside the container**. The example maps it to **port `8088` on the host**. You may change the host-side number, for example `8090:8000`, without changing the application port.

For a reverse proxy, point it to the server's mapped port, enable HTTPS, and keep access restricted. Do not mistake `robots.txt` or noindex headers for access control.

## 🔄 Updating

**Always back up the data before changing image versions.** In the directory containing your Compose file:

```bash
# Stop writes before backing up the JSON database
docker compose down

# Create a timestamped backup in the parent directory
sudo tar -czf "../equipment-desk-backup-$(date +%Y%m%d-%H%M%S).tar.gz" data .env
```

Change the image tag in `compose.yaml`, for example:

```yaml
image: snake16547/equipment-desk:0.2.2
```

Then deploy:

```bash
docker compose pull
docker compose up -d
docker compose logs --tail=100
```

Your data stays in the bind-mounted `./data` directory. **Do not delete that directory during upgrades.** If the upgrade fails, keep the backup and inspect the logs before attempting a rollback.

### Upgrading from v0.1.x to v0.2.x

The newer database format introduces equipment categories and saved people. Equipment without categories is migrated into **Uncategorized**. The application also creates `equipment.json.v1-backup` before migrating the original database. Check the categories, inventory quantities, and outstanding loans after the upgrade. Because migration changes the database schema, do not assume an older image can read the migrated file without restoring a pre-upgrade backup.

## 💾 Backups and data

The application stores its state in:

```text
equipment-desk/
├── compose.yaml
├── .env                  # Admin/session secrets
└── data/
    ├── equipment.json    # Inventory, people, loans, settings
    └── equipment.json.v1-backup  # Only if migrated from v1
```

Back up both `data/` and `.env` to a protected location. Avoid uploading backups to public GitHub repositories or sharing them in support issues. For consistent backups, stop the container first or use the admin's JSON export when appropriate.

**Run one application container and one worker per database.** The JSON storage is not designed for multiple independent replicas sharing the same file.

## 🔐 Security and privacy

Equipment Desk is designed for small trusted teams. Please review these limitations before deployment:

- **The kiosk is not authenticated.** Anyone who can reach it can use the public checkout/return functionality.
- **Saved people are visible at the kiosk.** Selecting a saved person can reveal their saved phone number. Restrict kiosk access if you use this feature.
- **Name and phone are not secure identity verification.** Do not rely on them to prevent malicious or mistaken returns.
- **Protect the admin interface with HTTPS** and a strong password. Keep `COOKIE_SECURE=true` in normal HTTPS deployments.
- **Treat `data/equipment.json` as confidential.** It may include personal details and SMTP credentials in plaintext.
- **Noindex is not security.** Use firewall rules, VPN, LAN-only access, or reverse-proxy access restrictions.
- **Do not expose a development or test deployment** containing real borrower data.

## 🛠️ Troubleshooting

**Container starts but checkout fails with `Permission denied: /data/...`**

The container cannot write to the bind mount. From the stack directory:

```bash
sudo chown -R 10001:10001 data
docker compose up -d
```

**Admin login doesn't stay signed in**

Check that you're using HTTPS if `COOKIE_SECURE=true`. For temporary local HTTP testing only, set it to `false` and recreate the container.

**Port 8088 is already in use**

Change the host-side port in Compose, for example `8090:8000`, and redeploy.

**The new version doesn't show your old equipment**

Check that `./data:/data` points to the *same existing folder* as before. Do not initialize a fresh data directory over your old deployment. Inspect logs with:

```bash
docker compose logs --tail=150
```

## 🧑‍💻 Development

```bash
git clone https://github.com/Snake16547/equipment-desk.git
cd equipment-desk
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt httpx
cp .env.example .env
# Edit .env, then load the values into your shell:
set -a; . ./.env; set +a
uvicorn app.main:app --reload
```

Local development defaults to `http://127.0.0.1:8000`. For local HTTP testing, set `COOKIE_SECURE=false` in `.env`.

To run the smoke tests:

```bash
PYTHONPATH=. python tests/test_smoke.py
```

Release images are built and published using GitHub Actions when a version tag is pushed. Check the workflow results before treating an image as published.

## 🗺️ Roadmap and feedback

Ideas, bug reports, and improvements are welcome via [GitHub Issues](https://github.com/Snake16547/equipment-desk/issues). Please remove personal information, real database files, secrets, and access tokens from issue reports.

## 📄 License

See [LICENSE](LICENSE) for the repository's license terms.

---

<div align="center">

**Equipment Desk** — less paperwork, more time with your gear.

</div>
