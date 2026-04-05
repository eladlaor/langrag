"""
Image Downloader

Downloads images from mxc:// URLs via the Matrix media endpoint.
Uses httpx for async HTTP downloads with bounded concurrency.

Single Responsibility: Download image bytes from Matrix homeserver.
"""

import asyncio
import logging
import os
import re

import aiofiles
import httpx

from config import VisionSettings
from constants import AUTH_BEARER_PREFIX, DEFAULT_IMAGE_EXTENSION, HEADER_CONTENT_LENGTH, MIME_TO_EXTENSION
from custom_types.common import ImageMetadata

logger = logging.getLogger(__name__)

# Pattern: mxc://{server_name}/{media_id}
MXC_URL_PATTERN = re.compile(r"^mxc://([^/]+)/(.+)$")


def _mxc_to_http_url(mxc_url: str, homeserver_url: str) -> str | None:
    """
    Convert mxc:// URL to HTTP download URL.

    Args:
        mxc_url: Matrix content URI (mxc://server/media_id)
        homeserver_url: Homeserver base URL (e.g. https://matrix.beeper.com)

    Returns:
        HTTP URL for downloading, or None if mxc_url is invalid
    """
    match = MXC_URL_PATTERN.match(mxc_url)
    if not match:
        return None
    server_name, media_id = match.groups()
    return f"{homeserver_url.rstrip('/')}/_matrix/media/v3/download/{server_name}/{media_id}"


async def download_images(
    images: list[ImageMetadata],
    homeserver_url: str,
    access_token: str,
    target_dir: str,
    settings: VisionSettings,
) -> list[ImageMetadata]:
    """
    Download images from mxc:// URLs to local filesystem.

    Uses bounded concurrency via asyncio.Semaphore. Skips images that exceed
    max_image_size_bytes. Returns images with storage_path populated for
    successful downloads.

    Args:
        images: List of ImageMetadata with mxc_url set
        homeserver_url: Matrix homeserver URL for downloads
        access_token: Bearer token for authentication
        target_dir: Local directory to save downloaded images
        settings: VisionSettings with download configuration

    Returns:
        List of ImageMetadata with storage_path set (only successfully downloaded)
    """
    if not images:
        return []

    os.makedirs(target_dir, exist_ok=True)
    semaphore = asyncio.Semaphore(settings.download_concurrency)

    async def _download_one(image: ImageMetadata, client: httpx.AsyncClient) -> ImageMetadata | None:
        async with semaphore:
            try:
                http_url = _mxc_to_http_url(image.mxc_url, homeserver_url)
                if not http_url:
                    logger.warning(f"Invalid mxc URL: {image.mxc_url}")
                    return None

                # Determine filename
                ext = _get_extension(image.mimetype, image.filename)
                safe_filename = f"{image.image_id}{ext}"
                file_path = os.path.join(target_dir, safe_filename)

                # Skip if already downloaded
                if os.path.exists(file_path):
                    image.storage_path = file_path
                    return image

                headers = {"Authorization": f"{AUTH_BEARER_PREFIX} {access_token}"}

                # Stream download to avoid loading oversized files into memory
                async with client.stream("GET", http_url, headers=headers) as response:
                    response.raise_for_status()

                    # Pre-check Content-Length header if available
                    content_length = response.headers.get(HEADER_CONTENT_LENGTH)
                    if content_length and int(content_length) > settings.max_image_size_bytes:
                        logger.info(
                            f"Skipping oversized image (Content-Length {content_length} > "
                            f"{settings.max_image_size_bytes}): {image.filename}"
                        )
                        return None

                    # Stream body with size cap
                    chunks: list[bytes] = []
                    total_bytes = 0
                    async for chunk in response.aiter_bytes():
                        total_bytes += len(chunk)
                        if total_bytes > settings.max_image_size_bytes:
                            logger.info(
                                f"Aborting oversized download ({total_bytes} bytes > "
                                f"{settings.max_image_size_bytes}): {image.filename}"
                            )
                            return None
                        chunks.append(chunk)
                    data = b"".join(chunks)

                # Decrypt if encrypted (Matrix E2EE media)
                if image.encryption_key and image.encryption_iv and image.encryption_sha256:
                    data = await asyncio.to_thread(
                        _decrypt_attachment, data, image.encryption_key, image.encryption_sha256, image.encryption_iv
                    )

                # Write to disk (async)
                async with aiofiles.open(file_path, "wb") as f:
                    await f.write(data)

                image.storage_path = file_path
                image.size_bytes = len(data)
                return image

            except Exception as e:
                logger.error(
                    f"Failed to download image {image.mxc_url}: {e}",
                    exc_info=False,
                )
                return None

    async with httpx.AsyncClient(timeout=settings.download_timeout_seconds, follow_redirects=True) as client:
        tasks = [_download_one(img, client) for img in images]
        results = await asyncio.gather(*tasks)

    downloaded = [r for r in results if r is not None]
    failures = sum(1 for r in results if r is None)

    logger.info(
        f"Downloaded {len(downloaded)}/{len(images)} images "
        f"({failures} failures) to {target_dir}"
    )
    return downloaded


def _decrypt_attachment(ciphertext: bytes, key: str, sha256_hash: str, iv: str) -> bytes:
    """
    Decrypt Matrix E2EE encrypted media attachment.

    Uses matrix-nio's decrypt_attachment which handles AES-CTR decryption
    with integrity verification via SHA-256 hash.

    Args:
        ciphertext: Encrypted binary data
        key: AES-CTR JWK key string (content.file.key.k)
        sha256_hash: Base64 SHA-256 hash of ciphertext (content.file.hashes.sha256)
        iv: Base64 AES-CTR IV (content.file.iv)

    Returns:
        Decrypted plaintext bytes
    """
    from nio.crypto import decrypt_attachment
    return decrypt_attachment(ciphertext, key, sha256_hash, iv)


def _get_extension(mimetype: str, filename: str) -> str:
    """Determine file extension from mimetype or filename."""
    if filename and "." in filename:
        return os.path.splitext(filename)[1]
    return MIME_TO_EXTENSION.get(mimetype, DEFAULT_IMAGE_EXTENSION)
