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


## Member credits, ranks and leaderboard
- Every task has an independent difficulty rank (F, E, D, C, B, A, S, SS, or SSS), a programming-language / technology tag, and a credit reward. The existing Low / Medium / High priority remains a separate urgency field.
- Credit rewards: F 5, E 10, D 20, C 35, B 55, A 85, S 125, SS 175, SSS 250.
- Credits are awarded once only when Founder or Core Management approves the Member's submitted task. Accepting a common task, starting work, or submitting for review earns no credits. Older Done tasks are not backfilled.
- Member progression rank is calculated from lifetime approved credits: F 0+, E 25+, D 75+, C 150+, B 300+, A 500+, S 800+, SS 1,200+, SSS 1,800+.
- The authenticated leaderboard lists the Top 10 active Members and the signed-in Member's own position. Top 3 Members with at least one earned credit are eligible for selected Core Management-led projects and Founder-led coding-competition consideration. This is a shortlist, not automatic Core Management access or a guaranteed competition seat; the Founder confirms participation.


## Task lifecycle, daily missions, penalties and discipline
- Individual and common tasks can be paused/resumed or soft-deleted by Founder/Core Management. Archive removes a task from active lists but retains task and audit history. Pausing a task freezes its deadline; resuming extends the due date by the pause duration.
- Choose **Repeat automatically every day** when creating a task to save a daily template. The first task copy is created immediately; future copies start the next calendar day. Assigned daily templates re-create tasks for the same selected active assignees; common daily templates publish a fresh common mission each day. Schedules can be paused, resumed or stopped; already-created copies remain.
- A backend maintenance worker checks every minute for daily schedule generation, expired temporary suspensions and missed deadlines. Daily generation is idempotent across multiple app instances. The worker runs inside the FastAPI service; it therefore depends on the Render service being awake. For guaranteed wall-clock execution while a free service is asleep, configure an external scheduled HTTP call to the Founder-only `POST /api/maintenance/run` endpoint through a secret-bearing scheduler or upgrade to an always-on worker. Do not expose the endpoint without authentication.
- A task that remains unsubmitted after its due date receives one automatic deduction equal to 25% of its credit reward (rounded up, minimum 1 credit). A task submitted for review on or before its due date is not penalized while waiting for staff approval. Paused tasks and archived tasks are excluded. A late task can still be submitted and approved for its reward; the late deduction remains visible as a separate debit.
- Founder/Core Management can temporarily suspend active Member accounts for 1–720 hours, record a reason, and optionally deduct 0–500 credits. The suspension automatically expires; an administrator can reinstate early. Active ID cards are revoked during suspension and the member can issue a new card after reinstatement.
- All task archive/pause, schedule and member discipline actions are audit logged. Discipline deductions and deadline deductions are separate from earned credits and reduce the leaderboard's net total.
- Penalties should be applied consistently under a published club policy, with a clear reason and an opportunity for the Member to contact management. Do not use automated penalties for subjective or unverified allegations.


### Deadline policy detail
- Deadlines are treated as the end of the due date in India Standard Time. The maintenance worker checks after the date has passed.
- The automatic deduction is capped at the Member's available positive credit balance; the credit total never falls below zero. A late task can still receive its normal completion reward after review.
- A submission made on time is exempt even if staff approval happens later. A task that is completed after the due date is still checked for a late submission penalty.
- Temporarily suspending a Member also pauses their unfinished tasks. Those tasks resume and their deadlines are extended when the Member is reinstated or the suspension expires.

- Repeating tasks receive a fresh same-day deadline for each generated copy. Unclaimed daily common missions are closed after their day ends, while accepted personal task copies remain on the member's task board.


## Task operations, daily automation and discipline rules
- Tasks and common missions can be paused/resumed by authorized management. Pausing freezes the task deadline; resuming extends the due date by the pause duration. Archived tasks are soft-deleted so their task history and audit trail remain in MongoDB.
- Daily tasks are configured by selecting **Repeat automatically every day** when creating a task. The first occurrence is created immediately; subsequent copies are generated each day by the backend maintenance worker using Asia/Kolkata dates. Pausing or stopping a schedule affects future copies; already-generated tasks remain.
- The backend maintenance worker runs every 60 seconds while the API service is running. It closes expired daily common missions, generates scheduled copies, expires temporary suspensions and applies overdue penalties. Render sleep/restarts can delay a maintenance cycle until the service starts again.
- A task not submitted for review by its due date receives a one-time 25% credit penalty (minimum 1 credit). The penalty is recorded even when the Member currently has zero credits, so it offsets later earnings. A task submitted on or before its due date is not penalized merely because staff approves it later.
- Founder/Core Management can temporarily suspend a Member for a reason, for 1–720 hours, and apply a credit deduction. The account is automatically reactivated after the expiry time; assigned active tasks are paused during the suspension and their due dates are extended on reinstatement. This is a management decision recorded in the audit log, not an automatic penalty for every missed deadline.
- Members can view their current credit balance and recent award/deduction ledger on the Leaderboard page. The leaderboard and workspace refresh every 15 seconds while the browser tab is visible.
- Hard deletion is intentionally avoided for task records; archive operations retain records for accountability and recovery.
