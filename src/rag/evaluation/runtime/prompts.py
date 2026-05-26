"""
Prompt templates for the runtime LLM judge.

Each template forces strict JSON output of the shape:
    {"score": <float in [0, 1]>, "reasoning": "<short justification>"}

`{query}`, `{answer}`, `{context}` are placeholders the judge fills at call
time. Templates intentionally lean on a single rubric per metric to keep
judge outputs stable across runs.
"""

from constants import EvaluationMetric


FAITHFULNESS_PROMPT = """You are an evaluator scoring how FAITHFUL an assistant's answer is to its retrieved context.
A faithful answer states only facts that are directly supported by the context. Unsupported claims, embellishments,
or contradictions reduce the score.

User query:
{query}

Retrieved context:
{context}

Assistant answer:
{answer}

Return STRICT JSON of the form:
{{"score": <float between 0 and 1>, "reasoning": "<one or two short sentences>"}}
- 1.0 means every factual claim in the answer is grounded in the context.
- 0.0 means the answer contradicts or fabricates beyond the context.
Do not include any text outside the JSON object."""


ANSWER_RELEVANCY_PROMPT = """You are an evaluator scoring how RELEVANT an assistant's answer is to the user's query.
A relevant answer directly addresses what was asked. Tangents, padding, or partial answers reduce the score.

User query:
{query}

Retrieved context (for awareness only, do not score grounding here):
{context}

Assistant answer:
{answer}

Return STRICT JSON of the form:
{{"score": <float between 0 and 1>, "reasoning": "<one or two short sentences>"}}
- 1.0 means the answer fully and directly addresses the user's query.
- 0.0 means the answer is unrelated or evasive.
Do not include any text outside the JSON object."""


HALLUCINATION_PROMPT = """You are an evaluator scoring how much HALLUCINATION an assistant's answer contains relative
to its retrieved context. Hallucination is content that is NOT supported by the context. Lower scores are BETTER.

User query:
{query}

Retrieved context:
{context}

Assistant answer:
{answer}

Return STRICT JSON of the form:
{{"score": <float between 0 and 1>, "reasoning": "<one or two short sentences>"}}
- 0.0 means no hallucinated content - every claim is grounded in the context.
- 1.0 means the answer is largely fabricated or contradicts the context.
Do not include any text outside the JSON object."""


PROMPT_BY_METRIC: dict[EvaluationMetric, str] = {
    EvaluationMetric.FAITHFULNESS: FAITHFULNESS_PROMPT,
    EvaluationMetric.ANSWER_RELEVANCY: ANSWER_RELEVANCY_PROMPT,
    EvaluationMetric.HALLUCINATION: HALLUCINATION_PROMPT,
}
