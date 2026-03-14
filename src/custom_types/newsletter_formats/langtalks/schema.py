"""
LangTalks Newsletter Response Schema

Pydantic models defining the structure of LLM responses for the LangTalks newsletter format.
"""

from pydantic import BaseModel, Field


class BulletPoint(BaseModel):
    """A single bullet point in a discussion summary."""

    label: str = Field(..., description="The label of the bullet point (1-3 words).")
    content: str = Field(..., description="The content of the bullet point (20-40 words).")


class DiscussionSource(BaseModel):
    """Metadata about a source group for merged discussions."""

    group: str = Field(..., description="The name of the chat/group")
    first_message_timestamp: int = Field(..., description="When this group started discussing")


class SummarizedDiscussion(BaseModel):
    """A summarized discussion with title, bullet points, and metadata."""

    title: str = Field(..., description="The title of the discussion (4-6 words).")
    bullet_points: list[BulletPoint] = Field(..., description="The bullet points summarizing the discussion.")
    first_message_timestamp: int = Field(..., description="The timestamp of the first message in the discussion.")
    last_message_timestamp: int = Field(..., description="The timestamp of the last message in the discussion.")
    ranking_of_relevance_to_gen_ai_engineering: int = Field(
        ...,
        description="A number between 1 and 10, where 10 is the most relevant and 1 is the least relevant.",
    )
    number_of_messages: int = Field(..., description="The number of messages in the discussion.")
    number_of_unique_participants: int = Field(..., description="The number of unique participants in the discussion.")
    chat_name: str = Field(
        default="LangTalks Community",
        description="The name of the chat/group where this discussion occurred (for standalone discussions).",
    )

    # NEW: Merged discussion metadata
    is_merged: bool | None = Field(default=False, description="True if this discussion combines multiple source groups")
    source_discussions: list[DiscussionSource] | None = Field(default=None, description="For merged discussions: list of source groups with timestamps")


class LlmResponseLangTalksNewsletterContent(BaseModel):
    """
    Response schema for LangTalks newsletter generation.

    The LLM should return content in this structure:
    - primary_discussion: The main/most important discussion
    - secondary_discussions: 3 additional notable discussions
    - worth_mentioning: 3-7 brief one-liners about other topics
    """

    primary_discussion: SummarizedDiscussion = Field(
        ...,
        description="The primary discussion of the newsletter with 5 bullet points.",
    )
    secondary_discussions: list[SummarizedDiscussion] = Field(
        ...,
        description="Three secondary discussions, each with 3 bullet points.",
    )
    worth_mentioning: list[str] = Field(
        ...,
        min_length=3,
        description="3-7 one-liners about things that are worth mentioning.",
    )
