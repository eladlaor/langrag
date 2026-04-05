"""
Image Extraction Pipeline Node

Extracts, downloads, and optionally describes images from WhatsApp messages.
Follows the same fail-soft pattern as slm_prefilter.py — any failure logs
and returns empty stats without breaking the pipeline.

Node position in graph:
    ... → slm_prefilter → extract_images → preprocess_messages → ...

Configuration:
- VISION_ENABLED: Master toggle (default: false)
- enable_image_extraction: Per-request toggle in API request body
"""

import json
import logging
import os
from typing import Any

import aiofiles

from langchain_core.runnables import RunnableConfig

from api.sse import STAGE_EXTRACT_IMAGES, with_logging, with_progress
from config import get_settings, Settings
from constants import (
    DIR_NAME_IMAGES,
    NodeNames,
    VisionDescribeScope,
    WORKFLOW_NAME_NEWSLETTER_GENERATION,
    OUTPUT_FILENAME_IMAGE_MANIFEST,
    ENV_BEEPER_ACCESS_TOKEN,
)
from core.ingestion.extractors.image_extractor import extract_image_metadata_from_raw_messages
from core.ingestion.extractors.image_downloader import download_images
from core.storage.media_storage import LocalMediaStorage
from custom_types.common import ImageExtractionStats, ImageMetadata
from graphs.single_chat_analyzer.state import SingleChatState
from graphs.state_keys import SingleChatStateKeys as Keys
from observability.metrics import with_metrics

logger = logging.getLogger(__name__)


