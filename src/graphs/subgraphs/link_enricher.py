"""
Link Enricher Subgraph - LangGraph 1.0 Implementation

This module implements a subgraph that enriches newsletter content with relevant links.
It extracts URLs from original discussion messages, searches for additional relevant links,
and uses an LLM to intelligently insert links into the newsletter content.

The enricher considers:
- URLs already present in discussion messages
- Relevant web search results based on discussion topics
- Natural link placement that enhances readability
- Context-appropriate hyperlink insertion

Current Architecture:
- Four-node subgraph with sequential execution
- Node 1 (extract_links_from_messages) and Node 2 (search_web_for_topics) run sequentially
- Node 3 (aggregate_links) receives results from both
- Node 4 (insert_links_into_content) performs LLM-powered enrichment
- Modular helper functions for easy maintenance
- Fail-fast error handling throughout
- LangGraph 1.0+ compatible with RunnableConfig

==============================================================================
PARALLEL EXECUTION NOTES (LangGraph 1.0)
==============================================================================

LangGraph 1.0 provides native async node support which enables better I/O
concurrency when using async operations (LLM calls, database access, etc.).

For this subgraph, the sequential execution is maintained as the operations
are fast and don't require true parallel execution. Native async support
is available for I/O-bound operations within nodes.

Both nodes use Annotated[List, operator.add] reducers to accumulate results
independently, which is then aggregated in Node 3.

==============================================================================
"""

import os
import logging
import json
import re
from typing import Any
from urllib.parse import urlparse

from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END

from config import get_settings
from graphs.subgraphs.state import LinkEnricherState
from graphs.state_keys import EnricherKeys
from utils.tools.web_searcher.web_search_agent import WebSearchAgent
from langchain_core.prompts import ChatPromptTemplate
from utils.llm.chat_model_factory import create_chat_model
from utils.llm.json_parser import parse_json_response
from custom_types.newsletter_formats import format_handles_links_internally
from custom_types.field_keys import DiscussionKeys, DbFieldKeys, NewsletterStructureKeys
from observability import langfuse_span, extract_trace_context
from utils.run_diagnostics import get_diagnostics
from constants import NodeNames, MessageRole, OUTPUT_FILENAME_AGGREGATED_LINKS, DIAGNOSTIC_CATEGORY_LINK_ENRICHMENT, NO_CONTENT_FOR_SECTION


# Configure logging
logger = logging.getLogger(__name__)

# Node 2 constants
MAX_DISCUSSIONS_TO_SEARCH = 5
SEARCH_RESULTS_PER_QUERY = 3
MIN_LINKS_TO_SKIP_SEARCH = 2


# ============================================================================
# PROMPTS
# ============================================================================

LINK_INSERTION_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            MessageRole.SYSTEM,
            """You are an expert newsletter editor specializing in adding hyperlinks to existing content.

CRITICAL RULES - YOU MUST FOLLOW THESE EXACTLY:
1. **PRESERVE ORIGINAL LANGUAGE**: If content is in Hebrew, keep it in Hebrew. If English, keep English. DO NOT TRANSLATE.
2. **DO NOT REWRITE**: Only add markdown links. DO NOT rephrase, summarize, or change the wording.
3. **DO NOT ADD NEW TEXT**: Only convert existing text to hyperlinks. DO NOT add explanations or extra words.
4. **EXACT CONTENT PRESERVATION**: The text before and after should be IDENTICAL except for markdown link syntax.

Newsletter Format: {summary_format}
- "langtalks_format": Technical AI/LangChain community - prefer GitHub repos, documentation, research papers
- "mcp_israel_format": Israeli tech community - prefer startup news, blog posts, community resources

Available Links:
{available_links_json}

How to Add Links:
1. Find where the content mentions a tool/library/resource that has a URL in available_links
2. Wrap ONLY that mention with markdown link syntax: [existing text](url)
3. If content has a raw URL like "https://github.com/...", convert it to: [descriptive text](https://github.com/...)

Example (Hebrew content):
BEFORE: "הוזכרו כלים כמו context7 (https://github.com/upstash/context7) שמסייעים בניהול"
AFTER:  "הוזכרו כלים כמו [context7](https://github.com/upstash/context7) שמסייעים בניהול"

Example (English content):
BEFORE: "Tools like OpenSpec help with memory management"
AFTER:  "Tools like [OpenSpec](https://github.com/Fission-AI/OpenSpec) help with memory management"

Output Format:
Return a valid JSON object with this EXACT structure:
{{
  "primary_discussion": {{
    "bullet_points": [
      {{
        "id": "bullet_1",
        "content": "EXACT ORIGINAL TEXT with [only links added](https://url.com) - NO OTHER CHANGES...",
        "links_inserted": [
          {{
            "url": "https://url.com",
            "anchor_text": "only links added",
            "reason": "Why this link was inserted here"
          }}
        ]
      }}
    ]
  }},
  "secondary_discussions": [
    {{
      "id": "secondary_1",
      "bullet_points": [
        {{
          "id": "sec1_bullet_1",
          "content": "EXACT ORIGINAL TEXT with links...",
          "links_inserted": [...]
        }}
      ]
    }}
  ],
  "worth_mentioning": [
    "EXACT ORIGINAL TEXT with [link](url) if relevant..."
  ],
  "metadata": {{
    "total_links_inserted": 5,
    "insertion_strategy": "Brief explanation of link placement decisions"
  }}
}}

CRITICAL - FINAL REMINDER:
- Preserve all existing JSON structure fields (id, label, timestamps, etc.)
- PRESERVE ORIGINAL LANGUAGE - DO NOT TRANSLATE
- PRESERVE ORIGINAL WORDING - DO NOT REWRITE
- Only modify "content" fields to add markdown links
- Use Markdown link syntax: [anchor text](https://url.com)
- If a section has no good link opportunities, copy content EXACTLY as-is
- Always output valid JSON, no additional commentary""",
        ),
        (
            MessageRole.USER,
            """Newsletter Content to Enrich:
{newsletter_json}

Add markdown links to the content following ALL rules above.
CRITICAL: Preserve the original language and wording exactly. Only add link syntax.
Output valid JSON only.""",
        ),
    ]
)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def load_discussions(discussions_file: str) -> list[dict[str, Any]]:
    """
    Load and parse discussions from JSON file.

    Args:
        discussions_file: Path to the discussions JSON file

    Returns:
        List of discussion dictionaries

    Raises:
        FileNotFoundError: If file doesn't exist
        RuntimeError: If file can't be parsed
    """
    try:
        if not os.path.exists(discussions_file):
            raise FileNotFoundError(f"Discussions file not found: {discussions_file}")

        with open(discussions_file, encoding="utf-8") as f:
            discussions_data = json.load(f)

        return discussions_data.get("discussions", [])
    except (FileNotFoundError, json.JSONDecodeError):
        raise
    except Exception as e:
        logger.error(f"Unexpected error loading discussions: {e}, discussions_file={discussions_file}")
        raise RuntimeError(f"Failed to read discussions file: {e}") from e


