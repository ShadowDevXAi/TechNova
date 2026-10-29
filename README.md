# TechNova Club Portal — Full-stack starter

React + FastAPI + MongoDB implementation with real persistence, JWT login, role-based backend authorization, member management, task assignment, task comments and attachments, profile editing, password reset, digital card issuance, server-side QR verification, rate limits, and audit events.

## Requirements
- Docker Desktop / Docker Engine + Compose (recommended), OR Python 3.11+ and Node.js 18+
- A modern browser

## Quick start with Docker
1. Copy `.env.example` to `.env`.
2. Set strong unique values for `MONGO_ROOT_PASSWORD`, `JWT_SECRET`, `BOOTSTRAP_FOUNDER_EMAIL`, and `BOOTSTRAP_FOUNDER_PASSWORD`. Do not use the example values.
3. From this folder run:
   ```bash
   docker compose up --build
   ```
4. Open `http://localhost:8080`.
5. Sign in using the bootstrap founder email/password you configured in `.env`.
6. API docs are at `http://localhost:8000/docs`.

MongoDB is published only to localhost by default. The frontend container's nginx proxies `/api/` to FastAPI.

## Local development without Docker
1. Start MongoDB and set `MONGODB_URI` in `.env`.
2. Backend:
   ```bash
   cd backend
   python -m venv .venv
   # Windows: .venv\\Scripts\\activate
   # macOS/Linux: source .venv/bin/activate
   pip install -r requirements.txt
   uvicorn app.main:app --reload
   ```
3. Frontend:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```
   Vite proxies `/api` to `http://localhost:8000`.

## Roles
- `Founder`: all permissions; only one founder account is bootstrapped. The API prevents changing/deleting the founder through ordinary member endpoints.
- `Core Management`: can review/approve members, manage tasks and teams, issue/revoke cards, and view members.
- `Member`: can view own profile, view tasks assigned to them, and update their own task status/submission notes.

Role checks are enforced by FastAPI, not just hidden frontend buttons. Treat this as a practical starter, not a completed security audit.

## Key endpoints
- `POST /api/auth/login`
- `GET /api/auth/me`
- `POST /api/auth/register` (public registration always creates a pending `Member`)
- `GET /api/members`, `POST /api/members`, `PATCH /api/members/{id}`, `POST /api/members/{id}/approve`
- `GET /api/tasks`, `POST /api/tasks`, `PATCH /api/tasks/{id}`
- `POST /api/cards/{member_id}/issue`, `POST /api/cards/{member_id}/revoke`
- `GET /api/verify/{token}` (public, minimal response)
- `GET /api/teams`, `POST /api/teams`
- `GET /api/dashboard`

## Password reset and attachments
- In local development, password reset returns a one-time reset token in the API response for testing. Never use `RESET_DELIVERY_MODE=development` on a public deployment.
- For email-based resets, set `RESET_DELIVERY_MODE=email` and configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`, and `SMTP_USE_TLS`. Test delivery with a dedicated mail account.
- Task attachments accept PNG, JPEG, WEBP, PDF, TXT, and ZIP up to 10 MB. In Docker, files are stored in the persistent `uploads_data` volume. Configure volume backups and malware scanning before public use.
- The ID card page includes browser Print / Save as PDF. Browser print output is intended for printing; it is not a professionally imposed double-sided card PDF template.

## Production checklist before public launch
- Deploy only behind HTTPS; use a proper domain and configure CORS origins.
- Use a strong unique JWT secret and MongoDB credentials stored in a secret manager.
- Configure backups, monitoring, log retention, and restore testing.
- Add email verification, WAF/abuse monitoring, and production security review. Password reset and basic rate limiting are included, but must be tested in your hosting environment.
- Decide whether college approval is required before claiming affiliation. Use only authorized club/college branding.
- Review privacy notice and consent, data retention/deletion, and access policies.
- Rotate bootstrap credentials immediately after first login; this project requires the bootstrap password to be configured before startup.
- QR tokens are random and only their SHA-256 hashes are stored. Public verification intentionally returns limited details.
- Do not store sensitive government identifiers, passwords in plain text, or unnecessary student information.

## Current scope and honest limitations
This is an expanded functional starter, not a guarantee of zero limitations or a certified production release. It does not yet include email verification, polished front/back ID PDF generation, cloud object storage, virus scanning, notifications, a full project/milestone module, or a full automated end-to-end test suite. Review the authorization model and deploy only after tests, backups, HTTPS, and secret management are in place.
