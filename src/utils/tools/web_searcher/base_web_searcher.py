from abc import ABC, abstractmethod


class BaseWebSearcher(ABC):
    @abstractmethod
    async def search(self, query, start=1, num_results=3):
        """
        Perform a web search using a query and return search results.

        Args:
            query (str): The search query.
            start (int): The starting index for search results (pagination).
            num_results (int): The number of search results to return.

        Returns:
            list: A list of search results (dictionaries) from the web search engine.
        """
        pass
