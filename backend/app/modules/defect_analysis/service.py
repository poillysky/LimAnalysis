from app.modules.defect_analysis.schemas import DefectSummary


def get_summary() -> DefectSummary:
    return DefectSummary(total=12, topReason="外观不良")
