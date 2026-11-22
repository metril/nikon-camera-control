from types import SimpleNamespace
from typing import Any

import pytest

from backend.core.security import (
    generate_api_key,
    hash_api_key,
    verify_api_key,
    ws_authorize,
    ws_subprotocol,
)


def test_hash_verify_generate() -> None:
    k = generate_api_key()
    assert len(k) >= 40 and generate_api_key() != k
    h = hash_api_key(k)
    assert len(h) == 64 and k not in h
    assert verify_api_key(k, h)
    assert not verify_api_key("nope", h)
    assert not verify_api_key(None, h)
    assert verify_api_key(None, None) and verify_api_key("x", "")


class FakeWS:
    def __init__(self, key_hash: str | None, protos: list[str], query: dict[str, str]) -> None:
        store = SimpleNamespace(config=SimpleNamespace(api_key_hash=key_hash))
        self.app = SimpleNamespace(state=SimpleNamespace(config_store=store))
        self.scope: dict[str, Any] = {"subprotocols": protos}
        self.query_params = query
        self.closed: int | None = None

    async def close(self, code: int = 1000) -> None:
        self.closed = code


async def test_ws_authorize() -> None:
    k = generate_api_key()
    h = hash_api_key(k)
    assert await ws_authorize(FakeWS(None, [], {}))  # type: ignore[arg-type]
    assert await ws_authorize(FakeWS(h, [f"apikey.{k}"], {}))  # type: ignore[arg-type]
    assert await ws_authorize(FakeWS(h, [], {"api_key": k}))  # type: ignore[arg-type]
    bad = FakeWS(h, ["apikey.wrong"], {})
    assert not await ws_authorize(bad)  # type: ignore[arg-type]
    assert bad.closed == 4401
    none = FakeWS(h, [], {})
    assert not await ws_authorize(none)  # type: ignore[arg-type]
    assert ws_subprotocol(FakeWS(h, ["x", "apikey.q"], {})) == "apikey.q"  # type: ignore[arg-type]


@pytest.mark.parametrize("key", ["a", "ü"])
def test_hash_unicode(key: str) -> None:
    assert verify_api_key(key, hash_api_key(key))
