import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api/client.js";

/** Phone verification and member-controlled email, push and SMS notification preferences. */
export default function ContactNotificationSettings({ token }) {
  const [status, setStatus] = useState(null);
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [consent, setConsent] = useState(false);
  const [pending, setPending] = useState(false);
  const [preferences, setPreferences] = useState({
    email_enabled: true, push_enabled: true, sms_enabled: false,
  });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = await api("/auth/contact/status", token);
      setStatus(result);
      setPreferences(result.preferences || {
        email_enabled: true, push_enabled: true, sms_enabled: false,
      });
    } catch (err) {
      setError(err.message || "Could not load notification settings.");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => { refresh(); }, [refresh]);

  // Ask the backend to generate and send a fresh OTP; the server enforces consent, provider readiness, cooldown and expiry.
  async function requestCode(event) {
    event.preventDefault();
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await api("/auth/contact/phone/request", token, {
        method: "POST",
        body: JSON.stringify({ phone_number: phone.trim(), consent }),
      });
      setPending(true);
      setMessage(result.message);
    } catch (err) {
      setError(err.message || "Could not send the verification code.");
    } finally { setBusy(false); }
  }

  // Submit the six-digit OTP. A successful response refreshes the account status so the verified number is shown.
  async function verifyPhone(event) {
    event.preventDefault();
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await api("/auth/contact/phone/confirm", token, {
        method: "POST",
        body: JSON.stringify({ code: code.trim() }),
      });
      setPending(false); setCode(""); setConsent(false);
      setMessage(result.message);
      await refresh();
    } catch (err) {
      setError(err.message || "Phone verification failed.");
    } finally { setBusy(false); }
  }

  async function savePreferences(event) {
    event.preventDefault();
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await api("/auth/contact/preferences", token, {
        method: "PATCH",
        body: JSON.stringify(preferences),
      });
      setPreferences(result.preferences);
      setMessage(result.message);
      await refresh();
    } catch (err) {
      setError(err.message || "Could not save notification preferences.");
    } finally { setBusy(false); }
  }

  async function removePhone() {
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await api("/auth/contact/phone", token, { method: "DELETE" });
      setPending(false); setPhone(""); setCode("");
      setMessage(result.message);
      await refresh();
    } catch (err) {
      setError(err.message || "Could not remove the phone number.");
    } finally { setBusy(false); }
  }

  const smsProvider = status?.sms_provider || {};
  return (
    <section className="contact-notification-settings">
      <div className="contact-notification-head">
        <div>
          <span className="two-factor-kicker">CONTACT & ALERT PREFERENCES</span>
          <h3>Email, push and SMS preferences</h3>
          <p>Choose which channels may send your TechNova account and task alerts. SMS is disabled until you verify your number and turn it on.</p>
        </div>
      </div>
      <div className="contact-notification-providers">
        <span><b>Email</b><small>Brevo email notifications</small></span>
        <span><b>Push</b><small>Browser/device alerts</small></span>
        <span><b>SMS</b><small>{smsProvider.configured ? `${smsProvider.provider || "SMS provider"} ready` : `${smsProvider.provider || "SMS provider"} setup pending`}</small></span>
      </div>
      {!smsProvider.configured && (
        <p className="contact-notification-note">
          SMS is not ready yet. {smsProvider.missing?.length ? `The backend is missing: ${smsProvider.missing.join(", ")}. ` : ""}The Founder must add the required SMS credentials and an approved sender in the backend Render environment, then redeploy. The SMS provider must also have transactional SMS permission and sufficient credits.
        </p>
      )}
      {!status?.phone_verification_enabled ? (
        <div className="contact-notification-note" role="status">
          <b>Phone verification is temporarily paused.</b>
          <p>The OTP, phone verification and SMS notification functions are kept in the project but are disabled. They will be activated only when the TechNova owner decides to enable them.</p>
        </div>
      ) : status?.phone_verified ? (
        <div className="contact-verified-phone">
          <div><b>Verified phone</b><strong>{status.phone_masked}</strong><small>Verification consent recorded. SMS alerts still require separate opt-in.</small></div>
          <button type="button" className="secondary" onClick={removePhone} disabled={busy}>Remove</button>
        </div>
      ) : (
        <div className="contact-phone-form">
          <form onSubmit={pending ? verifyPhone : requestCode}>
            {!pending && (
              <>
                <label>Phone number with country code
                  <input type="tel" value={phone} onChange={(event) => setPhone(event.target.value)} placeholder="+919876543210" required pattern="\+[1-9][0-9]{7,14}" />
                </label>
                <label className="contact-consent">
                  <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} required />
                  <span>I consent to receive a one-time verification SMS and, only if I enable it below, transactional TechNova task, account and security alerts. Standard carrier charges may apply.</span>
                </label>
              </>
            )}
            {pending && (
              <label>Six-digit verification code
                <input inputMode="numeric" autoComplete="one-time-code" maxLength="6" pattern="[0-9]{6}" value={code} onChange={(event) => setCode(event.target.value)} placeholder="123456" required />
              </label>
            )}
            <button className="primary" disabled={busy || loading || (!pending && !smsProvider.configured) || (!pending && !consent)}>
              {busy ? "Please wait…" : pending ? "Verify phone number" : "Send verification code"}
            </button>
            {/* Return to phone entry; submitting again requests a fresh OTP after the backend resend cooldown. */}
            {pending && <button type="button" className="textbtn" onClick={() => {setPending(false); setCode("");}} disabled={busy}>Change phone number / resend</button>}
          </form>
        </div>
      )}
      <form className="contact-preferences-form" onSubmit={savePreferences}>
        {[
          ["email_enabled", "Email notifications", "Task assignments, review updates and account alerts."],
          ["push_enabled", "Push notifications", "Browser and mobile device notifications."],
          ["sms_enabled", "SMS notifications", "Short task summaries, security and important account alerts."],
        ].map(([key, label, description]) => (
          <label className="contact-preference-row" key={key}>
            <span><b>{label}</b><small>{description}</small></span>
            <input
              type="checkbox"
              checked={Boolean(preferences[key])}
              disabled={key === "sms_enabled" && (!status?.phone_verification_enabled || !status?.phone_verified || !status?.sms_consent)}
              onChange={(event) => setPreferences((current) => ({...current, [key]: event.target.checked}))}
            />
          </label>
        ))}
        <button className="secondary" type="submit" disabled={busy || loading}>Save notification preferences</button>
      </form>
      {message && <p className="contact-notification-success" role="status">{message}</p>}
      {error && <p className="two-factor-error" role="alert">{error}</p>}
      <small className="contact-notification-footnote">Transactional SMS is optional, can be switched off at any time, and is never enabled by default.</small>
    </section>
  );
}
