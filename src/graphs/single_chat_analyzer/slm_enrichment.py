"""
SLM Message Enrichment Node

Enriches discussion messages with multi-label semantic signals using the
chat-message-tagger-deberta-v3 model from HuggingFace. Each message gets
15 independent label scores (sigmoid) describing content type and quality.

These enrichment labels feed into the discussion ranking prompt, giving the
LLM pre-computed semantic signals for weighting discussion quality.

Design:
- Fail-soft: If model unavailable, skip enrichment and continue pipeline
- Optional: Controlled by SLM_ENRICHMENT_ENABLED environment variable
- Local inference: Model loaded from HuggingFace Hub, no API calls

Configuration:
- SLM_ENRICHMENT_ENABLED: Set to "true" to enable (default: false)
- SLM_ENRICHMENT_MODEL: HuggingFace model name (default: eladlaor/chat-message-tagger-deberta-v3)
"""

import asyncio
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig

from api.sse import STAGE_RANK, with_logging, with_progress
from config import get_settings
from constants import NodeNames, WORKFLOW_NAME_NEWSLETTER_GENERATION
from custom_types.field_keys import DiscussionKeys
from graphs.single_chat_analyzer.state import SingleChatState
from graphs.state_keys import SingleChatStateKeys as Keys
from observability import extract_trace_context, langfuse_span
from observability.metrics import with_metrics

# torch, numpy, transformers are lazy-imported only when enrichment is enabled
# to avoid requiring PyTorch in the langrag base environment

logger = logging.getLogger(__name__)

# Lazy-loaded model singleton (loaded once per process, reused across chats)
_enrichment_model = None
_enrichment_tokenizer = None
_enrichment_thresholds = None

# Label names in model output order
ENRICHMENT_LABEL_NAMES = [
    "professional", "question", "experience_sharing", "resource", "opinion",
    "how_to", "humor", "announcement", "off_group_topic", "reaction",
    "substantive", "discussion_init", "emotional", "disagreement",
    "positive_reinforcement",
]

# Rule-based flag patterns
_URL_PATTERN = re.compile(r"https?://|www\.|\.com/|\.io/|\.org/|github\.com")
_EMOJI_PATTERN = re.compile(
    "[\U0001f600-\U0001f64f\U0001f300-\U0001f5ff\U0001f680-\U0001f6ff"
    "\U0001f1e0-\U0001f1ff\U00002702-\U000027b0\U0000fe0f]"
)


def _load_enrichment_model(model_name: str) -> tuple:
    """Load model, tokenizer, and thresholds from HuggingFace Hub (cached).

    Lazy-imports torch and transformers to avoid requiring PyTorch in the
    langrag base environment when enrichment is disabled.
    """
    global _enrichment_model, _enrichment_tokenizer, _enrichment_thresholds

    if _enrichment_model is not None:
        return _enrichment_model, _enrichment_tokenizer, _enrichment_thresholds

    try:
        import torch  # noqa: F811 — lazy import
        from huggingface_hub import hf_hub_download
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        logger.info("Loading enrichment model from HuggingFace: %s", model_name)

        _enrichment_tokenizer = AutoTokenizer.from_pretrained(model_name)
        _enrichment_model = AutoModelForSequenceClassification.from_pretrained(model_name)
        _enrichment_model.eval()

        # Load per-label thresholds
        thresholds_path = hf_hub_download(model_name, "thresholds.json")
        with open(thresholds_path) as f:
            _enrichment_thresholds = json.load(f)

        total_params = sum(p.numel() for p in _enrichment_model.parameters())
        logger.info(
            "Enrichment model loaded: %s (%d params, %d labels)",
            model_name, total_params, _enrichment_model.config.num_labels,
        )

        return _enrichment_model, _enrichment_tokenizer, _enrichment_thresholds

    except ImportError as e:
        logger.error(
            "Missing dependency for enrichment model. "
            "Install with: pip install torch transformers huggingface-hub. Error: %s", e,
        )
        raise
    except Exception as e:
        logger.error("Failed to load enrichment model %s: %s", model_name, e)
        raise


def _compute_flags(content: str) -> dict[str, bool]:
    """Compute rule-based flags from message content."""
    return {
        "contains_external_link": bool(_URL_PATTERN.search(content)),
        "contains_emoji": bool(_EMOJI_PATTERN.search(content)),
    }