def load_newsletter(newsletter_file: str) -> dict[str, Any]:
    """
    Load and parse newsletter JSON file.

    Args:
        newsletter_file: Path to the newsletter JSON file

    Returns:
        Newsletter dictionary

    Raises:
        FileNotFoundError: If file doesn't exist
        RuntimeError: If file can't be parsed
    """
    try:
        if not os.path.exists(newsletter_file):
            raise FileNotFoundError(f"Newsletter file not found: {newsletter_file}")

        with open(newsletter_file, encoding="utf-8") as f:
            newsletter_data = json.load(f)

        return newsletter_data
    except (FileNotFoundError, json.JSONDecodeError):
        raise
    except Exception as e:
        logger.error(f"Unexpected error loading newsletter: {e}, newsletter_file={newsletter_file}")
        raise RuntimeError(f"Failed to read newsletter file: {e}") from e


def extract_urls_from_text(text: str) -> list[str]:
    """
    Extract URLs from text using regex.

    Matches http://, https://, and www. patterns.

    Args:
        text: Text content to extract URLs from

    Returns:
        List of URL strings found in text
    """
    try:
        # Regex pattern for URLs (http, https, www)
        url_pattern = re.compile(r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+" r"|www\.(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+")

        urls = url_pattern.findall(text)

        # Normalize www. URLs to https://
        normalized_urls = []
        for url in urls:
            if url.startswith("www."):
                normalized_urls.append(f"https://{url}")
            else:
                normalized_urls.append(url)

        return normalized_urls
    except Exception as e:
        logger.error(f"Unexpected error extracting URLs from text: {e}, text_length={len(text) if text else 0}")
        raise RuntimeError(f"Failed to extract URLs from text: {e}") from e


def deduplicate_links(links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Deduplicate links by URL, keeping the first occurrence.

    Also normalizes URLs (removes trailing slashes, converts to lowercase domain).

    Args:
        links: List of link dictionaries with 'url' field

    Returns:
        Deduplicated list of link dictionaries
    """
    try:
        seen_urls = set()
        deduplicated = []

        for link in links:
            url = link.get("url", "")

            if not url:
                continue

            try:
                # Normalize URL for comparison
                parsed = urlparse(url)
                normalized_url = f"{parsed.scheme}://{parsed.netloc.lower()}{parsed.path.rstrip('/')}"

                if normalized_url not in seen_urls:
                    seen_urls.add(normalized_url)
                    # Keep original URL in output
                    deduplicated.append(link)
            except Exception as e:
                # Skip malformed URLs
                logger.warning(f"Skipping malformed URL '{url}': {e}")
                continue

        return deduplicated
    except Exception as e:
        logger.error(f"Unexpected error deduplicating links: {e}, num_links={len(links) if links else 0}")
        raise RuntimeError(f"Failed to deduplicate links: {e}") from e


def save_links_to_file(links: list[dict[str, Any]], output_file: str) -> None:
    """
    Save aggregated links to JSON file.

    Args:
        links: List of link dictionaries
        output_file: Path to output file

    Raises:
        RuntimeError: If file write fails
    """
    try:
        output_dir = os.path.dirname(output_file)
        os.makedirs(output_dir, exist_ok=True)

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump({"links": links, "count": len(links)}, f, indent=2, ensure_ascii=False)

        logger.info(f"Successfully saved {len(links)} links to: {output_file}")
    except Exception as e:
        logger.error(f"Failed to save links to file: {e}, output_file={output_file}")
        raise RuntimeError(f"Failed to write links to {output_file}: {e}") from e


def save_newsletter_to_file(newsletter_data: dict[str, Any], json_path: str, md_path: str) -> None:
    """
    Save enriched newsletter to both JSON and Markdown files.

    Args:
        newsletter_data: Enriched newsletter dictionary
        json_path: Path to output JSON file
        md_path: Path to output Markdown file

    Raises:
        RuntimeError: If file write fails
    """
    try:
        # Save JSON
        output_dir = os.path.dirname(json_path)
        os.makedirs(output_dir, exist_ok=True)

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(newsletter_data, f, indent=2, ensure_ascii=False)
        logger.info(f"Successfully saved enriched newsletter JSON to: {json_path}")

        # Generate and save Markdown
        markdown_content = convert_newsletter_json_to_markdown(newsletter_data)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        logger.info(f"Successfully saved enriched newsletter Markdown to: {md_path}")
    except Exception as e:
        logger.error(f"Failed to save newsletter to file: {e}, json_path={json_path}, md_path={md_path}")
        raise RuntimeError(f"Failed to save newsletter to file: {e}") from e


def convert_newsletter_json_to_markdown(newsletter_data: dict[str, Any]) -> str:
    """
    Convert newsletter JSON to Markdown format.

    Supports both LangTalks and MCP Israel formats:
    - LangTalks: primary_discussion, secondary_discussions, worth_mentioning
    - MCP Israel: Uses existing markdown_content field

    IMPORTANT: Preserves exact LangTalks format with numbered points and metadata footers

    Args:
        newsletter_data: Newsletter dictionary

    Returns:
        Markdown-formatted newsletter content
    """
    try:
        from datetime import datetime

        # Check if this is MCP Israel format (has markdown_content field)
        if NewsletterStructureKeys.MARKDOWN_CONTENT in newsletter_data:
            return newsletter_data[NewsletterStructureKeys.MARKDOWN_CONTENT]

        # LangTalks format processing - match exact format from langtalks generator
        markdown = "# LangTalks Newsletter\n\n"

        # Primary Discussion
        markdown += "## Primary Discussion\n\n"
        primary = newsletter_data.get(NewsletterStructureKeys.PRIMARY_DISCUSSION, {})
        if primary and primary.get(NewsletterStructureKeys.TITLE):
            markdown += f"### {primary[NewsletterStructureKeys.TITLE]}\n\n"
            for i, bullet in enumerate(primary.get(NewsletterStructureKeys.BULLET_POINTS, []), 1):
                if bullet.get(NewsletterStructureKeys.LABEL) and bullet.get(NewsletterStructureKeys.CONTENT):
                    markdown += f"{i}. **{bullet[NewsletterStructureKeys.LABEL]}**: {bullet[NewsletterStructureKeys.CONTENT]}\n\n"

            # Add attribution footer for primary discussion
            if NewsletterStructureKeys.FIRST_MESSAGE_TIMESTAMP in primary and primary[NewsletterStructureKeys.FIRST_MESSAGE_TIMESTAMP]:
                timestamp = primary[NewsletterStructureKeys.FIRST_MESSAGE_TIMESTAMP]
                if isinstance(timestamp, (int, float)):
                    dt = datetime.fromtimestamp(timestamp / 1000)  # Convert from milliseconds
                    time_str = dt.strftime("%H:%M")
                    date_str = dt.strftime("%d.%m.%y")
                    chat_name = primary.get(NewsletterStructureKeys.CHAT_NAME, "LangTalks Community")
                    markdown += f"\n📅 הדיון המלא התחיל בתאריך: {chat_name} | {time_str} | {date_str}\n"

        # Secondary Discussions
        markdown += "\n---\n\n## Secondary Discussions\n\n"
        secondary_discussions = newsletter_data.get(NewsletterStructureKeys.SECONDARY_DISCUSSIONS, [])
        for discussion in secondary_discussions:
            if discussion.get(NewsletterStructureKeys.TITLE) and discussion[NewsletterStructureKeys.TITLE] != NO_CONTENT_FOR_SECTION:
                markdown += f"### {discussion[NewsletterStructureKeys.TITLE]}\n\n"
                for i, bullet in enumerate(discussion.get(NewsletterStructureKeys.BULLET_POINTS, []), 1):
                    if bullet.get(NewsletterStructureKeys.LABEL) and bullet.get(NewsletterStructureKeys.CONTENT) and bullet[NewsletterStructureKeys.CONTENT] != NO_CONTENT_FOR_SECTION:
                        markdown += f"{i}. **{bullet[NewsletterStructureKeys.LABEL]}**: {bullet[NewsletterStructureKeys.CONTENT]}\n\n"

                # Add attribution footer for each secondary discussion
                if NewsletterStructureKeys.FIRST_MESSAGE_TIMESTAMP in discussion and discussion[NewsletterStructureKeys.FIRST_MESSAGE_TIMESTAMP]:
                    timestamp = discussion[NewsletterStructureKeys.FIRST_MESSAGE_TIMESTAMP]
                    if isinstance(timestamp, (int, float)):
                        dt = datetime.fromtimestamp(timestamp / 1000)
                        time_str = dt.strftime("%H:%M")
                        date_str = dt.strftime("%d.%m.%y")
                        chat_name = discussion.get(NewsletterStructureKeys.CHAT_NAME, "LangTalks Community")
                        markdown += f"\n📅 הדיון המלא התחיל בתאריך: {chat_name} | {time_str} | {date_str}\n"

                markdown += "\n---\n\n"

        # Worth Mentioning
        markdown += "## Worth Mentioning\n\n"
        worth_mentioning = newsletter_data.get(NewsletterStructureKeys.WORTH_MENTIONING, [])
        for point in worth_mentioning:
            if point:
                markdown += f"- {point}\n"

        return markdown
    except Exception as e:
        logger.error(f"Unexpected error converting newsletter JSON to markdown: {e}")
        raise RuntimeError(f"Failed to convert newsletter JSON to markdown: {e}") from e


# ============================================================================
# NODE 1: Extract Links from Messages
# ============================================================================


def extract_links_from_messages(state: LinkEnricherState, config: RunnableConfig | None = None) -> dict:
    """
    Extract URLs from original discussion messages.

    This node parses all messages in discussions and extracts URLs using regex.
    Each extracted URL is enriched with metadata (discussion_id, discussion_title,
    message context).

    Fail-Fast Conditions:
    - Input file not found or unreadable
    - JSON parsing errors
    - Invalid discussion structure

    Returns:
        dict: extracted_links (List[Dict]) to merge into state via reducer
    """
    # Langfuse tracing
    ctx = extract_trace_context(config)
    with langfuse_span(name=NodeNames.LinkEnricher.EXTRACT_LINKS_FROM_MESSAGES, trace_id=ctx.trace_id, parent_span_id=ctx.parent_span_id, input_data={"discussions_file": state[EnricherKeys.SEPARATE_DISCUSSIONS_FILE_PATH]}) as span:
        logger.info("Node: extract_links_from_messages - Starting")

        discussions_file = state[EnricherKeys.SEPARATE_DISCUSSIONS_FILE_PATH]

        try:
            discussions = load_discussions(discussions_file)

            extracted_links = []

            for discussion in discussions:
                discussion_id = discussion.get(DiscussionKeys.ID, "unknown")
                discussion_title = discussion.get(DiscussionKeys.TITLE, "Untitled Discussion")

                for message in discussion.get(DiscussionKeys.MESSAGES, []):
                    message_content = message.get(NewsletterStructureKeys.CONTENT, "")
                    urls = extract_urls_from_text(message_content)

                    for url in urls:
                        extracted_links.append(
                            {
                                "url": url,
                                "source": "discussion_message",
                                DbFieldKeys.DISCUSSION_ID: discussion_id,
                                "discussion_title": discussion_title,
                                "message_id": message.get(DiscussionKeys.ID),
                                "context_snippet": message_content[:200],  # First 200 chars for context
                            }
                        )

            logger.info(f"Extracted {len(extracted_links)} URLs from discussion messages")

            # Update span with output
            if span:
                span.update(output={"extracted_links_count": len(extracted_links)})

            return {EnricherKeys.EXTRACTED_LINKS: extracted_links}

        except Exception as e:
            error_message = f"Failed to extract links from messages: {e}"
            logger.error(error_message)
            raise RuntimeError(error_message) from e


# ============================================================================
# NODE 2: Search Web for Topics
# ============================================================================


async def search_web_for_topics(state: LinkEnricherState, config: RunnableConfig | None = None) -> dict:
    """
    Agentic web search: the LLM examines each discussion's existing links
    and decides whether to invoke the web_search tool.

    For each of the top discussions (by message count), a ReAct agent receives
    the discussion context plus links already extracted by Node 1. It then
    autonomously decides:
    - If sufficient links exist → skip (no tool call)
    - If links are lacking → formulate a query and call web_search

    Fail-Fast Conditions:
    - Input file not found

    Graceful Degradation (3 layers):
    1. Init failure (missing API keys): log warning, return empty searched_links
    2. Per-discussion failure: log warning, continue to next discussion
    3. Total failure: log error, return empty searched_links

    Returns:
        dict: searched_links (List[Dict]) to merge into state via reducer
    """
    # Langfuse tracing
    ctx = extract_trace_context(config)
    with langfuse_span(name=NodeNames.LinkEnricher.SEARCH_WEB_FOR_TOPICS, trace_id=ctx.trace_id, parent_span_id=ctx.parent_span_id, input_data={"discussions_file": state[EnricherKeys.SEPARATE_DISCUSSIONS_FILE_PATH]}) as span:
        logger.info("Node: search_web_for_topics - Starting (agentic mode)")

        discussions_file = state[EnricherKeys.SEPARATE_DISCUSSIONS_FILE_PATH]
        mongodb_run_id = state.get(EnricherKeys.MONGODB_RUN_ID)

        try:
            discussions = load_discussions(discussions_file)

            # Initialize WebSearchAgent (wraps GoogleSearcher + ReAct agent)
            try:
                agent = WebSearchAgent(max_search_results=SEARCH_RESULTS_PER_QUERY)
            except ValueError as e:
                logger.warning(f"WebSearchAgent initialization failed: {e}. Skipping web search.")

                if mongodb_run_id:
                    diagnostics = get_diagnostics(mongodb_run_id)
                    diagnostics.info(category=DIAGNOSTIC_CATEGORY_LINK_ENRICHMENT, message=f"Web search skipped: API keys not configured ({e})", node_name="search_web_for_topics", details={"error": str(e), "reason": "api_keys_missing"})

                if span:
                    span.update(output={"searched_links_count": 0, "skipped": True, "reason": "api_keys_missing"})
                return {EnricherKeys.SEARCHED_LINKS: []}

            searched_links = []

            # Sort discussions by num_messages (prioritize active discussions)
            sorted_discussions = sorted(discussions, key=lambda d: d.get(DiscussionKeys.NUM_MESSAGES, 0), reverse=True)[:MAX_DISCUSSIONS_TO_SEARCH]

            # Node 1 has already populated extracted_links in state
            extracted_links = state.get(EnricherKeys.EXTRACTED_LINKS, [])

            for discussion in sorted_discussions:
                discussion_id = discussion.get(DiscussionKeys.ID, "unknown")
                discussion_title = discussion.get(DiscussionKeys.TITLE, "")
                discussion_nutshell = discussion.get(DiscussionKeys.NUTSHELL, "")
                num_messages = discussion.get(DiscussionKeys.NUM_MESSAGES, 0)

                if not discussion_title:
                    continue

                # Filter extracted links for this specific discussion
                existing_links_for_discussion = [link for link in extracted_links if link.get(DbFieldKeys.DISCUSSION_ID) == discussion_id]

                try:
                    logger.info(f"Running agentic search for discussion '{discussion_title}' " f"(existing_links={len(existing_links_for_discussion)}, messages={num_messages})")

                    results = await agent.search_for_discussion(
                        discussion_id=discussion_id,
                        discussion_title=discussion_title,
                        discussion_nutshell=discussion_nutshell,
                        num_messages=num_messages,
                        existing_links=existing_links_for_discussion,
                    )

                    if results:
                        searched_links.extend(results)
                        logger.info(f"Agent found {len(results)} web results for '{discussion_title}'")
                    else:
                        logger.info(f"Agent decided no search needed for '{discussion_title}'")

                except Exception as search_error:
                    logger.warning(f"Agentic web search failed for '{discussion_title}': {search_error}")

                    if mongodb_run_id:
                        diagnostics = get_diagnostics(mongodb_run_id)
                        diagnostics.warning(category=DIAGNOSTIC_CATEGORY_LINK_ENRICHMENT, message=f"Agentic web search failed for discussion '{discussion_title}': {search_error}", node_name="search_web_for_topics", details={DbFieldKeys.DISCUSSION_ID: discussion_id, "discussion_title": discussion_title, "error": str(search_error)})

                    continue

            logger.info(f"Agentic web search completed: found {len(searched_links)} relevant URLs")

            if span:
                span.update(output={"searched_links_count": len(searched_links), "discussions_searched": len(sorted_discussions)})

            return {EnricherKeys.SEARCHED_LINKS: searched_links}

        except FileNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Web search node encountered error: {e}. Returning empty results.")

            if mongodb_run_id:
                diagnostics = get_diagnostics(mongodb_run_id)
                diagnostics.warning(category=DIAGNOSTIC_CATEGORY_LINK_ENRICHMENT, message=f"Web search node failed completely: {e}", node_name="search_web_for_topics", details={"error": str(e), "error_type": type(e).__name__})

            if span:
                span.update(output={"searched_links_count": 0, "error": str(e)})
            return {EnricherKeys.SEARCHED_LINKS: []}


# ============================================================================
# NODE 3: Aggregate Links
# ============================================================================


def aggregate_links(state: LinkEnricherState, config: RunnableConfig | None = None) -> dict:
    """
    Aggregate and deduplicate links from extraction and web search.

    This node receives results from both extract_links_from_messages and
    search_web_for_topics (via state reducers), merges them, deduplicates
    by URL, and saves to a file.

    Fail-Fast Conditions:
    - Output directory not writable
    - File write fails

    Returns:
        dict: aggregated_links_file_path, num_links_extracted, num_links_searched
    """
    # Langfuse tracing
    ctx = extract_trace_context(config)
    with langfuse_span(name=NodeNames.LinkEnricher.AGGREGATE_LINKS, trace_id=ctx.trace_id, parent_span_id=ctx.parent_span_id, input_data={"extracted_links_count": len(state.get(EnricherKeys.EXTRACTED_LINKS, [])), "searched_links_count": len(state.get(EnricherKeys.SEARCHED_LINKS, []))}) as span:
        logger.info("Node: aggregate_links - Starting")

        extracted_links = state.get(EnricherKeys.EXTRACTED_LINKS, [])
        searched_links = state.get(EnricherKeys.SEARCHED_LINKS, [])
        link_enrichment_dir = state[EnricherKeys.LINK_ENRICHMENT_DIR]

        try:
            # Combine all links
            all_links = extracted_links + searched_links

            # Deduplicate by URL
            deduplicated_links = deduplicate_links(all_links)

            # Save to file
            aggregated_file = os.path.join(link_enrichment_dir, OUTPUT_FILENAME_AGGREGATED_LINKS)
            save_links_to_file(deduplicated_links, aggregated_file)

            logger.info(f"Aggregated {len(all_links)} total links -> " f"{len(deduplicated_links)} unique links " f"({len(extracted_links)} extracted, {len(searched_links)} searched)")

            # Update span with output
            if span:
                span.update(output={"unique_links_count": len(deduplicated_links), "total_before_dedup": len(all_links), "file_path": aggregated_file})

            return {EnricherKeys.AGGREGATED_LINKS_FILE_PATH: aggregated_file, EnricherKeys.NUM_LINKS_EXTRACTED: len(extracted_links), EnricherKeys.NUM_LINKS_SEARCHED: len(searched_links)}

        except Exception as e:
            error_message = f"Failed to aggregate links: {e}"
            logger.error(error_message)
            raise RuntimeError(error_message) from e


# ============================================================================
# NODE 4: Insert Links into Content
# ============================================================================


async def insert_links_into_content(state: LinkEnricherState, config: RunnableConfig | None = None) -> dict:
    """
    Use LLM to intelligently insert links into newsletter content.

    This node loads the aggregated links and newsletter content, then uses
    an LLM to decide where and how to insert links naturally. The LLM considers:
    - Contextual relevance of each link
    - Natural placement that enhances readability
    - Quality over quantity (prefer fewer well-placed links)

    Format Support:
    - langtalks_format: Full LLM-powered link enrichment supported
    - mcp_israel_format: Links already embedded during content generation, copy newsletter as-is

    Fail-Fast Conditions:
    - Input files not found
    - OpenAI API errors (langtalks_format only)
    - Invalid LLM response structure (langtalks_format only)
    - Output file write fails

    Returns:
        dict: enriched_newsletter_json_path, enriched_newsletter_md_path, num_links_inserted
    """
    # Langfuse tracing
    ctx = extract_trace_context(config)
    with langfuse_span(name=NodeNames.LinkEnricher.INSERT_LINKS_INTO_CONTENT, trace_id=ctx.trace_id, parent_span_id=ctx.parent_span_id, input_data={"newsletter_file": state[EnricherKeys.NEWSLETTER_JSON_PATH], "summary_format": state[EnricherKeys.SUMMARY_FORMAT]}) as span:
        logger.info("Node: insert_links_into_content - Starting")

        aggregated_links_file = state[EnricherKeys.AGGREGATED_LINKS_FILE_PATH]
        newsletter_json_path = state[EnricherKeys.NEWSLETTER_JSON_PATH]
        expected_enriched_json = state[EnricherKeys.EXPECTED_ENRICHED_NEWSLETTER_JSON]
        expected_enriched_md = state[EnricherKeys.EXPECTED_ENRICHED_NEWSLETTER_MD]
        summary_format = state[EnricherKeys.SUMMARY_FORMAT]
        mongodb_run_id = state.get(EnricherKeys.MONGODB_RUN_ID)

        # Check if format handles links internally (embedded during content generation)
        if format_handles_links_internally(summary_format):
            logger.info(f"Format '{summary_format}' handles links internally - copying newsletter as-is")
            try:
                newsletter_data = load_newsletter(newsletter_json_path)
                save_newsletter_to_file(newsletter_data, expected_enriched_json, expected_enriched_md)
                if span:
                    span.update(output={"skipped": True, "reason": "format_handles_links_internally", "enriched_json": expected_enriched_json, "enriched_md": expected_enriched_md})
                return {
                    EnricherKeys.ENRICHED_NEWSLETTER_JSON_PATH: expected_enriched_json,
                    EnricherKeys.ENRICHED_NEWSLETTER_MD_PATH: expected_enriched_md,
                    EnricherKeys.NUM_LINKS_INSERTED: 0,  # Links already embedded, not counted separately
                }
            except Exception as e:
                error_message = f"Failed to copy newsletter for format '{summary_format}': {e}"
                logger.error(error_message)
                raise RuntimeError(error_message) from e

        try:
            # Load aggregated links
            if not os.path.exists(aggregated_links_file):
                raise FileNotFoundError(f"Aggregated links file not found: {aggregated_links_file}")

            with open(aggregated_links_file, encoding="utf-8") as f:
                links_data = json.load(f)

            available_links = links_data.get("links", [])

            if not available_links:
                logger.warning("No links available for insertion. Copying original newsletter as-is.")

                # Add diagnostic if run_id available
                if mongodb_run_id:
                    diagnostics = get_diagnostics(mongodb_run_id)
                    diagnostics.info(category=DIAGNOSTIC_CATEGORY_LINK_ENRICHMENT, message="No links available for insertion - newsletter published without link enrichment", node_name="insert_links_into_content", details={"reason": "no_links_available"})

                # Copy original newsletter to enriched output
                newsletter_data = load_newsletter(newsletter_json_path)
                save_newsletter_to_file(newsletter_data, expected_enriched_json, expected_enriched_md)
                if span:
                    span.update(output={"num_links_inserted": 0, "reason": "no_links_available", "enriched_json": expected_enriched_json})
                return {EnricherKeys.ENRICHED_NEWSLETTER_JSON_PATH: expected_enriched_json, EnricherKeys.ENRICHED_NEWSLETTER_MD_PATH: expected_enriched_md, EnricherKeys.NUM_LINKS_INSERTED: 0}

            # Load newsletter content
            newsletter_data = load_newsletter(newsletter_json_path)

            # Prepare data for LLM
            available_links_json = json.dumps(available_links, indent=2, ensure_ascii=False)
            newsletter_json = json.dumps(newsletter_data, indent=2, ensure_ascii=False)

            # Initialize LLM
            try:
                settings = get_settings()
                llm = create_chat_model(model=settings.llm.link_enricher_model, temperature=settings.llm.temperature_link_enricher, model_kwargs={"response_format": {"type": "json_object"}})
            except Exception as e:
                raise RuntimeError(f"Failed to initialize LLM client: {e}")

            # Create prompt chain
            chain = LINK_INSERTION_PROMPT | llm

            # Invoke LLM
            logger.info(f"Enriching newsletter with {len(available_links)} available links using LLM...")
            try:
                response = await chain.ainvoke({"newsletter_json": newsletter_json, "available_links_json": available_links_json, "summary_format": summary_format})

                # Parse LLM response
                enriched_newsletter = parse_json_response(response.content)

                # Validate response structure (basic check)
                if NewsletterStructureKeys.PRIMARY_DISCUSSION not in enriched_newsletter:
                    raise ValueError("LLM response missing 'primary_discussion' field")

                # Extract metadata
                metadata = enriched_newsletter.get(NewsletterStructureKeys.METADATA, {})
                num_links_inserted = metadata.get("total_links_inserted", 0)

                logger.info(f"LLM inserted {num_links_inserted} links into newsletter")

                # Merge enriched content back into original structure
                # Preserve all original fields (timestamps, ids, etc.) but update content
                final_newsletter = newsletter_data.copy()

                # Update primary discussion bullet points
                if NewsletterStructureKeys.PRIMARY_DISCUSSION in enriched_newsletter:
                    enriched_primary = enriched_newsletter[NewsletterStructureKeys.PRIMARY_DISCUSSION]
                    if NewsletterStructureKeys.BULLET_POINTS in enriched_primary:
                        for i, enriched_bullet in enumerate(enriched_primary[NewsletterStructureKeys.BULLET_POINTS]):
                            if i < len(final_newsletter[NewsletterStructureKeys.PRIMARY_DISCUSSION][NewsletterStructureKeys.BULLET_POINTS]):
                                final_newsletter[NewsletterStructureKeys.PRIMARY_DISCUSSION][NewsletterStructureKeys.BULLET_POINTS][i][NewsletterStructureKeys.CONTENT] = enriched_bullet.get(NewsletterStructureKeys.CONTENT, "")
                                # Add links_inserted metadata
                                final_newsletter[NewsletterStructureKeys.PRIMARY_DISCUSSION][NewsletterStructureKeys.BULLET_POINTS][i][NewsletterStructureKeys.LINKS_INSERTED] = enriched_bullet.get(NewsletterStructureKeys.LINKS_INSERTED, [])

                # Update secondary discussions
                if NewsletterStructureKeys.SECONDARY_DISCUSSIONS in enriched_newsletter:
                    for sec_idx, enriched_sec in enumerate(enriched_newsletter[NewsletterStructureKeys.SECONDARY_DISCUSSIONS]):
                        if sec_idx < len(final_newsletter.get(NewsletterStructureKeys.SECONDARY_DISCUSSIONS, [])):
                            if NewsletterStructureKeys.BULLET_POINTS in enriched_sec:
                                for bullet_idx, enriched_bullet in enumerate(enriched_sec[NewsletterStructureKeys.BULLET_POINTS]):
                                    if bullet_idx < len(final_newsletter[NewsletterStructureKeys.SECONDARY_DISCUSSIONS][sec_idx].get(NewsletterStructureKeys.BULLET_POINTS, [])):
                                        final_newsletter[NewsletterStructureKeys.SECONDARY_DISCUSSIONS][sec_idx][NewsletterStructureKeys.BULLET_POINTS][bullet_idx][NewsletterStructureKeys.CONTENT] = enriched_bullet.get(NewsletterStructureKeys.CONTENT, "")
                                        final_newsletter[NewsletterStructureKeys.SECONDARY_DISCUSSIONS][sec_idx][NewsletterStructureKeys.BULLET_POINTS][bullet_idx][NewsletterStructureKeys.LINKS_INSERTED] = enriched_bullet.get(NewsletterStructureKeys.LINKS_INSERTED, [])

                # Update worth_mentioning
                if NewsletterStructureKeys.WORTH_MENTIONING in enriched_newsletter:
                    final_newsletter[NewsletterStructureKeys.WORTH_MENTIONING] = enriched_newsletter[NewsletterStructureKeys.WORTH_MENTIONING]

                # Add enrichment metadata
                final_newsletter[NewsletterStructureKeys.LINK_ENRICHMENT_METADATA] = {"total_links_available": len(available_links), "total_links_inserted": num_links_inserted, "insertion_strategy": metadata.get("insertion_strategy", ""), "enriched_at": newsletter_data.get("updated_at", 0)}

                # Save enriched newsletter
                save_newsletter_to_file(final_newsletter, expected_enriched_json, expected_enriched_md)

                logger.info(f"Successfully enriched newsletter with {num_links_inserted} links")

                # Update span with output
                if span:
                    span.update(output={"num_links_inserted": num_links_inserted, "links_available": len(available_links), "enriched_json": expected_enriched_json, "enriched_md": expected_enriched_md})

                return {EnricherKeys.ENRICHED_NEWSLETTER_JSON_PATH: expected_enriched_json, EnricherKeys.ENRICHED_NEWSLETTER_MD_PATH: expected_enriched_md, EnricherKeys.NUM_LINKS_INSERTED: num_links_inserted}

            except json.JSONDecodeError as e:
                raise RuntimeError(f"Failed to parse LLM response as JSON: {e}")
            except Exception as e:
                raise RuntimeError(f"LLM enrichment failed: {e}")

        except FileNotFoundError:
            # Re-raise file not found (fail-fast)
            raise
        except Exception as e:
            error_message = f"Failed to insert links into content: {e}"
            logger.error(error_message)
            raise RuntimeError(error_message) from e


# ============================================================================
# GRAPH CONSTRUCTION
# ============================================================================


def build_link_enricher_graph() -> StateGraph:
    """
    Build and compile the link enricher subgraph.

    Graph Structure (LangGraph 1.0+):
    START → extract_links_from_messages → search_web_for_topics →
    aggregate_links → insert_links_into_content → END

    Note on Execution:
    - Nodes 1 and 2 are semantically independent (could run in parallel)
    - Currently run sequentially for simplicity (~2-6 seconds total overhead)
    - Both nodes populate state via Annotated reducers (operator.add)
    - Node 3 receives aggregated results from both

    Returns:
        Compiled StateGraph with checkpointing enabled
    """
    try:
        logger.info("Building link enricher subgraph...")

        # Create graph builder
        builder = StateGraph(LinkEnricherState)

        # Add nodes
        builder.add_node(NodeNames.LinkEnricher.EXTRACT_LINKS_FROM_MESSAGES, extract_links_from_messages)
        builder.add_node(NodeNames.LinkEnricher.SEARCH_WEB_FOR_TOPICS, search_web_for_topics)
        builder.add_node(NodeNames.LinkEnricher.AGGREGATE_LINKS, aggregate_links)
        builder.add_node(NodeNames.LinkEnricher.INSERT_LINKS_INTO_CONTENT, insert_links_into_content)

        # Define sequential flow
        # (Semantically parallel nodes 1 & 2, currently executed sequentially for simplicity)
        builder.add_edge(START, NodeNames.LinkEnricher.EXTRACT_LINKS_FROM_MESSAGES)
        builder.add_edge(NodeNames.LinkEnricher.EXTRACT_LINKS_FROM_MESSAGES, NodeNames.LinkEnricher.SEARCH_WEB_FOR_TOPICS)
        builder.add_edge(NodeNames.LinkEnricher.SEARCH_WEB_FOR_TOPICS, NodeNames.LinkEnricher.AGGREGATE_LINKS)
        builder.add_edge(NodeNames.LinkEnricher.AGGREGATE_LINKS, NodeNames.LinkEnricher.INSERT_LINKS_INTO_CONTENT)
        builder.add_edge(NodeNames.LinkEnricher.INSERT_LINKS_INTO_CONTENT, END)

        # Compile without checkpointer — subgraphs are invoked atomically via ainvoke
        # and are not resumable, so checkpointing provides no value and leaks memory
        compiled_graph = builder.compile()

        logger.info("Link enricher subgraph compiled successfully")

        return compiled_graph
    except Exception as e:
        logger.error(f"Failed to build link enricher graph: {e}")
        raise RuntimeError(f"Failed to build link enricher graph: {e}") from e


# Create and export the compiled subgraph
link_enricher_graph = build_link_enricher_graph()
