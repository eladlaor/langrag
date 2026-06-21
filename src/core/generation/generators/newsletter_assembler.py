"""
Newsletter Assembler — Deterministic metadata from source data.

Used by the /newsletter-iterate skill to produce newsletter JSON that is
guaranteed to have real timestamps and metadata (never hallucinated).

The assembler takes editorial content (titles, bullet points, worth_mentioning)
and merges it with verified metadata pulled from merged_discussions.json.

Usage from CLI / Docker exec:
    python -m core.generation.generators.newsletter_assembler \
        --run-dir <path> \
        --editorial <editorial.json> \
        --language hebrew
"""

import json
import logging
from pathlib import Path

from constants import (
    RESULT_KEY_NEWSLETTER_SUMMARY_PATH,
    RESULT_KEY_MARKDOWN_PATH,
    RESULT_KEY_HTML_PATH,
    RESULT_KEY_TRANSLATED_PATH,
    OUTPUT_FILENAME_IMAGE_MANIFEST,
    MAX_IMAGES_TOTAL,
)
from custom_types.field_keys import DiscussionKeys, ImageKeys, NewsletterStructureKeys
from custom_types.newsletter_formats.langtalks.renderer import LangTalksRenderer
from custom_types.newsletter_formats.langtalks.schema import (
    LlmResponseLangTalksNewsletterContent,
)
from graphs.single_chat_analyzer.associate_images import _build_image_discussion_map

logger = logging.getLogger(__name__)

MERGED_DISCUSSIONS_FILENAME = "merged_discussions.json"
ALL_CHATS_AGGREGATED_FILENAME = "all_chats_aggregated.json"


