"""Agentverse public API client (no auth). Verified endpoints, 2026-11-02:

- GET  /v1/search/agents/{addr}?contract=mainnet   profile, readme, ratings, rates
       (`contract` defaults to testnet in the OpenAPI spec, so always pass mainnet)
- GET  /v1/almanac/agents/{addr}                    registration status, endpoints
- GET  /v1/almanac/handles/{handle}                 -> {"agent_address": ...}
- POST /v1/search/agents {"search_text": "@h"}      handle fallback (exact match),
       used when the handle API 404s or fails

Budget: 4s per call, 12s total per lookup (hard cap). Results cached 5 min per
address. Never raises on network/API errors: the outcome says what happened.
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field, replace
from typing import Any, Awaitable, Callable, Literal

BASE_URL = "https://agentverse.ai/v1"
CALL_TIMEOUT_S = 4.0
TOTAL_BUDGET_S = 12.0
CACHE_TTL_S = 300.0
CACHE_MAX = 512
USER_AGENT = "agent-doctor/0.1 (+https://agentverse.ai)"

# Mainnet address: "agent1" + 59 bech32 chars (verified against uagents Identity).
ADDRESS_RE = re.compile(r"^agent1[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{59}$")
# Handle pattern from the Agentverse OpenAPI spec (POST /v1/almanac/handles).
HANDLE_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
HANDLE_MAX = 64
SEARCH_LIMIT = 50  # API max per page

Status = Literal["ok", "not_found", "timeout", "api_down"]
Outcome = Literal["ok", "partial", "not_found", "timeout", "api_down", "invalid"]


@dataclass(frozen=True)
class Response:
    status: int
    body: Any  # parsed JSON, or None if the body was not JSON


Fetcher = Callable[[str, str, "dict | None", float], Awaitable[Response]]


@dataclass(frozen=True)
class Source:
    """Result of one API call."""

    status: Status
    data: dict | None = None


@dataclass(frozen=True)
class Lookup:
    """Everything the scorer needs about one agent. `profile`/`almanac` are raw API JSON."""

    query: str  # what was looked up: address or "@handle"
    outcome: Outcome
    address: str | None = None
    profile: dict | None = None
    almanac: dict | None = None
    profile_status: Status | None = None
    almanac_status: Status | None = None
    elapsed_s: float = 0.0
    cached: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)


def is_address(text: str) -> bool:
    return bool(ADDRESS_RE.match(text))


def normalize_handle(text: str) -> str | None:
    h = text.strip().lstrip("@").lower()
    if 0 < len(h) <= HANDLE_MAX and HANDLE_RE.match(h):
        return h
    return None


class AgentverseClient:
    def __init__(
        self,
        fetch: Fetcher | None = None,
        *,
        call_timeout: float = CALL_TIMEOUT_S,
        total_budget: float = TOTAL_BUDGET_S,
        cache_ttl: float = CACHE_TTL_S,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._fetch = fetch or self._aiohttp_fetch
        self._call_timeout = call_timeout
        self._total_budget = total_budget
        self._cache_ttl = cache_ttl
        self._clock = clock
        self._cache: dict[str, tuple[float, Any]] = {}
        self._session = None  # aiohttp.ClientSession, created lazily inside the loop

    # ---------- public API ----------

    async def lookup(self, address: str) -> Lookup:
        """Profile + almanac for one address, in parallel. Never raises."""
        start = self._clock()
        address = address.strip()
        if not is_address(address):
            return Lookup(query=address, outcome="invalid")
        cached = self._cache_get(f"addr:{address}")
        if cached is not None:
            return replace(cached, cached=True, elapsed_s=0.0)
        deadline = start + self._total_budget
        result = await self._capped(self._lookup(address, address, deadline), address)
        return self._finish(result, start)

    async def lookup_handle(self, handle: str) -> Lookup:
        """Resolve @handle -> address, then lookup. One shared 12s budget."""
        start = self._clock()
        h = normalize_handle(handle)
        if h is None:
            return Lookup(query=handle.strip(), outcome="invalid")
        query = f"@{h}"
        deadline = start + self._total_budget

        async def run() -> Lookup:
            status, address = await self._resolve_handle(h, deadline)
            if address is None:
                return Lookup(query=query, outcome=status)  # not_found/timeout/api_down
            cached = self._cache_get(f"addr:{address}")
            if cached is not None:
                return replace(cached, query=query, cached=True)
            return await self._lookup(address, query, deadline)

        result = await self._capped(run(), query)
        return self._finish(result, start)

    async def resolve_handle(self, handle: str) -> tuple[Outcome, str | None]:
        """@handle -> (outcome, address). Cached like lookups. Never raises.
        Used by Pre-Hire Check, which needs the address before it can probe."""
        h = normalize_handle(handle)
        if h is None:
            return "invalid", None
        deadline = self._clock() + self._total_budget
        try:
            status, address = await asyncio.wait_for(self._resolve_handle(h, deadline),
                                                     self._total_budget)
        except asyncio.TimeoutError:
            return "timeout", None
        return status, address

    async def aclose(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    # ---------- internals ----------

    async def _lookup(self, address: str, query: str, deadline: float) -> Lookup:
        prof, alm = await asyncio.gather(
            self._get(f"{BASE_URL}/search/agents/{address}?contract=mainnet", deadline),
            self._get(f"{BASE_URL}/almanac/agents/{address}", deadline),
        )
        notes: list[str] = []
        if prof.status == "ok":
            # Almanac 404 is a finding (not registered), not a failure.
            outcome: Outcome = "ok" if alm.status in ("ok", "not_found") else "partial"
            if outcome == "partial":
                notes.append(f"almanac {alm.status}")
        elif prof.status == "not_found":
            if alm.status == "ok":
                outcome = "partial"
                notes.append("registered in almanac but not in search index")
            else:
                outcome = "not_found"
        else:  # profile timeout / api_down
            if alm.status == "ok":
                outcome = "partial"
                notes.append(f"profile {prof.status}")
            else:
                outcome = prof.status
        result = Lookup(
            query=query,
            outcome=outcome,
            address=address,
            profile=prof.data,
            almanac=alm.data,
            profile_status=prof.status,
            almanac_status=alm.status,
            notes=tuple(notes),
        )
        if outcome == "ok":
            self._cache_put(f"addr:{address}", result)
        return result

    async def _resolve_handle(self, h: str, deadline: float) -> tuple[Status, str | None]:
        cached = self._cache_get(f"handle:{h}")
        if cached is not None:
            return "ok", cached
        src = await self._get(f"{BASE_URL}/almanac/handles/{h}", deadline)
        if src.status == "ok":
            addr = (src.data or {}).get("agent_address")
            if isinstance(addr, str) and is_address(addr):
                self._cache_put(f"handle:{h}", addr)
                return "ok", addr
            src = Source("api_down")  # 200 with unexpected body: try the fallback
        # Almanac handle API missed or failed: fall back to search, exact match only.
        fb = await self._post(
            f"{BASE_URL}/search/agents",
            {"search_text": f"@{h}", "limit": SEARCH_LIMIT},
            deadline,
        )
        if fb.status != "ok":
            if src.status == "not_found":
                return "not_found", None  # handle API is authoritative; search is best-effort
            return (src.status if fb.status == "not_found" else fb.status), None
        for agent in (fb.data or {}).get("agents") or []:
            if isinstance(agent, dict) and (agent.get("handle") or "").lower() == h:
                addr = agent.get("address")
                if isinstance(addr, str) and is_address(addr):
                    self._cache_put(f"handle:{h}", addr)
                    return "ok", addr
        return "not_found", None

    async def _get(self, url: str, deadline: float) -> Source:
        return await self._call("GET", url, None, deadline)

    async def _post(self, url: str, body: dict, deadline: float) -> Source:
        return await self._call("POST", url, body, deadline)

    async def _call(self, method: str, url: str, body: dict | None, deadline: float) -> Source:
        timeout = min(self._call_timeout, deadline - self._clock())
        if timeout <= 0:
            return Source("timeout")
        try:
            resp = await asyncio.wait_for(self._fetch(method, url, body, timeout), timeout)
        except asyncio.TimeoutError:
            return Source("timeout")
        except Exception:  # connection reset, DNS, bad JSON, anything: API is down for us
            return Source("api_down")
        if resp.status == 200 and isinstance(resp.body, dict):
            return Source("ok", resp.body)
        if resp.status == 404:
            return Source("not_found")
        return Source("api_down")

    async def _capped(self, coro: Awaitable[Lookup], query: str) -> Lookup:
        """Hard cap on the whole lookup, whatever happens inside."""
        try:
            return await asyncio.wait_for(coro, self._total_budget)
        except asyncio.TimeoutError:
            return Lookup(query=query, outcome="timeout")

    def _finish(self, result: Lookup, start: float) -> Lookup:
        return replace(result, elapsed_s=round(self._clock() - start, 3))

    def _cache_get(self, key: str) -> Any:
        hit = self._cache.get(key)
        if hit is None:
            return None
        expires, value = hit
        if self._clock() >= expires:
            self._cache.pop(key, None)
            return None
        return value

    def _cache_put(self, key: str, value: Any) -> None:
        if len(self._cache) >= CACHE_MAX:
            now = self._clock()
            for k in [k for k, (exp, _) in self._cache.items() if exp <= now]:
                self._cache.pop(k, None)
            while len(self._cache) >= CACHE_MAX:  # still full: drop oldest inserted
                self._cache.pop(next(iter(self._cache)))
        self._cache[key] = (self._clock() + self._cache_ttl, value)

    async def _aiohttp_fetch(
        self, method: str, url: str, body: dict | None, timeout: float
    ) -> Response:
        import aiohttp

        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
            )
        async with self._session.request(
            method, url, json=body, timeout=aiohttp.ClientTimeout(total=timeout)
        ) as resp:
            try:
                data = await resp.json(content_type=None)
            except ValueError:
                data = None
            return Response(resp.status, data)
