# TechNova ID-card photo storage setup

The ID-card photo feature uses the existing S3-compatible private attachment adapter. It deliberately refuses uploads when durable private object storage is not configured; Render's ephemeral local filesystem is not accepted for member identity photos.

## Required backend environment

Set these values in the backend deployment environment (Render environment variables or equivalent):

- `ATTACHMENT_STORAGE_PROVIDER=s3`
- `S3_ENDPOINT_URL` — the S3-compatible endpoint (for Cloudflare R2, the account-specific R2 S3 API endpoint)
- `S3_BUCKET` — a dedicated private bucket
- `S3_REGION=auto` for R2, or the provider's region
- `S3_ACCESS_KEY_ID`
- `S3_SECRET_ACCESS_KEY`

Use a dedicated bucket or prefix for TechNova. Disable public bucket access and do not configure a public custom domain or public object URL for this bucket. The application serves photos only through authenticated API endpoints. Credentials must be stored as deployment secrets and must never be committed to Git.

## Photo handling

- Members must be active and explicitly opt in before upload.
- Input is limited to JPEG, PNG or WEBP, at most 5 MB and 12 megapixels.
- The backend verifies and decodes the image, applies EXIF orientation, flattens transparency, and re-encodes a JPEG to strip embedded metadata.
- Stored objects are private and use server-side encryption where supported by the configured S3 adapter.
- Only the owner or authenticated Founder/Core Management staff during an active card verification can retrieve the photo.
- Every retrieval is marked `Cache-Control: private, no-store`; the API never emits a public object URL.
- Withdrawing consent disables retrieval immediately, removes the active database reference, and attempts to delete the private object. Configure an object lifecycle rule for the `technova/id-card-photos/` prefix as a cleanup backstop for orphaned objects.
- This image pipeline is not a general-purpose antivirus scanner. It accepts only decoded raster formats and re-encodes them; do not upload documents or arbitrary files through this feature.

## Validation before enabling

1. Confirm the bucket is private from a separate, unauthenticated client.
2. Configure the variables above in staging.
3. Upload a test image as a Member and verify that a different Member receives 403/404.
4. Verify a valid active card as Founder/Core Management and confirm the photo loads.
5. Withdraw consent and confirm the same photo endpoint no longer returns an image.
6. Revoke the card or suspend the member and confirm photo access is denied.
7. Confirm the bucket object is deleted or covered by the lifecycle cleanup rule.

Do not enable production photo uploads until these staging checks pass.
