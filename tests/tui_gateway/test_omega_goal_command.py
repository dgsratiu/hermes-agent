"""Tests for /omega-goal handling in tui_gateway command.dispatch."""

from __future__ import annotations

import importlib
import threading
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def server():
    with patch.dict(
        "sys.modules",
        {
            "hermes_cli.env_loader": MagicMock(),
            "hermes_cli.banner": MagicMock(),
        },
    ):
        mod = importlib.import_module("tui_gateway.server")
        yield mod
        mod._sessions.clear()
        mod._pending.clear()
        mod._answers.clear()
        mod._methods.clear()
        importlib.reload(mod)


@pytest.fixture()
def session(server):
    sid = "sid-omega-tui"
    session_key = "tui-omega-session-1"
    server._sessions[sid] = {
        "session_key": session_key,
        "history": [],
        "history_lock": threading.Lock(),
        "history_version": 0,
        "running": False,
        "attached_images": [],
        "cols": 120,
    }
    return sid, session_key


def _call(server, method, **params):
    handler = server._methods[method]
    return handler(1, params)


def test_omega_goal_dispatch_returns_exec_output(server, session):
    sid, session_key = session
    r = _call(
        server,
        "command.dispatch",
        name="omega-goal",
        arg="push object forward --dry-run",
        session_id=sid,
    )

    result = r["result"]
    assert result["type"] == "exec"
    assert "Omega mission omega-" in result["output"]
    assert "Board: omega-" in result["output"]

    status = _call(server, "command.dispatch", name="omega", arg="status", session_id=sid)
    assert status["result"]["type"] == "exec"
    assert "push object forward" in status["result"]["output"]

    from hermes_cli.omega_goal import get_active_pointer

    assert get_active_pointer(session_key)["mission_id"].startswith("omega-")
