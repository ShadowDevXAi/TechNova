import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";

const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
const PBKDF2_ITERATIONS = 310000;

function toHex(bytes) {
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

function fromHex(value) {
  return new Uint8Array(value.match(/.{2}/g).map((part) => parseInt(part, 16)));
}

function toBase64(bytes) {
  let binary = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary);
}

function fromBase64(value) {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

async function deriveImageKey(passphrase, salt) {
  const material = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(passphrase),
    "PBKDF2",
    false,
    ["deriveKey"]
  );
  return crypto.subtle.deriveKey(
    { name: "PBKDF2", salt, iterations: PBKDF2_ITERATIONS, hash: "SHA-256" },
    material,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"]
  );
}

/** Member-only profile image UI. Passphrases and plaintext stay in this browser. */
export default function MemberProfileImage({ token }) {
  const [storedImage, setStoredImage] = useState(null);
  const [passphrase, setPassphrase] = useState("");
  const [photoUrl, setPhotoUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function loadEncryptedImage() {
    try {
      const result = await api("/profile-image", token);
      setStoredImage(result);
    } catch (requestError) {
      if (requestError.status === 404) {
        setStoredImage(null);
        return;
      }
      throw requestError;
    }
  }

  useEffect(() => {
    let active = true;
    api("/profile-image", token)
      .then((result) => { if (active) setStoredImage(result); })
      .catch((requestError) => {
        if (active && requestError.status !== 404) setError(requestError.message);
      });
    return () => { active = false; };
  }, [token]);

  useEffect(() => () => {
    if (photoUrl) URL.revokeObjectURL(photoUrl);
  }, [photoUrl]);

  async function unlockImage() {
    setError("");
    setMessage("");
    if (!storedImage) return;
    if (passphrase.length < 12) {
      setError("Enter the private image passphrase you used when uploading (at least 12 characters).");
      return;
    }
    setBusy(true);
    try {
      const key = await deriveImageKey(passphrase, fromHex(storedImage.salt));
      const clearBytes = await crypto.subtle.decrypt(
        { name: "AES-GCM", iv: fromHex(storedImage.iv), tagLength: 128 },
        key,
        fromBase64(storedImage.ciphertext)
      );
      const url = URL.createObjectURL(new Blob([clearBytes], { type: storedImage.media_type }));
      setPhotoUrl(url);
      setMessage("Your image was decrypted locally in this browser.");
    } catch {
      setError("Could not decrypt this image. Check the passphrase; it cannot be reset by TechNova.");
    } finally {
      setBusy(false);
    }
  }

  async function uploadImage(event) {
    event.preventDefault();
    setError("");
    setMessage("");
    const form = event.currentTarget;
    const file = form.elements.profile_image.files?.[0];
    if (!file) {
      setError("Choose a profile image first.");
      return;
    }
    if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
      setError("Choose a JPEG, PNG or WEBP image.");
      return;
    }
    if (file.size > MAX_IMAGE_BYTES) {
      setError("The original image must be 5 MB or smaller.");
      return;
    }
    if (passphrase.length < 12) {
      setError("Create a private image passphrase with at least 12 characters.");
      return;
    }
    if (!window.crypto?.subtle) {
      setError("This browser does not support secure Web Crypto. Open TechNova over HTTPS or a supported localhost origin.");
      return;
    }

    setBusy(true);
    try {
      const salt = crypto.getRandomValues(new Uint8Array(16));
      const iv = crypto.getRandomValues(new Uint8Array(12));
      const key = await deriveImageKey(passphrase, salt);
      const clearBytes = await file.arrayBuffer();
      const encrypted = await crypto.subtle.encrypt(
        { name: "AES-GCM", iv, tagLength: 128 },
        key,
        clearBytes
      );
      const formData = new FormData();
      formData.append("encrypted_file", new Blob([encrypted], { type: "application/octet-stream" }), "profile-image.enc");
      formData.append("salt", toHex(salt));
      formData.append("iv", toHex(iv));
      formData.append("media_type", file.type);
      await api("/profile-image", token, {
        method: "POST",
        body: formData,
        timeoutMs: 90000,
      });
      await loadEncryptedImage();
      setPhotoUrl(URL.createObjectURL(file));
      setMessage("Image encrypted in your browser and stored in the private Telegram channel.");
      form.reset();
    } catch (requestError) {
      setError(requestError.message || "Could not save the encrypted profile image.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="member-profile-image">
      <h3>Private profile image</h3>
      <p>
        Only you can decrypt this image. TechNova and Telegram store encrypted bytes, not your
        passphrase. Use a separate passphrase of at least 12 characters and keep it safe.
      </p>
      <div className="member-profile-image-preview">
        {photoUrl ? <img src={photoUrl} alt="Your decrypted profile" /> : <span>Image locked</span>}
      </div>
      {storedImage && (
        <p className="profile-image-status">
          Encrypted image stored · {storedImage.media_type} · {new Date(storedImage.updated_at).toLocaleString()}
        </p>
      )}
      <label>
        Private image passphrase
        <input
          type="password"
          autoComplete="off"
          value={passphrase}
          onChange={(event) => setPassphrase(event.target.value)}
          placeholder="At least 12 characters"
        />
      </label>
      <div className="profile-image-actions">
        {storedImage && (
          <button type="button" className="secondary" onClick={unlockImage} disabled={busy}>
            {busy ? "Working..." : "Unlock my image"}
          </button>
        )}
        <form onSubmit={uploadImage}>
          <label>
            Choose a new image
            <input name="profile_image" type="file" accept="image/jpeg,image/png,image/webp" />
          </label>
          <button className="primary" type="submit" disabled={busy}>
            {busy ? "Encrypting and saving..." : "Encrypt and save"}
          </button>
        </form>
      </div>
      {error && <p className="errorbanner" role="alert">{error}</p>}
      {message && <p className="profile-image-message" role="status">{message}</p>}
    </section>
  );
}
