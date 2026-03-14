"""
WhatsApp Newsletter Renderer

Renders newsletter content as WhatsApp-native plain text for sharing in groups,
plus a simple HTML viewer with copy-to-clipboard functionality.
"""

import html
import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from constants import (
    DEFAULT_HTML_LANGUAGE,
    HEBREW_LANGUAGE_CODES,
    TextDirection,
    HTML_LANG_HEBREW,
    HTML_LANG_ENGLISH,
    MS_TO_SECONDS_MULTIPLIER,
    NO_CONTENT_FOR_SECTION,
    DISPLAY_TIMEZONE,
)
from custom_types.field_keys import DiscussionKeys, NewsletterStructureKeys

logger = logging.getLogger(__name__)

WHATSAPP_SECTION_SEPARATOR = "───────────"
WHATSAPP_WORTH_MENTIONING_HEADING = "*🧰 נושאים נוספים שעלו:*"
WHATSAPP_ATTRIBUTION_PREFIX = "📅"


class WhatsAppRenderer:
    """Renders newsletter content to WhatsApp plain text and HTML viewer formats."""

    def render_whatsapp_text(self, response: dict) -> str:
        """
        Generate WhatsApp-formatted plain text newsletter from JSON response.

        Uses WhatsApp-native formatting:
        - *bold* for titles and labels
        - bullet points with unicode bullets
        - bare URLs (WhatsApp auto-detects links)
        - section separators

        Args:
            response: Newsletter JSON with primary_discussion, secondary_discussions, worth_mentioning

        Returns:
            WhatsApp-formatted plain text string
        """
        try:
            parts = []

            # Primary discussion
            primary = response[NewsletterStructureKeys.PRIMARY_DISCUSSION]
            parts.append(f"*{primary[NewsletterStructureKeys.TITLE]}*")
            parts.append("")

            if primary.get(NewsletterStructureKeys.IS_MERGED, False) and primary.get(NewsletterStructureKeys.SOURCE_DISCUSSIONS):
                group_names = [s.get(DiscussionKeys.SOURCE_GROUP, "") for s in primary[NewsletterStructureKeys.SOURCE_DISCUSSIONS] if s.get(DiscussionKeys.SOURCE_GROUP)]
                if group_names:
                    parts.append(f"📍 נדון ב-{len(group_names)} קבוצות: {', '.join(group_names)}")
                    parts.append("")

            for bullet in primary[NewsletterStructureKeys.BULLET_POINTS]:
                content = bullet[NewsletterStructureKeys.CONTENT]
                if self._is_no_content_placeholder(content):
                    continue
                label = self._strip_markdown_links(bullet[NewsletterStructureKeys.LABEL])
                content = self._strip_markdown_links(content)
                parts.append(f"• *{label}*: {content}")

            attribution = self._render_attribution(primary)
            if attribution:
                parts.append("")
                parts.append(attribution)

            parts.append("")
            parts.append(WHATSAPP_SECTION_SEPARATOR)
            parts.append("")

            # Secondary discussions
            for discussion in response[NewsletterStructureKeys.SECONDARY_DISCUSSIONS]:
                parts.append(f"*{discussion[NewsletterStructureKeys.TITLE]}*")
                parts.append("")

                if discussion.get(NewsletterStructureKeys.IS_MERGED, False) and discussion.get(NewsletterStructureKeys.SOURCE_DISCUSSIONS):
                    group_names = [s.get(DiscussionKeys.SOURCE_GROUP, "") for s in discussion[NewsletterStructureKeys.SOURCE_DISCUSSIONS] if s.get(DiscussionKeys.SOURCE_GROUP)]
                    if group_names:
                        parts.append(f"📍 נדון ב-{len(group_names)} קבוצות: {', '.join(group_names)}")
                        parts.append("")

                for bullet in discussion[NewsletterStructureKeys.BULLET_POINTS]:
                    content = bullet[NewsletterStructureKeys.CONTENT]
                    if self._is_no_content_placeholder(content):
                        continue
                    label = self._strip_markdown_links(bullet[NewsletterStructureKeys.LABEL])
                    content = self._strip_markdown_links(content)
                    parts.append(f"• *{label}*: {content}")

                attribution = self._render_attribution(discussion)
                if attribution:
                    parts.append("")
                    parts.append(attribution)

                parts.append("")
                parts.append(WHATSAPP_SECTION_SEPARATOR)
                parts.append("")

            # Worth mentioning (filter out "no content" placeholders)
            worth_mentioning = [item for item in response.get(NewsletterStructureKeys.WORTH_MENTIONING, []) if not self._is_no_content_placeholder(item)]
            if worth_mentioning:
                parts.append(WHATSAPP_WORTH_MENTIONING_HEADING)
                parts.append("")
                for item in worth_mentioning:
                    cleaned = self._strip_markdown_links(item)
                    # Strip **bold** markdown → *bold* WhatsApp
                    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"*\1*", cleaned)
                    parts.append(f"• {cleaned}")

            return "\n".join(parts)

        except Exception as e:
            logger.error(f"WhatsAppRenderer.render_whatsapp_text failed: {e}")
            raise

    def render_html_viewer(self, response: dict, whatsapp_text: str, desired_language: str = DEFAULT_HTML_LANGUAGE) -> str:
        """
        Generate HTML viewer with copy-to-clipboard for the WhatsApp text.

        Args:
            response: Newsletter JSON (used for page title)
            whatsapp_text: Pre-rendered WhatsApp plain text
            desired_language: Target language for HTML attributes

        Returns:
            HTML document string with copy button
        """
        try:
            if desired_language.lower() in HEBREW_LANGUAGE_CODES:
                lang_attr = HTML_LANG_HEBREW
                dir_attr = TextDirection.RTL
            else:
                lang_attr = HTML_LANG_ENGLISH
                dir_attr = TextDirection.LTR

            primary_title = response.get(NewsletterStructureKeys.PRIMARY_DISCUSSION, {}).get(NewsletterStructureKeys.TITLE, "Newsletter")

            # Escape HTML special characters for safe embedding
            escaped_title = html.escape(primary_title)
            escaped_text = html.escape(whatsapp_text)

            # Escape for JS template literal embedding
            js_escaped = (whatsapp_text
                .replace("\\", "\\\\")
                .replace("`", "\\`")
                .replace("$", "\\$")
                .replace("\n", "\\n")
                .replace("\r", "\\r"))

            return f"""<!DOCTYPE html>
<html lang="{lang_attr}" dir="{dir_attr}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{escaped_title} - WhatsApp Newsletter</title>
    <style>
        body {{
            font-family: 'Segoe UI', Arial, sans-serif;
            max-width: 700px;
            margin: 0 auto;
            padding: 20px 20px 80px;
            background-color: #f0f0f0;
        }}
        .whatsapp-preview {{
            background: #ffffff;
            border-radius: 8px;
            padding: 20px;
            white-space: pre-wrap;
            word-wrap: break-word;
            font-size: 15px;
            line-height: 1.6;
            color: #1a1a1a;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}
        .toolbar {{
            position: fixed;
            bottom: 20px;
            right: 20px;
            z-index: 100;
        }}
        .toolbar button {{
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            background: #25D366;
            color: white;
            cursor: pointer;
            font-size: 16px;
            font-weight: bold;
        }}
        .toolbar button:hover {{
            background: #1da851;
        }}
        .copy-success {{
            background: #4CAF50 !important;
        }}
    </style>
</head>
<body>
    <div class="whatsapp-preview">{escaped_text}</div>

    <div class="toolbar">
        <button onclick="copyForWhatsApp(this)">Copy for WhatsApp</button>
    </div>

    <script>
    function copyForWhatsApp(btn) {{
        const text = `{js_escaped}`;
        navigator.clipboard.writeText(text).then(() => {{
            const orig = btn.textContent;
            btn.textContent = 'Copied!';
            btn.classList.add('copy-success');
            setTimeout(() => {{
                btn.textContent = orig;
                btn.classList.remove('copy-success');
            }}, 1500);
        }});
    }}
    </script>
</body>
</html>"""

        except Exception as e:
            logger.error(f"WhatsAppRenderer.render_html_viewer failed: {e}")
            raise

    @staticmethod
    def _is_no_content_placeholder(text: str) -> bool:
        """Check if text is a 'no content' placeholder that should be omitted from output."""
        normalized = text.strip().lower().rstrip(".")
        return normalized in (NO_CONTENT_FOR_SECTION.lower(), "no content for this section", "אין תוכן לסעיף זה", "אין תוכן למדור זה")

    def _strip_markdown_links(self, text: str) -> str:
        """Convert markdown [text](url) to 'text (url)' for WhatsApp."""
        return re.sub(r"\[([^\]]+)\]\(([^\)]+)\)", r"\1 (\2)", text)

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

    def _render_attribution(self, discussion: dict) -> str:
        """Render attribution line for a discussion."""
        if discussion.get(NewsletterStructureKeys.IS_MERGED, False) and discussion.get(NewsletterStructureKeys.SOURCE_DISCUSSIONS):
            lines = []
            for source in discussion[NewsletterStructureKeys.SOURCE_DISCUSSIONS]:
                timestamp = source.get(NewsletterStructureKeys.FIRST_MESSAGE_TIMESTAMP, 0)
                if isinstance(timestamp, (int, float)) and timestamp > 0:
                    time_str, date_str = self._format_timestamp(timestamp)
                    group_name = source.get(DiscussionKeys.SOURCE_GROUP, "Unknown Group")
                    lines.append(f"{WHATSAPP_ATTRIBUTION_PREFIX} {group_name} | {time_str} | {date_str}")
            return "\n".join(lines)

        timestamp = discussion.get(NewsletterStructureKeys.FIRST_MESSAGE_TIMESTAMP, 0)
        if isinstance(timestamp, (int, float)) and timestamp > 0:
            time_str, date_str = self._format_timestamp(timestamp)
            chat_name = discussion.get(NewsletterStructureKeys.CHAT_NAME, "")
            return f"{WHATSAPP_ATTRIBUTION_PREFIX} {chat_name} | {time_str} | {date_str}"

        return ""
