import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api/client.js";

/** Shows whether task files will survive container replacements. */
export default function StorageSettings({ token }) {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try { setStatus(await api("/admin/storage/status", token)); }
    catch (err) { setError(err.message || "Could not check attachment storage."); }
    finally { setLoading(false); }
  }, [token]);
  useEffect(() => { refresh(); }, [refresh]);
  return (
    <section className="storage-settings">
      <div className="storage-settings-head">
        <div>
          <span className="two-factor-kicker">FILE STORAGE</span>
          <h3>Task attachment storage</h3>
          <p>Checks the configured storage adapter without exposing its credentials.</p>
        </div>
        <button type="button" className="textbtn" onClick={refresh} disabled={loading}>Refresh</button>
      </div>
      {loading ? <p>Checking storage configuration…</p> : status && (
        <>
          <p><b>Provider:</b> {status.provider}</p>
          <p><b>Status:</b> {status.configured ? "Configured" : "Not configured"}</p>
          <p><b>Persistence:</b> {status.durable ? "Durable object storage" : "Local disk — not guaranteed to survive container replacement"}</p>
          {status.missing?.length > 0 && <p className="two-factor-error">Missing: {status.missing.join(", ")}</p>}
          <small>{status.message}</small>
        </>
      )}
      {error && <p className="two-factor-error">{error}</p>}
    </section>
  );
}
