"""The OpenAPI document is the source of the generated client: keep it clean."""

from __future__ import annotations

import re
from typing import Any

import pytest
from fastapi import FastAPI

HTTP_METHODS = ("get", "put", "post", "delete", "patch")
OPEN_PATHS = {"/api/v1/health"}
SNAKE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")


@pytest.fixture
def spec(app: FastAPI) -> dict[str, Any]:
    return app.openapi()


def _ops(spec: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (path, m, op) for path, item in spec["paths"].items() for m, op in item.items()
        if m in HTTP_METHODS
    ]  # fmt: skip


def test_operation_ids_unique_snake_case(spec: dict[str, Any]) -> None:
    ids = [op.get("operationId") for _, _, op in _ops(spec)]
    assert all(ids), "operation without operationId"
    assert len(ids) == len(set(ids)), sorted(i for i in ids if ids.count(i) > 1)
    assert [i for i in ids if not SNAKE.match(i)] == []


def test_schema_names_not_module_qualified(spec: dict[str, Any]) -> None:
    assert [n for n in spec["components"]["schemas"] if "__" in n] == []


def test_json_2xx_responses_have_named_schemas(spec: dict[str, Any]) -> None:
    bad = []
    for path, m, op in _ops(spec):
        for code, resp in op["responses"].items():
            if not code.startswith("2"):
                continue
            js = resp.get("content", {}).get("application/json")
            if js is None:
                continue
            s = js.get("schema", {})
            named = "$ref" in s or (s.get("type") == "array" and "$ref" in s.get("items", {}))
            if not named:
                bad.append(f"{m.upper()} {path} {code}: {s}")
    assert bad == []


def test_routes_declare_api_key_security(spec: dict[str, Any]) -> None:
    bad = [
        f"{m.upper()} {p}"
        for p, m, op in _ops(spec)
        if p not in OPEN_PATHS and not any("APIKeyHeader" in s for s in op.get("security", []))
    ]
    assert bad == []


def test_routes_document_error_envelope(spec: dict[str, Any]) -> None:
    bad = []
    for p, m, op in _ops(spec):
        refs = [
            r.get("content", {}).get("application/json", {}).get("schema", {}).get("$ref", "")
            for code, r in op["responses"].items()
            if not code.startswith("2")
        ]
        if p not in OPEN_PATHS and not any(r.endswith("/ErrorResponse") for r in refs):
            bad.append(f"{m.upper()} {p}")
    assert bad == []


# TODO: GET /api/v1/liveview/snapshot (liveview agent) still has an empty binary schema.
KNOWN_UNTYPED_BINARY = {"/api/v1/liveview/snapshot"}


def test_binary_200_responses_declare_a_binary_schema(spec: dict[str, Any]) -> None:
    bad = []
    for path, m, op in _ops(spec):
        content = op["responses"].get("200", {}).get("content", {})
        for mime, body in content.items():
            if mime == "application/json" or path in KNOWN_UNTYPED_BINARY:
                continue
            if body.get("schema") != {"type": "string", "format": "binary"}:
                bad.append(f"{m.upper()} {path} {mime}: {body}")
    assert bad == []


def test_camera_files_tag_is_kebab_case(spec: dict[str, Any]) -> None:
    tags = {t for _, _, op in _ops(spec) for t in op.get("tags", [])}
    assert "camera-files" in tags and "camera files" not in tags
