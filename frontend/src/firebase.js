/**
 * Firebase browser push helpers using the official compat CDN SDK.
 * Web App config and the VAPID public key are public client values.
 * Admin credentials must never be added to this frontend bundle.
 */
const firebaseConfig = {
  // Always supply the API key from Firebase Console > Project settings > Your apps > Web app.
  // Do not fall back to an old hard-coded key: stale/deleted keys cause Installations API failures.
  apiKey: (import.meta.env.VITE_FIREBASE_API_KEY || "").trim(),
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN || "technova-f4460.firebaseapp.com",
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID || "technova-f4460",
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET || "technova-f4460.firebasestorage.app",
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID || "788928273384",
  appId: import.meta.env.VITE_FIREBASE_APP_ID || "1:788928273384:web:b9685a1acf4a687308a25d",
  measurementId: import.meta.env.VITE_FIREBASE_MEASUREMENT_ID || "G-ETG8Q387EH",
};
const vapidKey = (import.meta.env.VITE_FIREBASE_VAPID_KEY || "").trim();
const sdkBase = "https://www.gstatic.com/firebasejs/13.0.0/";
let firebasePromise;

function validateFirebaseConfig() {
  if (!firebaseConfig.apiKey) {
    throw new Error(
      "The Firebase Web API key is missing. Add VITE_FIREBASE_API_KEY to the TechNova frontend Render service using the apiKey from Firebase Console > Project settings > Your apps > Web app, then rebuild and redeploy."
    );
  }
  if (firebaseConfig.projectId !== "technova-f4460") {
    throw new Error(
      "The Firebase Web App config belongs to a different project. TechNova expects project technova-f4460. Copy the config from the correct Firebase Web App."
    );
  }
}

function loadScript(filename) {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = sdkBase + filename;
    script.async = true;
    script.onload = resolve;
    script.onerror = () => reject(new Error("Firebase SDK could not be loaded. Check your internet connection."));
    document.head.appendChild(script);
  });
}

async function getFirebase() {
  if (typeof window === "undefined") throw new Error("Push notifications are available in a browser.");
  if (!firebasePromise) {
    firebasePromise = (async () => {
      validateFirebaseConfig();
      if (!window.firebase?.apps) await loadScript("firebase-app-compat.js");
      if (!window.firebase?.messaging) await loadScript("firebase-messaging-compat.js");
      if (!window.firebase.apps.length) window.firebase.initializeApp(firebaseConfig);
      const supported = await window.firebase.messaging.isSupported();
      if (!supported) throw new Error("This browser does not support Firebase web push. Try the latest Chrome or Edge over HTTPS.");
      return window.firebase;
    })().catch((error) => { firebasePromise = null; throw error; });
  }
  return firebasePromise;
}

async function getServiceWorkerRegistration() {
  if (!("serviceWorker" in navigator)) throw new Error("This browser does not support service workers.");
  validateFirebaseConfig();

  // Keep the background worker on the exact same Web App config as the page.
  // This prevents a stale, hard-coded API key in the worker from breaking token creation.
  const workerUrl = new URL("/firebase-messaging-sw.js", window.location.origin);
  workerUrl.searchParams.set("firebaseConfig", JSON.stringify(firebaseConfig));
  const registration = await navigator.serviceWorker.register(workerUrl.toString());
  await navigator.serviceWorker.ready;
  return registration;
}

/** Ask the person to opt in and register the current browser with Firebase. */
export async function enableBrowserPush() {
  if (!("Notification" in window)) throw new Error("This browser does not support notification permissions.");
  if (!vapidKey) throw new Error("The frontend VAPID public key is missing. Add VITE_FIREBASE_VAPID_KEY to the Render frontend environment and redeploy.");
  const firebase = await getFirebase();
  const permission = await Notification.requestPermission();
  if (permission !== "granted") throw new Error("Notification permission was not granted. Allow notifications for the TechNova website in browser settings.");
  const serviceWorkerRegistration = await getServiceWorkerRegistration();
  const token = await firebase.messaging().getToken({ vapidKey, serviceWorkerRegistration });
  if (!token) throw new Error("Firebase did not return a device token. Try enabling notifications again.");
  return token;
}

/** Read an already-authorized browser token without prompting. */
export async function getBrowserPushToken() {
  if (!("Notification" in window) || Notification.permission !== "granted") return "";
  const firebase = await getFirebase();
  const serviceWorkerRegistration = await getServiceWorkerRegistration();
  return await firebase.messaging().getToken({ vapidKey, serviceWorkerRegistration });
}

/** Delete the current browser token after it has been unregistered on the API. */
export async function deleteBrowserPushToken() {
  if (!("Notification" in window) || Notification.permission !== "granted") return false;
  const firebase = await getFirebase();
  return await firebase.messaging().deleteToken();
}

/** Subscribe to push messages while the portal tab is active. */
export async function listenForForegroundMessages(callback) {
  try {
    const firebase = await getFirebase();
    return firebase.messaging().onMessage(callback);
  } catch {
    return () => {};
  }
}