@with_logging
@with_progress(STAGE_EXTRACT_IMAGES, start_message="Extracting images from messages...")
@with_metrics(node_name=NodeNames.SingleChatAnalyzer.EXTRACT_IMAGES, workflow_name=WORKFLOW_NAME_NEWSLETTER_GENERATION)
async def extract_images_node(state: SingleChatState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """
    Extract images from raw messages, download them, and optionally describe via vision LLM.

    Behavior:
    - If VISION_ENABLED=false or enable_image_extraction=false: Skip, return empty stats
    - If extraction/download fails: Log and continue (fail-soft)
    - On success: Save image manifest, store metadata in MongoDB

    Args:
        state: Current workflow state with extracted_file_path
        config: LangGraph runnable config

    Returns:
        State update with image_extraction_stats, image_manifest_path, images_dir
    """
    settings = get_settings()

    # Gate: disabled by config OR by request
    if not settings.vision.enabled or not state.get(Keys.ENABLE_IMAGE_EXTRACTION):
        logger.info("Image extraction disabled, skipping")
        return {
            Keys.IMAGE_EXTRACTION_STATS: ImageExtractionStats(enabled=False).model_dump(),
        }

    extracted_file_path = state.get(Keys.EXTRACTED_FILE_PATH)
    if not extracted_file_path or not os.path.exists(extracted_file_path):
        logger.warning("No extracted_file_path in state or file not found, skipping image extraction")
        return {
            Keys.IMAGE_EXTRACTION_STATS: ImageExtractionStats(enabled=True).model_dump(),
        }

    chat_name = state.get(Keys.CHAT_NAME)
    data_source_name = state.get(Keys.DATA_SOURCE_NAME)
    output_dir = state.get(Keys.OUTPUT_DIR)
    mongodb_run_id = state.get(Keys.MONGODB_RUN_ID)

    stats = ImageExtractionStats(enabled=True)

    if not chat_name or not data_source_name or not output_dir:
        logger.error(
            f"Missing required state fields for image extraction: "
            f"chat_name={chat_name}, data_source_name={data_source_name}, output_dir={output_dir}"
        )
        return {Keys.IMAGE_EXTRACTION_STATS: stats.model_dump()}

    try:
        # 1. Load raw messages (async)
        async with aiofiles.open(extracted_file_path, encoding="utf-8") as f:
            content = await f.read()
        raw_messages = json.loads(content)

        if not isinstance(raw_messages, list):
            logger.warning("Extracted messages not a list, skipping image extraction")
            return {Keys.IMAGE_EXTRACTION_STATS: stats.model_dump()}

        # 2. Extract image metadata from raw messages
        images = extract_image_metadata_from_raw_messages(
            raw_messages=raw_messages,
            chat_name=chat_name,
            data_source_name=data_source_name,
            max_images=settings.vision.max_images_per_chat,
        )

        stats.total_images_found = len(images)

        if not images:
            logger.info(f"No images found in {len(raw_messages)} messages for chat_name={chat_name}")
            return {Keys.IMAGE_EXTRACTION_STATS: stats.model_dump()}

        # 3. Deduplicate against MongoDB (skip already-stored images)
        images = await _deduplicate_images(images)

        if not images:
            logger.info(f"All images already stored for chat_name={chat_name}")
            return {Keys.IMAGE_EXTRACTION_STATS: stats.model_dump()}

        # 4. Validate access token
        access_token = os.getenv(ENV_BEEPER_ACCESS_TOKEN)
        if not access_token:
            logger.error(f"{ENV_BEEPER_ACCESS_TOKEN} not set, cannot download images")
            return {Keys.IMAGE_EXTRACTION_STATS: stats.model_dump()}

        # 5. Download images
        images_dir = os.path.join(output_dir, DIR_NAME_IMAGES)
        os.makedirs(images_dir, exist_ok=True)

        homeserver_url = settings.beeper.base_url

        downloaded_images = await download_images(
            images=images,
            homeserver_url=homeserver_url,
            access_token=access_token,
            target_dir=images_dir,
            settings=settings.vision,
        )

        stats.images_downloaded = len(downloaded_images)
        stats.download_failures = len(images) - len(downloaded_images)

        # 6. Optionally describe via vision LLM (before persist, while storage_path is absolute)
        if settings.vision.describe_scope == VisionDescribeScope.ALL and downloaded_images:
            described_images = await _describe_images(downloaded_images, settings)
            stats.images_described = sum(1 for img in described_images if img.description)
            stats.vision_failures = len(downloaded_images) - stats.images_described
            downloaded_images = described_images

        # 7. Persist to persistent storage and MongoDB (updates storage_path to relative)
        await _persist_to_storage_and_db(downloaded_images, data_source_name, chat_name, mongodb_run_id, settings)

        # 8. Save image manifest
        manifest_path = os.path.join(images_dir, OUTPUT_FILENAME_IMAGE_MANIFEST)
        manifest_data = [img.model_dump() for img in downloaded_images]
        async with aiofiles.open(manifest_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(manifest_data, ensure_ascii=False, indent=2))

        logger.info(
            f"Image extraction complete for chat_name={chat_name}: "
            f"found={stats.total_images_found}, downloaded={stats.images_downloaded}, "
            f"described={stats.images_described}"
        )

        return {
            Keys.IMAGE_EXTRACTION_STATS: stats.model_dump(),
            Keys.IMAGE_MANIFEST_PATH: manifest_path,
            Keys.IMAGES_DIR: images_dir,
        }

    except Exception as e:
        logger.error(
            f"Image extraction failed for chat_name={chat_name}: {e}",
            exc_info=True,
        )
        # Fail-soft: don't break pipeline
        return {Keys.IMAGE_EXTRACTION_STATS: stats.model_dump()}


async def _deduplicate_images(images: list[ImageMetadata]) -> list[ImageMetadata]:
    """Remove images already stored in MongoDB (by mxc_url), using a single $in query."""
    try:
        from db.connection import get_database
        from db.repositories.images import ImagesRepository

        db = await get_database()
        repo = ImagesRepository(db)

        mxc_urls = [img.mxc_url for img in images]
        existing_urls = await repo.find_existing_mxc_urls(mxc_urls)

        new_images = [img for img in images if img.mxc_url not in existing_urls]

        if len(images) != len(new_images):
            logger.info(
                f"Deduplication: {len(images)} → {len(new_images)} images "
                f"({len(images) - len(new_images)} already stored)"
            )
        return new_images

    except Exception as e:
        logger.warning(f"MongoDB deduplication failed, proceeding with all images: {e}")
        return images


async def _persist_to_storage_and_db(
    images: list[ImageMetadata],
    data_source_name: str,
    chat_name: str,
    mongodb_run_id: str | None,
    settings: Settings,
) -> None:
    """Copy downloaded images to persistent storage and save metadata to MongoDB."""
    try:
        storage = LocalMediaStorage(base_dir=settings.vision.media_base_dir)

        for image in images:
            if not image.storage_path or not os.path.exists(image.storage_path):
                continue

            # Build persistent path
            persistent_path = storage.get_persistent_path(
                data_source_name=data_source_name,
                chat_name=chat_name,
                timestamp_ms=image.timestamp,
                image_id=image.image_id,
                filename=image.filename,
            )

            # Use storage interface — only copy if not already stored
            if not await storage.exists(persistent_path):
                async with aiofiles.open(image.storage_path, "rb") as f:
                    data = await f.read()
                await storage.store(image.image_id, data, persistent_path)

            image.storage_path = persistent_path

        # Store in MongoDB
        if mongodb_run_id:
            from db.connection import get_database
            from db.repositories.images import ImagesRepository

            db = await get_database()
            repo = ImagesRepository(db)
            stored = await repo.store_images_batch(images, mongodb_run_id)
            logger.info(f"Stored {stored} image metadata documents in MongoDB")

    except Exception as e:
        logger.warning(f"Failed to persist images to storage/MongoDB: {e}")


async def _describe_images(
    images: list[ImageMetadata],
    settings: Settings,
) -> list[ImageMetadata]:
    """Describe images using vision LLM."""
    try:
        from core.generation.generators.image_describer import describe_images_batch
        from utils.llm.openai_provider import OpenAIProvider
        from db.cache import CacheService
        from constants import DEFAULT_LLM_PROVIDER

        if settings.vision.provider != DEFAULT_LLM_PROVIDER:
            logger.warning(
                f"Vision provider '{settings.vision.provider}' not supported for image description, "
                f"only '{DEFAULT_LLM_PROVIDER}' is currently implemented. Skipping."
            )
            return images

        llm_provider = OpenAIProvider()
        cache = CacheService(ttl_days=settings.vision.cache_ttl_days)

        return await describe_images_batch(
            images=images,
            llm_provider=llm_provider,
            cache=cache,
            settings=settings.vision,
        )
    except Exception as e:
        logger.warning(f"Vision description failed: {e}")
        return images
