"""
Newsletter → message provenance resolution (parent-document retrieval, D10).

A rag_chunks document is newsletter-derived text — a lossy summary of the
original WhatsApp discussions. To support parent-document retrieval (drilling
from a chunk down to the raw messages behind it), each newsletter chunk must
carry, in its metadata, the ids of the discussions that fed the newsletter and
the flattened raw-message ids behind those discussions.

This module is the single source of that resolution logic, reused by both the
ingest path (NewsletterSource.extract) and the one-shot backfill script, so the
two can never drift.

Granularity note: the linkage is WHOLE-NEWSLETTER. The newsletter LLM-output
schema has no per-section discussion id, so every chunk of a given newsletter
shares the same discussion_ids / message_ids set.
"""

import logging
from typing import Any

from custom_types.field_keys import DbFieldKeys
from db.repositories.discussions import DiscussionsRepository

logger = logging.getLogger(__name__)


def _newsletter_discussion_ids(newsletter: dict[str, Any]) -> list[str]:
    """Collect the discussion ids referenced by a stored newsletter document.

    Combines featured + brief-mention lists (brief is empty on most current
    newsletters but included for completeness). Order-preserving, deduped.
    """
    featured = newsletter.get(DbFieldKeys.FEATURED_DISCUSSION_IDS) or []
    brief = newsletter.get(DbFieldKeys.BRIEF_MENTION_DISCUSSION_IDS) or []
    seen: set[str] = set()
    ordered: list[str] = []
    for did in [*featured, *brief]:
        if did and did not in seen:
            seen.add(did)
            ordered.append(did)
    return ordered


async def resolve_newsletter_message_provenance(
    db: Any,
    newsletter: dict[str, Any],
) -> tuple[list[str], list[str]]:
    """Resolve a newsletter's (discussion_ids, message_ids) provenance.

    Args:
        db: An AsyncDatabase handle.
        newsletter: A stored newsletter document dict (must carry run_id and the
            featured/brief discussion-id lists).

    Returns:
        (discussion_ids, message_ids): the discussion ids that fed this
        newsletter, and the flattened, deduped raw-message ids behind them.
        Both empty when the newsletter references no discussions (legacy docs) —
        callers treat this as fail-soft, not an error.
    """
    newsletter_id = newsletter.get(DbFieldKeys.NEWSLETTER_ID, "")
    run_id = newsletter.get(DbFieldKeys.RUN_ID)
    discussion_ids = _newsletter_discussion_ids(newsletter)

    if not discussion_ids:
        logger.warning(
            "Newsletter %s has no featured/brief discussion ids; "
            "parent-document provenance will be empty (legacy newsletter).",
            newsletter_id,
        )
        return [], []

    try:
        discussions_repo = DiscussionsRepository(db)
        # Scope by run_id when present to avoid discussion-id collisions across
        # runs; fall back to id-only when a newsletter lacks run_id.
        query: dict[str, Any] = {DbFieldKeys.DISCUSSION_ID: {"$in": discussion_ids}}
        if run_id:
            query[DbFieldKeys.RUN_ID] = run_id

        discussions = await discussions_repo.find_many(
            query,
            projection=DiscussionsRepository._EXCLUDE_EMBEDDING_PROJECTION,
        )

        seen: set[str] = set()
        message_ids: list[str] = []
        for disc in discussions:
            for mid in disc.get(DbFieldKeys.MESSAGE_IDS) or []:
                if mid and mid not in seen:
                    seen.add(mid)
                    message_ids.append(mid)

        logger.info(
            "Resolved provenance for newsletter %s: %d discussions -> %d messages",
            newsletter_id,
            len(discussions),
            len(message_ids),
        )
        return discussion_ids, message_ids

    except Exception as e:
        logger.error(
            "Failed to resolve message provenance for newsletter %s: %s",
            newsletter_id,
            e,
            extra={"newsletter_id": newsletter_id, "run_id": run_id},
        )
        raise
