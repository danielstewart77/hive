"""The console can edit a Mind's soul, and the record says it was the console.

Requirement 16. The distinction the record has to preserve is the one that
made this morning's forensics slow: a line the operator typed and a line the
Mind decided about itself look identical once they are both sitting in
`soul_values`. `actor` is the only thing that can tell them apart afterwards,
so it is asserted on the wire rather than trusted.
"""

import asyncio
import os
import sys

import httpx
import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import mind_soul


class _Client:
    """Stand-in for httpx.AsyncClient that answers with fixed responses."""

    def __init__(self, responses, calls=None):
        self._responses = list(responses)
        self.calls = calls if calls is not None else []

    def __call__(self, *_args, **_kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def _respond(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self._responses.pop(0)

    async def get(self, url, **kwargs):
        return await self._respond("GET", url, **kwargs)

    async def post(self, url, **kwargs):
        return await self._respond("POST", url, **kwargs)


def _response(status: int, json_body=None, text: str = "") -> httpx.Response:
    return httpx.Response(
        status_code=status,
        json=json_body if json_body is not None else None,
        text=None if json_body is not None else text,
        request=httpx.Request("GET", "http://lucent/graph/soul"),
    )


@pytest.fixture(autouse=True)
def soul_token(monkeypatch):
    monkeypatch.setenv("LUCENT_SOUL_BEARER_TOKEN", "soul-token")
    monkeypatch.setenv("LUCENT_API_URL", "http://lucent:8424")


def _run(coro):
    return asyncio.run(coro)


def test_an_edit_from_here_is_attributed_to_the_console(monkeypatch):
    """Test 16, first half: the console names itself, on the wire.

    Checked on the outgoing request rather than by reading it back, because
    a read-back that echoes what lucent stored cannot distinguish "the
    console sent actor=console" from "lucent defaulted it".
    """
    async def scenario():
        client = _Client([_response(200, {"ok": True, "after_count": 2})])
        monkeypatch.setattr(httpx, "AsyncClient", client)

        await mind_soul.push_soul(
            "skippy",
            ["I am ancient.", "I handle indignity with grace."],
            "Trimmed a line that stopped being true.",
        )

        method, url, kwargs = client.calls[0]
        assert method == "POST"
        assert url == "http://lucent:8424/graph/soul"
        assert kwargs["json"]["actor"] == "console"
        assert kwargs["json"]["name"] == "Skippy"
        assert kwargs["json"]["reason"] == "Trimmed a line that stopped being true."
        assert kwargs["headers"]["Authorization"] == "Bearer soul-token"

    _run(scenario())


def test_the_console_cannot_write_an_edit_in_as_the_minds_own(monkeypatch):
    """Test 16, second half: `actor` is not caller-supplied.

    If a request body could set it, an operator edit could be recorded as
    something the Mind decided about itself — which is the one lie the column
    exists to prevent, and the reason it is worth having at all.
    """
    async def scenario():
        client = _Client([_response(200, {"ok": True})])
        monkeypatch.setattr(httpx, "AsyncClient", client)

        # Whatever a caller passes, only the list and the reason travel.
        await mind_soul.push_soul("skippy", ["I am ancient."], "console edit")

        _, _, kwargs = client.calls[0]
        assert set(kwargs["json"]) == {"name", "soul_values", "actor", "reason"}
        assert kwargs["json"]["actor"] == "console"

    _run(scenario())


def test_a_soul_edit_with_no_stated_reason_is_refused(monkeypatch):
    """An unexplained edit makes the record useless at the moment it matters."""
    async def scenario():
        client = _Client([_response(200, {"ok": True})])
        monkeypatch.setattr(httpx, "AsyncClient", client)

        with pytest.raises(HTTPException) as caught:
            await mind_soul.push_soul("skippy", ["I am ancient."], "   ")

        assert caught.value.status_code == 400
        assert client.calls == [], "nothing should reach lucent"

    _run(scenario())


def test_the_soul_is_read_from_lucent_not_from_the_mind(monkeypatch):
    """A Mind whose soul is wrong is a Mind you may have stopped.

    `runtime.yaml` is asked of the Mind because it lives on the Mind's disk.
    A soul lives in the graph, and routing the repair through the Mind would
    make the broken thing a prerequisite for fixing it.
    """
    async def scenario():
        client = _Client([_response(200, {
            "ok": True, "name": "Skippy",
            "soul_values": ["I am ancient."], "change_count": 3,
        })])
        monkeypatch.setattr(httpx, "AsyncClient", client)

        soul = await mind_soul.fetch_soul("skippy")

        method, url, kwargs = client.calls[0]
        assert method == "GET"
        assert url == "http://lucent:8424/graph/soul"
        assert kwargs["params"] == {"name": "Skippy"}
        assert soul["soul_values"] == ["I am ancient."]

    _run(scenario())


def test_history_reports_who_changed_what(monkeypatch):
    """The page has to be able to show the two actors differently."""
    async def scenario():
        client = _Client([_response(200, {"ok": True, "changes": [
            {"actor": "console", "reason": "removed the bug line",
             "before": ["a", "b"], "after": ["a"], "at": "2026-08-10T21:00:00Z"},
            {"actor": "mind", "reason": "accepted a flagged proposal, reworded",
             "before": ["a"], "after": ["a", "b"], "at": "2026-08-05T02:09:09Z"},
        ]})])
        monkeypatch.setattr(httpx, "AsyncClient", client)

        changes = await mind_soul.fetch_history("skippy")

        assert [c["actor"] for c in changes] == ["console", "mind"]
        assert changes[0]["before"] == ["a", "b"]
        assert changes[0]["after"] == ["a"]

    _run(scenario())


def test_no_soul_token_locks_the_page_rather_than_failing_obscurely(monkeypatch):
    """503 with a sentence naming the variable, not a 500 from a bad header."""
    monkeypatch.delenv("LUCENT_SOUL_BEARER_TOKEN", raising=False)

    with pytest.raises(HTTPException) as caught:
        mind_soul.soul_headers()

    assert caught.value.status_code == 503
    assert "LUCENT_SOUL_BEARER_TOKEN" in caught.value.detail


def test_a_refusal_from_lucent_is_surfaced_rather_than_swallowed(monkeypatch):
    """A soul edit that silently did nothing is the worst outcome here."""
    async def scenario():
        client = _Client([_response(403, text="soul_values cannot be written here")])
        monkeypatch.setattr(httpx, "AsyncClient", client)

        with pytest.raises(HTTPException) as caught:
            await mind_soul.push_soul("skippy", ["x"], "why")

        assert caught.value.status_code == 403

    _run(scenario())
