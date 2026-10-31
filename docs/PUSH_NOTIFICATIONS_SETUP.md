# TechNova Firebase Push Notifications

## What this adds
- Opt-in browser/mobile push controls under **Settings**.
- Per-user device-token registration and removal.
- Push delivery alongside existing in-app and optional SMTP notifications.
- Foreground alerts while the portal is open and service-worker notifications while it is in the background.
- Push events for existing task notifications, plus task/common-mission pause/resume and member reinstatement.

## Frontend configuration
The Firebase Web App config is public client configuration. It is set to the TechNova project in `src/firebase.js` and `public/firebase-messaging-sw.js`; optional Vite overrides are documented in `.env.example`.

Set this in the **Render frontend service**:
```env
VITE_FIREBASE_VAPID_KEY=YOUR_FIREBASE_WEB_PUSH_PUBLIC_KEY
```
Vite variables are embedded at build time. Save and redeploy the frontend after adding it.

## Backend service-account secret
Never commit the Firebase Admin JSON or paste its private key into source code.

In Render, open the **backend** service `technova-5h0g`:
1. Open **Environment**.
2. Under **Secret Files**, choose **Add Secret File**.
3. Use the filename `firebase-service-account.json`.
4. Paste the complete downloaded Firebase Admin service-account JSON into the secret-file editor.
5. Add these backend environment variables:
```env
FIREBASE_SERVICE_ACCOUNT_FILE=/etc/secrets/firebase-service-account.json
FIREBASE_PROJECT_ID=technova-f4460
```
6. Save and redeploy the backend.

The backend initializes Firebase Admin lazily and leaves ordinary portal operations working if this optional file is absent or invalid.

## Enable notifications
1. Open TechNova over HTTPS and sign in.
2. Open **Settings**.
3. Under **Mobile & browser push alerts**, press **Enable push notifications**.
4. Allow browser notification permission.

Each device/browser needs its own opt-in. Disabling in TechNova removes only the current browser token from the signed-in account. Logging out also unregisters this browser token.

## Verify and troubleshoot
- Authenticated `GET /api/push/status` reports Firebase Admin setup and this account's registered-device count.
- Assign a test task to an opted-in member and confirm they receive the in-app notification and push alert.
- If backend setup is pending, check the Render Secret File path and `FIREBASE_SERVICE_ACCOUNT_FILE`.
- If the VAPID key is missing, add `VITE_FIREBASE_VAPID_KEY` to the Render frontend environment and redeploy.
- If permission was blocked, allow notifications in the browser's site settings.
- Never put the Admin JSON in frontend variables, GitHub, or a `VITE_*` variable.
