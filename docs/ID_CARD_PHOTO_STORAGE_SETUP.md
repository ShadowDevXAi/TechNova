# TechNova ID-card photo storage setup

TechNova uses its existing MongoDB database for ID-card photos. Image bytes are stored in a dedicated MongoDB GridFS bucket named `id_card_photos`; owner metadata and the GridFS file ID are stored in the existing `card_photos` collection. GridFS creates `id_card_photos.files` and `id_card_photos.chunks` collections in the same database. No S3 bucket, separate database, or extra storage provider is required.

## Required backend environment

Use the existing TechNova MongoDB settings:

- `MONGODB_URI` — existing authenticated MongoDB connection string.
- `DATABASE_NAME` — existing TechNova database name.

No additional MongoDB connection string, bucket, access key, or S3 environment variables are needed for ID-card photos.

ClamAV is a separate malware-scanning service. Configure:

- `ID_PHOTO_CLAMAV_HOST` — private hostname/service name reachable by the backend.
- `ID_PHOTO_CLAMAV_PORT=3310` — optional; defaults to 3310.
- `ID_PHOTO_CLAMAV_TIMEOUT_SECONDS=8` — optional; defaults to 8, maximum 30.

Deploy ClamAV on a private network only. Do not expose its TCP port publicly. Keep virus definitions updated. The application does not deploy or manage the ClamAV daemon. If scanning is unavailable, uploads fail closed with HTTP 503.

## Photo handling and access

- Members must be active and explicitly opt in before upload.
- Input is limited to JPEG, PNG or WEBP, at most 5 MB and 12 megapixels.
- The backend decodes the image, applies EXIF orientation, flattens transparency, re-encodes as JPEG to strip metadata, and scans the normalized bytes with ClamAV INSTREAM.
- Malware detections are rejected. Scanner errors or missing configuration reject uploads.
- Image bytes stay in MongoDB GridFS and are served only through authenticated backend endpoints. No public object URLs are created.
- Secure MongoDB with TLS, authentication, least-privilege credentials, network allow-listing and encrypted backups.
- Only the owner or authorized Founder/Core Management staff during an active card verification can retrieve the photo.
- Every retrieval uses `Cache-Control: private, no-store`.
- Withdrawing consent disables retrieval immediately, removes the active database reference, and attempts to delete the corresponding GridFS file and chunks.

## Staging validation before production

1. Confirm the backend can connect to MongoDB over TLS and that GridFS writes and reads work in the intended TechNova database.
2. Deploy private ClamAV and verify the backend can reach it.
3. Upload a test image as a Member; verify a different Member cannot retrieve it.
4. Verify a valid active card as Founder/Core Management and confirm the consented photo loads.
5. Withdraw consent and confirm the verification photo endpoint no longer returns an image.
6. Revoke the card or suspend the member and confirm photo access is denied.
7. Confirm deletion removes the GridFS file and chunks.
8. Test the standard EICAR test file in a non-production environment; confirm it is rejected and never stored.

Do not enable production photo uploads until these staging checks pass.
