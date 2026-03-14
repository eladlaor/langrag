import os
import logging
from typing import Any
from substack import Api
from substack.post import Post
from constants import SummaryFormats, NO_CONTENT_FOR_SECTION
from custom_types.field_keys import NewsletterStructureKeys


class SubstackSender:
    """
    Substack newsletter publisher that creates styled draft posts.
    Follows existing BaseEmailSender pattern for consistency.
    """

    def __init__(self, email: str = None, password: str = None):
        # Get credentials from environment or parameters
        self.email = email or os.getenv("SUBSTACK_EMAIL")
        self.password = password or os.getenv("SUBSTACK_PASSWORD")

        if not self.email or not self.password:
            raise ValueError("Substack email and password are required. Set SUBSTACK_EMAIL and SUBSTACK_PASSWORD environment variables.")

        try:
            self.api = Api(email=self.email, password=self.password)
            self.user_id = self.api.get_user_id()
            logging.info(f"Successfully initialized Substack API for user: {self.user_id}")
        except Exception as e:
            logging.error(f"Failed to initialize Substack API: {e}")
            raise ValueError(f"Failed to authenticate with Substack: {e}")

    def create_draft(self, newsletter_data: dict, config: dict) -> dict[str, Any]:
        """
        Create Substack draft from newsletter data.
        Handles both MCP and LangTalks formats in single method (DRY).
        """
        try:
            logging.info(f"Creating Substack draft with title: {config.get('title', 'Newsletter Update')}")

            # Create post with basic info
            post = Post(title=config.get("title", "Newsletter Update"), subtitle=config.get("subtitle", ""), user_id=self.user_id)

            # Single method handles both formats (DRY principle)
            self._add_content_to_post(post, newsletter_data, config.get("summary_format"))

            # Create draft
            draft = self.api.post_draft(post.get_draft())
            logging.info(f"Successfully created draft with ID: {draft.get('id')}")

            # Handle section assignment if specified
            if config.get("section_name"):
                self._assign_section(draft, config["section_name"])

            # Auto-publish if explicitly requested (default: False for safety)
            published = False
            if config.get("auto_publish") is True:  # Explicit True check for safety
                try:
                    self.api.publish_draft(draft.get("id"))
                    published = True
                    logging.info(f"Successfully published draft: {draft.get('id')}")
                except Exception as e:
                    logging.warning(f"Failed to auto-publish draft: {e}")

            return {"success": True, "draft_id": draft.get("id"), "draft_url": f"https://substack.com/drafts/{draft.get('id')}", "published": published, "message": "Draft created successfully" + (" and published" if published else "")}

        except Exception as e:
            error_msg = f"Failed to create Substack draft: {e}"
            logging.error(error_msg)
            return {"success": False, "error": str(e)}

    def _add_content_to_post(self, post: Post, newsletter_data: dict, format_type: str):
        """
        Single method to handle both MCP and LangTalks formats.
        Eliminates need for separate transformer classes.
        """
        try:
            if format_type == SummaryFormats.MCP_ISRAEL_FORMAT:
                self._add_mcp_content(post, newsletter_data)
                logging.info("Added MCP Israel format content to post")
            elif format_type == SummaryFormats.LANGTALKS_FORMAT:
                self._add_langtalks_content(post, newsletter_data)
                logging.info("Added LangTalks format content to post")
            else:
                # Fallback: try to detect format from data structure
                if NewsletterStructureKeys.INDUSTRY_UPDATES in newsletter_data:
                    self._add_mcp_content(post, newsletter_data)
                    logging.info("Auto-detected MCP format and added content")
                elif NewsletterStructureKeys.PRIMARY_DISCUSSION in newsletter_data:
                    self._add_langtalks_content(post, newsletter_data)
                    logging.info("Auto-detected LangTalks format and added content")
                else:
                    logging.warning("Could not detect newsletter format, adding basic content")
                    post.add({"type": "paragraph", "content": "Newsletter content could not be formatted properly."})
        except Exception as e:
            logging.error(f"Error adding content to post: {e}")
            raise

    def _add_mcp_content(self, post: Post, data: dict):
        """Handle MCP Israel format content."""
        sections = [("industry_updates", "📣 עדכוני תעשייה"), ("tools_mentioned", "🧰 כלים שהוזכרו"), ("work_practices", "🧪 שיטות עבודה"), ("security_risks", "🔐 אבטחה וסיכונים"), ("valuable_posts", "📎 פוסטים בעלי ערך"), ("open_questions", "💭 שאלות פתוחות"), ("conceptual_discussions", "🧠 דיונים קונספטואליים"), ("issues_challenges", "🧰 בעיות ואתגרים")]

        content_added = False
        for key, title in sections:
            content = data.get(key, "").strip()
            if content and content != NO_CONTENT_FOR_SECTION and content != "No content provided for this section":
                self._add_section_to_post(post, title, content)
                content_added = True

        if not content_added:
            logging.warning("No valid MCP content sections found")
            post.add({"type": "paragraph", "content": "No content available for this newsletter period."})

    def _add_langtalks_content(self, post: Post, data: dict):
        """Handle LangTalks format content."""
        content_added = False

        # Primary Discussion
        primary = data.get(NewsletterStructureKeys.PRIMARY_DISCUSSION, {})
        if primary and primary.get(NewsletterStructureKeys.TITLE):
            post.add({"type": "paragraph", "content": [{"content": "🎯 Primary Discussion: ", "marks": [{"type": "strong"}]}, {"content": primary.get(NewsletterStructureKeys.TITLE, ""), "marks": [{"type": "strong"}]}]})

            for bullet in primary.get(NewsletterStructureKeys.BULLET_POINTS, []):
                if bullet.get(NewsletterStructureKeys.LABEL) and bullet.get(NewsletterStructureKeys.CONTENT):
                    post.add({"type": "paragraph", "content": [{"content": f"• {bullet.get(NewsletterStructureKeys.LABEL, '')}: ", "marks": [{"type": "strong"}]}, {"content": bullet.get(NewsletterStructureKeys.CONTENT, "")}]})
            content_added = True

        # Secondary Discussions
        secondary = data.get(NewsletterStructureKeys.SECONDARY_DISCUSSIONS, [])
        if secondary and len(secondary) > 0:
            post.add({"type": "paragraph", "content": [{"content": "📋 Secondary Discussions", "marks": [{"type": "strong"}]}]})
            for discussion in secondary:
                if discussion.get(NewsletterStructureKeys.TITLE) and discussion.get(NewsletterStructureKeys.TITLE) != "No secondary discussion":
                    post.add({"type": "paragraph", "content": [{"content": f"### {discussion[NewsletterStructureKeys.TITLE]}", "marks": [{"type": "strong"}]}]})
                    for bullet in discussion.get(NewsletterStructureKeys.BULLET_POINTS, []):
                        if bullet.get(NewsletterStructureKeys.LABEL) and bullet.get(NewsletterStructureKeys.CONTENT) and bullet.get(NewsletterStructureKeys.CONTENT) != "No content":
                            post.add({"type": "paragraph", "content": [{"content": f"• {bullet.get(NewsletterStructureKeys.LABEL, '')}: ", "marks": [{"type": "strong"}]}, {"content": bullet.get(NewsletterStructureKeys.CONTENT, "")}]})
            content_added = True

        # Worth Mentioning
        worth_mentioning = data.get(NewsletterStructureKeys.WORTH_MENTIONING, [])
        if worth_mentioning and len(worth_mentioning) > 0:
            post.add({"type": "paragraph", "content": [{"content": "💡 Worth Mentioning", "marks": [{"type": "strong"}]}]})
            for item in worth_mentioning:
                if item and item.strip():
                    post.add({"type": "paragraph", "content": f"• {item}"})
            content_added = True

        if not content_added:
            logging.warning("No valid LangTalks content found")
            post.add({"type": "paragraph", "content": "No discussions available for this newsletter period."})

    def _add_section_to_post(self, post: Post, title: str, content: str):
        """DRY helper method for adding sections."""
        # Add section header
        post.add({"type": "paragraph", "content": [{"content": title, "marks": [{"type": "strong"}]}]})

        # Split content into paragraphs and add each
        paragraphs = content.split("\n\n")
        for paragraph in paragraphs:
            paragraph = paragraph.strip()
            if paragraph:
                post.add({"type": "paragraph", "content": paragraph})

    def _assign_section(self, draft: dict, section_name: str):
        """Assign draft to specific section."""
        try:
            sections = self.api.get_sections()
            for section in sections:
                if section.get("name") == section_name:
                    self.api.put_draft(draft.get("id"), draft_section_id=section.get("id"))
                    logging.info(f"Successfully assigned draft to section: {section_name}")
                    return
            logging.warning(f"Section '{section_name}' not found in available sections")
        except Exception as e:
            logging.warning(f"Failed to assign section '{section_name}': {e}")

    # Note: SubstackSender doesn't inherit from BaseEmailSender to avoid import conflicts
    # It has its own create_draft() method instead of the email-based send() pattern
