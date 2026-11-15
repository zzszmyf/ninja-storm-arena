"""Small dependency-free client for the ZenMux image API.

Wraps the two endpoints this project needs:

    POST /images/generations   text  -> image
    POST /images/edits         image + text -> image   (keeps a design consistent)

Both return base64 PNG payloads. Everything is done with the standard library
so the art pipeline only needs Pillow for post-processing.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import random
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

API_BASE = os.environ.get("NINJA_IMG_API_BASE", "https://zenmux.ai/api/v1")
MODEL = os.environ.get("NINJA_IMG_MODEL", "openai/gpt-image-2.5-flare")

_KEY_FILE = Path(__file__).resolve().parent / ".zenmux_key"

RETRYABLE = {408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524}


class ImageAPIError(RuntimeError):
    pass


def api_key() -> str:
    """Key lookup order: $ZENMUX_API_KEY, tools/.zenmux_key."""
    env = os.environ.get("ZENMUX_API_KEY")
    if env and env.strip():
        return env.strip()
    if _KEY_FILE.exists():
        text = _KEY_FILE.read_text().strip()
        if text:
            return text
    raise RuntimeError(
        "No ZenMux API key. Set ZENMUX_API_KEY or write tools/.zenmux_key."
    )


def _multipart(fields: dict, files: list) -> tuple[bytes, str]:
    """Build a multipart/form-data body. `files` is a list of (name, path)."""
    boundary = "----ninjaart" + uuid.uuid4().hex
    out = bytearray()
    for name, value in fields.items():
        if value is None:
            continue
        out += f"--{boundary}\r\n".encode()
        out += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        out += str(value).encode()
        out += b"\r\n"
    for name, path in files:
        path = Path(path)
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        out += f"--{boundary}\r\n".encode()
        out += (
            f'Content-Disposition: form-data; name="{name}"; filename="{path.name}"\r\n'
        ).encode()
        out += f"Content-Type: {ctype}\r\n\r\n".encode()
        out += path.read_bytes()
        out += b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def _post(path: str, body: bytes, content_type: str, timeout: float) -> bytes:
    req = urllib.request.Request(
        API_BASE + path,
        data=body,
        headers={
            "Authorization": "Bearer " + api_key(),
            "Content-Type": content_type,
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _extract_png(payload: bytes) -> bytes:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ImageAPIError("response was not JSON: " + payload[:300].decode("utf-8", "replace")) from exc
    if isinstance(data, dict) and data.get("error"):
        raise ImageAPIError(str(data["error"])[:400])
    items = data.get("data") if isinstance(data, dict) else None
    if not items:
        raise ImageAPIError("no image data in response: " + json.dumps(data)[:300])
    first = items[0]
    if first.get("b64_json"):
        return base64.b64decode(first["b64_json"])
    if first.get("url"):
        with urllib.request.urlopen(first["url"], timeout=180) as resp:
            return resp.read()
    raise ImageAPIError("image entry had neither b64_json nor url")


def _call(path: str, body: bytes, content_type: str, timeout: float, attempts: int) -> bytes:
    last = None
    for attempt in range(attempts):
        try:
            return _extract_png(_post(path, body, content_type, timeout))
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:400].decode("utf-8", "replace")
            last = ImageAPIError(f"HTTP {exc.code}: {detail}")
            if exc.code not in RETRYABLE:
                raise last from None
        except (urllib.error.URLError, TimeoutError, ImageAPIError) as exc:
            last = exc if isinstance(exc, ImageAPIError) else ImageAPIError(str(exc))
        if attempt < attempts - 1:
            time.sleep(min(30.0, 3.0 * (2**attempt)) + random.random() * 2.0)
    raise ImageAPIError(f"giving up after {attempts} attempts: {last}")


def generate(
    prompt: str,
    size: str = "1024x1536",
    quality: str = "high",
    transparent: bool = True,
    attempts: int = 4,
    timeout: float = 300.0,
) -> bytes:
    fields = {
        "model": MODEL,
        "prompt": prompt,
        "n": 1,
        "size": size,
        "quality": quality,
        "output_format": "png",
    }
    if transparent:
        fields["background"] = "transparent"
    # This endpoint wants a plain JSON body; sending multipart makes the
    # upstream service answer 500.
    body = json.dumps(fields).encode()
    return _call("/images/generations", body, "application/json", timeout, attempts)


def edit(
    prompt: str,
    images: list,
    size: str = "1024x1536",
    quality: str = "high",
    transparent: bool = True,
    input_fidelity: str | None = None,
    attempts: int = 4,
    timeout: float = 300.0,
) -> bytes:
    fields = {
        "model": MODEL,
        "prompt": prompt,
        "n": 1,
        "size": size,
        "quality": quality,
        "output_format": "png",
    }
    if transparent:
        fields["background"] = "transparent"
    if input_fidelity:
        fields["input_fidelity"] = input_fidelity
    files = [("image[]", str(p)) for p in images]
    body, ctype = _multipart(fields, files)
    return _call("/images/edits", body, ctype, timeout, attempts)


def save(png: bytes, dest) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(png)
    return dest
