import logging
import re

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from utils.llm.chat_model_factory import create_chat_model

from config import get_settings
from custom_types.field_keys import DiscussionKeys, DbFieldKeys
from utils.tools.web_searcher.base_web_searcher import BaseWebSearcher
from utils.tools.web_searcher.google_searcher import GoogleSearcher

logger = logging.getLogger(__name__)

MIN_LINKS_THRESHOLD = 2


def _make_web_search_tool(search_engine: BaseWebSearcher, max_results: int):
    """Factory that returns a standalone @tool-decorated async function via closure.

    This avoids the known bug of decorating an instance method with @tool,
    which causes `self` to appear as a tool parameter.
    """

    @tool
    async def web_search(query: str) -> str:
        """Search the web for relevant articles, documentation, GitHub repos, or blog posts about a topic."""
        try:
            logger.info(f"WebSearchAgent tool invoked with query: {query}")
            results = await search_engine.search(query, num_results=max_results)

            if not results:
                return "No results found."

            formatted_results = []
            for i, result in enumerate(results, 1):
                title = result.get("title", "No title")
                url = result.get("link", "No link")
                snippet = result.get("snippet", "No description")
                formatted_results.append(f"Result {i}:\nTitle: {title}\nURL: {url}\nSnippet: {snippet}")

            return "\n\n".join(formatted_results)

        except Exception as e:
            logger.error(f"WebSearchAgent tool error: {e}", exc_info=True)
            return f"Error searching the web: {e}"

    return web_search


def _parse_tool_results(messages: list) -> list[dict]:
    """Walk messages in reverse, find the last ToolMessage, and parse structured results."""
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage):
            return _parse_search_output(msg.content)
    return []


def _parse_search_output(text: str) -> list[dict]:
    """Parse the formatted search output into structured dicts."""
    results = []
    # Split on "Result N:" boundaries
    blocks = re.split(r"Result \d+:", text)
    for block in blocks:
        block = block.strip()
        if not block:
            continue

        title_match = re.search(r"Title:\s*(.+)", block)
        url_match = re.search(r"URL:\s*(.+)", block)
        snippet_match = re.search(r"Snippet:\s*(.+)", block)

        url = url_match.group(1).strip() if url_match else ""
        if not url or url == "No link":
            continue

        results.append(
            {
                DiscussionKeys.TITLE: title_match.group(1).strip() if title_match else "",
                "url": url,
                "snippet": snippet_match.group(1).strip() if snippet_match else "",
            }
        )

    return results


class WebSearchAgent:
    """Agentic web search: the LLM examines existing links and decides whether to search."""

    def __init__(
        self,
        search_engine: BaseWebSearcher | None = None,
        model_name: str | None = None,
        temperature: float | None = None,
        max_search_results: int = 3,
    ):
        settings = get_settings()
        self.search_engine = search_engine or GoogleSearcher()
        self.model_name = model_name or settings.llm.web_search_model
        self.temperature = temperature if temperature is not None else settings.llm.temperature_web_search
        self.max_search_results = max_search_results

        self._tool = _make_web_search_tool(self.search_engine, self.max_search_results)
        self._llm = create_chat_model(model=self.model_name, temperature=self.temperature)
        self._agent = create_react_agent(self._llm, [self._tool])

    async def search_for_discussion(
        self,
        discussion_id: str,
        discussion_title: str,
        discussion_nutshell: str,
        num_messages: int,
        existing_links: list[dict],
    ) -> list[dict]:
        """Run the agentic search for a single discussion.

        The LLM decides whether to invoke the web_search tool based on
        how many relevant links the discussion already has.

        Returns:
            List of link dicts in canonical format, or empty list if the
            agent decided no search was needed.
        """
        try:
            formatted_existing = self._format_existing_links(existing_links)

            prompt = (
                f"You are enriching a newsletter discussion with relevant web links.\n\n"
                f'Discussion: "{discussion_title}"\n'
                f'Summary: "{discussion_nutshell}"\n'
                f"Message count: {num_messages}\n\n"
                f"Links already found in this discussion's messages:\n"
                f"{formatted_existing}\n\n"
                f"Your task:\n"
                f"- If the discussion already has {MIN_LINKS_THRESHOLD} or more relevant links, "
                f'respond: "No search needed - discussion already has sufficient links."\n'
                f"- If the discussion has fewer than {MIN_LINKS_THRESHOLD} relevant links, "
                f"call web_search with a targeted query to find relevant resources.\n"
                f"- Make at most 1 search call.\n"
            )

            response = await self._agent.ainvoke({"messages": [HumanMessage(content=prompt)]})

            parsed = _parse_tool_results(response["messages"])

            return [
                {
                    "url": r["url"],
                    DiscussionKeys.TITLE: r[DiscussionKeys.TITLE],
                    "snippet": r["snippet"],
                    "source": "web_search_agent",
                    DbFieldKeys.DISCUSSION_ID: discussion_id,
                    "discussion_title": discussion_title,
                    "search_query": self._extract_search_query(response["messages"]),
                }
                for r in parsed
            ]

        except Exception as e:
            logger.error(
                f"WebSearchAgent.search_for_discussion failed for discussion_id={discussion_id}, " f"title='{discussion_title}': {e}",
                exc_info=True,
            )
            raise

    @staticmethod
    def _format_existing_links(links: list[dict]) -> str:
        if not links:
            return "None"
        lines = []
        for link in links:
            url = link.get("url", "")
            title = link.get("discussion_title", link.get("title", ""))
            lines.append(f"- {url} ({title})" if title else f"- {url}")
        return "\n".join(lines)

    @staticmethod
    def _extract_search_query(messages: list) -> str:
        """Extract the query the agent used when calling the tool."""
        for msg in messages:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for call in msg.tool_calls:
                    if call.get("name") == "web_search":
                        return call.get("args", {}).get("query", "")
        return ""
