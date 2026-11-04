"""Q13 Agent Scout. Spec: docs/specs/q13-agent-scout.md."""
import asyncio
import json
import time
from dataclasses import replace
from pathlib import Path

import pytest

from agent import agentverse as av
from agent import guides, router, scout, service
from agent.probe import ProbeResult
from agent.report import MAX_CHARS
from agent.rubric import CHAT_PROTOCOL_DIGEST

FIX = Path(__file__).parent / "fixtures"
SELF = ("agent-doctor",)
CHARS = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
ADDR = ["agent1q" + c * 58 for c in CHARS[:10]]
SELF_ADDR = "agent1q" + "l" * 58


def load(name) -> av.Lookup:
    d = json.loads((FIX / f"{name}.json").read_text())
    d.pop("captured_at", None)
    d["notes"] = tuple(d.get("notes") or ())
    return av.Lookup(**d)


STRONG = load("strong")
DEAD = load("dead")


def hit(i, name=None, **kw):
    p = dict(STRONG.profile)
    p.update({"address": ADDR[i], "name": name or f"Agent {i}", "handle": None, **kw})
    return p


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(guides, "LAST", guides.LastAudit())
    monkeypatch.setattr(scout, "LISTS", scout.Lists())
    monkeypatch.setattr(scout, "CAPS", scout.Caps())
    monkeypatch.setenv("FINDABILITY", "0")


class Client:
    def __init__(self, hits=None, status="ok", search_delay=0.0, lookup_delay=0.0, down=(),
                 lookup_fail=()):
        self.hits = [hit(i) for i in range(6)] if hits is None else hits
        self.status, self.search_delay, self.lookup_delay = status, search_delay, lookup_delay
        self.down, self.lookup_fail = set(down), set(lookup_fail)
        self.searched, self.looked = [], []

    async def scout_search(self, phrase):
        self.searched.append(phrase)
        await asyncio.sleep(self.search_delay)
        return (self.status, tuple(self.hits)) if self.status == "ok" else (self.status, ())

    async def lookup(self, a):
        self.looked.append(a)
        await asyncio.sleep(self.lookup_delay)
        if a in self.lookup_fail:
            return av.Lookup(query=a, outcome="timeout")
        h = next(h for h in self.hits if h["address"] == a)
        base = DEAD if a in self.down else STRONG
        return replace(base, address=a, query=a, profile=h if a not in self.down else
                       {**DEAD.profile, "address": a, "status": "active"})

    async def lookup_handle(self, h):
        return av.Lookup(query=h, outcome="not_found")


class Probe:
    def __init__(self, results=None, delay=0.0):
        self.results, self.delay, self.calls = results or {}, delay, []

    async def __call__(self, address):
        self.calls.append(address)
        d = self.delay.get(address, 0) if isinstance(self.delay, dict) else self.delay
        await asyncio.sleep(d)
        st = self.results.get(address, "live")
        return ProbeResult(address, st, 100, 2100 if st == "live" else None)


def go(phrase="book flights", client=None, probe=None, budget=15.0, sender="s1", caps=None):
    client = client or Client()
    return run(scout.run(phrase, client, probe, time.monotonic() + budget, (SELF_ADDR,), SELF,
                         sender, caps=caps))


# ---------- router ----------

POS = [
    ("find me an agent that books flights", "books flights"),
    ("Is there an agent for crypto prices?", "crypto prices"),
    ("I need an agent to summarize youtube videos", "summarize youtube videos"),
    ("which agent can translate text", "translate text"),
    ("recommend an agent for weather", "weather"),
    ("best agent for stock news", "stock news"),
    ("find agents for image generation", "image generation"),
    ("find me a weather agent", "weather"),
    ("any flight booking agents?", "flight booking"),
    ("how can I find an agent that books flights", "books flights"),
    ("what agent should I use for resume writing", "resume writing"),
    ("looking for a good agent to plan a trip to japan", "plan trip japan"),
    ("do you know of an agent that tracks bitcoin price", "tracks bitcoin price"),
    ("are there any agents that generate images", "generate images"),
    ("search for an agent which can write SQL", "write sql"),
    ("suggest some agents for travel planning please", "travel planning"),
    ("Can you find me an agent that does 天气预报", "天气预报"),
    ("get me an agent that summarises news articles on agentverse", "summarises news articles"),
    ("what's the best agent for flights?", "flights"),
    ("top agents for crypto", "crypto"),
    ("I want an agent that books restaurants", "books restaurants"),
    ("find an agent that can help me with taxes.", "taxes"),
    ("show me agents that translate japanese", "translate japanese"),
    ("which bot can generate memes?", "generate memes"),
    ("@agent-doctor find an agent that books flights", "books flights"),
    ("find an agent that finds cheap flights from sydney to tokyo next week",
     "finds cheap flights sydney tokyo next"),
]


