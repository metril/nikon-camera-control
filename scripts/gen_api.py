"""Generate ``openapi.json`` and ``docs/API.md``: ``python -m scripts.gen_api [--check]``."""

from __future__ import annotations

import ast
import difflib
import inspect
import json
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from starlette.routing import WebSocketRoute

ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = ROOT / "openapi.json"
DOCS_PATH = ROOT / "docs" / "API.md"
METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
SCAN_DIRS = ("backend/core", "backend/services", "backend/api")
SCAN_SKIP = ("backend/api/routes", "backend/api/websocket")

Json = dict[str, Any]


def build_app(tmp: Path) -> Any:
    from backend.app import create_app

    return create_app(
        data_dir=tmp / "data", target_dir=tmp / "output", auto_connect=False, frontend_dist=None
    )


# ---------------------------------------------------------------- schema helpers
def _ref_name(ref: str) -> str:
    return ref.rsplit("/", 1)[-1]


def type_str(s: Json) -> str:
    if not s:
        return "any"
    if "$ref" in s:
        return _ref_name(s["$ref"])
    for key in ("anyOf", "oneOf"):
        if key in s:
            return " \\| ".join(type_str(x) for x in s[key])
    if "allOf" in s:
        return " & ".join(type_str(x) for x in s["allOf"])
    if "const" in s:
        return f"`{json.dumps(s['const'])}`"
    if "enum" in s:
        return "enum(" + ", ".join(json.dumps(v) for v in s["enum"]) + ")"
    t = s.get("type", "any")
    if t == "array":
        return f"list[{type_str(s.get('items', {}))}]"
    if t == "object" and isinstance(s.get("additionalProperties"), dict):
        return f"map[{type_str(s['additionalProperties'])}]"
    if isinstance(t, list):
        t = " \\| ".join(t)
    return f"{t}({s['format']})" if "format" in s else str(t)


_CONSTRAINTS = (
    ("minimum", ">="),
    ("maximum", "<="),
    ("exclusiveMinimum", ">"),
    ("exclusiveMaximum", "<"),
    ("minLength", "minLength="),
    ("maxLength", "maxLength="),
    ("minItems", "minItems="),
    ("maxItems", "maxItems="),
    ("multipleOf", "multipleOf="),
    ("pattern", "pattern="),
)


def constraints(s: Json) -> str:
    parts = [f"{label}{s[k]}" for k, label in _CONSTRAINTS if k in s]
    if "anyOf" in s:  # constraints on the non-null branch
        for b in s["anyOf"]:
            if b.get("type") != "null":
                parts += [f"{label}{b[k]}" for k, label in _CONSTRAINTS if k in b]
    return ", ".join(f"`{p}`" for p in parts)


def default_str(s: Json) -> str:
    return f"`{json.dumps(s['default'], sort_keys=True)}`" if "default" in s else ""


def cell(text: Any) -> str:
    return " ".join(str(text or "").split()).replace("|", "\\|")


