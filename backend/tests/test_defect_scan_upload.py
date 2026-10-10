from app.core.defect_scans import record_scans


def test_record_scans_inserts_without_server_time_attribute_error():
    result = record_scans("eagle_rcvr", "烟囱溢胶", ["TEST_UPLOAD_SN_001"])
    assert result["count"] == 1
    assert result["op"]["project_id"] == "eagle_rcvr"
    assert result["op"]["defect_item"] == "烟囱溢胶"
