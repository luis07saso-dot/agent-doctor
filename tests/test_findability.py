"""Q12: findability test (Agentverse search rank for the agent's own starter prompts).
Spec: docs/specs/q12-findability.md."""
import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest

from agent import agentverse as av
from agent import findability as F
from agent import guides, profile, router, service
from agent.report import MAX_CHARS, format_report
from agent.scorer import score

FIX = Path(__file__).parent / "fixtures"
FIXTURES = ["strong", "weak", "dead", "flagged"]
STRONG = "agent1qfvydlgcxrvga2kqjxhj3hpngegtysm2c7uk48ywdue0kgvtc2f5cwhyffv"
OTHER = "agent1q" + "x" * 58


def load(name) -> av.Lookup:
    d = json.loads((FIX / f"{name}.json").read_text())
    d.pop("captured_at", None)
    d["notes"] = tuple(d.get("notes") or ())
    return av.Lookup(**d)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(guides, "LAST", guides.LastAudit())
    monkeypatch.delenv("FINDABILITY", raising=False)


# ---------- phrases ----------

def test_doctor_prompts():
    assert F.phrases({"starter_prompts": list(profile.STARTER_PROMPTS)}) == (
        "Audit my agent", "How do I improve my agent's ranking on ASI:One")


@pytest.mark.parametrize("prompts,expected", [
    (["Summarise this article: <link>", "Weather in {city}", "Pick [one]"], ()),
    ([f"Check {STRONG} now please"], ("Check now please",)),
    (["Read https://x.com/a and reply", "mail me at foo@bar.com today"],
     ("Read and reply", "mail me at today")),
    (["ask @weather-bot about rain"], ("ask about rain",)),
    (['Say "hello world" twice'], ("Say hello world twice",)),
    (["What can you do?", "help", "Hi!", "Weather"], ()),
    (["Weather in Paris?", "weather in paris", "Rain in Rome", "Sun in Oslo", "Snow in Bern"],
     ("Weather in Paris", "Rain in Rome", "Sun in Oslo")),
    (["天气预报北京今天"], ("天气预报北京今天",)),
    (["天气"], ()),
    ([" ".join(["word"] * 13)], ()),
    (None, ()),
    ("not a list", ()),
    ([1, None, "Weather in Paris"], ("Weather in Paris",)),
])
def test_phrase_rules(prompts, expected):
    assert F.phrases({"starter_prompts": prompts}) == expected


# ---------- client ----------

class Fetch:
    def __init__(self, addresses=(STRONG,), status=200, delay=0.0):
        self.addresses, self.status, self.delay = addresses, status, delay
        self.calls = []

    async def __call__(self, method, url, body, timeout):
        self.calls.append((method, url, body, timeout))
        if self.delay:
            await asyncio.sleep(self.delay)
        agents = [{"address": a, "handle": None} for a in self.addresses]
        return av.Response(self.status, {"agents": agents, "total": len(agents)})


def test_search_body_and_timeout():
    f = Fetch()
    c = av.AgentverseClient(fetch=f)
    st, addrs = run(c.search_addresses("Weather in Paris"))
    assert st == "ok" and addrs == (STRONG,)
    method, url, body, timeout = f.calls[0]
    assert method == "POST" and url.endswith("/search/agents")
    assert body == {"search_text": "Weather in Paris", "limit": 50, "offset": 0,
                    "source": "agent-doctor-findability"}
    assert timeout == av.SEARCH_TIMEOUT_S


def test_search_status_mapping_and_no_cache_on_error():
    f = Fetch(status=500)
    c = av.AgentverseClient(fetch=f)
    assert run(c.search_addresses("x y")) == ("api_down", ())
    run(c.search_addresses("x y"))
    assert len(f.calls) == 2


def test_search_cache_separate_and_normalized():
    f = Fetch()
    c = av.AgentverseClient(fetch=f)

    async def go():
        await c.search_addresses("Weather  in Paris")
        await c.search_addresses("weather in paris")
    run(go())
    assert len(f.calls) == 1 and not c._cache  # lookup cache untouched


def test_search_inflight_shared_and_cancel_safe():
    f = Fetch(delay=0.05)
    c = av.AgentverseClient(fetch=f)

    async def go():
        t1 = asyncio.ensure_future(c.search_addresses("a b"))
        await asyncio.sleep(0)
        t2 = asyncio.ensure_future(c.search_addresses("a b"))
        await asyncio.sleep(0.01)
        t1.cancel()
        return await t2
    assert run(go()) == ("ok", (STRONG,)) and len(f.calls) == 1


def test_search_timeout_status():
    c = av.AgentverseClient(fetch=Fetch(delay=0.2))

    async def go(monkey_timeout):
        return await c.search_addresses("a b")
    old = av.SEARCH_TIMEOUT_S
    av.SEARCH_TIMEOUT_S = 0.05
    try:
        assert run(go(None))[0] == "timeout"
    finally:
        av.SEARCH_TIMEOUT_S = old


def test_search_never_raises():
    async def boom(*a):
        raise RuntimeError("x")
    c = av.AgentverseClient(fetch=boom)
    assert run(c.search_addresses("a b")) == ("api_down", ())


# ---------- check ----------

class SearchClient:
    def __init__(self, results=None, delays=None):
        self.results, self.delays, self.calls = results or {}, delays or {}, []

    async def search_addresses(self, phrase):
        self.calls.append(phrase)
        await asyncio.sleep(self.delays.get(phrase, 0))
        return self.results.get(phrase, ("ok", (OTHER,)))


