"""
Media Serving Router (admin-only)

Streams the raw bytes of extracted images back to the browser. Image bytes are
resolved through the MediaStorageInterface (LocalMediaStorage today, S3-ready)
rather than served as static files, so the storage abstraction and the admin
auth gate both stay in force.

Endpoint:
- GET /api/media/images/{image_id} -> raw image bytes with the stored mimetype
"""

from fastapi import APIRouter, Depends, HTTPException, Response

from constants import (
    HTTP_STATUS_NOT_FOUND,
    ROUTE_MEDIA_IMAGE,
)
from custom_types.api_schemas import CurrentUser
from custom_types.field_keys import ImageKeys
from api.auth import require_admin
from core.storage.media_storage import get_media_storage
from db.connection import get_database
from db.repositories.images import ImagesRepository
from observability.app import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="", tags=["media"], dependencies=[Depends(require_admin)])

_IMAGE_NOT_FOUND_MESSAGE = "Image not found"
_IMAGE_BYTES_MISSING_MESSAGE = "Image metadata exists but its stored bytes are missing"
_DEFAULT_IMAGE_MIMETYPE = "application/octet-stream"
# Bytes for a given image_id never change, so allow aggressive private caching.
_IMMUTABLE_CACHE_CONTROL = "private, max-age=86400, immutable"


@router.get(ROUTE_MEDIA_IMAGE)
async def serve_image(image_id: str, _: CurrentUser = Depends(require_admin)) -> Response:
    """Serve the raw bytes of a single extracted image by its image_id."""
    try:
        repo = ImagesRepository(await get_database())
        image = await repo.get_image_by_id(image_id)
        if image is None:
            raise HTTPException(status_code=HTTP_STATUS_NOT_FOUND, detail=_IMAGE_NOT_FOUND_MESSAGE)

        storage_path = image.get(ImageKeys.STORAGE_PATH)
        if not storage_path:
            logger.warning(
                "Image document has no storage_path",
                extra={"event": "media_serve_no_path", "function": "serve_image", "image_id": image_id},
            )
            raise HTTPException(status_code=HTTP_STATUS_NOT_FOUND, detail=_IMAGE_BYTES_MISSING_MESSAGE)

        storage = get_media_storage()
        if not await storage.exists(storage_path):
            logger.warning(
                "Image bytes missing from storage",
                extra={"event": "media_serve_missing_bytes", "function": "serve_image", "image_id": image_id, "storage_path": storage_path},
            )
            raise HTTPException(status_code=HTTP_STATUS_NOT_FOUND, detail=_IMAGE_BYTES_MISSING_MESSAGE)

        data = await storage.read(storage_path)
        mimetype = image.get(ImageKeys.MIMETYPE) or _DEFAULT_IMAGE_MIMETYPE
        return Response(
            content=data,
            media_type=mimetype,
            headers={"Cache-Control": _IMMUTABLE_CACHE_CONTROL},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "serve_image failed",
            extra={"event": "media_serve_error", "function": "serve_image", "image_id": image_id, "error": str(e)},
        )
        raise
