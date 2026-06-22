import fcntl
import os
import signal
import sys
from unittest.mock import patch

import pytest
import structlog

from dev_space.aop import GracefulShutdown, tool_lock, setup_observability
from dev_space.config import DevSpaceSettings


@pytest.mark.no_observability
def test_config_load():
    """Validates the Pydantic settings loading."""
    # Test overriding a value via env var
    with patch.dict(os.environ, {"DEV_SPACE_CORE__LOG_LEVEL": "debug"}):
        settings = DevSpaceSettings.load()
        assert settings.core.log_level == "debug"


@pytest.mark.no_observability
def test_setup_observability(monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    setup_observability(quiet=True)

    processors = structlog.get_config()["processors"]
    assert isinstance(processors[-1], structlog.processors.JSONRenderer)

    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    setup_observability(verbose=True)

    processors = structlog.get_config()["processors"]
    assert isinstance(processors[-1], structlog.dev.ConsoleRenderer)


@pytest.mark.no_observability
def test_graceful_shutdown():
    with GracefulShutdown() as gs:
        assert not gs._already_interrupted

        # Test first interrupt
        with pytest.raises(KeyboardInterrupt):
            gs._handle(signal.SIGINT, None)

        assert gs._already_interrupted

        # Test second interrupt (forces exit)
        with patch.object(sys, "exit") as mock_exit:
            with pytest.raises(KeyboardInterrupt):
                gs._handle(signal.SIGINT, None)
            mock_exit.assert_called_with(128 + signal.SIGINT)


@pytest.mark.no_observability
def test_tool_lock():
    with patch("dev_space.aop.fcntl.flock") as flock:
        with tool_lock("test-lock"):
            assert flock.call_args_list[0].args[1] == fcntl.LOCK_EX

        assert flock.call_args_list[1].args[1] == fcntl.LOCK_UN
        assert flock.call_args_list[0].args[0] is flock.call_args_list[1].args[0]
        assert flock.call_args_list[1].args[0].closed is True
