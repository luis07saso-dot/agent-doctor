"""Q17: "re-check the same agent" uses the remembered agent. Spec: docs/specs/q17-recheck-last.md."""
import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest

from agent import agentverse as av
from agent import guides, router, service

FIX = Path(__file__).parent / "fixtures"
STRONG = "agent1qfvydlgcxrvga2kqjxhj3hpngegtysm2c7uk48ywdue0kgvtc2f5cwhyffv"
SELF = ("agent-doctor",)


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
    monkeypatch.setenv("FINDABILITY", "0")
    monkeypatch.delenv("DIFF_KEY", raising=False)


class Client:
    def __init__(self, fixture="strong"):
        self.fixture = fixture
        self.asked: list[str] = []

    async def lookup(self, a):
        self.asked.append(a)
        return replace(load(self.fixture), address=STRONG)

    async def lookup_handle(self, h):
        self.asked.append("@" + h)
        return replace(load(self.fixture), address=STRONG)


def say(text, client, chat="c1", sender="s1", **kw):
    return run(service.handle(text, client, SELF, (), chat_key=chat, sender_key=sender, **kw))


def audit(client, chat="c1", sender="s1"):
    return say(f"audit {STRONG}", client, chat, sender)


# ---------- router ----------

STRONG_CUES = [
    "@agent-doctor can you re-check the same agent", "re-check the same agent", "recheck",
    "re-check", "Re-check please", "re-audit it", "rerun the audit", "re-run it", "rescan",
    "check it again", "audit it again", "check again", "do it again", "same agent again please",
    "same one", "check the last agent", "audit the previous one", "run the check again",
    "can you check that agent one more time?", "re-check now, I updated the README",
    # Sonnet re-review 2026-11-04: guards are per clause
    "When you get a chance, re-check the same agent", "Don't change anything, just re-check the same agent",
    "I will update the README, then re-check", "What's the new score? re-check the same agent",
    "let me know the new score, re-check", "remove the bad keyword and re-check",
    "Clear the cache and re-check", "re-check and explain what changed", "how's it going, re-check?",
    "check once more", "redo the audit", "can you redo it",
    "What changed? Please check it again", "how's it going? redo the audit",
]


@pytest.mark.parametrize("text", STRONG_CUES)
@pytest.mark.parametrize("has_audit", [False, True])
def test_strong_cues_route_to_last_audit(text, has_audit):
    i = router.classify(text, SELF, (), has_audit)
    assert (i.kind, i.last, i.targets) == ("audit", "any", ())
    assert i.fallback is not None and i.fallback.kind == "recheck_none"


WEAK_CUES = ["audit it", "check it", "check this agent", "can you audit that agent?",
             "score it", "check the agent"]


@pytest.mark.parametrize("text", WEAK_CUES)
def test_weak_cues_only_this_chat_with_old_fallback(text):
    i = router.classify(text, SELF, (), True)
    assert (i.kind, i.last) == ("audit", "chat")
    no_ref = router._no_target(text)
    assert i.fallback == no_ref  # memory gone meanwhile: the reply it got before Q17
    assert router.classify(text, SELF, (), False) == no_ref  # no audit in this chat: unchanged


@pytest.mark.parametrize("text,last", [("is it live?", "chat"), ("is that agent still responding?", "chat"),
                                       ("is the same agent live now?", "any"),
                                       ("re-check if it's online", "any"), ("ping it again", "any"),
                                       ("pre-hire check it", "chat")])
def test_prehire_back_reference(text, last):
    i = router.classify(text, SELF, (), True)
    assert (i.kind, i.last) == ("prehire", last)


NOT_BACKREF = [
    f"re-check {STRONG}", "re-check weather-bot", "audit weather-bot again",
    "how do I fix it?", "how do I fix #2 again", "what was the score again?", "why this score?",
    "how do I rank higher?", "what do you check?", "how is it scored?", "is my agent live?",
    "audit my agent", "forget", "hi", "thanks", "how do I test it?", "let me look at it",
    "tell me a joke", "how do I redo my README?",
    # Sonnet review 2026-11-04: FAQ, delete, question forms, explain, non-requests
    "what does the score check again", "what do you check again?", "what does Agent Doctor check again",
    "how do I rank higher, then re-check", "how is the score calculated, and can I re-check?",
    "delete the last audit", "forget the last audit", "what's the last audit", "explain the last audit",
    "last audit result", "what is a pre-hire check again", "how does pre-hire check work again",
    "how do I re-check?", "when should I re-check?", "can I re-check", "what is a re-check",
    "how does re-check work?", "how often can I re-check", "how to test it again",
    "how do I fix it again", "what is the score again", "what was the score again", "explain it again",
    "thanks, I'll check it later", "check it out", "what would it score", "does it check README",
    "how often do you check it", "don't re-check it", "no need to re-check",
    "did you check it?", "how do I redo my README?",
    "what is a pre-hire check, again?", "what's the last audit? and the previous one",
]


