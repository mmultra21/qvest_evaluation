
from pydantic import BaseModel, Field
from pydantic import field_validator
from typing import List


class JustifiedItem(BaseModel):
    catalog_id: str = Field(..., min_length=1)
    pitch: str = Field(..., min_length=3, max_length=240)
    why: str = Field(..., min_length=3, max_length=240)
    shelf: str = Field(..., min_length=1)

    @field_validator("why")
    def must_cite_lexile(cls, v: str) -> str:
        """Ensure 'why' clause contains 'Lexile' so it ties back to reading level."""
        if "lexile" not in v.lower():
            raise ValueError("Why must include a Lexile clause")
        return v



class JustifyResponse(BaseModel):
    items: List[JustifiedItem]
