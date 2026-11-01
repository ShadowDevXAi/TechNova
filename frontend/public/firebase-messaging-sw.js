/* Firebase Messaging background service worker for TechNova. */
importScripts("https://www.gstatic.com/firebasejs/13.0.0/firebase-app-compat.js");
importScripts("https://www.gstatic.com/firebasejs/13.0.0/firebase-messaging-compat.js");

// The page supplies its current Firebase Web App config in the registration URL.
// Never keep a second, hard-coded API key here.
const configParam = new URL(self.location.href).searchParams.get("firebaseConfig");
let firebaseConfig;
try {
  firebaseConfig = JSON.parse(configParam || "null");
} catch {
  firebaseConfig = null;
}

if (
  !firebaseConfig ||
  !firebaseConfig.apiKey ||
  firebaseConfig.projectId !== "technova-f4460" ||
  !firebaseConfig.messagingSenderId ||
  !firebaseConfig.appId
) {
  throw new Error("TechNova Firebase Messaging service worker received an invalid Web App config.");
}

firebase.initializeApp(firebaseConfig);
const messaging = firebase.messaging();

// Activate config updates promptly when the frontend deploys a corrected Web App API key.
self.addEventListener("install", (event) => {
  event.waitUntil(self.skipWaiting());
});
self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

messaging.onBackgroundMessage((payload) => {
  const title = payload?.notification?.title || payload?.data?.title || "TechNova notification";
  const body = payload?.notification?.body || payload?.data?.body || "You have a new update.";
  const targetUrl = payload?.data?.url || "/";
  self.registration.showNotification(title, {
    body,
    data: { url: targetUrl },
    tag: payload?.data?.taskId || payload?.data?.type || "technova-update",
  });
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const targetUrl = event.notification?.data?.url || "/";
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const client of windows) {
      if ("focus" in client) {
        if ("navigate" in client) await client.navigate(targetUrl);
        return client.focus();
      }
    }
    return self.clients.openWindow(targetUrl);
  })());
});
