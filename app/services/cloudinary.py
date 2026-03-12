import hashlib
import time
from typing import Optional

import httpx

from app.core.config import settings


class CloudinaryUploadError(Exception):
    pass


def cloudinary_is_configured() -> bool:
    return bool(
        (settings.cloudinary_cloud_name or "").strip()
        and (settings.cloudinary_api_key or "").strip()
        and (settings.cloudinary_api_secret or "").strip()
    )


def _sign_upload_params(params: dict[str, str], api_secret: str) -> str:
    serialized = "&".join(f"{key}={params[key]}" for key in sorted(params.keys()))
    payload = f"{serialized}{api_secret}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


async def upload_image_to_cloudinary(
    image_bytes: bytes,
    filename: str,
    content_type: str,
    folder: Optional[str] = None,
) -> str:
    cloud_name = (settings.cloudinary_cloud_name or "").strip()
    api_key = (settings.cloudinary_api_key or "").strip()
    api_secret = (settings.cloudinary_api_secret or "").strip()
    if not (cloud_name and api_key and api_secret):
        raise CloudinaryUploadError("Cloudinary credentials are not configured.")

    timestamp = str(int(time.time()))
    clean_folder = (folder or "").strip().strip("/")
    params_to_sign: dict[str, str] = {"timestamp": timestamp}
    if clean_folder:
        params_to_sign["folder"] = clean_folder

    signature = _sign_upload_params(params_to_sign, api_secret)
    form_data: dict[str, str] = {
        "api_key": api_key,
        "timestamp": timestamp,
        "signature": signature,
    }
    if clean_folder:
        form_data["folder"] = clean_folder

    endpoint = f"https://api.cloudinary.com/v1_1/{cloud_name}/image/upload"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                endpoint,
                data=form_data,
                files={"file": (filename, image_bytes, content_type)},
            )
    except httpx.HTTPError as exc:
        raise CloudinaryUploadError(f"Cloudinary request failed: {exc}") from exc

    if response.status_code >= 400:
        try:
            payload = response.json()
            message = payload.get("error", {}).get("message") or payload.get("message")
            if message:
                raise CloudinaryUploadError(f"Cloudinary upload failed: {message}")
        except Exception:
            pass
        raise CloudinaryUploadError(f"Cloudinary upload failed with status {response.status_code}.")

    try:
        payload = response.json()
    except Exception as exc:
        raise CloudinaryUploadError("Cloudinary returned invalid JSON.") from exc

    secure_url = str(payload.get("secure_url") or "").strip()
    if not secure_url:
        raise CloudinaryUploadError("Cloudinary response did not include secure_url.")
    return secure_url

