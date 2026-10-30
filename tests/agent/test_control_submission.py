import asyncio
import threading

import pytest
from test_agent import ACCOUNT, PEER, packet, wait

import QQBot.agent.service as module


def barrier(service):
    asyncio.run_coroutine_threadsafe(asyncio.sleep(0), service._loop).result(timeout=2)


def test_expired_queued_manual_request_never_starts_after_loop_recovers(stack, monkeypatch):
    service, receiver, sessions, _, _, connection, model = stack
    receiver.receive(ACCOUNT, packet())
    entered, release = threading.Event(), threading.Event()

    def block():
        entered.set()
        release.wait(2)

    monkeypatch.setattr(module, "CONTROL_TIMEOUT", 0.03)
    service._loop.call_soon_threadsafe(block)
    assert entered.wait(1)
    try:
        with pytest.raises(ValueError, match="未提交"):
            service.process_once(ACCOUNT, f"private:{PEER}")
    finally:
        release.set()
        barrier(service)
    assert not sessions.list(ACCOUNT) and not model.calls and not connection.calls
    assert not service._manual and not service._tasks


def test_expiration_during_validation_prevents_late_commit(stack, monkeypatch):
    service, receiver, sessions, settings, _, connection, model = stack
    receiver.receive(ACCOUNT, packet())
    original = settings.read
    release, entered = threading.Event(), threading.Event()

    def blocked(*args, **kwargs):
        entered.set()
        release.wait(2)
        return original(*args, **kwargs)

    monkeypatch.setattr(settings, "read", blocked)
    monkeypatch.setattr(module, "CONTROL_TIMEOUT", 0.03)
    try:
        with pytest.raises(ValueError, match="未提交"):
            service.process_once(ACCOUNT, f"private:{PEER}")
        assert entered.is_set()
    finally:
        release.set()
        barrier(service)
    assert (
        not service._tasks
        and not service._manual
        and not sessions.list(ACCOUNT)
        and not connection.calls
        and not model.calls
    )


def test_committed_request_returns_acceptance_even_when_status_callback_is_slow(stack, monkeypatch):
    service, receiver, sessions, _, _, connection, model = stack
    receiver.receive(ACCOUNT, packet())
    release = threading.Event()
    original = service._publish

    def slow(**kwargs):
        if threading.current_thread().name == "agent-loop" and kwargs.get("account") == ACCOUNT:
            release.wait(2)
        return original(**kwargs)

    monkeypatch.setattr(service, "_publish", slow)
    monkeypatch.setattr(module, "CONTROL_TIMEOUT", 0.03)
    try:
        assert service.process_once(ACCOUNT, f"private:{PEER}")["accepted"]
    finally:
        release.set()
    wait(lambda: sessions.list(ACCOUNT) and sessions.list(ACCOUNT)[0]["status"] == "done")
    assert len(connection.calls) == 1 and len(model.calls) == 1
