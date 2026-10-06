from pydantic import BaseModel


class InspectionSettingsIn(BaseModel):
    mold_root_path: str | None = None
    appearance_root_path: str | None = None
