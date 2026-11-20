# TechNova Automated Quality and Release Gates

## Purpose

Automated checks reduce regressions but cannot prove that software has zero bugs. A green CI run is necessary, not sufficient, for production release.

## Pull-request gates

Every pull request should:
1. Compile all Python backend modules.
2. Import the FastAPI app with CI-only environment variables.
3. Validate critical route contracts and Hub collection names.
4. Run focused backend unit/contract tests.
5. Run `npm ci` and `npm run build`.
6. Run dependency and secret scanning where configured.
7. Include a manual test plan for changed user workflows.
8. Include migration/rollback notes for schema or index changes.

## Critical regression journeys

- Registration → email verification → approval → login.
- Founder/Core Management login → TOTP → trusted device → logout/revoke.
- Member login → profile edit → encrypted private image upload/retrieve.
- Card issue → QR verification → revoke → verification rejected.
- Member opts in → uploads a separate image → staff verifies an active card and views the photo → withdrawal disables retrieval and removes the active photo record.
- Upload rejects oversized, malformed, animated, unsupported and over-dimension images; the stored image is re-encoded and served with private no-store headers.
- Without configured durable private object storage, uploads fail closed with HTTP 503.
- Task assignment → submission → review → credit award exactly once.
- Hub event → RSVP → attendance check-in → duplicate check-in rejected.
- Project visibility → join → unauthorized account denied.
- Certificate issue → public verify → revoke → invalid status.
- Notifications → preferences → delivery failure visible to user.
- Mobile login → camera permission → QR scan → session expiry.

## Security test matrix

| Risk | Test |
|---|---|
| Authentication bypass | Protected route without token returns 401 |
| IDOR | User A cannot read/update User B's private record |
| Privilege escalation | Member cannot call management-only mutation |
| MFA bypass | Management API rejects JWT without verified MFA claim |
| Replay | Expired/reused QR or event token is rejected |
| Duplicate effects | Repeated check-in/reward/certificate requests do not duplicate records |
| Upload spoofing | MIME/extension mismatch is rejected |
| Secret leakage | API responses and logs do not contain credentials |
| AI data leakage | Retrieval for one account cannot return another account's private data |
| Abuse | Rate limits and pagination caps are enforced |

## Staging release gates

Before production:
- Deploy the exact candidate commit to staging.
- Run database migrations against a staging copy.
- Run all automated tests and smoke tests.
- Verify email, push, storage and Telegram integrations using test accounts.
- Verify backup restoration and rollback.
- Review error logs for new exceptions and sensitive data.
- Obtain human approval for the production deployment.

## Rollback policy

- Keep each feature behind a server-side feature flag where feasible.
- Use backward-compatible schema changes.
- Take a verified backup before destructive migrations.
- Prefer disabling a feature over reverting data in place.
- Record the last known-good deployment commit and rollback steps.

- Print test: print/save the ID card only; unrelated portal controls and member data must not appear in the print output.