def _enrich_messages_batch(
    messages: list[dict],
    model,
    tokenizer,
    thresholds: dict[str, float],
    batch_size: int = 32,
    max_length: int = 256,
) -> list[dict]:
    """Enrich a list of messages with multi-label scores.

    Modifies messages in-place by adding slm_labels, slm_active_labels, slm_flags.

    Args:
        messages: List of message dicts with 'content' or 'translated_content'.
        model: Loaded HuggingFace model.
        tokenizer: Loaded tokenizer.
        thresholds: Per-label thresholds dict.
        batch_size: Inference batch size.
        max_length: Max token sequence length.

    Returns:
        The same messages list with enrichment fields added.
    """
    import numpy as np
    import torch

    device = next(model.parameters()).device

    # Collect texts
    texts = []
    for msg in messages:
        text = msg.get("translated_content") or msg.get("content", "")
        texts.append(text if text else "")

    # Process in batches
    all_scores = []
    for i in range(0, len(texts), batch_size):
        batch_texts = texts[i:i + batch_size]

        inputs = tokenizer(
            batch_texts,
            return_tensors="pt",
            truncation=True,
            padding=True,
            max_length=max_length,
        ).to(device)

        with torch.no_grad():
            logits = model(**inputs).logits
            scores = torch.sigmoid(logits).cpu().numpy()

        all_scores.append(scores)

    all_scores = np.concatenate(all_scores, axis=0)

    # Apply scores to messages
    for idx, msg in enumerate(messages):
        scores = all_scores[idx]

        label_scores = {
            name: round(float(scores[i]), 4)
            for i, name in enumerate(ENRICHMENT_LABEL_NAMES)
        }

        active_labels = [
            name for name in ENRICHMENT_LABEL_NAMES
            if label_scores[name] > thresholds.get(name, 0.5)
        ]

        content = msg.get("content", "")
        flags = _compute_flags(content)

        msg["slm_labels"] = label_scores
        msg["slm_active_labels"] = active_labels
        msg["slm_flags"] = flags

    return messages


def _atomic_json_write(file_path: str, data: Any) -> None:
    """Write JSON data atomically using temp file and rename."""
    path = Path(file_path)
    temp_fd, temp_path = tempfile.mkstemp(
        suffix=path.suffix, prefix=f"{path.stem}_tmp_", dir=path.parent,
    )
    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, file_path)
    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


@with_logging
@with_progress(STAGE_RANK, start_message="Enriching messages with SLM labels...")
@with_metrics(node_name=NodeNames.SingleChatAnalyzer.SLM_ENRICHMENT, workflow_name=WORKFLOW_NAME_NEWSLETTER_GENERATION)
async def slm_enrichment_node(state: SingleChatState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """
    Enrich discussion messages with multi-label semantic signals.

    This node runs between separate_discussions and rank_discussions.
    It loads the discussions file, enriches each message with 15 label scores
    from the chat-message-tagger model, and writes the enriched data back.

    Behavior:
    - If SLM_ENRICHMENT_ENABLED=false: Skip enrichment, pass through
    - If model unavailable: Skip enrichment (fail-soft), log warning
    - If enabled: Load model, enrich all messages, write back

    Args:
        state: Current workflow state with separate_discussions_file_path
        config: LangGraph runnable config

    Returns:
        Empty dict (enrichment modifies discussions file in-place)
    """
    settings = get_settings()

    if not settings.slm_enrichment.enabled:
        logger.info("SLM enrichment disabled (SLM_ENRICHMENT_ENABLED=false), skipping")
        return {}

    discussions_file = state.get(Keys.SEPARATE_DISCUSSIONS_FILE_PATH)
    if not discussions_file or not os.path.exists(discussions_file):
        logger.warning("Discussions file not found: %s, skipping enrichment", discussions_file)
        return {}

    chat_name = state.get(Keys.CHAT_NAME, "unknown")
    model_name = settings.slm_enrichment.model_name

    ctx = extract_trace_context(config)
    with langfuse_span(
        name=NodeNames.SingleChatAnalyzer.SLM_ENRICHMENT,
        trace_id=ctx.trace_id,
        parent_span_id=ctx.parent_span_id,
        input_data={"chat_name": chat_name, "model": model_name},
    ) as span:
        try:
            # Load model (cached after first call) — offloaded to thread
            # because HuggingFace/PyTorch model loading is CPU-bound and blocking
            model, tokenizer, thresholds = await asyncio.to_thread(
                _load_enrichment_model, model_name,
            )

            # Load discussions
            with open(discussions_file, encoding="utf-8") as f:
                data = json.load(f)

            discussions = data.get(DiscussionKeys.DISCUSSIONS, []) if isinstance(data, dict) else data
            if not isinstance(discussions, list):
                logger.warning("Discussions data not a list, skipping enrichment")
                return {}

            # Enrich all messages across all discussions — offloaded to thread
            # because PyTorch tensor inference is CPU-bound and blocking
            total_messages = 0
            total_enriched = 0

            for discussion in discussions:
                messages = discussion.get(DiscussionKeys.MESSAGES, [])
                if messages:
                    await asyncio.to_thread(
                        _enrich_messages_batch,
                        messages, model, tokenizer, thresholds,
                        settings.slm_enrichment.batch_size,
                    )
                    total_messages += len(messages)
                    total_enriched += sum(1 for m in messages if m.get("slm_active_labels"))

            # Write enriched discussions back atomically
            await asyncio.to_thread(_atomic_json_write, discussions_file, data)

            logger.info(
                "SLM enrichment for chat_name=%s: %d messages enriched (%d with active labels)",
                chat_name, total_messages, total_enriched,
            )

            if span:
                span.update(output={
                    "total_messages": total_messages,
                    "enriched_with_active_labels": total_enriched,
                    "model": model_name,
                })

            return {}

        except Exception as e:
            logger.error(
                "SLM enrichment failed for chat_name=%s: %s", chat_name, e,
                exc_info=True,
            )

            # Fail-soft: don't block pipeline
            if span:
                span.update(output={"error": str(e), "fallback_used": True})

            return {}
