import asyncio
import json
import time
from pathlib import Path

import pytest

from agent import agentverse as av
from agent.agentverse import AgentverseClient, Response

ADDR = "agent1qfvydlgcxrvga2kqjxhj3hpngegtysm2c7uk48ywdue0kgvtc2f5cwhyffv"
FIXTURES = Path(__file__).parent / "fixtures"


class FakeAPI:
    """Routes (method, url-substring) -> handler. Records every call."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    async def __call__(self, method, url, body, timeout):
        self.calls.append((method, url, body))
        for (m, frag), handler in self.routes.items():
            if m == method and frag in url:
                return await handler() if asyncio.iscoroutinefunction(handler) else handler()
        raise AssertionError(f"unrouted {method} {url}")


def ok(body):
    return lambda: Response(200, body)


def status(code):
    return lambda: Response(code, {"detail": "x"})


async def hang():
    await asyncio.sleep(3600)


def boom():
    raise ConnectionResetError("reset")


PROFILE = "/search/agents/"
ALMANAC = "/almanac/agents/"
HANDLES = "/almanac/handles/"
SEARCH = ("POST", "/search/agents")


def run(coro):
    return asyncio.run(coro)


def client(routes, **kw):
    api = FakeAPI(routes)
    return AgentverseClient(api, **kw), api


# ---------- address lookup ----------


def test_ok_uses_mainnet_contract_and_both_sources():
    c, api = client({("GET", PROFILE): ok({"status": "active"}), ("GET", ALMANAC): ok({"status": "active"})})
    r = run(c.lookup(ADDR))
    assert r.outcome == "ok"
    assert r.profile == {"status": "active"} and r.almanac == {"status": "active"}
    urls = [u for _, u, _ in api.calls]
    assert f"{av.BASE_URL}/search/agents/{ADDR}?contract=mainnet" in urls
    assert f"{av.BASE_URL}/almanac/agents/{ADDR}" in urls


def test_calls_run_in_parallel():
    async def slow_ok():
        await asyncio.sleep(0.3)
        return Response(200, {})

    c, _ = client({("GET", PROFILE): slow_ok, ("GET", ALMANAC): slow_ok})
    t = time.monotonic()
    run(c.lookup(ADDR))
    assert time.monotonic() - t < 0.5


def test_almanac_404_is_a_finding_not_a_failure():
    c, _ = client({("GET", PROFILE): ok({"a": 1}), ("GET", ALMANAC): status(404)})
    r = run(c.lookup(ADDR))
    assert r.outcome == "ok" and r.almanac_status == "not_found" and r.almanac is None


def test_almanac_timeout_gives_partial():
    c, _ = client({("GET", PROFILE): ok({"a": 1}), ("GET", ALMANAC): hang}, call_timeout=0.1)
    r = run(c.lookup(ADDR))
    assert r.outcome == "partial" and r.almanac_status == "timeout" and r.profile == {"a": 1}


def test_profile_down_almanac_ok_gives_partial():
    c, _ = client({("GET", PROFILE): status(500), ("GET", ALMANAC): ok({"status": "active"})})
    r = run(c.lookup(ADDR))
    assert r.outcome == "partial" and r.profile_status == "api_down"


def test_profile_404_almanac_ok_gives_partial():
    c, _ = client({("GET", PROFILE): status(404), ("GET", ALMANAC): ok({"status": "active"})})
    assert run(c.lookup(ADDR)).outcome == "partial"


def test_both_404_is_not_found():
    c, _ = client({("GET", PROFILE): status(404), ("GET", ALMANAC): status(404)})
    assert run(c.lookup(ADDR)).outcome == "not_found"


@pytest.mark.parametrize("handler", [status(500), status(429), boom, lambda: Response(200, None)])
def test_api_errors_are_api_down_never_raise(handler):
    c, _ = client({("GET", PROFILE): handler, ("GET", ALMANAC): handler})
    assert run(c.lookup(ADDR)).outcome == "api_down"


def test_both_hang_times_out_per_call():
    c, _ = client({("GET", PROFILE): hang, ("GET", ALMANAC): hang}, call_timeout=0.1)
    t = time.monotonic()
    r = run(c.lookup(ADDR))
    assert r.outcome == "timeout" and time.monotonic() - t < 0.4


@pytest.mark.parametrize("bad", ["", "agent1xyz", "agent1q/../../admin", ADDR.upper(), ADDR + "q", " "])
def test_invalid_address_makes_no_calls(bad):
    c, api = client({})
    assert run(c.lookup(bad)).outcome == "invalid"
    assert api.calls == []


# ---------- cache ----------


def test_ok_result_is_cached_until_ttl():
    now = [1000.0]
    c, api = client(
        {("GET", PROFILE): ok({"a": 1}), ("GET", ALMANAC): ok({})}, clock=lambda: now[0]
    )
    run(c.lookup(ADDR))
    r = run(c.lookup(ADDR))
    assert r.cached and len(api.calls) == 2
    now[0] += av.CACHE_TTL_S + 1
    r = run(c.lookup(ADDR))
    assert not r.cached and len(api.calls) == 4


def test_partial_and_errors_are_not_cached():
    c, api = client({("GET", PROFILE): ok({"a": 1}), ("GET", ALMANAC): status(500)})
    run(c.lookup(ADDR))
    run(c.lookup(ADDR))
    assert len(api.calls) == 4


# ---------- handles ----------


def test_handle_resolves_then_looks_up():
    c, api = client({
        ("GET", HANDLES): ok({"agent_address": ADDR}),
        ("GET", PROFILE): ok({"handle": "weather"}),
        ("GET", ALMANAC): ok({}),
    })
    r = run(c.lookup_handle("@Weather"))
    assert r.outcome == "ok" and r.address == ADDR and r.query == "@weather"
    assert api.calls[0][1] == f"{av.BASE_URL}/almanac/handles/weather"


def test_handle_404_and_no_search_match_is_not_found():
    c, api = client({("GET", HANDLES): status(404), SEARCH: ok({"agents": []})})
    assert run(c.lookup_handle("nope")).outcome == "not_found"
    assert len(api.calls) == 2


def test_handle_404_falls_back_to_search():
    c, _ = client({
        ("GET", HANDLES): status(404),
        SEARCH: ok({"agents": [{"handle": "weather", "address": ADDR}]}),
        ("GET", PROFILE): ok({}),
        ("GET", ALMANAC): ok({}),
    })
    assert run(c.lookup_handle("weather")).address == ADDR


def test_handle_fallback_search_404_after_handle_404_is_not_found():
    c, _ = client({("GET", HANDLES): status(404), SEARCH: status(404)})
    assert run(c.lookup_handle("weather")).outcome == "not_found"


def test_handle_api_down_falls_back_to_exact_search_match():
    c, api = client({
        ("GET", HANDLES): status(503),
        SEARCH: ok({"agents": [
            {"handle": "weather-pro", "address": "agent1" + "q" * 59},
            {"handle": "weather", "address": ADDR},
        ]}),
        ("GET", PROFILE): ok({}),
        ("GET", ALMANAC): ok({}),
    })
    r = run(c.lookup_handle("weather"))
    assert r.outcome == "ok" and r.address == ADDR
    assert any(m == "POST" and b == {"search_text": "@weather", "limit": av.SEARCH_LIMIT} for m, _, b in api.calls)


def test_handle_fallback_without_exact_match_is_not_found():
    c, _ = client({
        ("GET", HANDLES): status(503),
        SEARCH: ok({"agents": [{"handle": "weather-pro", "address": ADDR}]}),
    })
    assert run(c.lookup_handle("weather")).outcome == "not_found"


def test_handle_and_fallback_both_down_is_api_down():
    c, _ = client({("GET", HANDLES): status(503), SEARCH: status(503)})
    assert run(c.lookup_handle("weather")).outcome == "api_down"


@pytest.mark.parametrize("bad", ["", "@", "bad handle", "UPPER_case", "-lead", "a--b", "x" * 65, "../x"])
def test_invalid_handle_makes_no_calls(bad):
    c, api = client({})
    assert run(c.lookup_handle(bad)).outcome == "invalid"
    assert api.calls == []


# ---------- budget ----------


def test_default_budget_constants():
    assert av.CALL_TIMEOUT_S == 4.0 and av.TOTAL_BUDGET_S == 12.0 and av.CACHE_TTL_S == 300.0


def test_worst_case_handle_lookup_stays_within_total_budget():
    # Everything hangs: resolve (call cap) + fallback (call cap) + lookup (rest of budget).
    c, _ = client(
        {("GET", HANDLES): hang, SEARCH: hang, ("GET", PROFILE): hang, ("GET", ALMANAC): hang},
        call_timeout=0.2,
        total_budget=0.5,
    )
    t = time.monotonic()
    r = run(c.lookup_handle("slow"))
    elapsed = time.monotonic() - t
    assert r.outcome == "timeout"
    assert elapsed < 0.5 + 0.15


def test_total_budget_hard_cap_even_if_fetch_ignores_timeouts():
    # Budget smaller than one call cap: the whole-lookup cap must still win.
    c, _ = client({("GET", PROFILE): hang, ("GET", ALMANAC): hang}, call_timeout=5, total_budget=0.2)
    t = time.monotonic()
    assert run(c.lookup(ADDR)).outcome == "timeout"
    assert time.monotonic() - t < 0.4


# ---------- real fixtures ----------


@pytest.mark.parametrize("name", ["strong", "weak", "dead"])
def test_fixture_shape(name):
    d = json.loads((FIXTURES / f"{name}.json").read_text())
    assert d["outcome"] == "ok" and av.is_address(d["address"])
    for key in ("status", "readme", "protocols", "avatar_href", "total_interactions", "unresponsive"):
        assert key in d["profile"], key
    assert "status" in d["almanac"]


def test_fixtures_cover_strong_weak_dead():
    load = lambda n: json.loads((FIXTURES / f"{n}.json").read_text())  # noqa: E731
    strong, weak, dead = load("strong"), load("weak"), load("dead")
    assert strong["profile"]["status"] == "active" and strong["profile"]["readme"]
    assert strong["profile"]["avatar_href"] and strong["profile"]["description"]
    assert weak["profile"]["status"] == "active" and not weak["profile"]["readme"]
    assert dead["profile"]["status"] != "active" and dead["almanac"]["status"] != "active"
