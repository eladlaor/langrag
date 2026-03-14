"""
Discussion Merging Prompts

LLM prompts for:
1. Identifying which discussions should be merged (same/overlapping topics)
2. Generating titles for merged discussions
3. Synthesizing comprehensive nutshells from multiple source discussions
"""

# =============================================================================
# IDENTIFY MERGE GROUPS PROMPT
# =============================================================================
# Single LLM call to identify all merge groups across all discussions

IDENTIFY_MERGE_GROUPS_PROMPT = """You are an expert at analyzing technical discussions and identifying topical overlap.

Given {num_discussions} discussions from {num_groups} WhatsApp groups, identify which discussions cover the SAME or SUBSTANTIALLY OVERLAPPING topics and should be merged into a single comprehensive discussion.

**MERGE CRITERIA (merge if ANY of these apply):**
- Discussions cover the SAME core topic (even if from different angles)
- One discussion is a clear subtopic of another (e.g., "RAG chunking" is a subtopic of "RAG implementation")
- Discussions represent problem + solution on the same issue
- Discussions are different perspectives on the same debate/question

**DO NOT MERGE if:**
- Topics are merely "related" but distinct (e.g., "RAG" and "Fine-tuning" are both AI topics but should stay separate)
- Merging would create an unfocused, overly broad discussion
- Topics share keywords but are fundamentally about different things

**SIMILARITY THRESHOLD: {similarity_threshold}**
- "strict": Only merge near-identical topics (exact same subject matter)
- "moderate": Merge same topic + clear subtopics + problem/solution pairs
- "aggressive": Merge all related topics that could reasonably be covered together

**DISCUSSIONS TO ANALYZE:**
{formatted_discussions}

**OUTPUT FORMAT (JSON):**
{{
  "merge_groups": [
    {{
      "suggested_title": "A comprehensive title that captures all merged discussions",
      "discussion_ids": ["discussion_id_1", "discussion_id_2"],
      "source_groups": ["Group Name 1", "Group Name 2"],
      "merge_confidence": "high" | "medium",
      "reasoning": "Explanation of why these discussions should be merged"
    }}
  ],
  "standalone_ids": ["discussion_id_3", "discussion_id_4"]
}}

**RULES:**
1. Each discussion can only appear in ONE merge group OR in standalone_ids
2. A merge group must have at least 2 discussions
3. Maximum 5 discussions per merge group (if more would merge, pick the most central ones)
4. Be conservative - when in doubt, keep discussions separate
5. Every input discussion_id must appear exactly once in the output (either in a merge_group or standalone_ids)

Analyze the discussions and output valid JSON:"""


# =============================================================================
# GENERATE MERGED TITLE PROMPT
# =============================================================================
# Generate a comprehensive title for merged discussions

GENERATE_MERGED_TITLE_PROMPT = """Generate a single, comprehensive title that captures the breadth of these related discussions.

**Source Discussion Titles:**
{titles}

**Requirements:**
- Keep it concise (under 12 words)
- Capture the common theme across all discussions
- Be specific enough to be meaningful
- Use the primary language of the discussions (Hebrew or English)

**Examples:**
- Input: ["RAG chunking strategies", "Best practices for RAG chunking"]
  Output: "RAG Chunking: Strategies and Best Practices"

- Input: ["בעיות ביצועים ב-LangChain", "אופטימיזציה של LangChain pipelines"]
  Output: "ביצועים ואופטימיזציה ב-LangChain"

- Input: ["LangGraph state management", "Managing state in LangGraph workflows", "State bugs in LangGraph"]
  Output: "State Management in LangGraph: Patterns and Pitfalls"

Output ONLY the title, nothing else:"""


# =============================================================================
# SYNTHESIZE MERGED NUTSHELL PROMPT
# =============================================================================
# Create a comprehensive nutshell from multiple source discussions

SYNTHESIZE_MERGED_NUTSHELL_PROMPT = """You are synthesizing insights from multiple related discussions into one comprehensive summary.

**Merged Discussion Title:** {merged_title}

**Source Discussions:**
{formatted_sources}

**Generate a nutshell summary (2-4 sentences) that:**
1. Captures the KEY insights from ALL source discussions
2. Notes different perspectives or approaches mentioned across groups
3. Provides actionable takeaways for the reader
4. Acknowledges if there's debate or disagreement on the topic

**Style Guidelines:**
- Write in the same language as the source discussions (Hebrew or English)
- The summary should feel like a comprehensive overview, not a list of separate points
- If groups had different perspectives, highlight that diversity as valuable
- Focus on practical, teachable insights

**Example output (Hebrew):**
"דיון נרחב על אסטרטגיות chunking ב-RAG מכמה קהילות. בקהילת LangTalks העדיפו semantic chunking למסמכים משפטיים, בעוד ב-Code Generation Agents הדגישו את החשיבות של chunk overlap למניעת אובדן הקשר. מסקנה מעשית: כדאי לבדוק את שתי הגישות על ה-dataset הספציפי שלכם."

**Example output (English):**
"Comprehensive discussion on RAG chunking from multiple communities. LangTalks members favored semantic chunking for legal documents, while Code Generation Agents emphasized chunk overlap to prevent context loss. Practical takeaway: benchmark both approaches on your specific dataset."

Output ONLY the nutshell summary:"""


# =============================================================================
# VALIDATE MERGE CANDIDATES PROMPT (Hybrid Approach)
# =============================================================================
# LLM validation of embedding-based similarity matches

VALIDATE_MERGE_CANDIDATES_PROMPT = """You are validating embedding-based similarity matches to determine if discussions should be merged.

Given {num_candidates} candidate pairs with high embedding similarity (cosine ≥ {embedding_threshold}), determine which pairs represent the SAME or SUBSTANTIALLY OVERLAPPING topics.

**IMPORTANT**: Embeddings can produce false positives (keyword overlap without semantic overlap). Your job is to filter out false positives.

**MERGE if:**
- Discussions cover the SAME core topic (even from different angles)
- One is a clear subtopic of another (e.g., "RAG chunking" ⊂ "RAG implementation")
- Discussions are problem + solution on the same issue
- Different perspectives on the same debate/question

**DO NOT MERGE if:**
- Topics share keywords but are fundamentally different (e.g., "RAG" vs "Fine-tuning")
- Merging would create an unfocused, overly broad discussion
- Similarity is due to common AI terminology, not actual topic overlap

**SIMILARITY THRESHOLD: {similarity_threshold}**
- "strict": Only merge near-identical topics (exact same subject matter)
- "moderate": Merge same topic + clear subtopics + problem/solution pairs
- "aggressive": Merge all related topics that could reasonably be covered together

**CANDIDATE PAIRS:**
{formatted_candidates}

**OUTPUT FORMAT (JSON):**
{{
  "merge_groups": [
    {{
      "discussion_ids": ["id1", "id2", "id3"],
      "source_groups": ["Group A", "Group B"],
      "suggested_title": "Comprehensive title covering all discussions",
      "merge_confidence": "high" | "medium",
      "reasoning": "Why these should be merged"
    }}
  ],
  "rejected_pairs": [
    {{
      "disc1_id": "id1",
      "disc2_id": "id2",
      "rejection_reason": "Both mention 'agents' but discuss different agent types"
    }}
  ]
}}

**RULES:**
1. A merge group can include discussions from multiple validated pairs (transitive merging)
2. Maximum 5 discussions per merge group
3. Be conservative - when in doubt, reject the merge
4. Every candidate pair must appear in either merge_groups or rejected_pairs

Validate the candidate pairs and output valid JSON:"""