@pytest.mark.parametrize("text", NOT_BACKREF)
def test_not_back_references(text):
    assert router.classify(text, SELF, (), True).last == ""


def test_explicit_target_wins():
    i = router.classify(f"re-check the same agent {STRONG}", SELF, (), True)
    assert i.kind == "audit" and i.targets[0].value == STRONG and i.last == ""


# ---------- service ----------

def test_same_chat_recheck_audits_remembered_agent_with_diff():
    audit(Client("weak"))
    c = Client("strong")
    r = say("@agent-doctor can you re-check the same agent", c)
    assert c.asked == [STRONG]
    assert r.outcome == "ok" and r.input_type == "last" and r.targets == 1
    assert "Since the last check" in r.text and "Which agent?" not in r.text
    assert r.card is not None


def test_weak_cue_same_chat():
    audit(Client())
    c = Client()
    assert say("check it", c).outcome == "ok" and c.asked == [STRONG]


def test_strong_cue_other_chat_same_sender():
    audit(Client(), chat="c1", sender="s1")
    c = Client()
    r = say("re-check the same agent", c, chat="c2", sender="s1")
    assert r.outcome == "ok" and c.asked == [STRONG]


def test_weak_cue_other_chat_keeps_old_reply():
    audit(Client(), chat="c1", sender="s1")
    c = Client()
    r = say("audit this agent", c, chat="c2", sender="s1")
    assert r.outcome == "need_target" and c.asked == []


def test_other_sender_gets_nothing():
    audit(Client(), chat="c1", sender="s1")
    c = Client()
    r = say("re-check the same agent", c, chat="c3", sender="s2")
    assert r.outcome == "recheck_none" and r.text == router.RECHECK_NONE and c.asked == []


def test_diff_key_chat_disables_cross_chat(monkeypatch):
    monkeypatch.setenv("DIFF_KEY", "chat")
    audit(Client(), chat="c1", sender="s1")
    r = say("re-check the same agent", Client(), chat="c2", sender="s1")
    assert r.outcome == "recheck_none"
    assert say("re-check the same agent", Client(), chat="c1", sender="s1").outcome == "ok"


def test_most_recent_audit_of_sender_wins():
    other = "agent1qddwng42rgf0sm2nkvz7whf4xtmcfx8j725kz9nsd7zk4qx8jmwugr8p379"

    class Other(Client):
        async def lookup(self, a):
            self.asked.append(a)
            return replace(load("weak"), address=a)
    run(service.handle(f"audit {other}", Other(), SELF, (), chat_key="c1", sender_key="s1"))
    audit(Client(), chat="c2", sender="s1")  # newer
    c = Client()
    say("recheck", c, chat="c3", sender="s1")
    assert c.asked == [STRONG]


def test_nothing_remembered_strong():
    r = say("can you re-check the same agent", Client())
    assert r.outcome == "recheck_none" and "address" in r.text


def test_nothing_remembered_weak_prehire_keeps_old_reply():
    r = say("is that agent live?", Client())
    assert r.outcome == "prehire_need_target"


def test_prehire_on_remembered_agent():
    audit(Client())
    seen = []

    async def prehire(target):
        seen.append(target)
        return "live!", "live"
    r = say("is it live?", Client(), prehire=prehire)
    assert r.outcome == "prehire_live" and r.input_type == "last"
    assert seen[0].kind == "address" and seen[0].value == STRONG


def test_forget_then_recheck_has_nothing():
    audit(Client())
    say("forget", Client())
    assert say("re-check", Client()).outcome == "recheck_none"


def test_expired_memory_not_used(monkeypatch):
    audit(Client(), chat="c1", sender="s1")
    m = guides.LAST.memory
    t = m.clock() + m.chat_ttl + 1
    monkeypatch.setattr(m, "clock", lambda: t)
    assert say("re-check", Client(), chat="c1").outcome == "recheck_none"
    assert say("re-check", Client(), chat="c2").outcome == "recheck_none"


def test_report_tail_advertises_recheck():
    assert 'Say "re-check" any time after changes.' in audit(Client()).text


def test_help_mentions_recheck():
    assert "`re-check`" in router.HELP
