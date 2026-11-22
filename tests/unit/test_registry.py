from __future__ import annotations

import pytest

from backend.core.registry import ServiceRegistry


class Svc:
    def __init__(self, name: str, log: list[str], fail: bool = False) -> None:
        self.name, self.log, self.fail = name, log, fail

    async def aclose(self) -> None:
        self.log.append(f"a:{self.name}")
        if self.fail:
            raise RuntimeError("boom")


class SyncSvc:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    def close(self) -> None:
        self.log.append("sync")


def test_create_once() -> None:
    reg = ServiceRegistry()
    calls: list[int] = []

    def make() -> object:
        calls.append(1)
        return object()

    assert reg.get("x", make) is reg.get("x", make)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_reverse_close_and_failure_isolation() -> None:
    log: list[str] = []
    reg = ServiceRegistry()
    reg.get("a", lambda: Svc("a", log))
    reg.get("b", lambda: Svc("b", log, fail=True))
    reg.get("c", lambda: SyncSvc(log))
    reg.get("d", object)
    await reg.aclose()
    assert log == ["sync", "a:b", "a:a"]
    await reg.aclose()  # idempotent
    assert log == ["sync", "a:b", "a:a"]
