"""
State Schemas for Subgraphs

Defines TypedDict state schemas for reusable subgraph components:
- DiscussionRankerState: For ranking and categorizing discussions
- LinkEnricherState: For enriching newsletters with relevant links
"""

import operator
from typing import Annotated, Any
from typing_extensions import TypedDict

from graphs.state_keys import (
    RankerKeys,
    EnricherKeys,
    SingleChatKeys,
)
from config import get_settings


class DiscussionRankerState(TypedDict):
    """
    State for the discussions_ranker subgraph.

    This subgraph analyzes separated discussions and produces insights and recommendations
    about which discussions should be featured in which newsletter sections and why.

    The ranker considers factors like:
    - Discussion relevance and importance
    - Technical depth and quality
    - Community engagement (number of messages, participants)
    - Topical diversity for the newsletter
    - Recency and timeliness
    - Repetition with previous newsletters (anti-repetition feature)

    Output includes:
    - Ranked discussions with scores and reasoning
    - One-liner summaries for each discussion (teachable moments)
    - Categorization: 'featured' (top-K) or 'brief_mention' (rest)
    - Convenience lists: featured_discussion_ids, brief_mention_items
    - Repetition analysis: repetition_score and repetition_identification_reasoning
    """

    # === Input Fields (Required) ===
    separate_discussions_file_path: str  # Path to discussions JSON from separate_discussions node
    discussions_ranking_dir: str  # Output directory for ranking results
    expected_discussions_ranking_file: str  # Expected output file path
    summary_format: str  # Newsletter format (affects ranking criteria)

    # === Top-K Configuration ===
    top_k_discussions: int | None  # Number of discussions to feature (default: 5)

    # === MMR Diversity Configuration ===
    enable_mmr_diversity: bool | None  # Enable MMR diversity reranking (default: True)
    mmr_lambda: float | None  # MMR balance parameter (0-1, default: 0.7)

    # === Anti-Repetition Configuration ===
    previous_newsletters_to_consider: int | None  # Max previous newsletters to check (default: 5, 0 disables)
    data_source_name: str | None  # Data source name for loading history (e.g., "langtalks")
    current_start_date: str | None  # Current newsletter start date (YYYY-MM-DD) for filtering history

    # === Force Refresh Flag ===
    force_refresh_discussions_ranking: bool | None

    # === Langfuse Trace Context (Optional) ===
    # These fields are used to propagate trace context from parent graph
    # for proper parent-child span relationships in Langfuse
    langfuse_trace_id: str | None  # Root trace ID from API endpoint
    langfuse_session_id: str | None  # Session ID (thread_id)
    langfuse_user_id: str | None  # User ID (data_source_name)

    # === MongoDB Run Tracking (Optional - for diagnostics) ===
    mongodb_run_id: str | None  # MongoDB run ID for diagnostics tracking

    # === Output Fields ===
    discussions_ranking_file_path: str | None  # Path to ranking results JSON


class LinkEnricherState(TypedDict):
    """
    State for the link_enricher subgraph.

    This subgraph enriches newsletter content by:
    1. Extracting URLs from original discussion messages
    2. Searching web for relevant links based on discussion topics
    3. Aggregating and deduplicating links from both sources
    4. Using LLM to intelligently insert links into newsletter content

    Architecture Notes:
    - Uses sequential execution for extraction and web search (LangGraph 1.0+)
    - File-based state (stores paths, not content)
    - Fail-fast error handling with graceful degradation for web search
    - Reducers accumulate links from multiple sources
    """

    # === Input Fields (Required) ===
    separate_discussions_file_path: str  # Path to discussions JSON (source of URLs and topics)
    newsletter_json_path: str  # Path to newsletter JSON to enrich
    newsletter_md_path: str  # Path to newsletter MD to enrich
    link_enrichment_dir: str  # Output directory for enrichment results
    expected_enriched_newsletter_json: str  # Expected output file path
    expected_enriched_newsletter_md: str  # Expected output MD file path
    summary_format: str  # Newsletter format (affects link insertion strategy)

    # === Force Refresh Flag ===
    force_refresh_link_enrichment: bool | None

    # === MongoDB Run Tracking (Optional - for diagnostics) ===
    mongodb_run_id: str | None  # MongoDB run ID for diagnostics tracking

    # === Intermediate Fields (Set by nodes with reducers) ===
    # These fields accumulate results from extraction and web search nodes
    extracted_links: Annotated[list[dict[str, Any]], operator.add]  # URLs from messages
    searched_links: Annotated[list[dict[str, Any]], operator.add]  # URLs from web search

    # === Output Fields ===
    aggregated_links_file_path: str | None  # Path to merged & deduplicated links JSON
    enriched_newsletter_json_path: str | None  # Path to enriched newsletter JSON
    enriched_newsletter_md_path: str | None  # Path to enriched newsletter MD
    num_links_extracted: int | None  # Count of URLs extracted from messages
    num_links_searched: int | None  # Count of URLs from web search
    num_links_inserted: int | None  # Count of links inserted into content


# ============================================================================
# STATE MAPPING HELPERS
# ============================================================================
# These helper functions reduce boilerplate when creating subgraph state
# from parent graph state. They ensure all required fields are properly mapped.


