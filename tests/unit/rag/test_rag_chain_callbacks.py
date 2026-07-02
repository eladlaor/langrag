"""Unit tests: generate_answer / generate_answer_stream thread `callbacks` into
the LLM call as config={"callbacks": [...]} (Langfuse handler injection), and
stay backward compatible (config={}) when callbacks are omitted."""

from unittest.mock import AsyncMock, MagicMock, patch

from rag.generation import rag_chain

_SENTINEL = object()


def _fake_llm_ainvoke():
    llm = MagicMock()
    resp = MagicMock()
    resp.content = "answer text"
    llm.ainvoke = AsyncMock(return_value=resp)
    return llm


def _fake_llm_astream(tokens):
    llm = MagicMock()

    async def _astream(messages, config=None):
        _astream.config = config
        for t in tokens:
            chunk = MagicMock()
            chunk.content = t
            yield chunk

    llm.astream = _astream
    return llm


class TestGenerateAnswerCallbacks:
    async def test_generate_answer_passes_callbacks_as_config(self):
        llm = _fake_llm_ainvoke()
        with patch.object(rag_chain, "create_chat_model", return_value=llm):
            await rag_chain.generate_answer(query="q", context="ctx", conversation_history=[], callbacks=[_SENTINEL])

        _, kwargs = llm.ainvoke.call_args
        assert kwargs["config"] == {"callbacks": [_SENTINEL]}

    async def test_generate_answer_no_callbacks_passes_empty_config(self):
        llm = _fake_llm_ainvoke()
        with patch.object(rag_chain, "create_chat_model", return_value=llm):
            answer = await rag_chain.generate_answer(query="q", context="ctx", conversation_history=[])

        _, kwargs = llm.ainvoke.call_args
        assert kwargs["config"] == {}
        assert answer == "answer text"

    async def test_generate_answer_stream_passes_callbacks_as_config(self):
        llm = _fake_llm_astream(["a", "b", "c"])
        with patch.object(rag_chain, "create_chat_model", return_value=llm):
            out = [t async for t in rag_chain.generate_answer_stream(query="q", context="ctx", conversation_history=[], callbacks=[_SENTINEL])]

        assert out == ["a", "b", "c"]
        assert llm.astream.config == {"callbacks": [_SENTINEL]}