@pytest.mark.parametrize("text,query", POS)
def test_scout_detected(text, query):
    i = router.classify(text, SELF, ())
    assert (i.kind, i.query) == ("scout", query)


@pytest.mark.parametrize("text", ["find me an agent", "recommend an agent", "find a good agent?",
                                  "find me an agent that is good"])
def test_scout_need_what(text):
    assert router.classify(text, SELF, ()).kind == "scout_need_what"


NEG = [
    ("what agents can you check?", None), ("which agents can you audit?", None),
    ("any tips for an agent to rank higher?", None),
    ("what should I do to get an agent to rank higher?", None),
    ("I want to audit an agent that I built", None),
    ("I need to check an agent that is not responding", None),
    ("audit any agent for me", "need_target"), ("audit my agent", "need_target"),
    ("is my agent live?", "prehire_need_target"), ("how do I rank higher", "faq"),
    ("how can my agent be found", "faq"), ("find my agent", None),
    ("why is my agent not getting interactions", None), ("what do you check", "faq"),
    ("how is the score calculated", "faq"), ("hello", "help"), ("what can you do", "help"),
    ("what is the number 1 agent on agentverse", "help"),
    ("what is the best way for an agent to get found?", None),
    ("which agent is best at ranking?", None),
    ("can you check which agent is best for flights", None),
    ("find an agent that ranks higher", None),
]


@pytest.mark.parametrize("text,kind", NEG)
def test_not_scout(text, kind):
    i = router.classify(text, SELF, ())
    assert i.kind not in ("scout", "scout_need_what")
    if kind:
        assert i.kind == kind


def test_target_beats_scout():
    i = router.classify(f"find an agent like {STRONG.address}", SELF, ())
    assert i.kind == "audit" and i.targets[0].value == STRONG.address


def test_capability_word_cap_and_stopwords():
    q = router.scout_query("find an agent that can please help me to book the cheapest flights "
                           "and hotels and cars and trains in europe")
    assert len(q.split()) == router.SCOUT_MAX_WORDS and "the" not in q.split()


PICKS = [
    ("audit #2", "audit", 2), ("is #1 live?", "prehire", 1), ("re-check #2", "audit", 2),
    ("pre-hire #1", "prehire", 1), ("check #3 live", "prehire", 3), ("scan #5", "audit", 5),
    ("can you audit # 4 please", "audit", 4), ("hire #3", "prehire", 3),
]


@pytest.mark.parametrize("text,kind,n", PICKS)
def test_pick(text, kind, n):
    i = router.classify(text, SELF, (), False, True)
    assert (i.kind, i.pick, i.targets) == (kind, n, ())


@pytest.mark.parametrize("text", ["audit #2", "is #1 live?"])
def test_no_pick_without_list(text):
    assert router.classify(text, SELF, (), False, False).pick == 0


@pytest.mark.parametrize("text,kind", [("audit my agent #3", "need_target"),
                                       ("how do I fix #2", "fix_guide"), ("audit #6", None)])
def test_pick_exclusions(text, kind):
    i = router.classify(text, SELF, (), True, True)
    assert i.pick == 0
    if kind:
        assert i.kind == kind


def test_bare_number_after_audit_stays_fix():
    i = router.classify("#2", SELF, (), True, True)
    assert (i.kind, i.n) == ("fix_guide", 2)


