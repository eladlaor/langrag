"""podcast_slug retrieval-filter tests.

Verifies the vector-search pre_filter carries the podcast_slug when passed, and
omits it when not — so search_podcasts(podcast=<slug>) actually scopes retrieval
to a single tenant. Runs WITHOUT Docker (collection.aggregate is stubbed and the
pipeline captured).
"""

from custom_types.field_keys import RAGChunkKeys as Keys
from rag.retrieval import vector_search


class _FakeCursor:
    async def to_list(self, *args, **kwargs):
        return []


class _FakeCollection:
    def __init__(self):
        self.pipeline = None

    async def aggregate(self, pipeline):
        self.pipeline = pipeline
        return _FakeCursor()


def _pre_filter(pipeline):
    return pipeline[0]["$vectorSearch"].get("filter", {})


async def test_podcast_slug_in_pre_filter():
    coll = _FakeCollection()
    await vector_search.vector_search_chunks(
        collection=coll,
        query_embedding=[0.0] * 8,
        content_sources=["podcast"],
        podcast_slug="langtalks",
        top_k=5,
    )
    assert _pre_filter(coll.pipeline)[Keys.PODCAST_SLUG] == "langtalks"


async def test_no_podcast_slug_absent_from_pre_filter():
    coll = _FakeCollection()
    await vector_search.vector_search_chunks(
        collection=coll,
        query_embedding=[0.0] * 8,
        content_sources=["podcast"],
        top_k=5,
    )
    assert Keys.PODCAST_SLUG not in _pre_filter(coll.pipeline)
