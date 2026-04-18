"""
Image-to-Discussion Association Node

Maps extracted images to discussions by matching ImageMetadata.message_id
to Discussion.messages[].id. Produces a discussion_id -> image descriptions
map consumed by the generate_content node.

Node position in graph:
    ... -> rank_discussions -> associate_images -> generate_content -> ...

Fail-soft: any failure logs and returns None without breaking the pipeline.
"""

import json
import logging
import os
from collections import defaultdict
from typing import Any

from langchain_core.runnables import RunnableConfig

from constants import NodeNames, WORKFLOW_NAME_NEWSLETTER_GENERATION, MAX_IMAGES_PER_DISCUSSION, MAX_IMAGES_TOTAL
from custom_types.field_keys import DiscussionKeys, ImageKeys
from graphs.single_chat_analyzer.state import SingleChatState
from graphs.state_keys import SingleChatStateKeys as Keys
from observability.metrics import with_metrics
from api.sse import with_logging

logger = logging.getLogger(__name__)

@with_logging
@with_metrics(node_name=NodeNames.SingleChatAnalyzer.ASSOCIATE_IMAGES, workflow_name=WORKFLOW_NAME_NEWSLETTER_GENERATION)
async def associate_images_node(state: SingleChatState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """
    Associate extracted images with discussions by matching message IDs.

    Behavior:
    - If images disabled or no manifest: Skip, return None map
    - If association fails: Log and return None map (fail-soft)
    - On success: Return image_discussion_map and update MongoDB discussion_id fields

    Args:
        state: Current workflow state with image_manifest_path and separate_discussions_file_path
        config: LangGraph runnable config

    Returns:
        State update with image_discussion_map (dict or None)
    """
    if not state.get(Keys.ENABLE_IMAGE_EXTRACTION) or not state.get(Keys.IMAGE_MANIFEST_PATH):
        logger.info("Image extraction disabled or no manifest, skipping image association")
        return {Keys.IMAGE_DISCUSSION_MAP: None}

    manifest_path = state[Keys.IMAGE_MANIFEST_PATH]
    discussions_path = state.get(Keys.SEPARATE_DISCUSSIONS_FILE_PATH)

    if not os.path.exists(manifest_path):
        logger.warning(f"Image manifest not found at {manifest_path}, skipping association")
        return {Keys.IMAGE_DISCUSSION_MAP: None}

    if not discussions_path or not os.path.exists(discussions_path):
        logger.warning(f"Discussions file not found at {discussions_path}, skipping association")
        return {Keys.IMAGE_DISCUSSION_MAP: None}

    try:
        image_discussion_map = _build_image_discussion_map(manifest_path, discussions_path)
        if image_discussion_map:
            logger.info(f"Associated images with {len(image_discussion_map)} discussions, " f"{sum(len(imgs) for imgs in image_discussion_map.values())} total image descriptions")
            await _update_mongodb_discussion_ids(manifest_path, image_discussion_map)
        else:
            logger.info("No images matched any discussions")
        return {Keys.IMAGE_DISCUSSION_MAP: image_discussion_map if image_discussion_map else None}
    except Exception as e:
        logger.error(f"Failed to associate images with discussions: {e}", extra={"error": str(e)})
        return {Keys.IMAGE_DISCUSSION_MAP: None}


def _build_image_discussion_map(manifest_path: str, discussions_path: str) -> dict[str, list[dict]]:
    """
    Build mapping of discussion_id -> list of image description dicts.

    Matches images to discussions by comparing ImageMetadata.message_id
    against Discussion.messages[].id.

    Returns:
        Dict mapping discussion_id to list of dicts with description, filename, timestamp.
        Empty dict if no matches found.
    """
    try:
        with open(manifest_path, encoding="utf-8") as f:
            images = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise ValueError(f"Failed to load image manifest from {manifest_path}: {e}") from e

    try:
        with open(discussions_path, encoding="utf-8") as f:
            discussions_data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise ValueError(f"Failed to load discussions from {discussions_path}: {e}") from e

    discussions = discussions_data.get(DiscussionKeys.DISCUSSIONS, discussions_data) if isinstance(discussions_data, dict) else discussions_data

    # Build message_id -> discussion_id lookup from all discussions
    message_to_discussion: dict[str, str] = {}
    for disc in discussions:
        disc_id = disc.get(DiscussionKeys.ID)
        if not disc_id:
            continue
        for msg in disc.get(DiscussionKeys.MESSAGES, []):
            msg_id = msg.get(DiscussionKeys.ID)
            if msg_id:
                message_to_discussion[msg_id] = disc_id

    # Match images to discussions
    raw_map: dict[str, list[dict]] = defaultdict(list)
    for image in images:
        description = image.get(ImageKeys.DESCRIPTION)
        message_id = image.get(ImageKeys.MESSAGE_ID)
        if not description or not message_id:
            continue

        disc_id = message_to_discussion.get(message_id)
        if disc_id:
            raw_map[disc_id].append({
                ImageKeys.DESCRIPTION: description,
                ImageKeys.FILENAME: image.get(ImageKeys.FILENAME, ""),
                ImageKeys.TIMESTAMP: image.get(ImageKeys.TIMESTAMP),
                ImageKeys.IMAGE_ID: image.get(ImageKeys.IMAGE_ID, ""),
            })

    # Apply caps: max per discussion and total
    result: dict[str, list[dict]] = {}
    total_count = 0
    for disc_id, img_list in raw_map.items():
        capped = img_list[:MAX_IMAGES_PER_DISCUSSION]
        remaining_budget = MAX_IMAGES_TOTAL - total_count
        if remaining_budget <= 0:
            break
        capped = capped[:remaining_budget]
        result[disc_id] = capped
        total_count += len(capped)

    return result


async def _update_mongodb_discussion_ids(manifest_path: str, image_discussion_map: dict[str, list[dict]]) -> None:
    """
    Update MongoDB images with their associated discussion_id (fail-soft).

    Builds a reverse lookup from image_id -> discussion_id and updates each.
    """
    try:
        from db.connection import get_database
        from db.repositories.images import ImagesRepository

        db = await get_database()
        repo = ImagesRepository(db)

        image_to_discussion: dict[str, str] = {}
        for disc_id, img_list in image_discussion_map.items():
            for img in img_list:
                img_id = img.get(ImageKeys.IMAGE_ID)
                if img_id:
                    image_to_discussion[img_id] = disc_id

        updated = 0
        for image_id, discussion_id in image_to_discussion.items():
            try:
                await repo.update_discussion_id(image_id, discussion_id)
                updated += 1
            except Exception as e:
                logger.warning(f"Failed to update discussion_id for image {image_id}: {e}")

        logger.info(f"Updated discussion_id for {updated}/{len(image_to_discussion)} images in MongoDB")
    except Exception as e:
        logger.warning(f"Failed to update MongoDB discussion IDs (non-critical): {e}")
