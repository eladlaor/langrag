import json
import logging
import os
import urllib
from typing import Any

import httpx

from utils.tools.web_searcher.base_web_searcher import BaseWebSearcher
from constants import (
    HEADER_AUTHORIZATION,
    HEADER_ACCEPT,
    HEADER_CONTENT_TYPE,
    CONTENT_TYPE_JSON,
    AUTH_BEARER_PREFIX,
    JINA_READER_URI_PREFIX,
    JINA_SEARCH_URI_PREFIX,
    JINA_RERANKER_URI,
    JINA_RERANKER_MODEL,
)

logger = logging.getLogger(__name__)


class JinaSearcherWithReRanking(BaseWebSearcher):
    """
    Jina AI-powered search with re-ranking capabilities.

    Uses Jina's search and reranker APIs to find and rank relevant results.
    Requires JINA_API_KEY environment variable to be set.
    """

    def __init__(self, api_key: str | None = None):
        """
        Initialize Jina searcher.

        Args:
            api_key: Jina API key. If not provided, reads from JINA_API_KEY env variable.

        Raises:
            ValueError: If no API key is provided or found in environment.
        """
        self.api_key = api_key or os.getenv("JINA_API_KEY")
        if not self.api_key:
            raise ValueError("Jina API key not provided. Please set JINA_API_KEY environment variable " "or pass api_key parameter to JinaSearcherWithReRanking constructor.")

        self.jina_reader_uri_prefix = JINA_READER_URI_PREFIX
        self.jina_reader_query_search_uri_prefix = JINA_SEARCH_URI_PREFIX
        self.jina_reader_headers = {
            HEADER_AUTHORIZATION: f"{AUTH_BEARER_PREFIX} {self.api_key}",
            HEADER_ACCEPT: CONTENT_TYPE_JSON,
        }

        self.jina_reranker_uri = JINA_RERANKER_URI
        self.jina_reranker_headers = {
            HEADER_CONTENT_TYPE: CONTENT_TYPE_JSON,
            HEADER_AUTHORIZATION: f"{AUTH_BEARER_PREFIX} {self.api_key}",
        }
        self.jina_reranker_model = JINA_RERANKER_MODEL

    async def search(self, query: str, start: int = 1, num_results: int = 2) -> list[dict[str, Any]]:
        """
        Search using Jina AI and return re-ranked results.

        Args:
            query: Search query string
            start: Starting position (currently unused, kept for interface compatibility)
            num_results: Number of results to return after re-ranking

        Returns:
            List of re-ranked search results

        Raises:
            ValueError: If search fails or returns invalid response
        """
        try:
            encoded_query = urllib.parse.quote(query)
            url = f"{self.jina_reader_query_search_uri_prefix}/{encoded_query}"

            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=self.jina_reader_headers)

            if response.status_code == 422:
                logger.warning(f"No relevant results found for query: '{query}'")
                return []

            if response.status_code != 200:
                raise ValueError(f"Jina search API returned status {response.status_code}: {response.text}")

            search_results_list = response.json()["data"]
            most_relevant_search_results = await self.rerank(query, num_results, search_results_list)

            return most_relevant_search_results
        except httpx.HTTPError as e:
            raise ValueError(f"Network error during Jina search: {str(e)}") from e
        except (KeyError, ValueError) as e:
            raise ValueError(f"Invalid response from Jina search API: {str(e)}") from e

    async def rerank(self, query: str, top_n: int, search_results_list: list[dict[str, Any]], threshold: float = 0.8) -> list[dict[str, Any]]:
        """
        Re-rank search results using Jina's reranker API.

        Args:
            query: Original search query
            top_n: Number of top results to return
            search_results_list: List of search results to re-rank
            threshold: Similarity threshold (currently unused, reserved for future filtering)

        Returns:
            List of re-ranked search results, ordered by relevance

        Raises:
            ValueError: If re-ranking fails or returns invalid response
        """
        try:
            data = {
                "model": self.jina_reranker_model,
                "query": query,
                "top_n": top_n,
                "documents": [json.dumps(doc) for doc in search_results_list],
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(self.jina_reranker_uri, headers=self.jina_reranker_headers, json=data)

            if response.status_code != 200:
                raise ValueError(f"Jina reranker API returned status {response.status_code}: {response.text}")

            parsed_response = response.json()
            top_n_result_indices = [result["index"] for result in parsed_response["results"]]
            most_relevant_search_results = [search_results_list[i] for i in top_n_result_indices if i < len(search_results_list)]

            return most_relevant_search_results
        except httpx.HTTPError as e:
            raise ValueError(f"Network error during Jina reranking: {str(e)}") from e
        except (KeyError, ValueError) as e:
            raise ValueError(f"Invalid response from Jina reranker API: {str(e)}") from e
