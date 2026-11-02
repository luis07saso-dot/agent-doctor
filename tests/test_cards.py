"""Q4: ASI:One interactive card on audit replies + click handling (JSON and planner prose)."""
import asyncio
import json
from pathlib import Path

import pytest
from uagents_core.contrib.protocols.chat import ChatMessage, MetadataContent, TextContent

from agent import agentverse as av
from agent import cards, chat, guard, guides, router, service
from agent.report import MAX_CHARS, PROFILE_URL

FIX = Path(__file__).parent / "fixtures"


def load(name) -> av.Lookup:
    d = json.loads((FIX / f"{name}.json").read_text())
    d.pop("captured_at", None)
    d["notes"] = tuple(d.get("notes") or ())
    return av.Lookup(**d)


class FixtureClient:
    def __init__(self, name="weak", outcome=None):
        self.name, self.outcome, self.calls = name, outcome, []

    async def lookup(self, address):
        self.calls.append(address)
        if self.outcome:
            return av.Lookup(query=address, outcome=self.outcome)
        return load(self.name)

    async def lookup_handle(self, handle):
        self.calls.append("@" + handle)
        return load(self.name)


ADDR = load("weak").address


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(guides, "LAST", guides.LastAudit())
    monkeypatch.setattr(chat, "GUARD", guard.Guard())
    monkeypatch.setattr(chat, "CLIENT", FixtureClient("weak"))
    monkeypatch.setattr(chat, "SELF_HANDLES", ("agent-doctor",))


def ask(text, name="weak", key="chat-1"):
    return asyncio.run(service.handle(text, FixtureClient(name), ["agent-doctor"], chat_key=key))


def click(sel, name="weak", key="chat-1", client=None, prehire=None):
    return asyncio.run(service.handle_card(sel, client or FixtureClient(name), ["agent-doctor"],
                                           prehire=prehire, chat_key=key))


def walk(node):
    yield node
    for c in node.get("children", ()):
        yield from walk(c)


def buttons(meta):
    root = json.loads(meta["card_payload"])["root"]
    return [n for n in walk(root) if n.get("type") == "button"]


# ---------- payload + metadata (shape from the docs / Fetch examples) ----------

def test_audit_reply_carries_a_custom_card():
    res = ask(f"audit {ADDR}")
    assert res.outcome == "ok" and res.card is not None
    m = res.card
    assert set(m) == {"card_protocol_version", "requires_card_interaction", "card_kind",
                      "card_payload"}
    assert (m["card_protocol_version"], m["requires_card_interaction"], m["card_kind"]) == \
        ("1", "true", "custom")
    assert all(isinstance(v, str) for v in m.values())  # wire type is dict[str, str]
    payload = json.loads(m["card_payload"])
    assert set(payload) == {"root"}  # payload at top level, no {"data": ...} wrapper
    assert payload["root"]["type"] == "section"


def test_card_matches_the_text_report():
    res = ask(f"audit {ADDR}")
    root = json.loads(res.card["card_payload"])["root"]
    texts = [n["value"] for n in walk(root) if n.get("type") == "text"]
    badge = next(n for n in walk(root) if n.get("type") == "badge")
    assert f"Score {badge['label'].split()[1]}" in res.text
    shown = guides.LAST.get("chat-1")
    assert [t.split(" ", 1)[1] for t in texts] == [c.fix[:119] if len(c.fix) > 120 else c.fix
                                                   for c in shown.fixes]


def test_buttons_fix_recheck_live_profile():
    res = ask(f"audit {ADDR}")
    bs = buttons(res.card)
    sels = [b["action"]["selection"] for b in bs]
    n_fix = len(guides.LAST.get("chat-1").fixes)
    assert [s["action"] for s in sels] == [cards.FIX] * n_fix + [cards.RECHECK, cards.LIVE,
                                                                   cards.PROFILE]
    assert [s.get("n") for s in sels[:n_fix]] == [str(i) for i in range(1, n_fix + 1)]
    assert all(s["address"] == ADDR for s in sels)
    assert bs[0].get("primary") is True
    profile = bs[-1]["action"]
    assert profile["redirect"] == PROFILE_URL.format(address=ADDR)
    for b in bs:  # every value in a selection is a string (prose planner + our parser)
        assert all(isinstance(v, str) for v in b["action"]["selection"].values())


