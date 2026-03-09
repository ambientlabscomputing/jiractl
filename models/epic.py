from pydantic import BaseModel, field_validator


class Epic(BaseModel):
    """Pydantic model for a Jira Epic"""
    epic_name: str
    summary: str
    description: str
    project_key: str

    @field_validator("epic_name")
    @classmethod
    def epic_name_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("epic_name must not be empty")
        return v.strip()
