from pydantic import BaseModel


class DefectSummary(BaseModel):
    total: int
    topReason: str
