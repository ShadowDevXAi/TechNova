# TechNova API Contract Conventions

This document defines conventions for extending the existing `/api` surface without breaking deployed clients. It is not a claim that every proposed endpoint is implemented.

## Existing contract to preserve

The current Hub uses `/api/hub/{collection}` and related routes for projects, challenges, events, resources, discussions, rewards, attendance, polls, mentorship, messages and certificates. Digital ID and encrypted profile images have dedicated route modules. Phase 1A adds `/api/cards/me/photo-consent` (GET/PUT), a Member-owned preference endpoint. It records an explicit, revocable preference only; it does not upload or expose an image. Staff card verification may return the boolean `photo_consent` field, but never image bytes.

Before adding a new route:
1. Inspect the current frontend call sites and backend router.
2. Reuse an existing Hub operation if it already satisfies the requirement.
3. Add a dedicated router only when the feature has distinct authorization, validation or lifecycle needs.
4. Keep existing URLs and response fields compatible unless a versioned migration is planned.
5. Add contract tests for both the old and new behavior.

## Proposed domain route groups

| Domain | Proposed route family | Notes |
|---|---|---|
| Identity | Existing `/api/cards/*`, `/api/verify/*`, `/api/profile-image` | Extend existing routes; separate consented ID photo from private image |
| Events | Existing `/api/hub/events*` and attendance routes | Audit current behavior before splitting into a dedicated router |
| Projects | Existing `/api/hub/projects*` | Extend existing project records and task links |
| Learning | Existing `/api/hub/resources*`, challenges | Add course/lesson/progress routes only after schema review |
| Community | Existing `/api/hub/discussions*`, messages and polls | Add moderation and pagination with participant checks |
| Opportunities | `/api/opportunities*` | New domain if not already present |
| Achievements | Existing credits/leaderboard and Hub rewards | One idempotent ledger for new awards |
| Certificates | Existing Hub certificate routes and `/api/certificates/verify/{code}` | Preserve verification URL compatibility |
| AI | `/api/assistant/*` | Backend-only provider adapter and permission-aware retrieval |
| Analytics | `/api/analytics/*` | Aggregated data by default; scope individual records |

## Request and response rules

- Use Pydantic models for structured request bodies.
- Reject unknown or invalid enum values rather than silently coercing them.
- Bound text length, arrays, upload size and pagination.
- Use stable IDs, ISO-8601 UTC timestamps and documented status enums.
- Return consistent HTTP errors without tracebacks or database internals.
- Use cursor pagination for potentially large collections; cap page sizes.
- Avoid returning full database documents. Explicitly serialize approved response fields.
- Use idempotency keys or unique source-event indexes for attendance, certificates and rewards.
- Never accept the actor/member identity from an untrusted request body when it can be derived from the authenticated session.

## Suggested API design for future work

The following are design targets only and must be reconciled with current Hub routes before implementation.

### Events
- `GET /api/events`
- `POST /api/events`
- `POST /api/events/{event_id}/register`
- `DELETE /api/events/{event_id}/registration`
- `POST /api/events/{event_id}/check-in`
- `GET /api/events/{event_id}/attendance`

### Projects
- `GET /api/projects`
- `POST /api/projects`
- `GET /api/projects/{project_id}`
- `PATCH /api/projects/{project_id}`
- `POST /api/projects/{project_id}/members`
- `POST /api/projects/{project_id}/milestones`

### Learning
- `GET /api/courses`
- `GET /api/courses/{course_id}`
- `POST /api/courses/{course_id}/enroll`
- `PUT /api/lessons/{lesson_id}/progress`
- `POST /api/quizzes/{quiz_id}/attempts`

### Community and opportunities
- `GET /api/community/posts`
- `POST /api/community/posts`
- `POST /api/community/posts/{post_id}/report`
- `GET /api/opportunities`
- `POST /api/opportunities/{opportunity_id}/applications`

### AI and analytics
- `POST /api/assistant/chat`
- `POST /api/assistant/feedback`
- `GET /api/analytics/overview`
- `GET /api/analytics/events`

## Compatibility policy

- Do not rename collections or fields in place without a migration.
- Add optional response fields before requiring them.
- For breaking changes, support old and new contracts during a documented transition.
- Use database migrations that are safe to rerun and safe to roll back.
- Add tests for old clients' expected fields before changing serializers.