class NewsletterAssembler:
    """
    Assembles newsletter JSON from editorial content + source discussion metadata.

    Editorial content (titles, bullet_points, worth_mentioning) is provided by
    the human/LLM editor. All metadata (timestamps, chat_name, is_merged,
    source_discussions, message counts, participant counts) is pulled
    deterministically from the pipeline's intermediate data files.
    """

    def __init__(self, run_dir: str | Path):
        self.run_dir = Path(run_dir)
        self._discussions_by_title: dict[str, dict] = {}
        self._discussions_by_id: dict[str, dict] = {}
        self._source_path: Path | None = None
        self._load_source_data()
        # discussion_id -> list of image description dicts (from the vision pipeline).
        # Built once and cached; empty when no manifest is present (feature inert).
        self._image_map: dict[str, list[dict]] = self._build_image_map()

    def _load_source_data(self) -> None:
        """Load merged_discussions.json and build lookup indexes."""
        merged_path = self.run_dir / "consolidated" / "aggregated_discussions" / MERGED_DISCUSSIONS_FILENAME
        aggregated_path = self.run_dir / "consolidated" / "aggregated_discussions" / ALL_CHATS_AGGREGATED_FILENAME

        source_path = merged_path if merged_path.exists() else aggregated_path
        if not source_path.exists():
            raise FileNotFoundError(f"No source discussion data found at {merged_path} or {aggregated_path}")

        self._source_path = source_path

        with open(source_path) as f:
            data = json.load(f)

        discussions = data.get("discussions", data.get("merged_discussions", []))
        for d in discussions:
            title_lower = d.get("title", "").strip().lower()
            self._discussions_by_title[title_lower] = d

            disc_id = d.get("id", d.get("discussion_id", ""))
            if disc_id:
                self._discussions_by_id[disc_id.lower()] = d

        logger.info(f"Loaded {len(discussions)} source discussions from {source_path.name}")

    def _build_image_map(self) -> dict[str, list[dict]]:
        """
        Build a discussion_id -> image-description-dicts map from any image manifests
        in the run dir, matched against the same source-discussion file the assembler loaded.

        The vision pipeline writes one manifest per chat at
        <run_dir>/<chat_subdir>/images/image_manifest.json, so a consolidated run can
        carry several. Each is built via the shared, pure _build_image_discussion_map
        (which applies the per-discussion + total caps), then merged here under the
        global MAX_IMAGES_TOTAL budget.

        Fail-soft: any missing manifest or per-manifest error is logged and skipped;
        no manifest at all yields an empty map (the images feature is simply inert).
        """
        if self._source_path is None:
            return {}

        manifest_paths = sorted(self.run_dir.rglob(OUTPUT_FILENAME_IMAGE_MANIFEST))
        if not manifest_paths:
            logger.info("No image manifest found in run dir; image descriptions disabled")
            return {}

        merged: dict[str, list[dict]] = {}
        total = 0
        for manifest_path in manifest_paths:
            if total >= MAX_IMAGES_TOTAL:
                break
            try:
                per_manifest = _build_image_discussion_map(str(manifest_path), str(self._source_path))
            except Exception as e:
                logger.warning(f"Skipping image manifest {manifest_path} (fail-soft): {e}", extra={"error": str(e)})
                continue

            for disc_id, images in per_manifest.items():
                if total >= MAX_IMAGES_TOTAL:
                    break
                existing = merged.setdefault(disc_id, [])
                for image in images:
                    if total >= MAX_IMAGES_TOTAL:
                        break
                    existing.append(image)
                    total += 1

        logger.info(f"Built image map for {len(merged)} discussions, {total} total image descriptions")
        return merged

    def find_discussion(self, identifier: str) -> dict | None:
        """
        Find a source discussion by title or ID (case-insensitive fuzzy match).

        Tries exact match first, then substring match on titles.
        """
        key = identifier.strip().lower()

        # Exact match by ID
        if key in self._discussions_by_id:
            return self._discussions_by_id[key]

        # Exact match by title
        if key in self._discussions_by_title:
            return self._discussions_by_title[key]

        # Substring match on title
        for title, disc in self._discussions_by_title.items():
            if key in title or title in key:
                return disc

        return None

    def extract_metadata(self, source_discussion: dict) -> dict:
        """
        Extract all metadata fields from a source discussion.

        Returns a dict with only verified, real metadata — never fabricated.
        """
        messages = source_discussion.get("messages", [])
        timestamps = [m.get("timestamp", 0) for m in messages if m.get("timestamp")]
        unique_senders = {m.get("sender_id", m.get("sender", "")) for m in messages} - {""}

        metadata = {
            "first_message_timestamp": min(timestamps) if timestamps else 0,
            "last_message_timestamp": max(timestamps) if timestamps else 0,
            "number_of_messages": source_discussion.get("num_messages", len(messages)),
            "number_of_unique_participants": source_discussion.get("num_unique_participants", len(unique_senders)),
            "chat_name": source_discussion.get("source_chat", "LangTalks Community"),
        }

        # Merged discussion metadata
        source_discussions = source_discussion.get("source_discussions", [])
        if source_discussions and len(source_discussions) > 1:
            metadata["is_merged"] = True
            metadata["source_discussions"] = [{"group": sd.get("group", ""), "first_message_timestamp": sd.get("first_message_timestamp", 0)} for sd in source_discussions]
        else:
            metadata["is_merged"] = False

        return metadata

    def assemble(self, editorial: dict) -> dict:
        """
        Assemble final newsletter JSON from editorial content + source metadata.

        Args:
            editorial: Dict with structure:
                {
                    "primary_discussion": {
                        "source_title": "Enterprise AI Tools...",  # matches title in merged_discussions.json
                        "title": "Hebrew title for newsletter",
                        "bullet_points": [{"label": "...", "content": "..."}],
                        "ranking_of_relevance_to_gen_ai_engineering": 10
                    },
                    "secondary_discussions": [...same structure...],
                    "worth_mentioning": ["...", "..."]
                }

        Returns:
            Complete newsletter JSON dict with real metadata, validated against schema.

        Raises:
            ValueError: If a referenced discussion cannot be found in source data.
        """
        result = {}

        # Assemble primary discussion
        result["primary_discussion"] = self._assemble_discussion(editorial["primary_discussion"])

        # Assemble secondary discussions
        result["secondary_discussions"] = [self._assemble_discussion(d) for d in editorial["secondary_discussions"]]

        # Worth mentioning passes through (plain strings, no metadata to verify)
        result["worth_mentioning"] = editorial["worth_mentioning"]

        # Validate against Pydantic schema
        validated = LlmResponseLangTalksNewsletterContent(**result)
        return validated.model_dump()

    def _assemble_discussion(self, editorial_discussion: dict) -> dict:
        """
        Merge editorial content with real metadata for a single discussion.

        The editorial provides: title, bullet_points, ranking
        The source provides: timestamps, chat_name, is_merged, source_discussions, counts
        """
        source_title = editorial_discussion.get("source_title", editorial_discussion.get("title", ""))
        source = self.find_discussion(source_title)

        if source is None:
            raise ValueError(
                f"Discussion not found in source data: '{source_title}'. "
                f"Available titles: {list(self._discussions_by_title.keys())[:10]}..."
            )

        metadata = self.extract_metadata(source)

        assembled = {
            "title": editorial_discussion["title"],
            "bullet_points": editorial_discussion["bullet_points"],
            "ranking_of_relevance_to_gen_ai_engineering": editorial_discussion.get("ranking_of_relevance_to_gen_ai_engineering", 7),
            **metadata,
        }

        image_descriptions = self._image_descriptions_for(source)
        if image_descriptions:
            assembled[NewsletterStructureKeys.IMAGE_DESCRIPTIONS] = image_descriptions

        return assembled

    def _image_descriptions_for(self, source_discussion: dict) -> list[str]:
        """
        Return the verified image-description strings for a matched source discussion.

        Looks up the source discussion's id in the cached image map and flattens the
        per-image dicts down to their description strings. Fail-soft: returns an empty
        list when there are no images or no id.
        """
        disc_id = source_discussion.get(DiscussionKeys.ID, "")
        images = self._image_map.get(disc_id, []) if disc_id else []
        return [img[ImageKeys.DESCRIPTION] for img in images if img.get(ImageKeys.DESCRIPTION)]

    def assemble_render_save(self, editorial: dict, language: str = "hebrew") -> dict:
        """
        Full pipeline: assemble JSON, render HTML+MD, save all files.

        Returns dict with paths to saved files.
        """
        newsletter_json = self.assemble(editorial)

        # Save JSON
        newsletter_dir = self.run_dir / "consolidated" / "newsletter"
        newsletter_dir.mkdir(parents=True, exist_ok=True)

        json_path = newsletter_dir / "newsletter_summary.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(newsletter_json, f, indent=2, ensure_ascii=False)

        # Render HTML and MD
        renderer = LangTalksRenderer()

        html = renderer.render_html(newsletter_json, language)
        html_path = newsletter_dir / "newsletter_summary.html"
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)

        md = renderer.render_markdown(newsletter_json, language)
        md_path = newsletter_dir / "newsletter_summary.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md)

        # Also save to final_translation
        translation_dir = self.run_dir / "consolidated" / "final_translation"
        translation_dir.mkdir(parents=True, exist_ok=True)
        translated_path = translation_dir / "translated_consolidated.md"
        with open(translated_path, "w", encoding="utf-8") as f:
            f.write(md)

        logger.info(f"Newsletter assembled and saved: {json_path}")

        return {
            RESULT_KEY_NEWSLETTER_SUMMARY_PATH: str(json_path),
            RESULT_KEY_HTML_PATH: str(html_path),
            RESULT_KEY_MARKDOWN_PATH: str(md_path),
            RESULT_KEY_TRANSLATED_PATH: str(translated_path),
        }


def main():
    """CLI entrypoint for assembling newsletters from editorial JSON files."""
    import argparse

    parser = argparse.ArgumentParser(description="Assemble newsletter from editorial content + source metadata")
    parser.add_argument("--run-dir", required=True, help="Path to the newsletter run directory")
    parser.add_argument("--editorial", required=True, help="Path to editorial JSON file")
    parser.add_argument("--language", default="hebrew", help="Target language (default: hebrew)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    with open(args.editorial) as f:
        editorial = json.load(f)

    assembler = NewsletterAssembler(args.run_dir)
    paths = assembler.assemble_render_save(editorial, args.language)

    print(json.dumps(paths, indent=2))


if __name__ == "__main__":
    main()
