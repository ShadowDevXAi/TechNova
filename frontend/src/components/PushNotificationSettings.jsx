import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";
import { deleteBrowserPushToken, enableBrowserPush, getBrowserPushToken } from "../firebase.js";
import "../pushNotifications.css";

/** Per-account and per-browser push controls. Permission is requested only after opt-in. */
export default function PushNotificationSettings({ token }) {
  const [status, setStatus] = useState({ configured: false, registered_devices: 0 });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [enabledHere, setEnabledHere] = useState(Boolean(localStorage.getItem("tn_fcm_token")));
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    api("/push/status", token)
      .then((result) => { if (active) setStatus(result); })
      .catch((err) => { if (active) setError(err.message || "Could not load push status."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [token]);

  async function enable() {
    setBusy(true); setError(""); setMessage("");
    try {
      if (!status.configured) throw new Error("Firebase Admin is not configured on the backend yet. Add the Firebase service-account JSON as a Render Secret File, then redeploy the backend.");
      const deviceToken = await enableBrowserPush();
      const result = await api("/push/register", token, {
        method: "POST",
        body: JSON.stringify({ token: deviceToken, device_label: (navigator.userAgent || "Web browser").slice(0, 80) }),
      });
      localStorage.setItem("tn_fcm_token", deviceToken);
      setEnabledHere(true);
      setStatus((current) => ({ ...current, registered_devices: result.registered_devices }));
      setMessage("This browser is now registered. TechNova task and account alerts can appear here.");
    } catch (err) {
      setError(err.message || "Could not enable push notifications.");
    } finally { setBusy(false); }
  }

  async function disable() {
    setBusy(true); setError(""); setMessage("");
    try {
      const deviceToken = localStorage.getItem("tn_fcm_token") || await getBrowserPushToken();
      if (deviceToken) {
        await api("/push/unregister", token, { method: "POST", body: JSON.stringify({ token: deviceToken }) });
      }
      await deleteBrowserPushToken();
      localStorage.removeItem("tn_fcm_token");
      setEnabledHere(false);
      setStatus(await api("/push/status", token));
      setMessage("Push notifications are disabled for this browser. Browser permission can also be changed in site settings.");
    } catch (err) {
      setError(err.message || "Could not disable push notifications.");
    } finally { setBusy(false); }
  }

  return (
    <section className="push-settings-card">
      <div className="push-settings-heading">
        <div>
          <span className="push-settings-kicker">DEVICE NOTIFICATIONS</span>
          <h3>Mobile & browser push alerts</h3>
          <p>Receive TechNova task assignments, review updates, approvals, pauses and account alerts even when the portal is not open.</p>
        </div>
        <span className={enabledHere ? "push-status enabled" : "push-status"}>
          <i /> {enabledHere ? "This device enabled" : "This device not enabled"}
        </span>
      </div>
      <div className="push-settings-actions">
        <button type="button" className="primary" onClick={enable} disabled={busy || loading}>
          {busy ? "Please wait…" : enabledHere ? "Refresh this device" : "Enable push notifications"}
        </button>
        {enabledHere && <button type="button" className="secondary" onClick={disable} disabled={busy || loading}>Disable on this device</button>}
        <span className="push-device-count">{loading ? "Checking…" : (status.registered_devices || 0) + " device(s) registered to this account"}</span>
      </div>
      {!loading && !status.configured && <p className="push-settings-note">Backend setup is pending: add the Firebase Admin JSON as a Render Secret File and set FIREBASE_SERVICE_ACCOUNT_FILE.</p>}
      {message && <p className="push-settings-success" role="status">{message}</p>}
      {error && <p className="push-settings-error" role="alert">{error}</p>}
      <small className="push-settings-footnote">Permission is requested only when you press Enable. Each phone, tablet or browser must enable notifications separately. If permission was previously blocked, allow notifications in your browser's site settings.</small>
    </section>
  );
}
