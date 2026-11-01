import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api/client.js";

/** Management-only view of mandatory TOTP and the account's trusted browsers. */
export default function TwoFactorSettings({ token }) {
  const [status, setStatus] = useState(null);
  const [devices, setDevices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [nextStatus, nextDevices] = await Promise.all([
        api("/auth/2fa/status", token),
        api("/auth/2fa/devices", token),
      ]);
      setStatus(nextStatus);
      setDevices(nextDevices);
    } catch (err) {
      setError(err.message || "Could not load two-factor security settings.");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => { refresh(); }, [refresh]);

  async function revoke(deviceId) {
    setBusyId(deviceId);
    setError("");
    setMessage("");
    try {
      const result = await api("/auth/2fa/devices/" + encodeURIComponent(deviceId), token, { method: "DELETE" });
      setMessage(result.message);
      await refresh();
    } catch (err) {
      setError(err.message || "Could not revoke this trusted browser.");
    } finally {
      setBusyId("");
    }
  }

  return (
    <section className="two-factor-settings">
      <div className="two-factor-settings-head">
        <div>
          <span className="two-factor-kicker">MANAGEMENT SECURITY</span>
          <h3>Authenticator two-factor authentication</h3>
          <p>Required for Founder and Core Management. A trusted browser can skip the code prompt for up to 30 days.</p>
        </div>
        <span className={status?.enabled ? "two-factor-state enabled" : "two-factor-state"}>
          {loading ? "Checking…" : status?.enabled ? "Protected" : "Setup required"}
        </span>
      </div>
      {status && (
        <div className="two-factor-metrics">
          <span><b>{status.recovery_codes_remaining}</b><small>Recovery codes left</small></span>
          <span><b>{status.trusted_devices}</b><small>Trusted browsers</small></span>
          <span><b>{status.mandatory ? "Required" : "Optional"}</b><small>Management policy</small></span>
        </div>
      )}
      <div className="two-factor-device-list">
        <div className="two-factor-device-heading"><b>Trusted browsers</b><button type="button" className="textbtn" onClick={refresh} disabled={loading}>Refresh</button></div>
        {devices.map((device) => (
          <div className="two-factor-device" key={device.id}>
            <span>
              <b>{device.device}</b>
              <small>Last used: {device.last_seen_at ? new Date(device.last_seen_at).toLocaleString() : "Not recorded"} · Expires: {device.expires_at ? new Date(device.expires_at).toLocaleDateString() : "—"}</small>
            </span>
            <button type="button" className="secondary" onClick={() => revoke(device.id)} disabled={busyId === device.id}>{busyId === device.id ? "Revoking…" : "Revoke"}</button>
          </div>
        ))}
        {!loading && devices.length === 0 && <p className="two-factor-empty">No trusted browsers. You will be asked for an authenticator code at every management login.</p>}
      </div>
      {message && <p className="two-factor-success" role="status">{message}</p>}
      {error && <p className="two-factor-error" role="alert">{error}</p>}
      <small className="two-factor-footnote">Recovery codes are single-use. Keep them private and store them outside this browser. TechNova never displays the codes again after setup.</small>
    </section>
  );
}
