import React, { useEffect, useRef, useState } from "react";
import { api, API_BASE } from "../api/client.js";

/**
 * Member-controlled, separately uploaded ID-card photo.
 * This photo is not the private browser-encrypted profile image.
 */
export default function IdCardPhotoConsent({ token }) {
  const [consent, setConsent] = useState(false);
  const [savedConsent, setSavedConsent] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [photoUrl, setPhotoUrl] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const photoUrlRef = useRef("");

  function setManagedPhotoUrl(nextUrl) {
    if (photoUrlRef.current) URL.revokeObjectURL(photoUrlRef.current);
    photoUrlRef.current = nextUrl;
    setPhotoUrl(nextUrl);
  }

  async function refreshPhoto() {
    const response = await fetch(API_BASE + "/api/cards/me/photo", {
      headers: { Authorization: "Bearer " + token, Accept: "image/jpeg" },
      cache: "no-store",
    });
    if (response.status === 404) {
      setManagedPhotoUrl("");
      return;
    }
    if (!response.ok) {
      let detail = "Could not load your ID-card photo.";
      try { detail = (await response.json())?.detail || detail; } catch {}
      throw new Error(detail);
    }
    const blob = await response.blob();
    setManagedPhotoUrl(URL.createObjectURL(blob));
  }

  useEffect(() => {
    let active = true;
    api("/cards/me/photo-consent", token)
      .then(async (result) => {
        if (!active) return;
        setConsent(result.consent === true);
        setSavedConsent(result.consent === true);
        if (result.consent === true) {
          try { await refreshPhoto(); }
          catch (requestError) { if (active && requestError.status !== 404) setError(requestError.message); }
        }
      })
      .catch((requestError) => {
        if (active) setError(requestError.message || "Could not load your ID-photo preference.");
      })
      .finally(() => { if (active) setLoading(false); });
    return () => {
      active = false;
      if (photoUrlRef.current) URL.revokeObjectURL(photoUrlRef.current);
      photoUrlRef.current = "";
    };
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
      if (!nextConsent) {
        setManagedPhotoUrl("");
      }
      setMessage(nextConsent
        ? "Consent saved. Upload a separate photo below when you are ready."
        : "Consent withdrawn. Your ID-card photo has been removed from active storage.");
    } catch (requestError) {
      setConsent(savedConsent);
      setError(requestError.message || "Could not save your preference.");
    } finally {
      setSaving(false);
    }
  }

  async function uploadPhoto(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const file = form.elements.id_card_photo.files?.[0];
    setError("");
    setMessage("");
    if (!file) {
      setError("Choose a JPEG, PNG or WEBP photo first.");
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      setError("Choose an image no larger than 5 MB.");
      return;
    }
    setUploading(true);
    try {
      const body = new FormData();
      body.append("photo", file, file.name);
      await api("/cards/me/photo", token, { method: "POST", body, timeoutMs: 90000 });
      await refreshPhoto();
      setMessage("Your separate ID-card photo was securely uploaded.");
      form.reset();
    } catch (requestError) {
      setError(requestError.message || "Could not upload your ID-card photo.");
    } finally {
      setUploading(false);
    }
  }

  async function deletePhoto() {
    setUploading(true);
    setError("");
    setMessage("");
    try {
      await api("/cards/me/photo", token, { method: "DELETE" });
      setManagedPhotoUrl("");
      setMessage("Your ID-card photo was deleted.");
    } catch (requestError) {
      setError(requestError.message || "Could not delete your ID-card photo.");
    } finally {
      setUploading(false);
    }
  }

  return (
    <section className="id-photo-consent" aria-labelledby="id-photo-consent-title">
      <div className="id-photo-consent-heading">
        <span className="two-factor-kicker">DIGITAL ID PRIVACY</span>
        <h3 id="id-photo-consent-title">ID-card photo and consent</h3>
        <p>
          This is a separate photo from your private encrypted profile image.
          If you opt in, your separately uploaded photo can be viewed only by
          authenticated Founder or Core Management staff during an active ID
          verification. It is not a public image URL.
        </p>
      </div>
      {loading ? <p role="status">Loading your preference…</p> : (
        <>
          <label className="id-photo-consent-choice">
            <input
              type="checkbox"
              checked={consent}
              disabled={saving || uploading}
              onChange={(event) => setConsent(event.target.checked)}
            />
            <span>
              I explicitly consent to show my separately uploaded ID-card photo
              to authorized TechNova identity-verification staff.
            </span>
          </label>
          <div className="id-photo-consent-actions">
            <button
              type="button"
              className="primary"
              disabled={saving || consent === savedConsent}
              onClick={() => savePreference(consent)}
            >
              {saving ? "Saving…" : "Save consent"}
            </button>
            <button
              type="button"
              className="secondary"
              disabled={saving || uploading || !savedConsent}
              onClick={() => { setConsent(false); savePreference(false); }}
            >
              Withdraw consent and remove photo
            </button>
          </div>
          <small className="id-photo-consent-status">
            Saved status: {savedConsent ? "Opted in" : "Not opted in"}
          </small>
          {savedConsent && (
            <div className="id-photo-upload">
              {photoUrl ? (
                <div className="id-photo-preview">
                  <img src={photoUrl} alt="Your uploaded ID-card photo" />
                  <span>Separate ID-card photo</span>
                </div>
              ) : <p>No separate ID-card photo uploaded yet.</p>}
              <form onSubmit={uploadPhoto}>
                <label>
                  Upload ID-card photo (JPEG, PNG or WEBP · maximum 5 MB)
                  <input name="id_card_photo" type="file" accept="image/jpeg,image/png,image/webp" />
                </label>
                <button className="primary" type="submit" disabled={uploading}>
                  {uploading ? "Uploading…" : photoUrl ? "Replace ID-card photo" : "Upload ID-card photo"}
                </button>
              </form>
              {photoUrl && (
                <button className="secondary" type="button" onClick={deletePhoto} disabled={uploading}>
                  Delete photo
                </button>
              )}
            </div>
          )}
        </>
      )}
      {error && <p className="two-factor-error" role="alert">{error}</p>}
      {message && <p className="profile-image-message" role="status">{message}</p>}
    </section>
  );
}
