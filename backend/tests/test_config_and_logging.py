import logging

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.logging_setup import REDACTED, RedactingFilter


def test_launches_with_zero_configuration(tmp_path):
    s = Settings(_env_file=None, STUDY_TERMINAL_DATA_DIR=tmp_path)
    assert s.market_data_provider == "yahoo"
    assert s.execution_mode == "paper"
    assert s.secret_values() == []  # no credentials exist anywhere in config
    assert not any("alpaca" in name or "broker" in name for name in Settings.model_fields)


def test_execution_mode_cannot_be_live(tmp_path):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, STUDY_TERMINAL_DATA_DIR=tmp_path, execution_mode="live")


def test_old_alpaca_env_vars_are_ignored(monkeypatch, tmp_path):
    monkeypatch.setenv("ALPACA_API_KEY_ID", "PKOLD")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "oldsecret")
    s = Settings(_env_file=None, STUDY_TERMINAL_DATA_DIR=tmp_path)
    assert "PKOLD" not in repr(s.model_dump())


def test_csv_and_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("DEFAULT_WATCHLIST", "spy, qqq ,amd")
    monkeypatch.setenv("LIVE_MODE", "poll_only")
    monkeypatch.setenv("PAPER_STARTING_CASH", "10000")
    s = Settings(_env_file=None, STUDY_TERMINAL_DATA_DIR=tmp_path)
    assert s.default_watchlist == ["SPY", "QQQ", "AMD"]
    assert s.live_mode == "poll_only" and s.paper_starting_cash == 10_000


def test_log_redaction():
    f = RedactingFilter(["SUPERSECRETVALUE"])
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "auth %s", ("SUPERSECRETVALUE",), None)
    f.filter(rec)
    assert "SUPERSECRETVALUE" not in rec.getMessage() and REDACTED in rec.getMessage()


@pytest.mark.parametrize("line", ["url?token=abc123zzz&x=1", 'api_key="abc123zzz"', '{"secret": "abc123zzz"}'])
def test_pattern_redaction(line):
    assert "abc123zzz" not in RedactingFilter([]).redact(line)


def test_self_test_switch_ignores_the_real_env_file(tmp_path):
    """The installer's self-test sets STUDY_TERMINAL_NO_ENV_FILE=1 so it never loads your settings or credentials."""
    import os
    import subprocess
    import sys
    home = tmp_path / "home"
    (home / ".study-terminal").mkdir(parents=True)
    (home / ".study-terminal" / ".env").write_text("PORT=9123\n")
    code = "from app.config import Settings; print(Settings().port)"
    base = {k: v for k, v in os.environ.items() if k not in ("PORT", "STUDY_TERMINAL_NO_ENV_FILE")} | {"HOME": str(home), "LOCALAPPDATA": str(home)}
    run = lambda env: subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True,  # noqa: E731
                                     cwd=os.path.dirname(os.path.dirname(__file__)), check=True).stdout.strip()
    if sys.platform != "win32":
        assert run(base) == "9123"                                   # normally the data-folder .env is read
    assert run(base | {"STUDY_TERMINAL_NO_ENV_FILE": "1"}) != "9123"  # the self-test switch ignores it