def test_no_fixes_means_no_fix_buttons():
    p = cards.audit_payload("X", ADDR, 100, "Excellent", [], "u")
    root = p["root"]
    assert not any(n.get("action", {}).get("selection", {}).get("action") == cards.FIX
                   for n in walk(root))
    assert any(n.get("value", "").startswith("No fixes") for n in walk(root))


def test_no_address_means_no_action_buttons():
    p = cards.audit_payload("X", "", 50, "Fair", ["Add a README"])
    actions = [n["action"]["selection"]["action"] for n in walk(p["root"]) if n.get("type") == "button"]
    assert actions == [cards.FIX]


def test_oversize_payload_is_dropped_not_sent():
    assert cards.card_metadata({"root": {"type": "text", "value": "x" * 70000}}) is None


def test_long_fix_text_is_shortened():
    p = cards.audit_payload("X", ADDR, 10, "Poor", ["a" * 500])
    t = next(n for n in walk(p["root"]) if n.get("type") == "text")
    assert len(t["value"]) <= cards.MAX_FIX_CHARS + 4


def test_depth_within_limit():
    def depth(n):
        return 1 + max((depth(c) for c in n.get("children", ())), default=0)
    assert depth(json.loads(ask(f"audit {ADDR}").card["card_payload"])["root"]) <= 8


@pytest.mark.parametrize("text", ["hi", "how do I fix #1", "audit my agent", "what is 2+2"])
def test_non_audit_replies_have_no_card(text):
    assert ask(text).card is None


def test_failed_lookup_has_no_card():
    res = asyncio.run(service.handle(f"audit {ADDR}", FixtureClient(outcome="not_found"),
                                     chat_key="k"))
    assert res.card is None


# ---------- parsing clicks ----------

@pytest.mark.parametrize("text,expected", [
    (json.dumps({"action": "doctor_fix", "n": "2", "address": ADDR}), ("doctor_fix", 2, ADDR)),
    ("@agent-doctor " + json.dumps({"action": "doctor_recheck", "address": ADDR}),
     ("doctor_recheck", 0, ADDR)),
    (json.dumps({"action": "doctor_live_check", "address": ADDR.upper()}),
     ("doctor_live_check", 0, ADDR)),
    (f"The user picked action doctor_fix with n 3 and address {ADDR}.", ("doctor_fix", 3, ADDR)),
    (f"The user chose doctor_live_check for agent {ADDR}", ("doctor_live_check", 0, ADDR)),
    (f"User clicked doctor_profile, address {ADDR}", ("doctor_profile", 0, ADDR)),
    ("The user selected doctor_fix #1", ("doctor_fix", 1, "")),
])
def test_parse_selection(text, expected):
    sel = cards.parse_selection(text)
    assert sel is not None and (sel.action, sel.n, sel.address) == expected


@pytest.mark.parametrize("text", [
    "how do I fix #1",
    f"audit {ADDR}",
    f"is {ADDR} live?",
    json.dumps({"action": "book", "address": ADDR}),
    json.dumps({"action": "doctor_recheck"}),  # no address
    json.dumps({"action": "doctor_fix", "n": "0"}),
    "doctor_fix",  # no number
    f"doctor_recheck {ADDR[:-3]}",  # broken address
    "",
])
def test_not_a_click(text):
    assert cards.parse_selection(text) is None


# ---------- click handling ----------

def test_click_fix_gives_the_guide_of_the_shown_audit():
    ask(f"audit {ADDR}")
    res = click(cards.Selection(cards.FIX, 1, ADDR))
    assert res.outcome == "fix_guide" and res.text.startswith("**Fix #1 for ")
    assert len(res.text) <= MAX_CHARS and res.card is None


def test_click_fix_in_a_chat_that_forgot_rebuilds_the_audit():
    c = FixtureClient("weak")
    res = click(cards.Selection(cards.FIX, 2, ADDR), key="fresh-chat", client=c)
    assert res.outcome == "fix_guide" and res.text.startswith("**Fix #2 for ")
    assert c.calls == [ADDR]


