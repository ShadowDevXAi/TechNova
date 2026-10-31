/* Firebase Messaging background service worker for TechNova. */
importScripts("https://www.gstatic.com/firebasejs/13.0.0/firebase-app-compat.js");
importScripts("https://www.gstatic.com/firebasejs/13.0.0/firebase-messaging-compat.js");

firebase.initializeApp({
  apiKey: "AIzaSyCo7Hoq-4xoE7QYlSSiJtpHilGIwWrQnNo",
  authDomain: "technova-f4460.firebaseapp.com",
  projectId: "technova-f4460",
  storageBucket: "technova-f4460.firebasestorage.app",
  messagingSenderId: "788928273384",
  appId: "1:788928273384:web:b9685a1acf4a687308a25d",
  measurementId: "G-ETG8Q387EH",
});

const messaging = firebase.messaging();
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
