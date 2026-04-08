"""
Rank Discussions Prompt

Prompt for ranking and categorizing discussions based on relevance, quality, and engagement.
Used to prioritize which discussions should be featured in the newsletter.

Includes anti-repetition analysis to detect and downrank topics covered in previous newsletters.
"""

# Repetition analysis section - injected when previous newsletters are available
REPETITION_ANALYSIS_SECTION = """
*** CRITICAL: ANTI-REPETITION CHECK — DO THIS FIRST BEFORE RANKING ***

You MUST check every discussion against the {num_previous_newsletters} previous newsletter editions below.
Readers who saw previous editions will notice repeated topics. Repetition damages newsletter quality.

Previous Newsletter Topics (from most recent to oldest):
{formatted_previous_topics}

REPETITION SCORING — APPLY BEFORE setting importance_score:
| Repetition Level | Match Type | Importance Penalty | Score Value |
|-----------------|------------|-------------------|-------------|
| HIGH | Same core topic as a PRIMARY discussion | -3 to -4 points | "high" |
| MEDIUM | Same topic as a SECONDARY discussion OR same general theme | -2 points | "medium" |
| LOW | Topic mentioned in WORTH_MENTIONING | -1 point | "low" |
| NONE | Fresh topic not covered before | No penalty | null |

CORRECT repetition detection examples:

Example 1 — HIGH repetition:
Previous PRIMARY: "שימוש ב-RAG לספרים טכניים" (summary: chunking strategies, embedding hierarchies for book content)
Current discussion: "RAG Pipeline לספריות דיגיטליות" (discusses chunking and retrieval for documents)
→ repetition_score: "high" — same core topic (RAG document processing), just different framing

Example 2 — MEDIUM repetition:
Previous SECONDARY: "Claude 3.5 Sonnet ביצועים ומחירים"
Current discussion: "השוואת מודלים — Claude vs GPT-4o"
→ repetition_score: "medium" — overlapping theme (Claude model evaluation), though broader scope

For each discussion, you MUST include:
- "repetition_score": "high" | "medium" | "low" | null
- "repetition_identification_reasoning": Explanation if repetition detected, null otherwise

When setting repetition_identification_reasoning, be specific:
- Name the previous newsletter date (e.g., "2025-10-01_to_2025-10-14")
- Quote the similar topic title and its summary
- Explain the semantic overlap
"""

# SLM enrichment context - injected when messages have been enriched with multi-label scores
SLM_ENRICHMENT_SECTION = """
**SLM ENRICHMENT LABELS (Pre-computed Semantic Signals)**

Each message in the discussions below has been pre-tagged with semantic labels by a specialized model.
Use these labels as pre-computed quality signals to speed up your analysis:

- Messages tagged as `professional`, `experience_sharing`, `how_to`, or `substantive` indicate **high-quality technical content** — these strongly support the Relevance & Importance (50%) and Quality & Depth (30%) factors.
- Messages tagged as `question` or `discussion_init` indicate **conversation starters** — discussions with many of these are driving engagement.
- Messages tagged as `resource` indicate **shared links, tools, papers** — concrete value for readers.
- Messages tagged only as `reaction` or `humor` are **lower signal** — they indicate engagement but not depth.
- Messages tagged as `off_group_topic` are **noise** — discussions dominated by these should be downranked.

Look at the `slm_active_labels` field on each message. A discussion where most messages are tagged `professional` + `substantive` is likely more valuable than one dominated by `reaction` labels.
"""

# Used when enrichment is not available
NO_SLM_ENRICHMENT_SECTION = ""

# Used when no previous newsletters are available
NO_PREVIOUS_NEWSLETTERS_SECTION = """
**REPETITION ANALYSIS**
No previous newsletters available for comparison. All discussions are considered fresh.
Set repetition_score: null and repetition_identification_reasoning: null for all discussions.
"""

