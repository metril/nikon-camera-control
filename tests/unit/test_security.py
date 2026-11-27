import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from backend.core.security import (
    LOCKED_HASH,
    ApiKeyStore,
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
        self.cookies: dict[str, str] = {}
        self.state = SimpleNamespace()
        self.closed: int | None = None
        self.accepted: str | None | bool = False

    async def accept(self, subprotocol: str | None = None) -> None:
        self.accepted = subprotocol

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.closed = code


async def test_ws_authorize() -> None:
    k = generate_api_key()
    h = hash_api_key(k)
    assert await ws_authorize(FakeWS(None, [], {}))  # type: ignore[arg-type]
    assert await ws_authorize(FakeWS(h, [f"apikey.{k}"], {}))  # type: ignore[arg-type]
    q = FakeWS(h, [], {"api_key": k})  # query-string key is no longer honoured
    assert not await ws_authorize(q)  # type: ignore[arg-type]
    bad = FakeWS(h, ["apikey.wrong"], {})
    assert not await ws_authorize(bad)  # type: ignore[arg-type]
    assert bad.closed == 4401
    assert bad.accepted == "apikey.wrong"  # accepted first so the client sees 4401, not 403
    none = FakeWS(h, [], {})
    assert not await ws_authorize(none)  # type: ignore[arg-type]
    assert ws_subprotocol(FakeWS(h, ["x", "apikey.q"], {})) == "apikey.q"  # type: ignore[arg-type]


@pytest.mark.parametrize("key", ["a", "ü"])
def test_hash_unicode(key: str) -> None:
    assert verify_api_key(key, hash_api_key(key))


def test_api_key_store_roundtrip_and_missing(tmp_path: Path) -> None:
    ks = ApiKeyStore(tmp_path / "api_key.json")
    assert ks.load() is None
    h = hash_api_key("k")
    ks.save(h)
    data = json.loads((tmp_path / "api_key.json").read_text())
    assert data["sha256"] == h and "created" in data
    assert ks.load() == h
    ks.clear()
    ks.clear()
    assert ks.load() is None


@pytest.mark.parametrize("content", ["{not json", "[]", '{"sha256": 5}', '{"sha256": "abc"}', ""])
def test_api_key_store_invalid_fails_closed(tmp_path: Path, content: str) -> None:
    p = tmp_path / "api_key.json"
    p.write_text(content)
    h = ApiKeyStore(p).load()
    assert h == LOCKED_HASH
    assert not verify_api_key("anything", h)
    assert not verify_api_key(None, h)
