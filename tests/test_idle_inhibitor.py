"""
Unit tests for :mod:`space_flight.global_architecture.idle_inhibitor`.

The platform is faked through ``sys.platform`` and every OS call is stubbed,
so no test touches the real D-Bus session, Win32 API or ``caffeinate``.
jeepney is a Linux-only dependency, so the Linux tests use a fake jeepney
package registered in ``sys.modules`` and run on every OS.
"""

import sys
import types

import pytest

from space_flight.global_architecture import idle_inhibitor as ii
from space_flight.global_architecture.idle_inhibitor import IdleInhibitor


class _FakeConnection:
    def __init__(self):
        self.calls = []
        self.closed = False
        self.fail_on = None

    def send_and_get_reply(self, message, timeout=None):
        self.calls.append((message.member, message.body))
        if message.member == self.fail_on:
            raise ConnectionError("bus gone")
        return types.SimpleNamespace(body=(42,) if message.member == "Inhibit" else ())

    def close(self):
        self.closed = True


@pytest.fixture
def fake_jeepney(monkeypatch):
    """
    Install a minimal fake jeepney (just what idle_inhibitor imports).

    :return: the fake ``jeepney.io.blocking`` module, whose
        ``open_dbus_connection`` tests may replace
    """
    jeepney = types.ModuleType("jeepney")
    jeepney.DBusAddress = lambda object_path, bus_name, interface: object_path
    jeepney.new_method_call = lambda address, member, signature, body: (
        types.SimpleNamespace(member=member, body=body)
    )
    io = types.ModuleType("jeepney.io")
    blocking = types.ModuleType("jeepney.io.blocking")
    wrappers = types.ModuleType("jeepney.wrappers")
    wrappers.unwrap_msg = lambda reply: reply.body
    jeepney.io, io.blocking, jeepney.wrappers = io, blocking, wrappers
    for module in (jeepney, io, blocking, wrappers):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(sys, "platform", "linux")
    return blocking


@pytest.fixture
def linux(fake_jeepney):
    connection = _FakeConnection()
    fake_jeepney.open_dbus_connection = lambda bus: connection
    return connection


def test_linux_acquire_and_release(linux):
    inhibitor = IdleInhibitor()
    inhibitor.acquire()
    assert inhibitor.active
    assert linux.calls == [("Inhibit", ("SpaceFlight", "Playing"))]

    inhibitor.release()
    assert not inhibitor.active
    assert linux.calls[-1] == ("UnInhibit", (42,))
    assert linux.closed


def test_acquire_and_release_are_idempotent(linux):
    inhibitor = IdleInhibitor()
    inhibitor.acquire()
    inhibitor.acquire()
    inhibitor.release()
    inhibitor.release()
    assert [member for member, _ in linux.calls] == ["Inhibit", "UnInhibit"]


def test_release_without_acquire_is_a_no_op(linux):
    IdleInhibitor().release()
    assert linux.calls == []


def test_linux_acquire_failure_is_swallowed(linux, caplog):
    linux.fail_on = "Inhibit"
    inhibitor = IdleInhibitor()
    inhibitor.acquire()
    assert not inhibitor.active
    assert linux.closed
    assert "Could not inhibit" in caplog.text


def test_linux_no_session_bus_is_swallowed(fake_jeepney, caplog):
    def no_bus(bus):
        raise KeyError("DBUS_SESSION_BUS_ADDRESS")

    fake_jeepney.open_dbus_connection = no_bus
    inhibitor = IdleInhibitor()
    inhibitor.acquire()
    assert not inhibitor.active
    assert "Could not inhibit" in caplog.text


def test_linux_release_failure_is_swallowed(linux, caplog):
    inhibitor = IdleInhibitor()
    inhibitor.acquire()
    linux.fail_on = "UnInhibit"
    inhibitor.release()
    assert not inhibitor.active
    assert linux.closed
    assert "Could not release" in caplog.text


def test_windows_sets_and_resets_execution_state(monkeypatch):
    states = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        IdleInhibitor, "_set_execution_state", staticmethod(states.append)
    )

    inhibitor = IdleInhibitor()
    inhibitor.acquire()
    inhibitor.release()
    assert states == [
        ii._ES_CONTINUOUS | ii._ES_DISPLAY_REQUIRED,
        ii._ES_CONTINUOUS,
    ]


def test_macos_runs_caffeinate_until_release(monkeypatch):
    launched = []

    class FakePopen:
        def __init__(self, args, **kwargs):
            launched.append(args)
            self.terminated = False

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(ii.subprocess, "Popen", FakePopen)

    inhibitor = IdleInhibitor()
    inhibitor.acquire()
    caffeinate = inhibitor._caffeinate
    assert launched == [["caffeinate", "-d", "-w", str(ii.os.getpid())]]

    inhibitor.release()
    assert caffeinate.terminated
    assert inhibitor._caffeinate is None


def test_macos_missing_caffeinate_is_swallowed(monkeypatch, caplog):
    def missing(*args, **kwargs):
        raise FileNotFoundError("caffeinate")

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(ii.subprocess, "Popen", missing)
    inhibitor = IdleInhibitor()
    inhibitor.acquire()
    assert not inhibitor.active
    assert "Could not inhibit" in caplog.text


def test_unknown_platform_is_a_no_op(monkeypatch):
    monkeypatch.setattr(sys, "platform", "freebsd14")
    inhibitor = IdleInhibitor()
    inhibitor.acquire()
    assert not inhibitor.active
