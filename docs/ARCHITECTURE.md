# TechNova code map

This guide explains where the portal's frontend and backend responsibilities live.
The goal is to make changes easier to locate without changing the public API contract.

## Frontend

The frontend is a React + Vite application in `frontend/src`.

| File or folder | What it does |
| --- | --- |
| `main.jsx` | Browser entry point. Mounts the root React application and global stylesheet. |
| `App.jsx` | Portal coordinator. Owns session state, selected screen, screen layout and shared component state. |
| `api/client.js` | Shared HTTP client. Adds the API base URL, bearer token, JSON/FormData handling and normalized API errors. |
| `services/portalActions.js` | Named UI action handlers: login/logout, member management, task creation/review, schedules, suspensions, notifications, attachments, ID cards, verification, teams, profile and password workflows. |
| `hooks/useWorkspaceData.js` | Loads the signed-in member and the initial dashboard, member, task, team, notification and leaderboard data. Returns `load()` for manual refreshes. |
| `hooks/useWorkspacePolling.js` | Refreshes operational data every 30 seconds while the browser tab is visible. It avoids overlapping requests and preserves the last successful view after a temporary network error. |
| `components/TechNovaLogo.jsx` | Reusable TechNova logo link with a fallback monogram. |
| `config/branding.js` | Central location for the logo share URL and direct image URL. |
| `config/navigation.js` | Sidebar labels and their Lucide icons. |
| `utils/formatters.js` | Shared formatting helpers such as storage-size labels and member initials. |
| `TechNovaHub.jsx` | Club Hub screen: projects, coding arena, events, library, polls, community, rewards, attendance, mentorship, messages and certificates. |
| `styles.css` | Global layout, component styles, responsive rules and scrolling behavior. |

### Frontend editing convention

- Put reusable HTTP behavior in `api/client.js`; do not build a second fetch wrapper inside a screen.
- Put an action that changes portal data in `services/portalActions.js` and add a purpose comment above it.
- Put reusable stateful behavior in a custom hook under `hooks/`.
- Put repeated visual elements in `components/`.
- Keep environment-specific URLs and navigation definitions in `config/`.
- Keep shared, display-only transformations in `utils/`.

`App.jsx` remains the screen coordinator and still contains the current page JSX. This avoids moving large state-dependent markup before it can be tested screen by screen.

## Backend

The backend is a FastAPI + MongoDB application in `backend/app`.

| File or folder | What it does |
| --- | --- |
| `main.py` | Application entry point. Creates FastAPI, configures CORS/rate limiting and mounts the feature routers. |
| `core.py` | Shared database/security helpers, response serializers, authorization dependencies, notifications, credit calculations, daily-task generation, maintenance worker and application lifespan. |
| `config.py` | Validates environment variables such as MongoDB, JWT, SMTP, Gemini and founder bootstrap settings. |
| `db.py` | Creates the shared async MongoDB client and indexes needed by portal queries. |
| `models.py` | Pydantic request schemas and shared role/status types. |
| `security.py` | Password hashing, JWT creation/verification, digital-ID tokens and UTC timestamps. |
| `routes/system.py` | Root/health responses, database statistics and automatic daily-task controls. |
| `routes/auth.py` | Registration, login, profile, password reset/change, current user, dashboard and credit ledger. |
| `routes/members.py` | Member directory, member administration and leaderboard. |
| `routes/tasks.py` | Individual/shared tasks, review queue, notifications, announcements, task state, suspension, schedules, attachments and comments. |
| `routes/teams.py` | Team listing and team creation. |
| `routes/cards.py` | Digital ID issue/revoke, QR verification, task-completion confirmation and audit history. |
| `routes/hub.py` | All Club Hub APIs, including projects, events, challenges, discussions, attendance, rewards, polls, mentorship, messages and certificates. |

### Backend editing convention

- Add an endpoint to the router that owns its feature; keep the existing `/api/...` URL unless a coordinated frontend/API migration is intended.
- Reuse `get_current_user` and `allow(...)` from `core.py` for authentication and role checks.
- Put request validation in `models.py`, not in ad-hoc frontend assumptions.
- Put password/token operations in `security.py`.
- Put database indexes in `db.py`.
- Add a short purpose comment above new functions and endpoints.
- Do not store raw password-reset or digital-ID secrets in the database; keep using the existing token-hash helpers.

## Checks

The repository's GitHub Actions workflow runs:
1. Python syntax compilation for `backend/app`.
2. `npm ci` in `frontend`.
3. A Vite production build with `npm run build`.

A successful file update in GitHub is not the same as a successful production build. Check the Actions result after pushing changes.
