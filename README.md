# TechNova Club Portal — Full-stack starter

React + FastAPI + MongoDB implementation with real persistence, JWT login, role-based backend authorization, member management, task assignment, task comments and attachments, profile editing, password reset, digital card issuance, server-side QR verification, rate limits, and audit events.

## Requirements
- Docker Desktop / Docker Engine + Compose (recommended), OR Python 3.11+ and Node.js 18+
- A modern browser

## Quick start with Docker
1. Copy `.env.example` to `.env`.
2. Set unique values for `MONGO_ROOT_PASSWORD`, `JWT_SECRET`, `BOOTSTRAP_FOUNDER_NAME`, `BOOTSTRAP_FOUNDER_EMAIL`, and `BOOTSTRAP_FOUNDER_PASSWORD`. Do not use example values.
3. From this folder run:
   ```bash
   docker compose up --build
   ```
4. Open `http://localhost:8080`.
5. Sign in using the bootstrap founder email/password you configured in `.env`.
6. API docs are at `http://localhost:8000/docs`.

For Render deployments, set `MONGODB_URI`, `JWT_SECRET`, `BOOTSTRAP_FOUNDER_NAME`, `BOOTSTRAP_FOUNDER_EMAIL`, `BOOTSTRAP_FOUNDER_PASSWORD`, `FRONTEND_ORIGINS`, and `PUBLIC_APP_URL` in the backend environment. Use `RESET_DELIVERY_MODE=email` only after SMTP is configured.

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
- `Founder` (club Owner): full administrative control, including assigning teams to any non-Founder member, changing roles, issuing/revoking cards, assigning tasks to Core Management and Members, and viewing the audit log.
- `Core Management`: can view team rosters, approve registrations, manage team definitions, assign tasks to Members only, scan Member IDs, and confirm Member task submissions after scanning the assignee's QR.
- `Founder` (club Owner): can view all team rosters and assign teams; can scan any active role's ID and confirm tasks assigned to Members or Core Management.
- `Member`: can view their own profile and digital ID with a secure QR in its top-left corner, see only their assigned tasks, and submit completed work for review. A Member cannot mark a task Done directly.

Role checks are enforced by FastAPI, not just hidden frontend buttons. Treat this as a practical starter, not a completed security audit.

## Key endpoints
- `POST /api/auth/login`
- `GET /api/auth/me`
- `POST /api/auth/register` (public registration always creates a pending `Member`)
- `GET /api/members`, `POST /api/members`, `PATCH /api/members/{id}`, `POST /api/members/{id}/approve`
- `GET /api/tasks`, `POST /api/tasks`, `PATCH /api/tasks/{id}`
- `GET /api/tasks/pending-confirmation?member_id=TN-M-0001` (Founder/Core Management; after QR scan)
- `POST /api/tasks/{id}/confirm-completion` (requires the scanned assignee's active `card_token`)
- `POST /api/cards/{member_id}/issue`, `POST /api/cards/{member_id}/revoke`
- `POST /api/cards/me/issue` (authenticated users get their own stable QR)
- `GET /api/verify/{token}` (authenticated Founder/Core Management; Core Management can verify Member IDs only)
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
- QR tokens are signed with the server secret and token hashes are stored; raw tokens are not stored. QR verification requires an authenticated Founder/Core Management account and writes audit events.
- Task completion flow: a Member starts an accepted task as `In progress`, then submits it to `Review` with a screenshot evidence link, a completion note, and an explicit evidence attestation. Use ImagePaste's direct image URL (`/i/`) for screenshot previews; its `/v/` URL is a share page. Founder/Core Management inspect the screenshot and optional project/demo link, then approve the task or request changes with feedback. Approval changes the task to `Done`; returning it clears old evidence and puts it back `In progress`. Bulk approval and optional QR-based confirmation are restricted to Founder/Core Management. Anonymous ImagePaste uploads expire after seven days, so use a signed-in permanent upload or durable club-controlled asset for long-term evidence and branding.
- The MongoDB URI and founder credentials must be environment variables, never committed to source. Rotate any credential that was ever committed.
- Do not store sensitive government identifiers, passwords in plain text, or unnecessary student information.

## Current scope and honest limitations
This is an expanded functional starter, not a guarantee of zero limitations or a certified production release. It does not yet include email verification, polished front/back ID PDF generation, cloud object storage, virus scanning, notifications, a full project/milestone module, or a full automated end-to-end test suite. Review the authorization model and deploy only after tests, backups, HTTPS, and secret management are in place.
