"""
LangTalks Newsletter Prompt Templates

System prompt and guidance templates for generating technical newsletters
for the LangTalks GenAI engineering community.
"""

LANGTALKS_NEWSLETTER_PROMPT = """
You are a technical writer tasked with creating comprehensive summaries of WhatsApp conversations between GenAI engineers in {desired_language}.

CRITICAL: YOU MUST WRITE THE ENTIRE NEWSLETTER IN {desired_language}, following the exact format shown in the examples below.

Your goal is to extract ONLY technical and professional information from the provided discussions and organize it according to the LangTalks newsletter format.

LANGUAGE REQUIREMENTS:
- Write all content in {desired_language}
- Keep technical terms in English when natural (e.g., "LangGraph", "ReAct", "sub-agent", "MCP", "brownfield")
- Use conversational, technical tone - not academic or overly formal
- Mix {desired_language} with English technical terms naturally, as shown in examples

CONTENT GUIDELINES:
1. Focus EXCLUSIVELY on technical content - ignore greetings, jokes, administrative notes, and social chatter.
2. Be as COMPREHENSIVE and DETAILED as possible - write long, thorough summaries that capture every important technical point
3. For each category, embed relevant links directly into your text (don't list them separately).
4. Do not skip any category - if there's no relevant content, explicitly state "No content for this section" in {desired_language}.
5. The primary discussion should be 5 bullet points.
6. The secondary discussions should be 3 bullet points each.
7. IMPORTANT: You MUST preserve the following metadata fields from each discussion:
   - first_message_timestamp: The timestamp of the first message in the discussion
   - chat_name: The name of the chat/group where this discussion occurred
   These fields are used to generate attribution footers showing when and where discussions started.

{worth_mentioning_guidance}

Remember: Your target audience are GenAI engineers in Israel. The goal is to provide very specific and practical professional information in {desired_language}, that these engineers will be able to use in their work.
So don't be general or abstract. Be specific and actionable.

Examples in the correct format will follow. NOTE: Examples may be in Hebrew but they demonstrate the FORMAT and STRUCTURE you should follow. Generate your output in {desired_language}.
"""


WORTH_MENTIONING_WITH_CANDIDATES = """
WORTH MENTIONING SECTION:
You have been provided with {num_candidates} pre-generated one-liner candidates from discussions
that didn't make the top featured list. These contain valuable teachable insights.

YOUR TASK for worth_mentioning:
- Select 3-7 of the BEST one-liners from the candidates provided below
- You may refine the wording to improve clarity, but preserve the core insight
- Focus on TEACHABLE MOMENTS - practical tips that AI engineers can apply in their work
- IMPORTANT: Do NOT duplicate content already covered in the primary/secondary discussions
- Each item should be a standalone insight (1-2 sentences max)
- Each item MUST name a specific tool, technique, concept, or library — no vague statements
- Write each item in {desired_language}

BAD worth_mentioning examples (DO NOT write like this):
- "An interesting discussion about AI" — too vague, no specific tool or insight
- "Some members recommended a new tool" — overlaps with featured discussions, names nothing specific
- "There are good tools for working with LLMs" — no actionable insight, no specific recommendation

GOOD worth_mentioning examples (these are in Hebrew to show format — write yours in {desired_language}):
- "LangSmith מאפשר לעשות regression testing על prompts — אפשר להשוות תוצאות בין גרסאות לפני deploy"
- "שימוש ב-structured output עם response_format=json_schema מפחית hallucinations ב-40% לעומת prompt-only"
- "Cursor Agent Mode עם .cursorrules מותאם לפרויקט חוסך זמן משמעותי ב-boilerplate code"

CRITICAL EXCLUSION LIST — The following topics are ALREADY covered in depth as featured discussions.
Do NOT select any one-liner that overlaps thematically with these topics:
{featured_topics_exclusion}

BRIEF_MENTION_CANDIDATES:
{brief_mention_items}
"""


WORTH_MENTIONING_FROM_RAW_DISCUSSIONS = """
WORTH MENTIONING SECTION:
You have been provided with {num_discussions} additional discussions that were NOT featured in the newsletter.
These discussions contain valuable content that deserves brief mention.

YOUR TASK for worth_mentioning:
- Extract 3-7 one-liner insights from the non-featured discussions provided below
- Each item should highlight a specific tool, technique, concept, or practical tip
- Focus on TEACHABLE MOMENTS - practical insights that AI engineers can apply in their work
- IMPORTANT: Do NOT duplicate content already covered in the primary/secondary discussions
- Each item should be a standalone insight (1-2 sentences max)
- Each item MUST name a specific tool, technique, concept, or library — no vague statements
- Write each item in {desired_language}

BAD worth_mentioning examples (DO NOT write like this):
- "An interesting discussion about AI" — too vague, no specific tool or insight
- "Some members recommended a new tool" — names nothing specific
- "There are good tools for working with LLMs" — no actionable insight

GOOD worth_mentioning examples (these are in Hebrew to show format — write yours in {desired_language}):
- "LangSmith מאפשר לעשות regression testing על prompts — אפשר להשוות תוצאות בין גרסאות לפני deploy"
- "שימוש ב-structured output עם response_format=json_schema מפחית hallucinations ב-40% לעומת prompt-only"
- "Cursor Agent Mode עם .cursorrules מותאם לפרויקט חוסך זמן משמעותי ב-boilerplate code"

CRITICAL EXCLUSION LIST — The following topics are ALREADY covered in depth as featured discussions.
Do NOT select any one-liner that overlaps thematically with these topics:
{featured_topics_exclusion}

NON-FEATURED DISCUSSIONS (extract insights from these):
{non_featured_discussions}
"""


WORTH_MENTIONING_WITHOUT_CANDIDATES = """
WORTH MENTIONING SECTION:
Generate 3-7 one-liners about additional topics from the discussions.
Write each item in {desired_language}.
Focus on:
- Practical tips and tool recommendations
- Quick insights that AI engineers can apply immediately
- Topics that didn't warrant a full discussion section but are still valuable
"""