def create_ranker_state_from_single_chat(parent_state: dict[str, Any]) -> DiscussionRankerState:
    """
    Create DiscussionRankerState from SingleChatState.

    This helper reduces boilerplate in the rank_discussions node by mapping
    all required fields from the parent state to the subgraph state.

    Args:
        parent_state: SingleChatState dictionary from newsletter generation graph

    Returns:
        DiscussionRankerState ready for discussions_ranker subgraph invocation

    Example:
        # In rank_discussions node (async - LangGraph 1.0+):
        ranker_state = create_ranker_state_from_single_chat(state)
        result = await discussions_ranker_graph.ainvoke(ranker_state)
    """
    settings = get_settings()
    return {
        # Input fields
        RankerKeys.SEPARATE_DISCUSSIONS_FILE_PATH: parent_state[SingleChatKeys.SEPARATE_DISCUSSIONS_FILE_PATH],
        RankerKeys.DISCUSSIONS_RANKING_DIR: parent_state[SingleChatKeys.DISCUSSIONS_RANKING_DIR],
        RankerKeys.EXPECTED_DISCUSSIONS_RANKING_FILE: parent_state[SingleChatKeys.EXPECTED_DISCUSSIONS_RANKING_FILE],
        RankerKeys.SUMMARY_FORMAT: parent_state[SingleChatKeys.SUMMARY_FORMAT],
        # Top-K configuration
        RankerKeys.TOP_K_DISCUSSIONS: parent_state.get(SingleChatKeys.TOP_K_DISCUSSIONS),
        # Anti-repetition configuration
        RankerKeys.PREVIOUS_NEWSLETTERS_TO_CONSIDER: parent_state.get(SingleChatKeys.PREVIOUS_NEWSLETTERS_TO_CONSIDER, settings.ranking.default_previous_newsletters_to_consider),
        RankerKeys.DATA_SOURCE_NAME: parent_state.get(SingleChatKeys.DATA_SOURCE_NAME),
        RankerKeys.CURRENT_START_DATE: parent_state.get(SingleChatKeys.START_DATE),
        # Force refresh flag
        RankerKeys.FORCE_REFRESH_DISCUSSIONS_RANKING: parent_state.get(SingleChatKeys.FORCE_REFRESH_DISCUSSIONS_RANKING, False),
        # Langfuse trace context (if available from parent state)
        RankerKeys.LANGFUSE_TRACE_ID: parent_state.get(SingleChatKeys.LANGFUSE_TRACE_ID),
        RankerKeys.LANGFUSE_SESSION_ID: parent_state.get(SingleChatKeys.LANGFUSE_SESSION_ID),
        RankerKeys.LANGFUSE_USER_ID: parent_state.get(SingleChatKeys.LANGFUSE_USER_ID),
        # MongoDB run tracking (for diagnostics)
        RankerKeys.MONGODB_RUN_ID: parent_state.get(SingleChatKeys.MONGODB_RUN_ID),
        # Output field (initialized as None)
        RankerKeys.DISCUSSIONS_RANKING_FILE_PATH: None,
    }


def create_enricher_state_from_single_chat(parent_state: dict[str, Any]) -> LinkEnricherState:
    """
    Create LinkEnricherState from SingleChatState.

    This helper reduces boilerplate in the enrich_with_links node by mapping
    all required fields from the parent state to the subgraph state.

    Args:
        parent_state: SingleChatState dictionary from newsletter generation graph

    Returns:
        LinkEnricherState ready for link_enricher subgraph invocation

    Example:
        # In enrich_with_links node (async - LangGraph 1.0+):
        enricher_state = create_enricher_state_from_single_chat(state)
        result = await link_enricher_graph.ainvoke(enricher_state)
    """
    return {
        # Input fields
        EnricherKeys.SEPARATE_DISCUSSIONS_FILE_PATH: parent_state[SingleChatKeys.SEPARATE_DISCUSSIONS_FILE_PATH],
        EnricherKeys.NEWSLETTER_JSON_PATH: parent_state[SingleChatKeys.NEWSLETTER_JSON_PATH],
        EnricherKeys.NEWSLETTER_MD_PATH: parent_state[SingleChatKeys.NEWSLETTER_MD_PATH],
        EnricherKeys.LINK_ENRICHMENT_DIR: parent_state[SingleChatKeys.LINK_ENRICHMENT_DIR],
        EnricherKeys.EXPECTED_ENRICHED_NEWSLETTER_JSON: parent_state[SingleChatKeys.EXPECTED_ENRICHED_NEWSLETTER_JSON],
        EnricherKeys.EXPECTED_ENRICHED_NEWSLETTER_MD: parent_state[SingleChatKeys.EXPECTED_ENRICHED_NEWSLETTER_MD],
        EnricherKeys.SUMMARY_FORMAT: parent_state[SingleChatKeys.SUMMARY_FORMAT],
        # Force refresh flag
        EnricherKeys.FORCE_REFRESH_LINK_ENRICHMENT: parent_state.get(SingleChatKeys.FORCE_REFRESH_LINK_ENRICHMENT, False),
        # MongoDB run tracking (for diagnostics)
        EnricherKeys.MONGODB_RUN_ID: parent_state.get(SingleChatKeys.MONGODB_RUN_ID),
        # Accumulator fields (initialized as empty lists)
        EnricherKeys.EXTRACTED_LINKS: [],
        EnricherKeys.SEARCHED_LINKS: [],
        # Output fields (initialized as None)
        EnricherKeys.AGGREGATED_LINKS_FILE_PATH: None,
        EnricherKeys.ENRICHED_NEWSLETTER_JSON_PATH: None,
        EnricherKeys.ENRICHED_NEWSLETTER_MD_PATH: None,
        EnricherKeys.NUM_LINKS_EXTRACTED: None,
        EnricherKeys.NUM_LINKS_SEARCHED: None,
        EnricherKeys.NUM_LINKS_INSERTED: None,
    }
