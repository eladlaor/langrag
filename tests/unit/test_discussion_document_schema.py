"""Unit tests that DiscussionDocument is the source of truth for stored docs.

Guards the fix that added embedding fields to the model and made the repository
build documents through the model (instead of a free dict that the model didn't
describe). No MongoDB needed: we exercise the model + model_dump shape directly.
"""

from __future__ import annotations

from custom_types.db_schemas import DiscussionDocument
from custom_types.field_keys import DbFieldKeys


def _base_kwargs() -> dict:
    return dict(
        discussion_id="d1",
        run_id="r1",
        chat_name="LangTalks Community",
        title="t",
        nutshell="n",
        message_ids=["m1", "m2"],
        message_count=2,
        ranking_score=1.0,
        first_message_timestamp=123,
        metadata={},
    )


def test_model_dump_keys_match_field_keys():
    """Every persisted key the repo relies on exists in model_dump output."""
    doc = DiscussionDocument(**_base_kwargs()).model_dump(exclude_none=True)
    for key in (
        DbFieldKeys.DISCUSSION_ID,
        DbFieldKeys.RUN_ID,
        DbFieldKeys.CHAT_NAME,
        DbFieldKeys.TITLE,
        DbFieldKeys.NUTSHELL,
        DbFieldKeys.MESSAGE_IDS,
        DbFieldKeys.MESSAGE_COUNT,
        DbFieldKeys.RANKING_SCORE,
        DbFieldKeys.CREATED_AT,
    ):
        assert key in doc


def test_embedding_fields_excluded_when_absent():
    """Without an embedding, the sparse embedding fields are not persisted."""
    doc = DiscussionDocument(**_base_kwargs()).model_dump(exclude_none=True)
    assert DbFieldKeys.EMBEDDING not in doc
    assert DbFieldKeys.EMBEDDING_MODEL not in doc
    assert DbFieldKeys.EMBEDDING_TIMESTAMP not in doc


def test_embedding_fields_present_when_set():
    """An embedding-bearing discussion serializes its embedding fields."""
    doc = DiscussionDocument(
        **_base_kwargs(),
        embedding=[0.1, 0.2, 0.3],
        embedding_model="text-embedding-3-small",
    ).model_dump(exclude_none=True)
    assert doc[DbFieldKeys.EMBEDDING] == [0.1, 0.2, 0.3]
    assert doc[DbFieldKeys.EMBEDDING_MODEL] == "text-embedding-3-small"


def test_stored_document_validates_back():
    """A dumped document validates back into the model (round-trip contract)."""
    original = DiscussionDocument(**_base_kwargs(), embedding=[0.4, 0.5])
    dumped = original.model_dump(exclude_none=True)
    revalidated = DiscussionDocument.model_validate(dumped)
    assert revalidated.discussion_id == original.discussion_id
    assert revalidated.embedding == [0.4, 0.5]
