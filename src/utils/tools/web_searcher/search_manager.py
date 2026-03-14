import logging
import requests
from utils.tools.web_searcher.base_web_searcher import BaseWebSearcher
from utils.tools.web_searcher.google_searcher import GoogleSearcher
from utils.tools.web_searcher.jina_search_by_query import JinaSearcherWithReRanking

logger = logging.getLogger(__name__)


class SearchManager(BaseWebSearcher):
    def __init__(self):
        self.jina = JinaSearcherWithReRanking()
        self.google = GoogleSearcher()

    def search(self, query, num_results):
        try:
            # jina_results = self.jina.search(query, num_results)
            google_results = self.google.search(query, num_results)
            read_google_results = []

            for google_result in google_results[:num_results]:
                # title, url, content
                link = google_result.get("link") or google_result.get("url")
                jina_read_url = f"{self.jina.jina_reader_uri_prefix}/{link}"
                response = requests.get(jina_read_url, headers=self.jina.jina_reader_headers)

                if response.status_code != 200:
                    continue

                jina_read_result = response.json()
                data = jina_read_result.get("data")
                read_google_results.append(
                    {
                        "title": data.get("title"),
                        "url": data.get("url"),
                        "content": data.get("content"),
                    }
                )

            reranked_results = self.jina.rerank(
                # query, num_results, read_google_results + jina_results
                query,
                num_results,
                read_google_results,
            )

            logger.debug(f"Reranked results: {reranked_results}")
            return reranked_results
        except Exception as e:
            raise ValueError(f"Error in search: {str(e)}")