def test_check_partial_results_and_case():
    c = SearchClient({"fast one": ("ok", (OTHER, STRONG.upper()))}, {"slow one": 1.0})
    f = run(F.check(c, STRONG, ("fast one", "slow one", "missing one"), 0.2))
    assert f.items == (("fast one", "ok", 2), ("slow one", "not_checked", None),
                       ("missing one", "ok", None))


def test_check_error_is_not_checked():
    c = SearchClient({"a b": ("timeout", ())})
    assert run(F.check(c, STRONG, ("a b",), 0.2)).items == (("a b", "not_checked", None),)


# ---------- report ----------

WORST = F.Find(items=(("How do I improve my agent's ranking on ASI:One", "ok", None),
                      ("Weather forecast for the next ten days", "ok", 17),
                      ("Temperature in Mexico City right now", "not_checked", None)))


@pytest.mark.parametrize("name", FIXTURES)
def test_report_with_block_keeps_hows(name):
    lk = load(name)
    out = format_report(lk, score(lk), find=WORST)
    assert len(out) <= MAX_CHARS and out.count("How:") == 3
    assert "🔍 Agentverse search" in out  # full or counts-only level
    assert out.rstrip().endswith(")")  # profile link still last


def test_report_block_format_and_advice():
    lk = load("strong")  # active
    out = format_report(lk, score(lk), find=WORST)
    line = next(ln for ln in out.split("\n") if ln.startswith("🔍"))
    assert "not found" in line and "#17" in line and "not checked" in line
    assert "Use those words in your README." in out


def test_no_advice_for_inactive_or_all_found():
    dead = load("dead")
    out = format_report(dead, score(dead), find=WORST)
    assert "Use those words" not in out
    ok = F.Find(items=(("a b", "ok", 1),))
    strong = load("strong")
    assert "Use those words" not in format_report(strong, score(strong), find=ok)


def test_no_block_without_find():
    lk = load("strong")
    assert "🔍" not in format_report(lk, score(lk))
    assert "🔍" not in format_report(lk, score(lk), find=F.Find(items=()))


def test_findability_not_scored():
    lk = load("strong")
    sc = score(lk)
    before = (sc.total, [c.rule for c in sc.fixes])
    format_report(lk, sc, find=WORST)
    assert (sc.total, [c.rule for c in sc.fixes]) == before


# ---------- service ----------

class Client(SearchClient):
    def __init__(self, fixture="strong", **kw):
        super().__init__(**kw)
        self.fixture = fixture

    async def lookup(self, a):
        return load(self.fixture)

    async def lookup_handle(self, h):
        return load(self.fixture)


PROMPTS = ("What is the weather in London", "Temperature in Mexico City")  # strong.json


def test_audit_runs_findability():
    c = Client(results={PROMPTS[0]: ("ok", (STRONG,))})
    r = run(service.handle(f"audit {STRONG}", c, chat_key="k"))
    assert sorted(c.calls) == sorted(PROMPTS)
    assert '"What is the weather in London" #1' in r.text
    assert r.find == "2/2" and r.find_top50 == 1


def test_slow_search_not_checked(monkeypatch):
    monkeypatch.setattr(service, "FIND_WAIT_S", 0.1)
    monkeypatch.setattr(service, "MIN_FIND_S", 0.05)
    c = Client(delays={PROMPTS[1]: 1.0})
    r = run(service.handle(f"audit {STRONG}", c, chat_key="k"))
    assert "not checked" in r.text and r.find == "1/2"


@pytest.mark.parametrize("value", ["0", " 0 "])
def test_env_off(monkeypatch, value):
    monkeypatch.setenv("FINDABILITY", value)
    c = Client()
    r = run(service.handle(f"audit {STRONG}", c, chat_key="k"))
    assert c.calls == [] and "🔍" not in r.text and r.find == ""


def test_explain_and_no_prompts_skip():
    c = Client()
    run(service.handle(f"why is {STRONG} scored like this?", c, chat_key="k"))
    assert c.calls == []
    c = Client(fixture="weak")  # no starter prompts
    r = run(service.handle(f"audit {STRONG}", c, chat_key="k2"))
    assert c.calls == [] and "🔍" not in r.text


def test_low_budget_no_wait(monkeypatch):
    monkeypatch.setattr(service, "FIND_MARGIN_S", service.REPLY_BUDGET_S)  # nothing left
    c = Client(delays={PROMPTS[0]: 0.5, PROMPTS[1]: 0.5})
    r = run(service.handle(f"audit {STRONG}", c, chat_key="k"))
    assert r.find == "0/2" and len(c.calls) == 2  # started (warms the cache), not awaited


def test_client_without_search_still_audits():
    class Plain:
        async def lookup(self, a):
            return load("strong")

        async def lookup_handle(self, h):
            return load("strong")
    r = run(service.handle(f"audit {STRONG}", Plain(), chat_key="k"))
    assert r.outcome == "ok" and "🔍" not in r.text


def test_faq_mentions_findability_info_only():
    assert "findability" in router.FAQ["checks"].lower() and "not scored" in router.FAQ["checks"]


def test_chat_logs_find_counts(monkeypatch):
    from agent import chat
    from tests.test_chat import FakeCtx
    from uagents_core.contrib.protocols.chat import ChatMessage, TextContent
    monkeypatch.setattr(chat, "CLIENT", Client(results={PROMPTS[0]: ("ok", (STRONG,))}))
    monkeypatch.setattr(chat, "GUARD", chat.Guard())
    ctx = FakeCtx()
    run(chat.on_chat(ctx, "user1", ChatMessage(content=[TextContent(text=f"audit {STRONG}")])))
    req = [m for m in ctx.logs if m.startswith("REQ ")][-1]
    rec = json.loads(req[4:])
    assert rec["find"] == "2/2" and rec["find_top50"] == 1
    assert "London" not in req
