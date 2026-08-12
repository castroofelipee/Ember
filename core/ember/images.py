"""Cloudinary setup shared by every endpoint that accepts an image upload."""

from urllib.parse import urlparse

import cloudinary
from fastapi import HTTPException

from ember.config import env

MAX_IMAGE_BYTES = 10 * 1024 * 1024


def configure_cloudinary() -> None:
    parsed = urlparse(env["CLOUDINARY_URL"])
    if parsed.scheme != "cloudinary" or not all(
        (parsed.hostname, parsed.username, parsed.password)
    ):
        raise HTTPException(status_code=503, detail="Image uploads are not configured.")
    cloudinary.config(
        cloud_name=parsed.hostname,
        api_key=parsed.username,
        api_secret=parsed.password,
        secure=True,
    )
