from pydantic import BaseModel, field_validator


class Story(BaseModel):
    """Pydantic model for a Jira ticket (Story)"""

    summary: str
    description: str
    epic_link: str
    project_key: str

    @field_validator("epic_link")
    @classmethod
    def epic_link_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("epic_link must not be empty")
        return v.strip()
