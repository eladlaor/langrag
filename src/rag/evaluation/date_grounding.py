"""
Live ground-truth date resolution for the date-grounding eval.

DateGroundingMetric (src/rag/evaluation/custom_metrics.py) needs the TRUE date of
each cited source, derived *independently* of the date the chunk stored at ingest
time — otherwise the check is circular and proves nothing. This module is that
independent oracle: given a citation, it goes back to the source-of-truth and
re-derives the date the same way ingestion was supposed to, but from scratch.

  - newsletter: read start_date straight off the `newsletters` MongoDB document by
    source_id (the newsletter_id). This is the field NewsletterSource.extract reads
    to stamp source_date_start, so a chunk whose stored date disagrees with it was
    corrupted between read and write (the timezone / cache-key class of bug).
  - podcast: parse the YYYY-MM-DD prefix from the audio filename, with the manifest
    episode_date as an override — exactly PodcastSource's own contract, recomputed
    here without going through the chunk.

Used by the live integration eval (tests/integration/rag/test_date_grounding.py).
The offline CI gate uses golden-set expected_source_dates instead and never touches
this module, so the unit eval stays infra-free.

Fail-soft by design: a source we cannot resolve returns None and the metric skips
that citation (a golden-set / corpus gap is not a grounding failure). It never
fabricates a date — that would defeat the metric's whole purpose.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from constants import ContentSourceType, DIR_NAME_PODCASTS

logger = logging.getLogger(__name__)

_PODCAST_DATA_DIR = Path("data") / DIR_NAME_PODCASTS
_PODCAST_MANIFEST_FILENAME = "manifest.json"
_FILENAME_DATE_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def _parse_iso(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value[:10] if len(value) >= 10 else value)
        except ValueError:
            return None
    return None


async def _resolve_newsletter_true_date(source_id: str) -> datetime | None:
    """True start date from the newsletters collection, read independently of chunks."""
    try:
        from constants import DbFieldKeys
        from db.connection import get_database
        from db.repositories.newsletters import NewslettersRepository

        db = await get_database()
        repo = NewslettersRepository(db)
        newsletter = await repo.get_newsletter(source_id)
        if not newsletter:
            logger.warning("date_grounding: newsletter %s not found for ground-truth lookup", source_id)
            return None
        return _parse_iso(newsletter.get(DbFieldKeys.START_DATE))
    except Exception as e:  # noqa: BLE001 - oracle failure must not crash the eval; skip instead
        logger.warning("date_grounding: failed to resolve newsletter %s true date: %s", source_id, e)
        return None


def _resolve_podcast_true_date(
    source_id: str, source_title: str | None, audio_file: str | None = None
) -> datetime | None:
    """True episode date from filename prefix or manifest override, recomputed from disk.

    Podcast chunks key on an episode_id (uuid5 of the audio path), not the filename,
    so source_id alone rarely maps back to a file. The citation's metadata['audio_file']
    is the reliable join key (PodcastSource stamps it as audio_path.name); we fall back
    to source_id / source_title only when it's absent. We then re-derive the date the
    same way PodcastSource does — explicit manifest episode_date wins, else the
    YYYY-MM-DD filename prefix — WITHOUT reading the chunk's own stored episode_date
    (that would be circular: it is the value under test).
    """
    try:
        manifest_path = _PODCAST_DATA_DIR / _PODCAST_MANIFEST_FILENAME
        manifest: dict = {}
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())

        candidates = [audio_file, source_id, source_title]
        # Manifest is keyed by filename; match either the id or the title against it.
        for fname, entry in manifest.items():
            stem = Path(fname).stem
            if any(c and (c == fname or c == stem or c == entry.get("title")) for c in candidates):
                explicit = _parse_iso(entry.get("episode_date"))
                if explicit is not None:
                    return explicit
                m = _FILENAME_DATE_PATTERN.match(stem)
                if m:
                    return _parse_iso(m.group(1))

        # No manifest hit: try to find a file on disk whose stem/title matches.
        if _PODCAST_DATA_DIR.exists():
            for f in _PODCAST_DATA_DIR.iterdir():
                if not f.is_file():
                    continue
                if any(c and (c == f.name or c == f.stem) for c in candidates):
                    m = _FILENAME_DATE_PATTERN.match(f.stem)
                    if m:
                        return _parse_iso(m.group(1))
        logger.warning(
            "date_grounding: no podcast file/manifest match for audio_file=%s / id=%s / title=%s",
            audio_file, source_id, source_title,
        )
        return None
    except Exception as e:  # noqa: BLE001 - oracle failure must not crash the eval; skip instead
        logger.warning("date_grounding: failed to resolve podcast %s true date: %s", source_id, e)
        return None


async def resolve_true_source_date(citation: dict) -> datetime | None:
    """Return the true source date for a citation, derived from the source-of-truth.

    Routes by the citation's source_type. Returns None when the source can't be
    resolved (the metric skips it rather than failing). Never reads the citation's
    own source_date_* — that is the value under test.
    """
    source_type = citation.get("source_type")
    source_id = citation.get("source_id")
    source_title = citation.get("source_title")
    metadata = citation.get("metadata") or {}

    if source_type == ContentSourceType.NEWSLETTER:
        if not source_id:
            return None
        return await _resolve_newsletter_true_date(source_id)
    if source_type == ContentSourceType.PODCAST:
        return _resolve_podcast_true_date(source_id or "", source_title, metadata.get("audio_file"))

    logger.warning("date_grounding: unknown source_type %r; cannot resolve ground truth", source_type)
    return None


async def build_expected_source_dates(citations: list[dict]) -> dict[str, str]:
    """Build the {citation-key -> ISO date} map DateGroundingMetric consumes, live.

    The key matches custom_metrics._citation_key: source_id when present, else
    source_title. Unresolvable sources are omitted so the metric skips them.
    """
    expected: dict[str, str] = {}
    for cite in citations:
        key = cite.get("source_id") or cite.get("source_title")
        if not key or key in expected:
            continue
        true_date = await resolve_true_source_date(cite)
        if true_date is not None:
            expected[key] = true_date.date().isoformat()
    return expected
