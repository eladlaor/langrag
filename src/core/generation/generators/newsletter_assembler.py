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
import sys
from pathlib import Path

from custom_types.newsletter_formats.langtalks.renderer import LangTalksRenderer
from custom_types.newsletter_formats.langtalks.schema import (
    LlmResponseLangTalksNewsletterContent,
)

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
        self._load_source_data()

    def _load_source_data(self) -> None:
        """Load merged_discussions.json and build lookup indexes."""
        merged_path = self.run_dir / "consolidated" / "aggregated_discussions" / MERGED_DISCUSSIONS_FILENAME
        aggregated_path = self.run_dir / "consolidated" / "aggregated_discussions" / ALL_CHATS_AGGREGATED_FILENAME

        source_path = merged_path if merged_path.exists() else aggregated_path
        if not source_path.exists():
            raise FileNotFoundError(f"No source discussion data found at {merged_path} or {aggregated_path}")

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

        return {
            "title": editorial_discussion["title"],
            "bullet_points": editorial_discussion["bullet_points"],
            "ranking_of_relevance_to_gen_ai_engineering": editorial_discussion.get("ranking_of_relevance_to_gen_ai_engineering", 7),
            **metadata,
        }

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
            "json_path": str(json_path),
            "html_path": str(html_path),
            "md_path": str(md_path),
            "translated_path": str(translated_path),
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
