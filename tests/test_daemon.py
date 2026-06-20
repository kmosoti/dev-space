import pytest
from unittest.mock import patch
from typer.testing import CliRunner
from dev_space.cli import app

runner = CliRunner()


@pytest.mark.no_observability
@patch("granian.Granian")
def test_daemon_start(mock_granian):
    # Setup mock server instance
    mock_server = mock_granian.return_value

    result = runner.invoke(app, ["--format", "json", "daemon", "start"])
    assert result.exit_code == 0
    mock_granian.assert_called_once()
    mock_server.serve.assert_called_once()


@pytest.mark.no_observability
@patch("granian.Granian")
def test_daemon_start_failure(mock_granian):
    mock_granian.side_effect = Exception("Granian failed")

    result = runner.invoke(app, ["--format", "json", "daemon", "start"])
    assert result.exit_code == 1


@pytest.mark.asyncio
@pytest.mark.no_observability
async def test_rsgi_app():
    from dev_space.daemon import rsgi_app

    class MockScope:
        def __init__(self, path):
            self.path = path

    async def mock_receive():
        pass

    sent = []

    async def mock_send(data):
        sent.append(data)

    await rsgi_app(MockScope("/healthz"), mock_receive, mock_send)
    assert sent[0]["status"] == 200
    assert b"ok" in sent[1]["body"]

    sent.clear()
    await rsgi_app(MockScope("/metrics"), mock_receive, mock_send)
    assert sent[0]["status"] == 200
    assert b"uptime" in sent[1]["body"]

    sent.clear()
    await rsgi_app(MockScope("/invalid"), mock_receive, mock_send)
    assert sent[0]["status"] == 404
