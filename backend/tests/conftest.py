from __future__ import annotations

import pytest

from app.config import Settings
from app.db.session import Database


@pytest.fixture
def settings(tmp_path) -> Settings:
    # _env_file=None: tests never read your real .env
    return Settings(_env_file=None, app_env="test", STUDY_TERMINAL_DATA_DIR=tmp_path, poll_interval_seconds=3600,
                    paper_slippage_bps=0, paper_slippage_min=0)


@pytest.fixture
def db(settings) -> Database:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    d = Database(settings.resolved_database_url)
    d.create_all()
    yield d
    d.dispose()
