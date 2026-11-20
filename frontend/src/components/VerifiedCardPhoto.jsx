import React, { useEffect, useState } from "react";
import { API_BASE } from "../api/client.js";

/** Loads a verified card photo with the staff bearer token; never uses a public image URL. */
export default function VerifiedCardPhoto({ token, cardToken, enabled }) {
  const [photoUrl, setPhotoUrl] = useState("");
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    let objectUrl = "";
    setPhotoUrl("");
    setError("");
    if (!enabled || !token || !cardToken) {
      setStatus("unavailable");
      return undefined;
    }
    setStatus("loading");
    fetch(API_BASE + "/api/verify/" + encodeURIComponent(cardToken) + "/photo", {
      headers: { Authorization: "Bearer " + token, Accept: "image/jpeg" },
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) {
          let message = "No consented ID-card photo is available.";
          try {
            const body = await response.json();
            message = body?.detail || message;
          } catch {}
          throw new Error(message);
        }
        return response.blob();
      })
      .then((blob) => {
        if (!active) return;
        objectUrl = URL.createObjectURL(blob);
        setPhotoUrl(objectUrl);
        setStatus("ready");
      })
      .catch((requestError) => {
        if (!active) return;
        setError(requestError.message || "Could not load the ID-card photo.");
        setStatus("unavailable");
      });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [token, cardToken, enabled]);

  if (!enabled) return null;
  return (
    <div className="verified-card-photo" aria-live="polite">
      {status === "loading" && <span>Loading consented ID photo…</span>}
      {photoUrl && <img src={photoUrl} alt="Member ID-card photo for identity verification" />}
      {error && <small>{error}</small>}
    </div>
  );
}
