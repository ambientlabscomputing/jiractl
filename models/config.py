from pydantic import BaseModel

class Config(BaseModel):
    base_url: str
    email: str
    allowed_projects: list[str]
    synonyms: dict[str, list[str]] = {}