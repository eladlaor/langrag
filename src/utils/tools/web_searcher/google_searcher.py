import logging
import os
from ssl import SSLError

import httpx
from dotenv import load_dotenv

from utils.tools.web_searcher.base_web_searcher import BaseWebSearcher

logger = logging.getLogger(__name__)
load_dotenv()


class GoogleSearcher(BaseWebSearcher):
    def __init__(self):
        self.api_key = os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("Google API key is required")

        self.cse_id = os.getenv("GOOGLE_CSE_ID")
        if not self.cse_id:
            raise ValueError("Google CSE ID is required")

        self.url = "https://www.googleapis.com/customsearch/v1"

    async def search(self, query, start=1, num_results=10):
        """
        Perform a Google Custom Search Engine (CSE) search using a query and return search results.

        Args:
            query (str): The search query.
            start (int): The starting index for search results (pagination).
            num_results (int): The number of search results to return.

        Returns:
            list: A list of search results (dictionaries) from the Google CSE.
        """

        params = {
            "q": query,
            "key": self.api_key,
            "cx": self.cse_id,
            "start": start,
            "num": num_results,
        }

        try:
            logger.info(f"Sending request to Google API for query: {query}")
            async with httpx.AsyncClient() as client:
                response = await client.get(self.url, params=params)
            response.raise_for_status()
            return response.json().get("items", [])

        except SSLError as ssl_err:
            logger.error(f"SSL error occurred for query '{query}': {ssl_err}")
            raise ssl_err

        except httpx.HTTPError as req_err:
            logger.error(f"Request error occurred for query '{query}': {req_err}")
            raise req_err
