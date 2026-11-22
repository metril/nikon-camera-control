"""The committed openapi.json and docs/API.md must match what the app generates."""

from __future__ import annotations

from scripts.gen_api import check


def test_generated_api_files_are_current() -> None:
    problems = check()
    assert not problems, "API spec/docs are stale; run `make api` and commit.\n" + "\n".join(
        problems
    )
