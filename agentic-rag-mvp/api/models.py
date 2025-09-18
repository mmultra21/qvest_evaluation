from pydantic import BaseModel
from typing import Optional


class Health(BaseModel):
    status: str = "ok"


class Item(BaseModel):
    id: int
    name: str
    description: Optional[str]
