from pathlib import Path

import config


def test_default_model_is_pinned():
    assert config.DEFAULT_MODEL == "gpt-4o-mini"


def test_db_path_is_under_project_root():
    assert config.DB_PATH == config.PROJECT_ROOT / "data" / "meetings.db"


def test_get_api_key_returns_none_when_unset(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert config.get_api_key() is None


def test_get_api_key_reads_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-123")
    assert config.get_api_key() == "sk-test-123"