def test_click_fix_for_other_agent_than_last_audit_uses_that_agent():
    ask(f"audit {ADDR}", name="weak")
    other = load("strong").address
    c = FixtureClient("strong")
    res = click(cards.Selection(cards.FIX, 1, other), client=c)
    assert c.calls == [other]
    assert res.outcome in ("fix_guide", "fix_guide_none")


def test_click_fix_when_lookup_fails_asks_for_audit():
    res = click(cards.Selection(cards.FIX, 1, ADDR), key="x",
                client=FixtureClient(outcome="api_down"))
    assert (res.text, res.outcome) == (router.NO_AUDIT_YET, "fix_guide_none")


def test_click_recheck_runs_a_new_audit_with_card():
    res = click(cards.Selection(cards.RECHECK, 0, ADDR))
    assert res.outcome == "ok" and res.card is not None and "Score " in res.text


def test_click_live_check_runs_prehire():
    seen = []

    async def prehire(target):
        seen.append(target.value)
        return "LIVE REPLY", "live"

    res = click(cards.Selection(cards.LIVE, 0, ADDR), prehire=prehire)
    assert seen == [ADDR] and res.outcome == "prehire_live" and res.text == "LIVE REPLY"


def test_click_profile_replies_with_the_link():
    res = click(cards.Selection(cards.PROFILE, 0, ADDR))
    assert res.outcome == "card_profile"
    assert f"]({PROFILE_URL.format(address=ADDR)})" in res.text


def test_click_never_raises():
    class Boom:
        async def lookup(self, a):
            raise RuntimeError("x")
    res = click(cards.Selection(cards.FIX, 1, ADDR), key="y", client=Boom())
    assert res.text and res.outcome == "fallback"


# ---------- chat wiring ----------

class Ctx:
    def __init__(self, session="s1"):
        self.sent, self.logs, self.session = [], [], session
        self.logger = type("L", (), {"info": lambda _s, m: self.logs.append(m),
                                     "error": lambda _s, m: self.logs.append("ERR " + m)})()

    async def send(self, dest, msg):
        self.sent.append(msg)

    def chats(self):
        return [m for m in self.sent if isinstance(m, ChatMessage)]

    def reqs(self):
        return [json.loads(m[4:]) for m in self.logs if m.startswith("REQ ")]


def say(ctx, text, sender="agent1qsender"):
    asyncio.run(chat.on_chat(ctx, sender, ChatMessage(content=[TextContent(text=text)])))


def test_chat_audit_message_has_text_then_card():
    ctx = Ctx()
    say(ctx, f"audit {ADDR}")
    (msg,) = ctx.chats()
    assert isinstance(msg.content[0], TextContent) and "Score " in msg.content[0].text
    assert isinstance(msg.content[1], MetadataContent)
    assert msg.content[1].metadata["card_kind"] == "custom"
    assert ctx.reqs()[0]["card"] is True


def test_chat_help_has_no_card():
    ctx = Ctx()
    say(ctx, "hi")
    (msg,) = ctx.chats()
    assert len(msg.content) == 1


def test_chat_click_json_then_logged_without_body():
    ctx = Ctx()
    say(ctx, f"audit {ADDR}")
    say(ctx, json.dumps({"action": "doctor_fix", "n": "1", "address": ADDR}))
    reply = ctx.chats()[1].text()
    assert reply.startswith("**Fix #1 for ")
    rec = ctx.reqs()[1]
    assert rec["click"] == "doctor_fix" and rec["outcome"] == "fix_guide"
    assert ADDR not in ctx.logs[1]


# ---------- kill switch: AUDIT_CARDS=0 sends the same text with no card ----------

@pytest.mark.parametrize("value,has_card", [("0", False), (" 0 ", False), ("1", True), ("", True)])
def test_audit_cards_switch(monkeypatch, value, has_card):
    on = ask(f"audit {ADDR}")
    monkeypatch.setenv("AUDIT_CARDS", value)
    res = ask(f"audit {ADDR}")
    assert (res.card is not None) == has_card
    assert res.text == on.text and res.outcome == "ok"


def test_audit_cards_default_on(monkeypatch):
    monkeypatch.delenv("AUDIT_CARDS", raising=False)
    assert ask(f"audit {ADDR}").card is not None
