"""
Runtime LLM evaluation package.

Replaces DeepEval at runtime. The judge here is a thin langchain-openai
wrapper around three prompt templates (faithfulness, answer relevancy,
hallucination). The scorer orchestrates the judges and dual-writes scores
to MongoDB (rag_evaluations) and to Langfuse (trace scores).

DeepEval is intentionally NOT imported in this package; the CI eval gate
keeps DeepEval for its LLM-judge metrics.
"""
