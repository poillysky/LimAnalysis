from pydantic import BaseModel, Field


class DefectScanCreate(BaseModel):
    project_id: str = Field(min_length=1, max_length=50)
    defect_item: str = Field(min_length=1, max_length=80)
    sn: str = Field(min_length=1, max_length=120)


class DefectScanItemsIn(BaseModel):
    project_id: str = Field(min_length=1, max_length=50)
    items: list[str] = Field(default_factory=list)


class DefectScanBatchIn(BaseModel):
    project_id: str = Field(min_length=1, max_length=50)
    defect_item: str = Field(min_length=1, max_length=80)
    sns: list[str] = Field(default_factory=list)
