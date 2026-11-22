# TechNova ID-card photo storage setup

The ID-card photo feature stores image bytes in MongoDB GridFS inside TechNova's existing MongoDB database. The `card_photos` collection stores owner metadata and the GridFS file ID; image bytes are stored in GridFS's `id_card_photos.files` and `id_card_photos.chunks` collections. No S3 bucket or separate database is required.

## Required backend environment

Use the same MongoDB connection already configured for TechNova. Ensure `MONGODB_URI` points to the production MongoDB deployment and `DATABASE_NAME` is the intended TechNova database. No additional MongoDB URI, bucket, access key, or S3 environment variables are needed for ID-card photos.\n\nClamAV is the only additional service required for malware scanning. Set these values in the backend deployment environment:

- `ATTACHMENT_STORAGE_PROVIDER=s3`
- `S3_ENDPOINT_URL` — the S3-compatible endpoint (for Cloudflare R2, the account-specific R2 S3 API endpoint)
- `S3_BUCKET` — a dedicated MongoDB GridFS storage
- `S3_REGION=auto` for R2, or the provider's region
- `S3_ACCESS_KEY_ID`
- `S3_SECRET_ACCESS_KEY`
- `ID_PHOTO_CLAMAV_HOST` — private hostname or service name for a ClamAV daemon reachable by the backend
- `ID_PHOTO_CLAMAV_PORT=3310` (optional; default 3310)
- `ID_PHOTO_CLAMAV_TIMEOUT_SECONDS=8` (optional; default 8, maximum 30)

Use a dedicated bucket or prefix for TechNova. Disable public bucket access and do not configure a public custom domain or public object URL for this bucket. The application serves photos only through authenticated API endpoints. Credentials must be stored as deployment secrets and must never be committed to Git.

## Photo handling

- Members must be active and explicitly opt in before upload.
- Input is limited to JPEG, PNG or WEBP, at most 5 MB and 12 megapixels.
- The backend verifies and decodes the image, applies EXIF orientation, flattens transparency, and re-encodes a JPEG to strip embedded metadata. It then sends the normalized bytes to ClamAV using the INSTREAM protocol. A detected threat is rejected; if ClamAV is missing, unreachable, or returns an invalid response, the upload fails closed with HTTP 503.
- Image bytes remain inside the MongoDB deployment and are accessed only through the backend's authenticated routes. Secure MongoDB with TLS, authentication, least-privilege credentials, network allow-listing and encrypted backups.
- Only the owner or authenticated Founder/Core Management staff during an active card verification can retrieve the photo.
- Every retrieval is marked `Cache-Control: private, no-store`; the API never emits a public object URL.
- Withdrawing consent disables retrieval immediately, removes the active database reference, and attempts to delete the corresponding GridFS file and chunks.
- ClamAV must be deployed as a private service reachable only from the backend network; never expose its TCP port publicly. Keep virus definitions updated. The application does not start or manage the ClamAV daemon.

## Validation before enabling

1. Confirm the bucket is private from a separate, unauthenticated client.
2. Deploy a private ClamAV daemon, configure all variables above in staging, and verify that the backend can reach the scanner.
3. Upload a test image as a Member and verify that a different Member receives 403/404.
4. Verify a valid active card as Founder/Core Management and confirm the photo loads.
5. Withdraw consent and confirm the same photo endpoint no longer returns an image.
6. Revoke the card or suspend the member and confirm photo access is denied.
7. Confirm the corresponding GridFS file and chunks are deleted.
8. Test the ClamAV path with the standard EICAR test file in a non-production environment; confirm it is rejected and never stored.

Do not enable production photo uploads until these staging checks pass.
