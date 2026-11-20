import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";

/**
 * Explicit opt-in for a future, separately stored ID-card photo.
 * This preference never unlocks or publishes the private encrypted profile image.
 */
export default function IdCardPhotoConsent({ token }) {
  const [consent, setConsent] = useState(false);
  const [savedConsent, setSavedConsent] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    let active = true;
    api("/cards/me/photo-consent", token)
      .then((result) => {
        if (!active) return;
        setConsent(result.consent === true);
        setSavedConsent(result.consent === true);
      })
      .catch((requestError) => {
        if (active) setError(requestError.message || "Could not load your ID-photo preference.");
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [token]);

  async function savePreference(nextConsent) {
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const result = await api("/cards/me/photo-consent", token, {
        method: "PUT",
        body: JSON.stringify({ consent: nextConsent }),
      });
      setConsent(result.consent === true);
      setSavedConsent(result.consent === true);
      setMessage(nextConsent
        ? "Your opt-in preference was saved. No photo is shared yet."
        : "Your photo-sharing consent has been withdrawn.");
    } catch (requestError) {
      setError(requestError.message || "Could not save your preference.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="id-photo-consent" aria-labelledby="id-photo-consent-title">
      <div className="id-photo-consent-heading">
        <span className="two-factor-kicker">DIGITAL ID PRIVACY</span>
        <h3 id="id-photo-consent-title">ID-card photo consent</h3>
        <p>
          This is separate from your private encrypted profile image. Choosing
          “Allow” records your preference for a future, separately uploaded card
          photo; it does not publish your private image or display any photo.
        </p>
      </div>
      {loading ? <p role="status">Loading your preference…</p> : (
        <>
          <label className="id-photo-consent-choice">
            <input
              type="checkbox"
              checked={consent}
              disabled={saving}
              onChange={(event) => setConsent(event.target.checked)}
            />
            <span>
              I explicitly allow a separately uploaded ID-card photo to be shown
              to authorized TechNova identity-verification staff when that feature
              becomes available.
            </span>
          </label>
          <div className="id-photo-consent-actions">
            <button
              type="button"
              className="primary"
              disabled={saving || consent === savedConsent}
              onClick={() => savePreference(consent)}
            >
              {saving ? "Saving…" : "Save preference"}
            </button>
            <button
              type="button"
              className="secondary"
              disabled={saving || !savedConsent}
              onClick={() => { setConsent(false); savePreference(false); }}
            >
              Withdraw consent
            </button>
          </div>
          <small className="id-photo-consent-status">
            Saved status: {savedConsent ? "Opted in" : "Not opted in"} · Photo sharing is not enabled yet.
          </small>
        </>
      )}
      {error && <p className="two-factor-error" role="alert">{error}</p>}
      {message && <p className="profile-image-message" role="status">{message}</p>}
    </section>
  );
}
