import pytest


@pytest.fixture(autouse=True)
def _artifacts_in_tmp(tmp_path, monkeypatch):
    """Lượt chạy không gắn project ghi vào tmp — test không được rải file vào repo."""
    import qctool.pipeline as pipeline
    monkeypatch.setattr(pipeline, "ARTIFACTS_ROOT", tmp_path / "artifacts")
    monkeypatch.setattr(pipeline, "WEB_ROOT", tmp_path / "web")
