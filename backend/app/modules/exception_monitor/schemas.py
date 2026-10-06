from pydantic import BaseModel


class ExceptionItem(BaseModel):
    id: str
    line: str
    title: str
    status: str
