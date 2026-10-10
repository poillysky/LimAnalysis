from pathlib import Path

from app.core.disk_cleanup import _estimate_dir_size, _file_usage_bytes


def test_file_usage_bytes_prefers_blocks(monkeypatch):
    class St:
        st_size = 100
        st_blocks = 8

    assert _file_usage_bytes(St()) == 4096


def test_file_usage_bytes_falls_back_to_size():
    class St:
        st_size = 1234

    assert _file_usage_bytes(St()) == 1234


def test_estimate_dir_size_counts_nested_files(tmp_path: Path):
    root = tmp_path / "photos"
    (root / "a").mkdir(parents=True)
    (root / "a" / "1.txt").write_bytes(b"x" * 100)
    (root / "b").mkdir()
    (root / "b" / "2.txt").write_bytes(b"y" * 200)

    total, files, truncated = _estimate_dir_size(root)

    assert files == 2
    assert total == 300
    assert truncated is False
