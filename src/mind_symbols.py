"""Resolving a function through the Mind that owns the disk it lives on.

Same shape as `mind_skills`, `mind_files` and `mind_runtime`, and for the
same reason: this console holds no checkout of anything, and a Mind on
another machine has no bind mount to offer. The Mind reads its own
filesystem and reports; the console renders and issues the actions.

Admin-guarded on the Mind, reads included — the reply is the contents of a
source file, on a port that answers across the LAN.
"""

from __future__ import annotations

import httpx
from fastapi import HTTPException

from mind_runtime import admin_headers

_TIMEOUT = 20.0


def _endpoint(gateway_url: str, suffix: str = "") -> str:
    url = (gateway_url or "").strip().rstrip("/")
    if not url:
        raise HTTPException(
            status_code=400, detail="This Mind has no gateway URL in the registry"
        )
    return f"{url}/symbols{suffix}"


def _detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text
    if isinstance(body, dict) and body.get("error"):
        return str(body["error"])
    return response.text


def _unwrap(response: httpx.Response) -> dict:
    # A 404 here means the Mind predates this API — Starlette answers 404 for
    # a path matching no route. A function that is merely absent comes back
    # 200 with `resolved` false, precisely so the two cannot be confused.
    if response.status_code == 404 and "no route" not in _detail(response).lower():
        raise HTTPException(status_code=404, detail=_detail(response))
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=_detail(response))
    body = response.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=502, detail="Mind returned an unexpected body")
    return body


async def _call(url: str, params: dict | None = None) -> dict:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(url, headers=admin_headers(), params=params)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail=f"Mind is unreachable: {exc}"
        ) from exc
    return _unwrap(response)


async def resolve(gateway_url: str, repo: str, path: str, name: str) -> dict:
    """One named function as it actually exists on that Mind's disk."""
    return await _call(
        _endpoint(gateway_url), {"repo": repo, "path": path, "name": name}
    )


async def roots(gateway_url: str) -> dict:
    """The checkouts that Mind will read for a design session."""
    return await _call(_endpoint(gateway_url, "/roots"))
