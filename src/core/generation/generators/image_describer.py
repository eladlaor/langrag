"""
Image Describer Service

Uses a vision-capable LLM to generate concise descriptions of images
extracted from WhatsApp group messages. Descriptions are cached in
MongoDB to avoid redundant API calls.

Single Responsibility: Image bytes → text description via vision LLM.
"""

import hashlib
import logging

import aiofiles

from config import VisionSettings
from constants import LlmInputPurposes, VISION_CACHE_PREFIX
from custom_types.common import ImageMetadata
from db.cache import CacheService
from utils.llm.interface import LLMProviderInterface

logger = logging.getLogger(__name__)

VISION_DESCRIPTION_PROMPT = (
    "You are analyzing an image shared in a WhatsApp group chat about AI/GenAI engineering.\n"
    "Describe this image in 1-2 concise sentences for a newsletter audience.\n"
    "Focus on: what is shown, why it might be relevant, any visible text/diagrams/tools.\n"
    "If it's a meme, briefly describe its message. If it's a screenshot, identify the tool."
)


async def describe_image(
    image: ImageMetadata,
    image_data: bytes,
    llm_provider: LLMProviderInterface,
    cache: CacheService | None,
    settings: VisionSettings,
) -> str | None:
    """
    Describe an image using a vision LLM, with caching.

    Args:
        image: ImageMetadata with mxc_url for cache key
        image_data: Raw image bytes
        llm_provider: LLM provider with call_with_vision method
        cache: CacheService for description caching (optional)
        settings: VisionSettings configuration

    Returns:
        Description string or None on failure
    """
    cache_key = _build_cache_key(image.mxc_url)

    # Check cache
    if cache:
        try:
            cached = await cache.get(VISION_CACHE_PREFIX, cache_key)
            if cached:
                logger.debug(f"Cache hit for image description: {image.image_id}")
                return cached
        except Exception as e:
            logger.debug(f"Cache lookup failed: {e}")

    # Call vision LLM
    try:
        description = await llm_provider.call_with_vision(
            purpose=LlmInputPurposes.DESCRIBE_IMAGE,
            prompt=VISION_DESCRIPTION_PROMPT,
            image_data=image_data,
            image_media_type=image.mimetype or "image/jpeg",
            model=settings.model,
            temperature=settings.temperature,
            max_tokens=settings.description_max_tokens,
        )

        if not description:
            return None

        # Cache the result
        if cache:
            try:
                await cache.set(
                    VISION_CACHE_PREFIX,
                    cache_key,
                    description,
                    ttl_days=settings.cache_ttl_days,
                )
            except Exception as e:
                logger.debug(f"Cache write failed: {e}")

        return description

    except Exception as e:
        logger.error(
            f"Vision LLM failed for image {image.image_id}: {e}",
            exc_info=True,
        )
        raise


async def describe_images_batch(
    images: list[ImageMetadata],
    llm_provider: LLMProviderInterface,
    cache: CacheService | None,
    settings: VisionSettings,
) -> list[ImageMetadata]:
    """
    Describe multiple images, updating each ImageMetadata in-place.

    Args:
        images: List of ImageMetadata with storage_path set
        llm_provider: LLM provider with call_with_vision
        cache: CacheService for caching
        settings: VisionSettings configuration

    Returns:
        Same list with description and description_model populated where successful
    """
    described_count = 0

    for image in images:
        if not image.storage_path:
            continue

        try:
            async with aiofiles.open(image.storage_path, "rb") as f:
                image_data = await f.read()
        except Exception as e:
            logger.warning(f"Failed to read image file {image.storage_path}: {e}")
            continue

        try:
            description = await describe_image(
                image=image,
                image_data=image_data,
                llm_provider=llm_provider,
                cache=cache,
                settings=settings,
            )
        except Exception as e:
            logger.warning(f"Skipping description for {image.image_id}: {e}")
            continue

        if description:
            image.description = description
            image.description_model = settings.model
            described_count += 1

    logger.info(f"Described {described_count}/{len(images)} images via vision LLM")
    return images


def _build_cache_key(mxc_url: str) -> str:
    """Build a deterministic cache key from an mxc URL."""
    return hashlib.sha256(mxc_url.encode()).hexdigest()[:32]
