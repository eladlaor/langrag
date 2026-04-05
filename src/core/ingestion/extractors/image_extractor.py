"""
Image Metadata Extractor

Parses raw extracted Matrix/Beeper messages and identifies image entries.
Extracts metadata (mxc URL, dimensions, mimetype, sender, timestamp) from
messages with msgtype == "m.image".

Handles both unencrypted (content.url) and encrypted (content.file.url) images.

Single Responsibility: Parse raw messages → produce ImageMetadata objects.
"""

import logging

from constants import MatrixMessageType
from custom_types.common import ImageMetadata
from custom_types.field_keys import (
    DecryptionResultKeys as DKeys,
    MatrixEncryptedFileKeys,
    MatrixImageInfoKeys,
)

logger = logging.getLogger(__name__)


class _ImageUrlInfo:
    """Extracted mxc URL and optional encryption parameters."""
    __slots__ = ("url", "key", "iv", "sha256")

    def __init__(self, url: str = "", key: str | None = None, iv: str | None = None, sha256: str | None = None):
        self.url = url
        self.key = key
        self.iv = iv
        self.sha256 = sha256


def _extract_mxc_url(content: dict) -> _ImageUrlInfo:
    """
    Extract mxc:// URL and encryption params from message content.

    Matrix has two patterns:
    - Unencrypted: content.url = "mxc://..."
    - Encrypted: content.file.url = "mxc://..." (with encryption keys alongside)

    Returns:
        _ImageUrlInfo with url and optional encryption keys
    """
    # Try unencrypted path first
    url = content.get(DKeys.URL, "")
    if url and url.startswith("mxc://"):
        return _ImageUrlInfo(url=url)

    # Try encrypted path: content.file.url
    file_obj = content.get(MatrixEncryptedFileKeys.FILE)
    if isinstance(file_obj, dict):
        url = file_obj.get(MatrixEncryptedFileKeys.URL, "")
        if url and url.startswith("mxc://"):
            key_obj = file_obj.get("key", {})
            return _ImageUrlInfo(
                url=url,
                key=key_obj.get("k") if isinstance(key_obj, dict) else None,
                iv=file_obj.get("iv"),
                sha256=file_obj.get("hashes", {}).get("sha256") if isinstance(file_obj.get("hashes"), dict) else None,
            )

    return _ImageUrlInfo()


def extract_image_metadata_from_raw_messages(
    raw_messages: list[dict],
    chat_name: str,
    data_source_name: str,
    max_images: int,
) -> list[ImageMetadata]:
    """
    Scan raw extracted messages for image entries and build ImageMetadata objects.

    Args:
        raw_messages: Raw messages from extraction (same JSON slm_prefilter reads)
        chat_name: WhatsApp group name
        data_source_name: Community identifier
        max_images: Maximum images to return (most recent kept)

    Returns:
        List of ImageMetadata objects, capped at max_images (most recent first)
    """
    images: list[ImageMetadata] = []

    for msg in raw_messages:
        content = msg.get(DKeys.CONTENT, {})
        if not isinstance(content, dict):
            continue

        msgtype = content.get(DKeys.MSGTYPE, "")
        if msgtype != MatrixMessageType.IMAGE:
            continue

        url_info = _extract_mxc_url(content)
        if not url_info.url:
            continue

        info = content.get(DKeys.INFO, {})
        if not isinstance(info, dict):
            info = {}

        # Use content.filename if present, fall back to content.body
        filename = content.get(MatrixEncryptedFileKeys.FILENAME, "") or content.get(DKeys.BODY, "")

        image = ImageMetadata(
            mxc_url=url_info.url,
            encryption_key=url_info.key,
            encryption_iv=url_info.iv,
            encryption_sha256=url_info.sha256,
            mimetype=info.get(MatrixImageInfoKeys.MIMETYPE, ""),
            width=info.get(MatrixImageInfoKeys.WIDTH),
            height=info.get(MatrixImageInfoKeys.HEIGHT),
            size_bytes=info.get(MatrixImageInfoKeys.SIZE),
            filename=filename,
            sender_id=msg.get(DKeys.SENDER, ""),
            timestamp=msg.get(DKeys.ORIGIN_SERVER_TS, 0),
            message_id=msg.get(DKeys.EVENT_ID, ""),
            chat_name=chat_name,
            data_source_name=data_source_name,
        )
        images.append(image)

    # Sort by timestamp descending (most recent first) and cap
    images.sort(key=lambda img: img.timestamp, reverse=True)
    if len(images) > max_images:
        logger.info(
            f"Capping images from {len(images)} to {max_images} for chat_name={chat_name}"
        )
        images = images[:max_images]

    logger.info(
        f"Extracted {len(images)} image metadata entries from {len(raw_messages)} "
        f"raw messages for chat_name={chat_name}"
    )
    return images
