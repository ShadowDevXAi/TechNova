"""Fail-closed ClamAV INSTREAM scanner for ID-card image payloads."""
from __future__ import annotations

import os
import socket
import struct


class ScannerUnavailable(RuntimeError):
    """ClamAV is not configured or could not be reached."""


class MalwareDetected(RuntimeError):
    """ClamAV identified a threat in the uploaded image."""


def parse_clamd_response(response: bytes) -> str:
    message = response.decode("utf-8", errors="replace").strip("\x00\r\n ")
    if message.endswith(": OK") or message == "OK":
        return "clean"
    if message.endswith(" FOUND"):
        raise MalwareDetected("ClamAV detected a threat in the uploaded image.")
    raise ScannerUnavailable("ClamAV returned an invalid or error response.")


def scan_image_bytes(payload: bytes) -> None:
    """Send bytes using ClamAV's INSTREAM protocol; never fail open."""
    host = os.getenv("ID_PHOTO_CLAMAV_HOST", "").strip()
    if not host:
        raise ScannerUnavailable("ID_PHOTO_CLAMAV_HOST is not configured.")
    try:
        port = int(os.getenv("ID_PHOTO_CLAMAV_PORT", "3310"))
        timeout = float(os.getenv("ID_PHOTO_CLAMAV_TIMEOUT_SECONDS", "8"))
        if not 1 <= port <= 65535 or not 1 <= timeout <= 30:
            raise ValueError("Invalid ClamAV port or timeout.")
        with socket.create_connection((host, port), timeout=timeout) as client:
            client.settimeout(timeout)
            client.sendall(b"zINSTREAM\0")
            for offset in range(0, len(payload), 64 * 1024):
                chunk = payload[offset:offset + 64 * 1024]
                client.sendall(struct.pack("!I", len(chunk)))
                client.sendall(chunk)
            client.sendall(struct.pack("!I", 0))
            response = bytearray()
            while b"\0" not in response and len(response) < 4096:
                part = client.recv(1024)
                if not part:
                    break
                response.extend(part)
        parse_clamd_response(bytes(response))
    except MalwareDetected:
        raise
    except ScannerUnavailable:
        raise
    except Exception as exc:
        raise ScannerUnavailable("ClamAV scan could not be completed.") from exc
