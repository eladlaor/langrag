"""
LangTalks Newsletter Renderer

Two-layer architecture:
- Layer 1: _render_substack_body() — clean Substack-compatible <article> HTML
- Layer 2: render_html() — full viewer document with edit/copy controls

Converts LLM responses to Markdown and HTML formats for the LangTalks newsletter.
"""

import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from constants import (
    DEFAULT_HTML_LANGUAGE,
    HEBREW_LANGUAGE_CODES,
    TextDirection,
    LANGTALKS_CHAT_NAME_DEFAULT,
    LANGTALKS_CHAT_PREFIX,
    HTML_LANG_HEBREW,
    HTML_LANG_ENGLISH,
    LANGTALKS_WHATSAPP_JOIN_URL,
    LANGTALKS_NEWSLETTER_SIGNUP_URL,
    MS_TO_SECONDS_MULTIPLIER,
    DISPLAY_TIMEZONE,
    get_langtalks_i18n,
)
from custom_types.field_keys import NewsletterStructureKeys

logger = logging.getLogger(__name__)


class LangTalksRenderer:
    """Renders LangTalks newsletter content to Markdown and HTML formats."""

    def render_markdown(self, response: dict, desired_language: str = DEFAULT_HTML_LANGUAGE) -> str:
        """
        Generate Markdown newsletter from JSON response.

        Args:
            response: Newsletter JSON with primary_discussion, secondary_discussions, worth_mentioning
            desired_language: Target language for content strings (default: DEFAULT_HTML_LANGUAGE)

        Returns:
            Markdown-formatted newsletter string
        """
        try:
            i18n = get_langtalks_i18n(desired_language)
            markdown = "# LangTalks Newsletter\n\n"

            markdown += "## Primary Discussion\n\n"
            primary = response[NewsletterStructureKeys.PRIMARY_DISCUSSION]
            markdown += f"### {primary[NewsletterStructureKeys.TITLE]}\n\n"
            if primary.get(NewsletterStructureKeys.IS_MERGED, False) and primary.get(NewsletterStructureKeys.SOURCE_DISCUSSIONS):
                group_names = [s.get("group", "") for s in primary[NewsletterStructureKeys.SOURCE_DISCUSSIONS] if s.get("group")]
                if group_names:
                    markdown += i18n["merged_discussed_in"].format(count=len(group_names), groups=", ".join(group_names)) + "\n\n"
            for i, bullet in enumerate(primary[NewsletterStructureKeys.BULLET_POINTS], 1):
                markdown += f"{i}. **{bullet[NewsletterStructureKeys.LABEL]}**: {bullet[NewsletterStructureKeys.CONTENT]}\n\n"

            markdown += self._render_markdown_attribution(primary, desired_language)

            markdown += "\n---\n\n## Secondary Discussions\n\n"
            for discussion in response[NewsletterStructureKeys.SECONDARY_DISCUSSIONS]:
                markdown += f"### {discussion[NewsletterStructureKeys.TITLE]}\n\n"
                if discussion.get(NewsletterStructureKeys.IS_MERGED, False) and discussion.get(NewsletterStructureKeys.SOURCE_DISCUSSIONS):
                    group_names = [s.get("group", "") for s in discussion[NewsletterStructureKeys.SOURCE_DISCUSSIONS] if s.get("group")]
                    if group_names:
                        markdown += i18n["merged_discussed_in"].format(count=len(group_names), groups=", ".join(group_names)) + "\n\n"
                for i, bullet in enumerate(discussion[NewsletterStructureKeys.BULLET_POINTS], 1):
                    markdown += f"{i}. **{bullet[NewsletterStructureKeys.LABEL]}**: {bullet[NewsletterStructureKeys.CONTENT]}\n\n"

                markdown += self._render_markdown_attribution(discussion, desired_language)
                markdown += "\n---\n\n"

            markdown += "## Worth Mentioning\n\n"
            for point in response[NewsletterStructureKeys.WORTH_MENTIONING]:
                markdown += f"- {point}\n"

            return markdown

        except Exception as e:
            error_message = f"Error generating markdown: {e}"
            logger.error(error_message)
            raise Exception(error_message) from e

    def _render_markdown_attribution(self, discussion: dict, desired_language: str = DEFAULT_HTML_LANGUAGE) -> str:
        """Render markdown attribution footer for a discussion."""
        i18n = get_langtalks_i18n(desired_language)

        if discussion.get(NewsletterStructureKeys.IS_MERGED, False) and discussion.get(NewsletterStructureKeys.SOURCE_DISCUSSIONS):
            result = f"\n{i18n['merged_attribution_header']}\n"
            for source in discussion[NewsletterStructureKeys.SOURCE_DISCUSSIONS]:
                timestamp = source.get(NewsletterStructureKeys.FIRST_MESSAGE_TIMESTAMP, 0)
                if isinstance(timestamp, (int, float)) and timestamp > 0:
                    time_str, date_str = self._format_timestamp(timestamp)
                    group_name = source.get("group", "Unknown Group")
                    result += f"- {group_name} ({i18n['merged_started_at'].format(date=date_str, time=time_str)})\n"
            return result
        elif NewsletterStructureKeys.FIRST_MESSAGE_TIMESTAMP in discussion and discussion[NewsletterStructureKeys.FIRST_MESSAGE_TIMESTAMP]:
            timestamp = discussion[NewsletterStructureKeys.FIRST_MESSAGE_TIMESTAMP]
            if isinstance(timestamp, (int, float)):
                time_str, date_str = self._format_timestamp(timestamp)
                chat_name = discussion.get(NewsletterStructureKeys.CHAT_NAME, LANGTALKS_CHAT_NAME_DEFAULT)
                return f"\n{i18n['attribution_prefix']} {chat_name} | {time_str} | {date_str}\n"
        return ""

    def _markdown_links_to_html(self, text: str) -> str:
        """Convert markdown links [text](url) to HTML anchor tags."""
        pattern = r"\[([^\]]+)\]\(([^\)]+)\)"
        return re.sub(pattern, r'<a href="\2">\1</a>', text)

    def _backticks_to_code(self, text: str) -> str:
        """Convert backtick-wrapped terms to <code> tags."""
        return re.sub(r"`([^`]+)`", r"<code>\1</code>", text)

    def _process_inline_formatting(self, text: str) -> str:
        """Apply all inline formatting: markdown links -> HTML anchors, backticks -> code tags."""
        result = self._markdown_links_to_html(text)
        result = self._backticks_to_code(result)
        return result

    def _format_timestamp(self, timestamp_ms: int | float) -> tuple[str, str]:
        """
        Convert millisecond timestamp to formatted time and date strings.

        Args:
            timestamp_ms: Timestamp in milliseconds

        Returns:
            Tuple of (time_str "HH:MM", date_str "DD.MM.YY")
        """
        dt = datetime.fromtimestamp(timestamp_ms / MS_TO_SECONDS_MULTIPLIER, tz=ZoneInfo(DISPLAY_TIMEZONE))
        return dt.strftime("%H:%M"), dt.strftime("%d.%m.%y")

    def _strip_chat_prefix(self, chat_name: str) -> str:
        """Remove 'LangTalks - ' prefix from chat name if present."""
        if chat_name.startswith(LANGTALKS_CHAT_PREFIX):
            return chat_name[len(LANGTALKS_CHAT_PREFIX) :]
        return chat_name

    def _render_discussion_attribution_html(self, discussion: dict, desired_language: str = DEFAULT_HTML_LANGUAGE) -> str:
        """Render the attribution line for a single discussion."""
        i18n = get_langtalks_i18n(desired_language)

        if discussion.get(NewsletterStructureKeys.IS_MERGED, False) and discussion.get(NewsletterStructureKeys.SOURCE_DISCUSSIONS):
            lines = []
            for source in discussion[NewsletterStructureKeys.SOURCE_DISCUSSIONS]:
                timestamp = source.get(NewsletterStructureKeys.FIRST_MESSAGE_TIMESTAMP, 0)
                if isinstance(timestamp, (int, float)) and timestamp > 0:
                    time_str, date_str = self._format_timestamp(timestamp)
                    group_name = source.get("group", "Unknown Group")
                    lines.append(f"<p>{i18n['attribution_prefix']} {group_name} | {time_str} | {date_str}</p>")
            return "\n".join(lines)

        if NewsletterStructureKeys.FIRST_MESSAGE_TIMESTAMP in discussion and discussion[NewsletterStructureKeys.FIRST_MESSAGE_TIMESTAMP]:
            timestamp = discussion[NewsletterStructureKeys.FIRST_MESSAGE_TIMESTAMP]
            if isinstance(timestamp, (int, float)):
                time_str, date_str = self._format_timestamp(timestamp)
                chat_name = self._strip_chat_prefix(discussion.get(NewsletterStructureKeys.CHAT_NAME, LANGTALKS_CHAT_NAME_DEFAULT))
                return f"<p>{i18n['attribution_prefix']} {chat_name} | {time_str} | {date_str}</p>"

        return ""

    def _render_bullet_points_html(self, bullet_points: list[dict], ordered: bool = True) -> str:
        """Render bullet points as <ol> or <ul> list items."""
        tag = "ol" if ordered else "ul"
        items = []
        for bullet in bullet_points:
            label = self._process_inline_formatting(bullet.get(NewsletterStructureKeys.LABEL, ""))
            content = self._process_inline_formatting(bullet.get(NewsletterStructureKeys.CONTENT, ""))
            items.append(f"<li><p><strong>{label}</strong>: {content}</p></li>")
        return f"<{tag}>\n" + "\n".join(items) + f"\n</{tag}>"

    def _parse_worth_mentioning_item(self, text: str) -> str:
        """
        Parse a worth_mentioning string into HTML with bold labels.

        Handles patterns like "**Label:** content" or "**Label**: content"
        """
        processed = self._process_inline_formatting(text)
        # Convert **text** to <strong>text</strong>
        processed = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", processed)
        return f"<li><p>{processed}</p></li>"

    def _render_substack_body(self, response: dict, desired_language: str = DEFAULT_HTML_LANGUAGE) -> str:
        """
        Render clean Substack-compatible article HTML.

        No <html>, no <style>, no viewer controls. Structure matches Substack's
        native HTML format (news-24/content.html).

        Args:
            response: Newsletter JSON response
            desired_language: Target language for content

        Returns:
            Clean <article> HTML string
        """
        try:
            i18n = get_langtalks_i18n(desired_language)
            parts = []
            parts.append("<article>")
            parts.append("<div><hr></div>")

            # Primary discussion — uses <h2>
            primary = response.get(NewsletterStructureKeys.PRIMARY_DISCUSSION)
            if primary:
                parts.append(f"\n<h2><strong>{self._process_inline_formatting(primary.get(NewsletterStructureKeys.TITLE, ''))}</strong></h2>")
                parts.append("")
                parts.append(self._render_bullet_points_html(primary.get(NewsletterStructureKeys.BULLET_POINTS, [])))
                attribution = self._render_discussion_attribution_html(primary, desired_language)
                if attribution:
                    parts.append("")
                    parts.append(attribution)
                parts.append("")
                parts.append("<div><hr></div>")

            # Secondary discussions — each uses <h3>
            for discussion in response.get(NewsletterStructureKeys.SECONDARY_DISCUSSIONS, []):
                parts.append(f"\n<h3><strong>{self._process_inline_formatting(discussion.get(NewsletterStructureKeys.TITLE, ''))}</strong></h3>")
                parts.append("")
                parts.append(self._render_bullet_points_html(discussion.get(NewsletterStructureKeys.BULLET_POINTS, [])))
                attribution = self._render_discussion_attribution_html(discussion, desired_language)
                if attribution:
                    parts.append("")
                    parts.append(attribution)
                parts.append("")
                parts.append("<div><hr></div>")

            # Worth mentioning section
            worth_mentioning = response.get(NewsletterStructureKeys.WORTH_MENTIONING, [])
            if worth_mentioning:
                parts.append(f"\n<h2>{i18n['worth_mentioning_heading']}</h2>")
                parts.append("")
                items = [self._parse_worth_mentioning_item(point) for point in worth_mentioning]
                parts.append("<ul>")
                parts.extend(items)
                parts.append("</ul>")
                parts.append("")
                parts.append("<div><hr></div>")

            # Footer
            parts.append(self._render_footer_html(desired_language))
            parts.append("")
            parts.append("</article>")

            return "\n".join(parts)

        except Exception as e:
            error_message = f"Error generating Substack body HTML: {e}"
            logger.error(error_message)
            raise Exception(error_message) from e

    def render_substack_html(self, response: dict, desired_language: str = DEFAULT_HTML_LANGUAGE) -> str:
        """
        Render clean Substack-ready HTML document (no CSS, no JS).

        For direct pasting into Substack editor.

        Args:
            response: Newsletter JSON response
            desired_language: Target language

        Returns:
            Minimal HTML document with article content
        """
        try:
            if desired_language.lower() in HEBREW_LANGUAGE_CODES:
                lang_attr = HTML_LANG_HEBREW
                dir_attr = TextDirection.RTL
            else:
                lang_attr = HTML_LANG_ENGLISH
                dir_attr = TextDirection.LTR

            body = self._render_substack_body(response, desired_language)

            return f"""<!DOCTYPE html>
<html lang="{lang_attr}" dir="{dir_attr}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body>
{body}
</body>
</html>"""

        except Exception as e:
            error_message = f"Error generating Substack HTML: {e}"
            logger.error(error_message)
            raise Exception(error_message) from e

    def render_html(self, response: dict, desired_language: str = DEFAULT_HTML_LANGUAGE) -> str:
        """
        Generate full HTML viewer document with Substack content + edit/copy controls.

        Features:
        - Substack-like CSS styling
        - Section wrappers with contenteditable for inline editing
        - Per-section "Copy" buttons on hover
        - Floating toolbar: "Copy for Substack" and "Copy All"
        - Visual "Copied!" feedback

        Args:
            response: Newsletter JSON with primary_discussion, secondary_discussions, worth_mentioning
            desired_language: Target language for HTML attributes

        Returns:
            Full HTML document string
        """
        try:
            if desired_language.lower() in HEBREW_LANGUAGE_CODES:
                lang_attr = HTML_LANG_HEBREW
                dir_attr = TextDirection.RTL
            else:
                lang_attr = HTML_LANG_ENGLISH
                dir_attr = TextDirection.LTR

            # Get the page title from primary discussion
            primary_title = response.get(NewsletterStructureKeys.PRIMARY_DISCUSSION, {}).get(NewsletterStructureKeys.TITLE, "LangTalks Newsletter")

            # Build the article body with section wrappers for the viewer
            article_html = self._render_viewer_article(response, desired_language)

            return f"""<!DOCTYPE html>
<html dir="{dir_attr}" lang="{lang_attr}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{primary_title} - LangTalks</title>
    <style>
        body {{
            font-family: 'Segoe UI', Arial, sans-serif;
            max-width: 700px;
            margin: 0 auto;
            padding: 20px 20px 80px;
            line-height: 1.7;
            color: #1a1a1a;
            background-color: #ffffff;
        }}
        h1, h2, h3, h4 {{
            margin-top: 1.2em;
        }}
        ol, ul {{
            padding-inline-start: 25px;
        }}
        li {{
            margin-bottom: 8px;
        }}
        a {{
            color: #0066cc;
            text-decoration: none;
        }}
        a:hover {{
            text-decoration: underline;
        }}
        hr {{
            border: none;
            border-top: 1px solid #e0e0e0;
            margin: 24px 0;
        }}
        code {{
            background: #f0f0f0;
            padding: 2px 6px;
            border-radius: 3px;
            font-size: 0.9em;
        }}
        .button-wrapper a.button {{
            display: inline-block;
            padding: 10px 24px;
            background: #000;
            color: #fff;
            border-radius: 4px;
            text-decoration: none;
        }}
        .button-wrapper a.button:hover {{
            background: #333;
        }}
        /* Viewer controls */
        .section-wrapper {{
            position: relative;
            border: 2px solid transparent;
            border-radius: 6px;
            padding: 4px;
            transition: border-color 0.2s;
        }}
        .section-wrapper:hover {{
            border-color: #e0e0e0;
        }}
        .section-wrapper:focus-within {{
            border-color: #4CAF50;
            outline: none;
        }}
        .section-copy-btn {{
            position: absolute;
            top: 4px;
            left: 4px;
            opacity: 0;
            transition: opacity 0.2s;
            padding: 4px 10px;
            border: 1px solid #ccc;
            border-radius: 4px;
            background: #fff;
            cursor: pointer;
            font-size: 12px;
            color: #555;
            z-index: 10;
        }}
        .section-wrapper:hover .section-copy-btn {{
            opacity: 1;
        }}
        .toolbar {{
            position: fixed;
            bottom: 20px;
            right: 20px;
            display: flex;
            gap: 8px;
            z-index: 100;
        }}
        .toolbar button {{
            padding: 10px 16px;
            border: none;
            border-radius: 6px;
            background: #333;
            color: white;
            cursor: pointer;
            font-size: 14px;
        }}
        .toolbar button:hover {{
            background: #555;
        }}
        .copy-success {{
            background: #4CAF50 !important;
        }}
    </style>
</head>
<body>
    <div id="substack-content">
        {article_html}
    </div>

    <div class="toolbar">
        <button onclick="copyForSubstack(this)">Copy for Substack</button>
        <button onclick="copyAll(this)">Copy All</button>
    </div>

    <script>
    function copyForSubstack(btn) {{
        const article = document.querySelector('article').cloneNode(true);
        article.querySelectorAll('.section-copy-btn').forEach(el => el.remove());
        article.querySelectorAll('.section-wrapper').forEach(wrapper => {{
            wrapper.removeAttribute('contenteditable');
            wrapper.removeAttribute('data-section-id');
            while (wrapper.firstChild) wrapper.parentNode.insertBefore(wrapper.firstChild, wrapper);
            wrapper.remove();
        }});
        navigator.clipboard.writeText(article.outerHTML).then(() => showFeedback(btn));
    }}
    function copyAll(btn) {{
        const article = document.querySelector('article').cloneNode(true);
        article.querySelectorAll('.section-copy-btn').forEach(el => el.remove());
        navigator.clipboard.writeText(article.outerHTML).then(() => showFeedback(btn));
    }}
    function copySectionHtml(sectionId) {{
        const section = document.querySelector('[data-section-id="' + sectionId + '"]').cloneNode(true);
        const btn = section.querySelector('.section-copy-btn');
        if (btn) btn.remove();
        navigator.clipboard.writeText(section.innerHTML).then(() => {{
            const origBtn = document.querySelector('[data-section-id="' + sectionId + '"] .section-copy-btn');
            if (origBtn) showFeedback(origBtn);
        }});
    }}
    function showFeedback(btn) {{
        const orig = btn.textContent;
        btn.textContent = 'Copied!';
        btn.classList.add('copy-success');
        setTimeout(() => {{
            btn.textContent = orig;
            btn.classList.remove('copy-success');
        }}, 1500);
    }}
    </script>
</body>
</html>"""

        except Exception as e:
            error_message = f"Error generating HTML viewer: {e}"
            logger.error(error_message)
            raise Exception(error_message) from e

    def _render_viewer_article(self, response: dict, desired_language: str = DEFAULT_HTML_LANGUAGE) -> str:
        """
        Render article content with section wrappers for the viewer.

        Each discussion and the worth-mentioning block gets wrapped in a
        contenteditable section-wrapper div with a hover-reveal copy button.
        """
        i18n = get_langtalks_i18n(desired_language)
        parts = []
        parts.append("<article>")
        parts.append("<div><hr></div>")

        section_idx = 0

        # Primary discussion
        primary = response.get(NewsletterStructureKeys.PRIMARY_DISCUSSION)
        if primary:
            section_content = self._render_discussion_section_html(primary, heading_tag="h2", desired_language=desired_language)
            parts.append(f'<div class="section-wrapper" data-section-id="section-{section_idx}" contenteditable="true">')
            parts.append(f'<button class="section-copy-btn" onclick="copySectionHtml(\'section-{section_idx}\')">Copy</button>')
            parts.append(section_content)
            parts.append("</div>")
            parts.append("<div><hr></div>")
            section_idx += 1

        # Secondary discussions
        for discussion in response.get(NewsletterStructureKeys.SECONDARY_DISCUSSIONS, []):
            section_content = self._render_discussion_section_html(discussion, heading_tag="h3", desired_language=desired_language)
            parts.append(f'<div class="section-wrapper" data-section-id="section-{section_idx}" contenteditable="true">')
            parts.append(f'<button class="section-copy-btn" onclick="copySectionHtml(\'section-{section_idx}\')">Copy</button>')
            parts.append(section_content)
            parts.append("</div>")
            parts.append("<div><hr></div>")
            section_idx += 1

        # Worth mentioning
        worth_mentioning = response.get(NewsletterStructureKeys.WORTH_MENTIONING, [])
        if worth_mentioning:
            wm_content = self._render_worth_mentioning_html(worth_mentioning, desired_language)
            parts.append(f'<div class="section-wrapper" data-section-id="section-{section_idx}" contenteditable="true">')
            parts.append(f'<button class="section-copy-btn" onclick="copySectionHtml(\'section-{section_idx}\')">Copy</button>')
            parts.append(wm_content)
            parts.append("</div>")
            parts.append("<div><hr></div>")
            section_idx += 1

        # Footer (not editable)
        parts.append(self._render_footer_html(desired_language))

        parts.append("</article>")
        return "\n".join(parts)

    def _render_discussion_section_html(self, discussion: dict, heading_tag: str = "h3", desired_language: str = DEFAULT_HTML_LANGUAGE) -> str:
        """Render a single discussion's content (heading + bullets + attribution)."""
        parts = []
        title = self._process_inline_formatting(discussion.get(NewsletterStructureKeys.TITLE, ""))
        parts.append(f"<{heading_tag}><strong>{title}</strong></{heading_tag}>")
        parts.append("")
        parts.append(self._render_bullet_points_html(discussion.get(NewsletterStructureKeys.BULLET_POINTS, [])))
        attribution = self._render_discussion_attribution_html(discussion, desired_language)
        if attribution:
            parts.append("")
            parts.append(attribution)
        return "\n".join(parts)

    def _render_worth_mentioning_html(self, worth_mentioning: list[str], desired_language: str = DEFAULT_HTML_LANGUAGE) -> str:
        """Render the worth mentioning section content."""
        i18n = get_langtalks_i18n(desired_language)
        parts = []
        parts.append(f"<h2>{i18n['worth_mentioning_heading']}</h2>")
        parts.append("")
        parts.append("<ul>")
        for point in worth_mentioning:
            parts.append(self._parse_worth_mentioning_item(point))
        parts.append("</ul>")
        return "\n".join(parts)

    def _render_footer_html(self, desired_language: str = DEFAULT_HTML_LANGUAGE) -> str:
        """Render the static newsletter footer with CTA buttons."""
        i18n = get_langtalks_i18n(desired_language)
        return "\n".join(
            [
                f"\n<h1><strong>{i18n['footer_thanks']}</strong></h1>",
                "",
                f"<h4><strong>{i18n['footer_description']}</strong></h4>",
                "",
                f"<h4><strong>{i18n['footer_share_cta']}</strong></h4>",
                "",
                f'<p class="button-wrapper"><a class="button primary" href="{LANGTALKS_WHATSAPP_JOIN_URL}"><span>{i18n["footer_whatsapp_button"]}</span></a></p>',
                "",
                f'<p class="button-wrapper"><a class="button primary" href="{LANGTALKS_NEWSLETTER_SIGNUP_URL}"><span>{i18n["footer_signup_button"]}</span></a></p>',
            ]
        )
