"""Environment-aware storage for generated evidence images.

Local Docker keeps using the existing generation directory. Vercel uses the
connected private Blob store and exposes images through an authenticated API
proxy; raw Blob credentials never reach the browser.
"""

import asyncio
import os
import urllib.request
from pathlib import Path

from backend.services.vision_base import guess_mime_type


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GENERATIONS_ROOT = PROJECT_ROOT / "frontend" / "assets" / "generations"
BLOB_PREFIX = "blob:"


def blob_enabled() -> bool:
    return bool(os.getenv("BLOB_READ_WRITE_TOKEN", "").strip())


def is_blob_reference(reference: str | None) -> bool:
    return bool(reference and reference.startswith(BLOB_PREFIX))


def blob_url(reference: str) -> str:
    if not is_blob_reference(reference):
        raise ValueError("Not a Blob image reference")
    return reference[len(BLOB_PREFIX):]


def save_image_bytes_sync(payload: bytes, filename: str, prefix: str = "generations") -> str:
    if blob_enabled():
        from vercel.blob import BlobClient

        result = BlobClient().put(
            f"{prefix.strip('/')}/{filename}",
            payload,
            access="private",
            content_type=guess_mime_type(payload),
            add_random_suffix=False,
        )
        return f"{BLOB_PREFIX}{result.url}"

    local_root = Path.cwd() / "frontend" / "assets" / "generations"
    suffix = prefix.removeprefix("generations").strip("/")
    destination = local_root / suffix / filename if suffix else local_root / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.part")
    temporary.write_bytes(payload)
    os.replace(temporary, destination)
    return destination.relative_to(local_root).as_posix()


async def save_image_bytes(payload: bytes, filename: str, prefix: str = "generations") -> str:
    return await asyncio.to_thread(save_image_bytes_sync, payload, filename, prefix)


def read_image_bytes_sync(reference: str) -> bytes:
    if is_blob_reference(reference):
        request = urllib.request.Request(
            blob_url(reference),
            headers={
                "Authorization": f"Bearer {os.environ['BLOB_READ_WRITE_TOKEN']}",
                "User-Agent": "AI-World-Lens/2.0",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read(12 * 1024 * 1024 + 1)
        if len(payload) > 12 * 1024 * 1024:
            raise ValueError("Stored image exceeded 12 MB")
        return payload

    safe_reference = Path(reference)
    if safe_reference.is_absolute() or ".." in safe_reference.parts:
        raise ValueError("Unsafe local image reference")
    path = (GENERATIONS_ROOT / safe_reference).resolve()
    if GENERATIONS_ROOT.resolve() not in path.parents or not path.is_file():
        raise FileNotFoundError(f"Generated image file was not found: {safe_reference.name}")
    return path.read_bytes()


async def read_image_bytes(reference: str) -> bytes:
    return await asyncio.to_thread(read_image_bytes_sync, reference)
