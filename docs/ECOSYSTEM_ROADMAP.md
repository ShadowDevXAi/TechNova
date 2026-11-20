# TechNova Ecosystem Roadmap

## Product objective

Evolve TechNova into a connected student ecosystem while preserving the existing React + Vite frontend, FastAPI backend, MongoDB persistence, Firebase integrations, authentication, role model, management TOTP MFA, tasks, digital cards, QR verification, notifications and Telegram backup integration.

This roadmap is an implementation sequence, not a claim that every listed capability is already complete.

## Existing foundation to reuse

The current repository already includes:
- Account registration, email verification, login, profile and password workflows.
- Founder, Core Management, Faculty and Member roles; backend authorization and management TOTP MFA.
- Member approval, tasks, review, attachments, task comments, teams, announcements and notification preferences.
- Digital card issue/revoke and authenticated QR verification.
- Credits, ranks, leaderboard and recurring task maintenance.
- A Club Hub router and UI covering projects, coding challenges, events, resources, discussions, rewards, attendance, polls, mentorship, messages and certificates.
- Member-owned encrypted profile-image storage (merged through PR #24). The passphrase remains in the browser; only ciphertext is stored through the configured private Telegram channel.

## Product modules

| Module | Current foundation | Planned completion |
|---|---|---|
| Digital identity | Cards, signed QR verification, encrypted profile image | Consented card-visible photo, polished front/back card, PDF export, revocation/expiry UX |
| Events | Hub events and RSVP | Capacity, waitlist, check-in passes, staff scanning, reports |
| Projects | Hub projects and task references | Membership roles, milestones, timeline, Kanban, project activity |
| AI assistant | Existing AI configuration may be present | Permission-aware retrieval, quotas, feedback, provider adapter, safe response policy |
| Learning | Hub resources and coding challenges | Courses, lessons, quizzes, progress, bookmarks |
| Community | Discussions, polls, messages, mentorship | Moderation, reports, blocking, pagination and privacy controls |
| Opportunities | No confirmed complete workflow | Verified internships/jobs, bookmarks, application tracking |
| Achievements | Task credits, ranks and leaderboard | Idempotent achievement ledger, badges, team challenges |
| Certificates | Hub certificate records and verification route | Public minimal verification, revocation, reissue and audit trail |
| Analytics | Existing dashboard/operational data | Aggregated event, learning, project and security analytics |
| Mobile | Responsive web foundation | Capacitor Android/iOS shell, camera, push, deep links and offline-safe views |

## Phase delivery status

- **Phase 0:** merged to `main` through PR #25.
- **Phase 1A (in progress):** explicit member-owned ID-card photo-consent recording and staff-visible consent status. This is consent metadata only; no image is published, uploaded, or returned by the verification API yet.

## Phased delivery

### Phase 0 — Baseline and safety
1. Map existing API/UI capabilities and preserve their contracts.
2. Add automated regression tests for critical routes, role rules and progression helpers.
3. Establish security, API and release-gate documentation.
4. Keep all development on feature branches and use reviewed pull requests.
5. Use staging and a test database; never run migration experiments against production data.

Exit gate: existing registration, login, email verification, management MFA, member approvals, tasks, QR verification, notifications and profile-image ownership checks pass regression tests.

### Phase 1 — Identity and storage
1. Review the merged encrypted profile-image implementation and its deployment configuration.
2. Keep the private owner-only image endpoint private.
3. Record a separate, revocable explicit consent preference (implemented in Phase 1A); build the distinct card-photo upload/review workflow only after private storage and file-scanning controls are ready.
4. Improve card front/back layout, print/PDF output and verification details.
5. Validate private object storage, file signatures, size limits, malware scanning, backup and restore.

Exit gate: another account cannot retrieve a private image; a card photo is displayed only after explicit consent; revoked IDs do not verify.

### Phase 2 — Events and projects
1. Audit and complete existing Hub event registration and attendance before creating replacement APIs.
2. Add capacity, waitlists, event-specific short-lived check-in passes and staff reports.
3. Extend existing projects with member roles, milestones, timeline and Kanban.
4. Link project work to the existing task system rather than creating duplicate task records.

Exit gate: check-in is idempotent, replay attempts fail, and project data is visible only to authorized participants/staff.

### Phase 3 — Learning and community
1. Extend existing resources and challenges into courses, lessons, quizzes and progress.
2. Add skill tags and learning bookmarks.
3. Add community reporting, blocking, moderation, pagination and content controls.

Exit gate: members cannot modify another user's private progress or content; moderation is auditable.

### Phase 4 — Opportunities, achievements and certificates
1. Add verified opportunity listings and application tracking.
2. Extend the existing credit ledger with unique source-event IDs for new rewards.
3. Add badges and team challenges.
4. Complete certificate issue, public verification, revocation and reissue.

Exit gate: reward issuance is idempotent; public verification reveals only approved fields; revoked certificates report invalid.

### Phase 5 — AI assistant
1. Build a provider-independent backend adapter.
2. Retrieve only resources the signed-in user is authorized to access.
3. Add quotas, feedback, moderation, retention controls and usage analytics.
4. Keep provider credentials on the backend; never put secrets in Vite variables.

Exit gate: cross-user data is not retrieved; the assistant cannot execute privileged actions or bypass backend authorization.

### Phase 6 — Mobile and analytics
1. Package the adaptive React app with Capacitor.
2. Add camera-based QR scanning, push notifications and deep links.
3. Add offline-safe, expiring event passes and selected cached learning content.
4. Add aggregated analytics and security monitoring.

Exit gate: test Android/iOS permissions, token expiry, offline behavior, duplicate scans, deep links and device logout.

## Architecture decisions

- Start with a modular monolith. Do not introduce microservices until independent scaling or operational needs justify them.
- MongoDB remains the source of truth for application records.
- Preserve Firebase's existing authentication/realtime responsibilities; do not create a second account identity system.
- Reuse the shared React API client and portal action conventions.
- Reuse `get_current_user`, `allow(...)`, existing serializers, audit helpers and collection naming conventions in FastAPI.
- Keep large files outside MongoDB documents. Store metadata and access references in MongoDB and binary objects in private storage.
- Add backward-compatible database changes before switching application behavior; remove legacy fields only after verified migration and a rollback window.

## Release policy

A phase is not complete merely because code has been committed. It must pass CI, targeted API tests, frontend production build, authorization tests, migration review, staging smoke tests and an explicit release review. No automated process can prove the absence of all defects.
