"""
MCP Israel Newsletter Renderer

Converts LLM responses to Markdown and HTML formats for the MCP Israel newsletter.
"""

import logging

from constants import DEFAULT_HTML_LANGUAGE, HEBREW_LANGUAGE_CODES, TextDirection, HTML_LANG_HEBREW, HTML_LANG_ENGLISH
from custom_types.field_keys import NewsletterStructureKeys

logger = logging.getLogger(__name__)


class McpIsraelRenderer:
    """Renders MCP Israel newsletter content to Markdown and HTML formats."""

    def render_markdown(self, response: dict) -> str:
        """
        Generate Markdown newsletter from JSON response.

        Args:
            response: Newsletter JSON with markdown_content and individual sections

        Returns:
            Markdown-formatted newsletter string
        """
        try:
            # The MCP format already returns markdown_content from the LLM
            markdown_content = response.get(NewsletterStructureKeys.MARKDOWN_CONTENT, "")
            if markdown_content:
                return markdown_content

            # Fallback: build markdown from individual section fields
            markdown = "# MCP Israel Group - Technical Summary\n\n"

            # Headline section (paragraph, not bullet points)
            headline = response.get(NewsletterStructureKeys.HEADLINE, "")
            markdown += "## 🎯 Headline\n\n"
            if headline and headline.strip():
                markdown += f"{headline}\n\n"
            else:
                markdown += "No headline for this period.\n\n"

            # Categorical sections (bullet points)
            sections = {
                NewsletterStructureKeys.INDUSTRY_UPDATES: response.get(NewsletterStructureKeys.INDUSTRY_UPDATES, ""),
                NewsletterStructureKeys.TOOLS_MENTIONED: response.get(NewsletterStructureKeys.TOOLS_MENTIONED, ""),
                NewsletterStructureKeys.WORK_PRACTICES: response.get(NewsletterStructureKeys.WORK_PRACTICES, ""),
                NewsletterStructureKeys.SECURITY_RISKS: response.get(NewsletterStructureKeys.SECURITY_RISKS, ""),
                NewsletterStructureKeys.VALUABLE_POSTS: response.get(NewsletterStructureKeys.VALUABLE_POSTS, ""),
                NewsletterStructureKeys.OPEN_QUESTIONS: response.get(NewsletterStructureKeys.OPEN_QUESTIONS, ""),
                NewsletterStructureKeys.CONCEPTUAL_DISCUSSIONS: response.get(NewsletterStructureKeys.CONCEPTUAL_DISCUSSIONS, ""),
                NewsletterStructureKeys.ISSUES_CHALLENGES: response.get(NewsletterStructureKeys.ISSUES_CHALLENGES, ""),
            }

            section_emojis = {
                NewsletterStructureKeys.INDUSTRY_UPDATES: "📣",
                NewsletterStructureKeys.TOOLS_MENTIONED: "🧰",
                NewsletterStructureKeys.WORK_PRACTICES: "🧪",
                NewsletterStructureKeys.SECURITY_RISKS: "🔐",
                NewsletterStructureKeys.VALUABLE_POSTS: "📎",
                NewsletterStructureKeys.OPEN_QUESTIONS: "💭",
                NewsletterStructureKeys.CONCEPTUAL_DISCUSSIONS: "🧠",
                NewsletterStructureKeys.ISSUES_CHALLENGES: "🧰",
            }

            section_titles = {
                NewsletterStructureKeys.INDUSTRY_UPDATES: "Industry Updates",
                NewsletterStructureKeys.TOOLS_MENTIONED: "Tools Mentioned",
                NewsletterStructureKeys.WORK_PRACTICES: "Work Practices",
                NewsletterStructureKeys.SECURITY_RISKS: "Security & Risks",
                NewsletterStructureKeys.VALUABLE_POSTS: "Valuable Posts",
                NewsletterStructureKeys.OPEN_QUESTIONS: "Open Questions",
                NewsletterStructureKeys.CONCEPTUAL_DISCUSSIONS: "Conceptual Discussions",
                NewsletterStructureKeys.ISSUES_CHALLENGES: "Issues / Challenges",
            }

            for key, title in section_titles.items():
                content = sections.get(key, "")
                emoji = section_emojis.get(key, "")
                markdown += f"## {emoji} {title}\n\n"
                if content and content.strip():
                    markdown += f"{content}\n\n"
                else:
                    markdown += "No content for this section.\n\n"

            return markdown

        except Exception as e:
            error_message = f"Error generating markdown: {e}"
            logger.error(error_message)
            raise Exception(error_message) from e

    def render_html(self, response: dict, desired_language: str = DEFAULT_HTML_LANGUAGE) -> str:
        """
        Generate HTML newsletter from JSON response.

        Args:
            response: Newsletter JSON with markdown_content and individual sections
            desired_language: Target language for HTML attributes (default: DEFAULT_HTML_LANGUAGE)

        Returns:
            HTML string with complete document structure
        """
        try:
            # Get markdown content first
            markdown = self.render_markdown(response)

            # Convert basic markdown to HTML
            html_content = self._markdown_to_html(markdown)

            # Determine HTML lang and dir attributes based on desired language
            if desired_language.lower() in HEBREW_LANGUAGE_CODES:
                lang_attr = HTML_LANG_HEBREW
                dir_attr = TextDirection.RTL
            else:
                lang_attr = HTML_LANG_ENGLISH
                dir_attr = TextDirection.LTR

            return f"""<!DOCTYPE html>
<html lang="{lang_attr}" dir="{dir_attr}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MCP Israel Newsletter</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
            background-color: #ffffff;
            color: #333333;
            line-height: 1.8;
        }}
        h1 {{
            font-size: 28px;
            font-weight: bold;
            margin-bottom: 30px;
            text-align: center;
            color: #2c3e50;
        }}
        h2 {{
            font-size: 20px;
            font-weight: bold;
            margin-top: 40px;
            margin-bottom: 15px;
            border-bottom: 2px solid #3498db;
            padding-bottom: 8px;
            color: #2c3e50;
        }}
        p {{
            margin-bottom: 15px;
        }}
        ul, ol {{
            margin-bottom: 20px;
            padding-right: 25px;
        }}
        li {{
            margin-bottom: 10px;
        }}
        code {{
            background-color: #f4f4f4;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: 'Courier New', monospace;
        }}
        pre {{
            background-color: #f4f4f4;
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
            direction: ltr;
            text-align: left;
        }}
        a {{
            color: #3498db;
            text-decoration: none;
        }}
        a:hover {{
            text-decoration: underline;
        }}
        .section {{
            margin-bottom: 40px;
        }}
    </style>
</head>
<body>
{html_content}
</body>
</html>"""

        except Exception as e:
            error_message = f"Error generating HTML: {e}"
            logger.error(error_message)
            raise Exception(error_message) from e

    def _markdown_to_html(self, markdown: str) -> str:
        """
        Convert basic markdown to HTML.

        Simple conversion for headers, paragraphs, lists, and links.
        """
        import re

        lines = markdown.split("\n")
        html_lines = []
        in_list = False
        in_code_block = False

        for line in lines:
            # Code blocks
            if line.startswith("```"):
                if in_code_block:
                    html_lines.append("</pre>")
                    in_code_block = False
                else:
                    html_lines.append("<pre>")
                    in_code_block = True
                continue

            if in_code_block:
                html_lines.append(line)
                continue

            # Close list if needed
            if in_list and not line.strip().startswith("-") and not line.strip().startswith("*"):
                html_lines.append("</ul>")
                in_list = False

            # Headers
            if line.startswith("# "):
                html_lines.append(f"<h1>{line[2:]}</h1>")
            elif line.startswith("## "):
                html_lines.append(f"<h2>{line[3:]}</h2>")
            elif line.startswith("### "):
                html_lines.append(f"<h3>{line[4:]}</h3>")
            # Lists
            elif line.strip().startswith("- ") or line.strip().startswith("* "):
                if not in_list:
                    html_lines.append("<ul>")
                    in_list = True
                content = line.strip()[2:]
                # Convert markdown links to HTML
                content = re.sub(r"\[([^\]]+)\]\(([^\)]+)\)", r'<a href="\2">\1</a>', content)
                html_lines.append(f"<li>{content}</li>")
            # Paragraphs
            elif line.strip():
                content = line
                # Convert markdown links to HTML
                content = re.sub(r"\[([^\]]+)\]\(([^\)]+)\)", r'<a href="\2">\1</a>', content)
                # Convert inline code
                content = re.sub(r"`([^`]+)`", r"<code>\1</code>", content)
                # Convert bold
                content = re.sub(r"\*\*([^\*]+)\*\*", r"<strong>\1</strong>", content)
                html_lines.append(f"<p>{content}</p>")

        # Close any open list
        if in_list:
            html_lines.append("</ul>")

        return "\n".join(html_lines)