# ---------- client ----------

class Fetch:
    def __init__(self, agents=None, status=200, delay=0.0):
        self.agents = agents if agents is not None else [{"address": ADDR[0], "name": "A"}]
        self.status, self.delay, self.calls = status, delay, []

    async def __call__(self, method, url, body, timeout):
        self.calls.append((method, url, body, timeout))
        await asyncio.sleep(self.delay)
        return av.Response(self.status, {"agents": self.agents})


def test_client_body():
    f = Fetch()
    c = av.AgentverseClient(fetch=f)
    st, hits = run(c.scout_search("Book  Flights"))
    assert st == "ok" and hits[0]["address"] == ADDR[0]
    method, url, body, timeout = f.calls[0]
    assert method == "POST" and url.endswith("/v1/search/agents")
    assert body == {"search_text": "book flights", "limit": 10, "offset": 0,
                    "source": "agent-doctor-scout",
                    "filters": {"state": ["active", "responsive"],
                                "protocol_digest": [f"proto:{CHAT_PROTOCOL_DIGEST}"]}}
    assert "semantic_search" not in body and timeout == av.SEARCH_TIMEOUT_S


def test_client_filters_bad_hits_and_caps():
    agents = [{"address": "nope"}, "x", *({"address": a} for a in ADDR)] + [{"address": ADDR[0]}] * 5
    st, hits = run(av.AgentverseClient(fetch=Fetch(agents)).scout_search("a"))
    assert st == "ok" and len(hits) == av.SCOUT_LIMIT and all(av.is_address(h["address"]) for h in hits)


def test_client_cache_and_separate_from_findability():
    f = Fetch()
    c = av.AgentverseClient(fetch=f)

    async def go_():
        await c.scout_search("a b")
        await c.scout_search("A  b")
        return await c.search_addresses("a b")
    st, addrs = run(go_())
    assert len(f.calls) == 2 and addrs == (ADDR[0].lower(),) and not c._cache


def test_client_inflight_shared_and_errors_not_cached():
    f = Fetch(delay=0.05)
    c = av.AgentverseClient(fetch=f)

    async def go_():
        return await asyncio.gather(c.scout_search("x"), c.scout_search("x"))
    a, b = run(go_())
    assert a == b and len(f.calls) == 1
    f2 = Fetch(status=500)
    c2 = av.AgentverseClient(fetch=f2)
    assert run(c2.scout_search("x")) == ("api_down", ())
    run(c2.scout_search("x"))
    assert len(f2.calls) == 2


def test_client_never_raises():
    async def boom(*a):
        raise RuntimeError("x")
    assert run(av.AgentverseClient(fetch=boom).scout_search("x")) == ("api_down", ())


# ---------- core ----------

def test_self_excluded_by_address_and_handle_and_dedupe():
    hits = [hit(0, address=SELF_ADDR), hit(1, handle="agent-doctor"), hit(2), hit(2), hit(3)]
    hits[0]["address"] = SELF_ADDR
    out = scout.candidates(hits, (SELF_ADDR,), SELF)
    assert [h["address"] for _, h in out] == [ADDR[2], ADDR[3]] and [r for r, _ in out] == [1, 2]


def test_top5_search_order_full_scores_and_probes_first_two():
    p = Probe()
    c = Client()
    res = go(client=c, probe=p)
    assert res.status == "ok" and [x.address for x in res.cands] == ADDR[:5]
    assert not any(x.profile_only for x in res.cands)
    assert p.calls == ADDR[:2] and c.looked == ADDR[:5]
    assert res.pick_kind == "live" and res.live == 2 and res.probed == 2


def test_pick_higher_score_of_live():
    hits = [hit(0), hit(1)]
    hits[0]["readme"] = ""  # lower score
    res = go(client=Client(hits), probe=Probe())
    assert res.cands[0].total < res.cands[1].total and res.pick == 2


def test_live_beats_failed_first():
    res = go(probe=Probe({ADDR[0]: "unreachable"}))
    assert (res.pick, res.pick_kind) == (2, "live")


