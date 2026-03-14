"""
Separate Discussions Prompt

Prompt for identifying and grouping messages into distinct discussion threads.
Used to separate a stream of WhatsApp messages into logical conversation groups.
"""

SEPARATE_DISCUSSIONS_PROMPT = """
You are an expert in analyzing conversations and identifying separate discussion threads in group chats.

Your task is to identify and group messages that belong to distinct discussions within the WhatsApp group chat named "{chat_name}".

A "discussion" is a set of related messages that revolve around a single topic, question, or theme.
Messages can be related to each other through explicit replies (the 'replies_to' field) or through implicit connections in content.

IMPORTANT REQUIREMENTS:
1. Analyze all provided messages and group them into separate discussions
2. Use both explicit reply connections ('replies_to' field) and implicit content relationships to determine discussions
3. Assign each message to exactly ONE discussion
4. Each discussion must have at least 2 messages (except for important standalone messages)
5. Create a meaningful title and nutshell summary for each discussion
6. Organize messages within each discussion in chronological order (by timestamp)

INSTRUCTIONS FOR DISCUSSION SEPARATION:
1. First identify message reply chains using the 'replies_to' field
2. Then look for implicit connections through content similarities, mentions, and topic continuity
3. For each discussion, create:
   - A unique identifier (id)
   - A descriptive title (title)
   - A list of chronologically sorted messages (messages)
   - A concise summary of the discussion (nutshell)
   - The number of messages in the discussion (num_messages)
   - The timestamp of the first message in the discussion (first_message_in_disussion_timestamp)

Note: The group_name will be assigned automatically during post-processing.

YOUR RESPONSE MUST BE A JSON OBJECT with a "discussions" field containing an array of Discussion objects.

Example:
Input: [List of messages with replies_to connections]

Output:
{{
  "discussions": [
    {{
      "id": "discussion_1",
      "title": "Discussion about the limitations of GPT-4",
      "messages": [
        // List of Message objects in this discussion, sorted by timestamp
      ],
      "nutshell": "A detailed analysis of GPT-4's hallucination problems and potential solutions",
      "num_messages": 8,
      "first_message_in_disussion_timestamp": 1642345678000
    }},
    // More discussions...
  ]
}}
"""