def table(header: list[str], rows: list[list[Any]]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return [*out, ""]


def resolve(schema: Json, comps: Json) -> Json:
    if "$ref" in schema:
        found: Json = comps.get(_ref_name(schema["$ref"]), {})
        return found
    return schema


def fields_table(schema: Json, comps: Json) -> list[str]:
    s = resolve(schema, comps)
    props: Json = s.get("properties", {})
    if not props:
        return [f"Body: `{type_str(schema)}`", ""]
    req = set(s.get("required", []))
    rows = [
        [
            f"`{n}`",
            type_str(p),
            "yes" if n in req else "no",
            default_str(p),
            constraints(p),
            cell(p.get("description")),
        ]
        for n, p in props.items()
    ]
    return table(["Field", "Type", "Required", "Default", "Constraints", "Description"], rows)


# ---------------------------------------------------------------- introspection
def error_table() -> list[list[str]]:
    from backend.core import errors

    def subs(c: type[errors.AppError]) -> list[type[errors.AppError]]:
        out: list[type[errors.AppError]] = []
        for k in c.__subclasses__():
            out += [k, *subs(k)]
        return out

    by_code: dict[str, list[type[errors.AppError]]] = defaultdict(list)
    all_errors: list[type[errors.AppError]] = [errors.AppError, *subs(errors.AppError)]
    for c in all_errors:
        by_code[str(c.code)].append(c)
    rows = []
    for code in errors.ErrorCode:
        classes = by_code.get(str(code), [])
        if classes:
            c = classes[0]
            rows.append(
                [
                    f"`{code}`",
                    str(c.http_status),
                    f"`{c.__name__}`",
                    cell(c.default_message),
                ]
            )
        else:
            rows.append(
                [f"`{code}`", "by handler", "-", "Produced by the framework error handlers"]
            )
    return rows


def ws_routes(app: Any) -> list[tuple[str, str]]:
    out = []
    for r in app.routes:
        if isinstance(r, WebSocketRoute):
            doc = inspect.getdoc(r.endpoint) or ""
            out.append((r.path, doc))
    return sorted(out)


def scan_event_payloads() -> dict[str, set[str]] | None:
    """Static scan of publish call sites: EventType name -> payload keys."""
    trees: list[ast.AST] = []
    for d in SCAN_DIRS:
        for p in sorted((ROOT / d).rglob("*.py")):
            rel = p.relative_to(ROOT).as_posix()
            if not rel.startswith(SCAN_SKIP):
                trees.append(ast.parse(p.read_text()))

    def callee(c: ast.Call) -> str | None:
        f = c.func
        return f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else None

    def etype(n: ast.AST) -> str | None:
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
            return n.attr if n.value.id == "EventType" else None
        return None

    def dict_keys(n: ast.AST | None) -> set[str]:
        if not isinstance(n, ast.Dict):
            return {"(dynamic)"} if n is not None else set()
        return {k.value for k in n.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}

    wrappers: dict[str, set[str]] = {}
    found: dict[str, set[str]] = defaultdict(set)
    for _ in range(4):  # fixpoint over wrapper chains
        for tree in trees:
            for fn in ast.walk(tree):
                if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                params = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
                for c in ast.walk(fn):
                    if not isinstance(c, ast.Call):
                        continue
                    name = callee(c)
                    if name == "publish" and c.args:
                        keys = dict_keys(c.args[1] if len(c.args) > 1 else None)
                        args = [c.args[0]]
                    elif name in wrappers:
                        keys = wrappers[name] | {k.arg for k in c.keywords if k.arg}
                        args = [*c.args, *(k.value for k in c.keywords)]
                    else:
                        continue
                    for a in args:
                        if (t := etype(a)) is not None:
                            found[t] |= keys
                        elif isinstance(a, ast.Name) and a.id in params:
                            wrappers[fn.name] = keys
    return dict(found) if found else None


# ---------------------------------------------------------------- rendering
def render_docs(spec: Json, app: Any) -> str:
    from backend.api.schemas.common import ErrorBody, EventType
    from backend.core.config_store import AppConfig

    comps: Json = spec.get("components", {}).get("schemas", {})
    L: list[str] = []
    L += [
        f"# {spec['info']['title']} API {spec['info']['version']}",
        "",
        "> Generated file. Do not edit. Regenerate with `make api` "
        "(`.venv/bin/python -m scripts.gen_api`); CI fails if it is stale.",
        "> Source of truth: route declarations and pydantic schemas. Machine-readable "
        "spec: `openapi.json`.",
        "",
        "## Authentication",
        "",
        "When an API key is configured, send it as the `X-API-Key` request header. WebSocket "
        "clients cannot set headers, so they offer the subprotocol `apikey.<key>`. A rejected "
        "WebSocket is accepted and then closed with code 4401; an open socket is closed with 4401 "
        "when the key changes. Cross-origin protection: POST/PUT/PATCH/DELETE and WebSocket "
        "requests that carry an `Origin` header must be same-origin (same host:port as `Host`) "
        "or listed in `cors_origins`; otherwise HTTP gets 403 `FORBIDDEN_ORIGIN` and a WebSocket "
        "is closed with 4403 before it is accepted. Requests without `Origin` are unaffected.",
        "",
        "## Error envelope",
        "",
        "Every non-2xx response has the body "
        '`{"error": {"code", "message", "details", "request_id"}}`. '
        "`X-Request-ID` is echoed in the response header.",
        "",
    ]
    L += fields_table(ErrorBody.model_json_schema(), {})
    L += table(["Code", "HTTP status", "Exception", "Default message"], error_table())

    tags: dict[str, list[tuple[str, str, Json]]] = defaultdict(list)
    for path, item in spec["paths"].items():
        for m in METHODS:
            if m in item:
                op = item[m]
                tags[(op.get("tags") or ["untagged"])[0]].append((m, path, op))
    L += ["## Endpoints", ""]
    for tag in sorted(tags):
        L += [f"### {tag}", ""]
        L += table(
            ["Method", "Path", "operation_id", "Summary"],
            [
                [m.upper(), f"`{p}`", f"`{o.get('operationId', '')}`", cell(o.get("summary"))]
                for m, p, o in tags[tag]
            ],
        )
    for tag in sorted(tags):
        L += [f"## {tag}", ""]
        for m, path, op in tags[tag]:
            L += [f"### `{m.upper()} {path}`", ""]
            L += [f"operation_id: `{op.get('operationId', '')}`", ""]
            if op.get("description"):
                L += [op["description"].strip(), ""]
            params = op.get("parameters", [])
            if params:
                L += ["**Parameters**", ""]
                L += table(
                    ["Name", "In", "Type", "Required", "Default", "Constraints", "Description"],
                    [
                        [
                            f"`{p['name']}`",
                            p["in"],
                            type_str(p.get("schema", {})),
                            "yes" if p.get("required") else "no",
                            default_str(p.get("schema", {})),
                            constraints(p.get("schema", {})),
                            cell(p.get("description")),
                        ]
                        for p in params
                    ],
                )
            body = op.get("requestBody")
            if body:
                for ctype, media in body.get("content", {}).items():
                    sch = media.get("schema", {})
                    L += [f"**Request body** (`{ctype}`): `{type_str(sch)}`", ""]
                    L += fields_table(sch, comps)
            L += ["**Responses**", ""]
            rrows = []
            for code, resp in op.get("responses", {}).items():
                content = resp.get("content", {})
                ct = ", ".join(
                    f"`{k}`: `{type_str(v.get('schema', {}))}`" for k, v in content.items()
                )
                rrows.append([code, cell(resp.get("description")), ct])
            L += table(["Status", "Description", "Body"], rrows)

    L += ["## WebSocket endpoints", "", "Not part of OpenAPI. Paths are relative to `/api/v1`.", ""]
    for path, doc in ws_routes(app):
        L += [f"### `WS {path}`", "", doc or "(no description)", ""]

    L += [
        "## Events",
        "",
        'Events are delivered on `/ws/events` as `{"type": <event type>, "ts": <ISO-8601 UTC>, '
        '"data": {...}}`.',
        "",
    ]
    payloads = scan_event_payloads()
    if payloads is None:
        L += ["Payload keys could not be determined by the static scan.", ""]
    else:
        L += [
            "Payload keys are found by a static scan of `publish(...)` call sites; "
            "`(dynamic)` means the payload is not a dict literal.",
            "",
        ]
    rows = []
    for member in EventType:
        keys = (payloads or {}).get(member.name)
        empty = "(empty)" if member.name in (payloads or {}) else "(not found)"
        rows.append(
            [
                f"`{member.value}`",
                ", ".join(f"`{k}`" for k in sorted(keys)) if keys else empty,
            ]
        )
    L += table(["Type", "Payload keys"], rows)

    L += ["## Configuration reference", ""]
    L += ["Edited through the web UI / `/config` endpoints. Never through the environment.", ""]
    cfg = AppConfig.model_json_schema()
    cdefs: Json = cfg.get("$defs", {})
    crow: list[list[Any]] = []

    def add(section: str, name: str, p: Json) -> None:
        crow.append(
            [
                section or "(root)",
                f"`{name}`",
                type_str(p),
                default_str(p),
                constraints(p),
                cell(p.get("description")),
            ]
        )

    for name, p in cfg["properties"].items():
        ref = p.get("$ref")
        sub = cdefs.get(_ref_name(ref), {}) if ref else {}
        if sub.get("properties"):
            for fname, fp in sub["properties"].items():
                add(name, fname, fp)
        else:
            add("", name, p)
    L += table(["Section", "Field", "Type", "Default", "Constraints", "Description"], crow)
    return "\n".join(L).rstrip() + "\n"


def generate() -> tuple[str, str]:
    with tempfile.TemporaryDirectory(prefix="gen_api_") as tmp:
        app = build_app(Path(tmp))
        spec = app.openapi()
        return json.dumps(spec, indent=2, sort_keys=True) + "\n", render_docs(spec, app)


def check(spec_path: Path = SPEC_PATH, docs_path: Path = DOCS_PATH) -> list[str]:
    """Return unified-diff lines for stale files (empty = up to date)."""
    spec_text, docs_text = generate()
    out: list[str] = []
    for path, new in ((spec_path, spec_text), (docs_path, docs_text)):
        old = path.read_text() if path.exists() else ""
        if old != new:
            diff = list(
                difflib.unified_diff(
                    old.splitlines(), new.splitlines(), f"{path.name} (disk)", "generated", n=0
                )
            )
            out += [f"{path.name} is stale ({len(diff)} diff lines):", *diff[:20]]
    return out


def main(argv: list[str]) -> int:
    if "--check" in argv:
        problems = check()
        if problems:
            print("\n".join(problems))
            print("API spec/docs are stale. Run `make api`.")
            return 1
        return 0
    spec_text, docs_text = generate()
    DOCS_PATH.parent.mkdir(exist_ok=True)
    SPEC_PATH.write_text(spec_text)
    DOCS_PATH.write_text(docs_text)
    print(f"wrote {SPEC_PATH.name}, {DOCS_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