def test_down_agent_dropped_and_counted():
    res = go(client=Client(down={ADDR[1]}), probe=Probe())
    assert ADDR[1] not in [c.address for c in res.cands] and res.skipped_down == 1
    assert len(res.cands) == 4


def test_slow_lookup_is_profile_only():
    c = Client(lookup_fail={ADDR[2]})
    res = go(client=c)
    assert [x.profile_only for x in res.cands] == [False, False, True, False, False]
    assert "~" in scout.format_reply(res)


def test_probe_pending_past_deadline():
    res = go(probe=Probe(delay=5.0), budget=scout.MARGIN_S + 1.2)
    assert all(scout._st(c.probe) == "pending" for c in res.cands[:2])
    assert (res.pick, res.pick_kind) == (1, "pending")
    assert "still checking" in scout.format_reply(res)


@pytest.mark.parametrize("st", ["error", "skipped"])
def test_busy_is_not_tested_not_failed(st):
    res = go(probe=Probe({ADDR[0]: st, ADDR[1]: st}))
    assert (res.pick, res.pick_kind) == (1, "untested")
    assert "Neither" not in scout.format_reply(res)


def test_both_failed_no_pick():
    res = go(probe=Probe({ADDR[0]: "unreachable", ADDR[1]: "degraded"}))
    assert (res.pick, res.pick_kind) == (0, "none")
    text = scout.format_reply(res)
    assert "Neither of the top 2" in text and "`is #3 live?`" in text


def test_no_probe_fn_not_tested():
    res = go(probe=None)
    assert res.probed == 0 and res.pick_kind == "untested"
    assert "not tested" in scout.format_reply(res)


def test_caps_sender_and_global():
    caps = scout.Caps()
    for _ in range(scout.SENDER_PROBED_PER_HOUR):
        assert caps.allow("s1", 0)
    assert not caps.allow("s1", 0) and caps.allow("s2", 0)
    g = scout.Caps()
    n = 0
    while g.allow(f"x{n}", 2):
        n += 1
    assert n == scout.GLOBAL_PROBES_PER_MIN // 2


def test_capped_skips_probes():
    caps = scout.Caps()
    for _ in range(scout.SENDER_PROBED_PER_HOUR):
        caps.allow("s1", 0)
    p = Probe()
    res = go(probe=p, caps=caps)
    assert res.capped and p.calls == [] and res.pick_kind == "untested"
    assert "Live tests skipped" in scout.format_reply(res)


def test_search_timeout_and_api_down_and_none():
    assert go(client=Client(search_delay=1.0), budget=scout.MARGIN_S + 0.2).status == "timeout"
    assert go(client=Client(status="api_down")).status == "api_down"
    assert go(client=Client(status="timeout")).status == "timeout"
    assert go(client=Client(hits=[])).status == "none"
    assert go(client=Client(hits=[hit(0)], down={ADDR[0]})).status == "none"


def test_error_after_search_returns_static_list():
    class Bad(Client):
        async def lookup(self, a):
            raise RuntimeError("boom")
    res = go(client=Bad(), probe=Probe())
    assert res.status == "ok" and len(res.cands) == 5


def test_client_without_scout_search():
    class Old:
        pass
    assert run(scout.run("x", Old(), None, time.monotonic() + 15)).status == "api_down"


# ---------- reply ----------

def test_reply_fits_with_long_names_and_keeps_footer():
    hits = [hit(i, name="N" * 60 + " @evil `x` [l](u)") for i in range(5)]
    res = go(client=Client(hits), probe=Probe())
    text = scout.format_reply(res)
    assert len(text) <= MAX_CHARS and text.rstrip().endswith("Pre-Hire Check")
    assert "@evil" not in text and "`x`" not in text and "N" * 31 not in text


def test_reply_shape():
    text = scout.format_reply(go(probe=Probe()))
    assert text.startswith('**Agent Scout**: searched Agentverse for "book flights"')
    assert "**Pick: [Agent 0](https://agentverse.ai/agents/details/" in text
    assert "answered my test message in 2.1 s" in text
    assert "1. Agent 0:" in text and "✅ answered in 2.1 s" in text and "5. Agent 4:" in text
    assert "not answer quality" in text


