"""
MCP Israel Newsletter Response Schema

Pydantic models defining the structure of LLM responses for the MCP Israel newsletter format.
"""

from pydantic import BaseModel, Field


class LlmResponseMcpIsraelNewsletterContent(BaseModel):
    """
    Response schema for MCP Israel newsletter generation.

    The MCP Israel format organizes content into categorical sections
    rather than primary/secondary discussions.
    """

    markdown_content: str = Field(..., description="The complete newsletter summary in markdown format")
    industry_updates: str = Field("", description="Industry updates section content")
    tools_mentioned: str = Field("", description="Tools mentioned section content")
    work_practices: str = Field("", description="Work practices section content")
    security_risks: str = Field("", description="Security and risks section content")
    valuable_posts: str = Field("", description="Valuable posts section content")
    open_questions: str = Field("", description="Open questions section content")
    conceptual_discussions: str = Field("", description="Conceptual discussions section content")
    issues_challenges: str = Field("", description="Issues and challenges section content")
