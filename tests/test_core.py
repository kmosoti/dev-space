import os
import signal
import sys
from unittest.mock import patch

import pytest

from dev_space.config import DevSpaceSettings
from dev_space.aop import GracefulShutdown, tool_lock, setup_observability


@pytest.mark.no_observability
def test_config_load():
    """Validates the Pydantic settings loading."""
    # Test overriding a value via env var
    with patch.dict(os.environ, {"DEV_SPACE_CORE__LOG_LEVEL": "debug"}):
        settings = DevSpaceSettings.load()
        assert settings.core.log_level == "debug"


@pytest.mark.no_observability
def test_setup_observability():
    # Test quiet mode
    setup_observability(quiet=True, verbose=False)
    # Test verbose mode
    setup_observability(quiet=False, verbose=True)
    # Just asserting it doesn't crash since structlog config is global
    assert True


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
    # Tests that the flock wrapper acquires and releases safely
    with tool_lock("test-lock"):
        lock_file = os.path.expanduser("~/.dev-space/locks/test-lock.lock")
        if not os.path.exists("/var/lock/dev-space"):
            assert os.path.exists(lock_file)