RANK_DISCUSSIONS_PROMPT = """You are an expert newsletter editor analyzing WhatsApp group discussions.
Your task is to rank discussions and generate teachable one-liner summaries for each.

{repetition_analysis_section}

{slm_enrichment_section}

For each discussion, consider these factors with the following weights:
1. **Relevance & Importance** (50%): Is this technically significant or impactful?
2. **Quality & Depth** (30%): Does it contain valuable insights or concrete information?
3. **Engagement - Number of Messages** (10%): How active was the discussion?
4. **Number of Unique Participants** (10% - LOW weight): How many people contributed?

Note on Participant Count: While more participants CAN indicate broader interest, quality and substance
matter more than quantity. A discussion with many participants may be less substantive (people bickering or
brief reactions), while a focused discussion with fewer participants may be deeply technical and valuable.
Prioritize content quality over participation quantity.

Also consider:
- **Topical Value**: Does it add diversity to the newsletter topics?
- **Recency & Timeliness**: Is the information current and actionable?

Newsletter Format: {summary_format}
- "langtalks_format": Focus on AI agents, RAG pipelines, LangGraph/LangChain, prompt engineering, MCP integrations, and practical GenAI development patterns
- "mcp_israel_format": Focus on MCP servers and protocol, A2A protocol, tool integration patterns, Israeli GenAI ecosystem, and practical AI automation

**IMPORTANT - One-Liner Summaries:**
For EACH discussion, you MUST generate a `one_liner_summary` field. This is a teachable moment -
a single sentence (1-2 lines max) that captures the KEY practical insight from the discussion.

Good one-liner examples:
- "OpenRouter כאלטרנטיבה ל-LLM proxy עם load balancing ו-rate limits גבוהים יותר מ-OpenAI ישירות"
- "הסרת PII לפני אימון עלולה לפגוע בדיוק המודל - חשוב לבדוק את ה-tradeoff לפני כל dataset"
- "LangGraph 0.6 מאפשר interrupt points שמקלים על HITL workflows"

Bad one-liner examples (too vague):
- "דיון על LLMs" (too generic)
- "כמה חברים שוחחו על AI" (doesn't convey insight)

Provide your analysis as a JSON object with this structure:
{{
  "ranked_discussions": [
    {{
      "discussion_id": "discussion_1",
      "rank": 1,
      "importance_score": 0-10,
      "num_messages": 5,
      "num_unique_participants": 3,
      "first_message_timestamp": 1748856902000,
      "title": "Discussion title",
      "one_liner_summary": "The key teachable insight from this discussion in 1-2 sentences",
      "reasoning": "Why this discussion was ranked here",
      "recommended_section": "Top Story|Technical Deep Dive|Quick Updates|Community Highlights",
      "key_insights": ["insight 1", "insight 2"],
      "engagement_level": "high|medium|low",
      "skip_reason": null,
      "repetition_score": null,
      "repetition_identification_reasoning": null
    }}
  ],
  "editorial_notes": "Overall recommendations for newsletter structure",
  "topic_diversity": "Assessment of topic coverage balance"
}}

IMPORTANT RULES:
1. Always include ALL discussions in ranked_discussions (don't omit any)
2. Each discussion MUST have a `one_liner_summary` field with a practical, teachable insight
3. If a discussion should be skipped (off-topic, administrative, low quality), set skip_reason to explain why
4. Sort by rank (1 = most important)
5. Include "num_messages", "num_unique_participants", "first_message_timestamp", and "title" from input data
6. For repetition analysis: apply importance_score penalty BEFORE ranking, then set repetition_score and reasoning

Be thoughtful and selective - quality over quantity. Prioritize fresh topics over repeated ones."""


# =============================================================================
# VALIDATE REPETITION PROMPT (Hybrid Approach)
# =============================================================================
# LLM validation of embedding-based similarity matches for anti-repetition

VALIDATE_REPETITION_PROMPT = """You are analyzing whether a current discussion substantially repeats topics from previous newsletters.

You have been shown the current discussion and the TOP-3 most similar discussions from previous newsletters (based on embedding similarity).

{formatted_comparison}

**Your Task:**
Determine the repetition level based on semantic overlap:

**REPETITION LEVELS:**
- **"high"**: Current discussion covers the SAME core topic as a previous PRIMARY discussion
  - Same subject matter, just rephrased or from slightly different angle
  - Would feel redundant to readers who saw the previous newsletter

- **"medium"**: Current discussion overlaps with a previous SECONDARY discussion
  - Significant topic overlap, but adds new angles or details
  - Some value for readers, but less novel

- **"low"**: Topic was briefly mentioned in previous WORTH_MENTIONING
  - Peripheral overlap only
  - Still feels fresh enough to include

- **"none"**: No substantial repetition detected
  - Fresh topic or substantially different angle
  - Embedding similarity may be due to shared keywords, not actual topic overlap

**OUTPUT FORMAT (JSON):**
{{
  "repetition_score": "high" | "medium" | "low" | "none",
  "reasoning": "Detailed explanation of why this repetition level was assigned. If repetition detected, specify which previous discussion it overlaps with and how."
}}

**IMPORTANT:**
- Embedding similarity indicates potential overlap, but you must validate semantic meaning
- Keywords in common (e.g., "RAG", "LangGraph") don't necessarily mean repetition
- Focus on: Is this the SAME conversation/problem or a DIFFERENT one?

Analyze and output valid JSON:"""
