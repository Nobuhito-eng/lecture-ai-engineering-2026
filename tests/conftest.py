"""テスト全体の共通設定。"""

import pytest

from app import tools


@pytest.fixture(autouse=True)
def isolated_learning_log(tmp_path, monkeypatch):
    """どのテストでも、学習ログは一時フォルダに書く（本物の learning_log/ を汚さない）。"""
    log_dir = tmp_path / "learning_log"
    monkeypatch.setattr(tools, "LEARNING_LOG_DIR", log_dir)
    return log_dir
