/**
 * Reusable TechNova logo link.
 * Falls back to a text monogram if the external logo image cannot be loaded.
 */
import React, { useState } from "react";
import {
  TECHNOVA_LOGO_IMAGE_URL,
  TECHNOVA_LOGO_SHARE_URL,
} from "../config/branding.js";

export default function TechNovaLogo({ className = "" }) {
  const [failed, setFailed] = useState(false);

  return (
    <a
      className={("technova-logo-link " + className).trim()}
      href={TECHNOVA_LOGO_SHARE_URL}
      target="_blank"
      rel="noopener noreferrer"
      aria-label="Open the TechNova logo image"
    >
      {failed ? (
        <span className="technova-logo-fallback">TN</span>
      ) : (
        <img
          className="technova-logo-image"
          src={TECHNOVA_LOGO_IMAGE_URL}
          alt="TechNova logo"
          loading="eager"
          decoding="async"
          onError={() => setFailed(true)}
        />
      )}
    </a>
  );
}
