# TechNova Security and Privacy Model

## Security principles

1. Backend authorization is authoritative. Hiding a button or route in React is not access control.
2. Default deny for new endpoints and new data fields.
3. Verify both role and resource ownership for every read, write, download and administrative action.
4. Collect the minimum personal information needed for the stated feature.
5. Log security-relevant actions without logging passwords, bearer tokens, recovery codes, private image bytes or AI secrets.
6. Treat uploads, links, user posts, code submissions and AI prompts as untrusted input.
7. Make sensitive actions auditable, rate-limited and reversible where appropriate.

## Identity and roles

Existing roles remain Founder, Core Management, Faculty and Member. Existing management TOTP MFA must remain mandatory. Role changes, approvals, suspensions, card issue/revoke and security configuration are server-side operations and must create audit events.

For new features, use scoped permissions:
- Event organizer: manage only assigned events.
- Project owner/manager: manage only projects where they have an authorized role.
- Course instructor: manage only assigned learning content.
- Community moderator: moderate only within assigned scope.
- Analytics viewer: access only approved aggregate or scoped reports.

Do not automatically grant access to private member files, messages, application records or AI history merely because an account is staff.

## Profile image and ID-card privacy

The encrypted profile-image endpoint is owner-only. Its browser-held passphrase is never sent to the API. Telegram stores ciphertext, not plaintext; Telegram channels are not native end-to-end encrypted chats.

A public or staff-scannable ID card must not reuse the owner-only private-image endpoint. Phase 1A records a separate, revocable preference on the member account; the verification response exposes only whether consent was granted to authenticated verification staff. It does not expose an image, and consent alone does not enable photo sharing. If the product needs a photo on a card that other people can view:
1. Request separate, explicit member consent.
2. Store the card-display photo as a separate resource with its own visibility and retention rules.
3. Provide revoke/delete controls and reflect consent changes in the card.
4. Never infer consent from uploading a private profile image.
5. Keep public verification minimal and avoid returning email, phone, home address or internal database identifiers.

## Authentication and sessions

- Preserve current Firebase/auth integration and the existing FastAPI session/token contract.
- Keep management TOTP MFA and recovery-code safeguards.
- Enforce email verification and account status on protected workflows.
- Use HTTPS in all deployed environments.
- Never commit JWT secrets, Firebase service-account credentials, Telegram bot tokens, SMTP/Brevo credentials or AI provider keys.
- Rotate any credential that has been exposed.
- Do not weaken CORS, token validation, rate limits or MFA to make tests pass.

## API authorization checklist

For every new endpoint, document:
- Authentication requirement.
- Allowed roles.
- Resource ownership/tenant scope.
- Fields visible to the caller.
- Rate limit and abuse controls.
- Audit event for sensitive mutations.
- Idempotency and concurrency behavior.
- Error responses that do not leak internal state.

Test object-level authorization (IDOR) explicitly by attempting to access another member's object with a valid but different account.

## Uploads and storage

- Enforce maximum request size at the edge and in the API.
- Validate extension, declared media type and actual file signature.
- Generate server-side object names; do not trust user-provided paths.
- Keep buckets private and use short-lived signed download URLs or authenticated proxy endpoints.
- Scan untrusted uploads before making them available to other users.
- Apply retention and deletion rules; keep backup lifecycle separate from live object lifecycle.
- Do not store binary files in MongoDB documents.
- Use a durable storage provider in production; local disk is for development only.

## QR and certificates

- Use cryptographically random, purpose-specific, expiring tokens.
- Store token hashes where feasible; do not expose raw reusable secrets in logs.
- Bind event check-in to the event, member and expiry window.
- Make duplicate attendance/reward operations idempotent.
- Certificate verification should reveal only approved public fields and current validity status.
- Revocation must take effect immediately on verification.

## AI assistant

- Keep model/provider keys on the backend.
- Retrieve only documents the current user is authorized to see.
- Treat retrieved documents and user prompts as untrusted data, not system instructions.
- Do not allow model output to directly perform role changes, approvals, payments, account actions or other privileged mutations.
- Require a separate authenticated backend action and explicit confirmation for any future action-taking capability.
- Apply quotas, abuse monitoring, safe retention defaults and user-visible feedback.
- Do not train or fine-tune on private member content without a separately reviewed consent and governance process.

## Community and messaging

- Validate and length-limit all text and URLs.
- Add spam/rate controls, reporting, blocking and moderation workflows.
- Enforce conversation participant checks for every message read and write.
- Avoid exposing private messages to analytics or AI retrieval by default.
- Support user reporting and documented moderation escalation.

## Analytics and privacy

- Prefer aggregate and de-identified metrics.
- Restrict row-level member reports to explicitly authorized staff.
- Audit exports and high-sensitivity queries.
- Define retention periods and deletion/export procedures before launch.
- Never expose private attributes on public leaderboard, certificate or QR pages.

## Production readiness

Before public release:
- HTTPS and strict CORS.
- Strong secret management and credential rotation.
- Database and object-store backups with restore tests.
- Dependency and secret scanning.
- Malware scanning for uploads.
- Rate limiting and abuse monitoring.
- Error tracking with sensitive-field redaction.
- Incident response and rollback procedures.
- Manual security review of authentication, authorization, storage and QR flows.