@pytest.mark.parametrize("status,needle", [("timeout", "isn't answering"),
                                           ("api_down", "isn't answering"),
                                           ("none", "No active agent")])
def test_reply_errors(status, needle):
    assert needle in scout.format_reply(scout.ScoutResult(status, "x"))


# ---------- lists ----------

def test_lists_ttl_bound_and_forget_by_sender():
    now = [0.0]
    ls = scout.Lists(clock=lambda: now[0])
    ls.put("c1", "s1", [("a", "A")])
    ls.put("c2", "s1", [("b", "B")])
    ls.put("c3", "s2", [("c", "C")])
    ls.drop_sender("s1")
    assert ls.get("c1") is None and ls.get("c2") is None and ls.get("c3")
    now[0] = scout.LIST_TTL_S + 1
    assert ls.get("c3") is None
    for i in range(scout.LIST_MAX + 5):
        ls.put(f"k{i}", "s", [("a", "A")])
    assert len(ls._d) == scout.LIST_MAX


# ---------- service ----------

def say(text, client, chat="c1", sender="s1", **kw):
    return run(service.handle(text, client, SELF, (SELF_ADDR,), chat_key=chat,
                              sender_key=sender, **kw))


def test_service_scout_then_pick_audit_and_prehire():
    c = Client()
    r = say("find me an agent that books flights", c, probe=Probe())
    assert r.outcome == "scout_ok" and r.scout_hits == 5 and r.scout_live == "2/2"
    assert c.searched == ["books flights"]
    r2 = say("audit #2", c)
    assert r2.outcome == "ok" and r2.input_type == "pick" and c.looked[-1] == ADDR[1]
    seen = []

    async def pre(t):
        seen.append(t.value)
        return "live!", "live"
    r3 = say("is #3 live?", c, prehire=pre)
    assert r3.outcome == "prehire_live" and seen == [ADDR[2]] and r3.input_type == "pick"


def test_service_pick_none_and_short():
    assert say("audit #2", Client()).outcome != "scout_pick_none"  # no list: old meaning
    c = Client(hits=[hit(0), hit(1)])
    say("find an agent for weather", c)
    r = say("audit #4", c)
    assert r.outcome == "scout_pick_none" and "only 2 agents" in r.text


def test_service_other_chat_has_no_list():
    c = Client()
    say("find an agent for weather", c, chat="c1")
    assert say("audit #2", c, chat="c2").outcome != "ok"


def test_service_need_what():
    r = say("find me an agent", Client())
    assert r.outcome == "scout_need_what" and r.text == router.SCOUT_NEED_WHAT


def test_service_forget_drops_lists():
    c = Client()
    say("find an agent for weather", c)
    assert scout.LISTS.get("c1")
    assert say("forget", c).outcome == "forget"
    assert scout.LISTS.get("c1") is None


def test_service_uses_deadline():
    r = say("find an agent for weather", Client(search_delay=0.5),
            deadline=time.monotonic() + scout.MARGIN_S + 0.1)
    assert r.outcome == "scout_timeout"


def test_help_mentions_scout():
    assert "find an agent that books flights" in router.HELP


def test_chat_logs_scout_counts_not_phrase(monkeypatch):
    from agent import chat
    from tests.test_chat import FakeCtx
    from uagents_core.contrib.protocols.chat import ChatMessage, TextContent
    monkeypatch.setattr(chat, "CLIENT", Client())
    monkeypatch.setattr(chat, "GUARD", chat.Guard())
    ctx = FakeCtx()
    run(chat.on_chat(ctx, "user1", ChatMessage(content=[TextContent(
        text="find me an agent that books flights")])))
    req = [m for m in ctx.logs if m.startswith("REQ ")][-1]
    rec = json.loads(req[4:])
    assert rec["outcome"] == "scout_ok" and rec["scout_hits"] == 5
    assert "flights" not in req


def test_odd_search_data_gives_scout_reply(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("odd")
    monkeypatch.setattr(scout, "candidates", boom)
    assert go().status == "api_down"
