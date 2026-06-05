"""
Extracted Images Gallery Router (admin-only)

Lists extracted-image metadata for the admin gallery. Supports any combination
of community (data_source_name), chat, discussion, and date-range filters, with
pagination. Each item is enriched with its associated discussion title and a
ready-to-use serving URL pointing at the media router.

Endpoint:
- GET /api/images -> paginated ExtractedImagesResponse
"""

from fastapi import APIRouter, Depends, Query

from constants import (
    API_V1_PREFIX,
    ROUTE_IMAGES,
)
from custom_types.api_schemas import (
    CurrentUser,
    ExtractedImageItem,
    ExtractedImagesResponse,
)
from custom_types.field_keys import DbFieldKeys, ImageKeys
from api.auth import require_admin
from db.connection import get_database
from db.repositories.discussions import DiscussionsRepository
from db.repositories.images import ImagesRepository
from observability.app import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="", tags=["images"], dependencies=[Depends(require_admin)])

_DEFAULT_GALLERY_LIMIT = 60
_MAX_GALLERY_LIMIT = 500


def _image_serving_url(image_id: str) -> str:
    """Build the media-serving URL the frontend uses as an <img> src."""
    return f"{API_V1_PREFIX}/media/images/{image_id}"


async def _resolve_discussion_titles(
    discussions_repo: DiscussionsRepository,
    discussion_ids: set[str],
) -> dict[str, str]:
    """Batch-resolve discussion_id -> title for the gallery's discussion links."""
    if not discussion_ids:
        return {}
    docs = await discussions_repo.find_many(
        {DbFieldKeys.DISCUSSION_ID: {"$in": list(discussion_ids)}},
        projection={DbFieldKeys.DISCUSSION_ID: 1, DbFieldKeys.TITLE: 1, "_id": 0},
    )
    return {doc[DbFieldKeys.DISCUSSION_ID]: doc.get(DbFieldKeys.TITLE) for doc in docs if doc.get(DbFieldKeys.DISCUSSION_ID)}


def _to_item(image: dict, discussion_titles: dict[str, str]) -> ExtractedImageItem:
    """Project a raw image document into the gallery response item."""
    image_id = image["_id"]
    discussion_id = image.get(ImageKeys.DISCUSSION_ID)
    return ExtractedImageItem(
        image_id=image_id,
        image_url=_image_serving_url(image_id),
        chat_name=image.get(ImageKeys.CHAT_NAME),
        data_source_name=image.get(ImageKeys.DATA_SOURCE_NAME),
        timestamp=image.get(ImageKeys.TIMESTAMP),
        sender_id=image.get(ImageKeys.SENDER_ID),
        mimetype=image.get(ImageKeys.MIMETYPE),
        width=image.get(ImageKeys.WIDTH),
        height=image.get(ImageKeys.HEIGHT),
        size_bytes=image.get(ImageKeys.SIZE_BYTES),
        filename=image.get(ImageKeys.FILENAME),
        description=image.get(ImageKeys.DESCRIPTION),
        discussion_id=discussion_id,
        discussion_title=discussion_titles.get(discussion_id) if discussion_id else None,
    )


@router.get(ROUTE_IMAGES, response_model=ExtractedImagesResponse)
async def list_extracted_images(
    data_source_name: str | None = Query(default=None, description="Filter by community / data source"),
    chat_name: str | None = Query(default=None, description="Filter by exact chat name"),
    discussion_id: str | None = Query(default=None, description="Filter by associated discussion"),
    start_date: str | None = Query(default=None, description="Inclusive start date (YYYY-MM-DD)"),
    end_date: str | None = Query(default=None, description="Inclusive end date (YYYY-MM-DD)"),
    limit: int = Query(default=_DEFAULT_GALLERY_LIMIT, ge=1, le=_MAX_GALLERY_LIMIT),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_admin),
) -> ExtractedImagesResponse:
    """List extracted images for the admin gallery, filtered and paginated."""
    try:
        db = await get_database()
        images_repo = ImagesRepository(db)
        discussions_repo = DiscussionsRepository(db)

        images = await images_repo.query_images(
            data_source_name=data_source_name,
            chat_name=chat_name,
            discussion_id=discussion_id,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset,
        )
        total = await images_repo.count_images(
            data_source_name=data_source_name,
            chat_name=chat_name,
            discussion_id=discussion_id,
            start_date=start_date,
            end_date=end_date,
        )

        discussion_ids = {img[ImageKeys.DISCUSSION_ID] for img in images if img.get(ImageKeys.DISCUSSION_ID)}
        discussion_titles = await _resolve_discussion_titles(discussions_repo, discussion_ids)

        items = [_to_item(img, discussion_titles) for img in images]
        logger.info(
            "Listed extracted images",
            extra={"event": "images_gallery_list", "function": "list_extracted_images", "returned": len(items), "total": total, "data_source_name": data_source_name, "chat_name": chat_name, "discussion_id": discussion_id},
        )
        return ExtractedImagesResponse(images=items, total=total, limit=limit, offset=offset)
    except Exception as e:
        logger.error(
            "list_extracted_images failed",
            extra={"event": "images_gallery_error", "function": "list_extracted_images", "error": str(e)},
        )
        raise
