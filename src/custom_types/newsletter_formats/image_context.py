"""
Shared Image Context Builder for Newsletter Format Plugins

Builds the IMAGE CONTEXT text section appended to LLM prompts when
discussions have associated images with descriptions.

Used by all format plugins (langtalks, mcp_israel, whatsapp) to inject
image awareness into the newsletter generation prompt.
"""

from custom_types.field_keys import DiscussionKeys, ImageKeys


def build_image_context_text(discussions: list[dict], image_discussion_map: dict[str, list[dict]]) -> str:
    """
    Build IMAGE CONTEXT section for LLM prompt.

    Groups image descriptions by discussion title, producing a text block
    that gives the newsletter LLM awareness of visual content shared in discussions.

    Args:
        discussions: List of discussion dicts (must have id and title fields)
        image_discussion_map: Maps discussion_id -> list of image description dicts

    Returns:
        Formatted text block, or empty string if no images match any discussion.
    """
    if not image_discussion_map:
        return ""

    # Build discussion_id -> title lookup
    disc_titles: dict[str, str] = {}
    for disc in discussions:
        disc_id = disc.get(DiscussionKeys.ID)
        if disc_id:
            disc_titles[disc_id] = disc.get(DiscussionKeys.TITLE, disc_id)

    sections: list[str] = []
    for disc_id, images in image_discussion_map.items():
        title = disc_titles.get(disc_id)
        if not title or not images:
            continue
        descriptions = [desc for img in images if (desc := img.get(ImageKeys.DESCRIPTION))]
        if not descriptions:
            continue
        lines = [f'Discussion "{title}" contains these shared images:']
        for desc in descriptions:
            lines.append(f"- {desc}")
        sections.append("\n".join(lines))

    if not sections:
        return ""

    header = (
        "\n\nIMAGE CONTEXT:\n"
        "The following images were shared during these discussions. "
        "Incorporate relevant visual content into your summaries when it adds value.\n"
    )
    return header + "\n\n".join(sections)
