"""
SE (Semantic Entropy) shadow scorer.

Runs ALONGSIDE the LLM judge as a pure observability sink. For each scored
response, this module generates N independent answer samples at temperature > 0
and asks the `taste` library to compute a semantic-entropy score over them. The
score is written to Langfuse (and optionally Mongo as a separate field), and the
escalation flag is recorded — but the conversation answer is NEVER replaced
(judge=None). This is shadow mode: observe-only.

Design:
- Default OFF (`RUNTIME_EVAL_SE_SHADOW_ENABLED=false`) -> instant `None`, zero
  work, zero heavy imports (taste/torch are lazy-imported inside the try block,
  only when enabled and sampled-in). This preserves ZERO behavior change and
  ZERO taste/torch coupling when the flag is off.
- SE-ONLY: samples carry no token logprobs, so predictive entropy (PE) is
  impossible by construction; semantic entropy is the only valid detector.
- Fail-soft: any exception is logged and swallowed; never re-raised. A shadow
  failure can never break a request, mirroring `_run_background_scoring`.
"""

from __future__ import annotations

import logging
import random
from typing import Any

from config import get_settings
from constants import SeShadowKey
from observability.llm.langfuse_client import get_langfuse_client

# taste, torch and transformers are lazy-imported only when the shadow flag is
# on (mirrors graphs/single_chat_analyzer/slm_enrichment.py) so the langrag base
# environment never needs them when SE shadow scoring is disabled.

logger = logging.getLogger(__name__)


async def shadow_score_se(
    *,
    evaluation_id: str,
    session_id: str,
    query: str,
    contexts: list[str],
    conversation_history: list[dict[str, Any]] | None,
    langfuse_trace_id: str | None,
) -> dict[str, Any] | None:
    """
    SE shadow-score a single RAG response.

    Generates its OWN N samples (the production `answer` is a single low-temp
    decode and is not reusable for diversity), computes semantic entropy via
    taste, and writes the result to the Langfuse trace as a sink. Returns the
    sink dict for observability/tests, or None when disabled / sampled-out /
    on any failure (fail-soft).
    """
    settings = get_settings().runtime_eval

    # Disabled fast-path: zero work, zero heavy imports.
    if not settings.se_shadow_enabled:
        return None

    # Independent sub-sampling on top of the judge sampling.
    if random.random() > settings.se_shadow_sampling_rate:
        return None

    try:
        # Lazy imports: only reached when enabled AND sampled-in.
        from taste import (
            DetectorName,
            Sample,
            SampleSet,
            SemanticEntropyDetector,
            SingleDetector,
            evaluate_responses,
        )

        from rag.generation.rag_chain import _build_messages
        from utils.llm.chat_model_factory import create_chat_model

        settings_rag = get_settings().rag

        # Build the same prompt the production answer path uses, minus the
        # date/freshness args (shadow scoring is diversity-only).
        messages = _build_messages(
            query,
            "\n\n".join(contexts),
            conversation_history or [],
            date_start=None,
            date_end=None,
            freshness_warning=False,
            newest_source_date=None,
        )

        # Build the answer model at temperature > 0 for sample diversity.
        # Texts only: no logprobs, no n>1 (the rag chain has no such support),
        # which guarantees PE is impossible and SE is the only valid detector.
        llm = create_chat_model(
            model=settings_rag.rag_llm_model,
            temperature=settings.se_shadow_temperature,
            provider=settings_rag.rag_llm_provider,
        )

        texts: list[str] = []
        for _ in range(settings.se_shadow_sample_n):
            response = await llm.ainvoke(messages)
            texts.append(response.content)

        sample_set = SampleSet(prompt=query, samples=[Sample(text=t) for t in texts])

        result = evaluate_responses(
            prompt=query,
            samples=sample_set,
            detectors=[SemanticEntropyDetector()],
            escalation_detector=DetectorName.SEMANTIC_ENTROPY,
            escalation_threshold=settings.se_shadow_threshold,
            judge=None,  # SHADOW: never escalate/replace the answer.
            greedy_answer=texts[0],  # required by the response-shaped API; never surfaced.
            escalation_policy=SingleDetector(DetectorName.SEMANTIC_ENTROPY, settings.se_shadow_threshold),
        )

        se_score = result.detector_scores[DetectorName.SEMANTIC_ENTROPY]
        n_clusters = len(result.clusters) if result.clusters else 0
        escalated = result.escalated

        sink = {
            str(SeShadowKey.SE_SCORE): se_score,
            str(SeShadowKey.N_CLUSTERS): n_clusters,
            str(SeShadowKey.N_SAMPLES): len(texts),
            str(SeShadowKey.ESCALATION_FLAG): escalated,
        }

        # Langfuse sink (fail-soft, only if trace id + client available).
        if langfuse_trace_id:
            langfuse = get_langfuse_client()
            if langfuse:
                langfuse_scores = {
                    str(SeShadowKey.SE_SCORE): float(se_score),
                    str(SeShadowKey.N_CLUSTERS): float(n_clusters),
                    str(SeShadowKey.N_SAMPLES): float(len(texts)),
                    str(SeShadowKey.ESCALATION_FLAG): float(escalated),
                }
                for name, value in langfuse_scores.items():
                    try:
                        langfuse.score(trace_id=langfuse_trace_id, name=name, value=value)
                    except Exception as exc:
                        logger.warning(
                            f"Failed to post SE shadow score to Langfuse "
                            f"(evaluation_id={evaluation_id}, session_id={session_id}, name={name}): {exc}"
                        )

        logger.info(
            f"SE shadow scoring complete: evaluation_id={evaluation_id}, session_id={session_id}, "
            f"se_score={se_score}, n_clusters={n_clusters}, n_samples={len(texts)}, escalated={escalated}"
        )
        return sink

    except Exception as exc:
        logger.warning(
            f"SE shadow scoring failed (non-blocking): evaluation_id={evaluation_id}, "
            f"session_id={session_id}, error={exc}"
        )
        return None
