import asyncio
from types import SimpleNamespace

from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, TextContent

from agent import chat, router


class FakeCtx:
    def __init__(self):
        self.sent = []
        self.logger = SimpleNamespace(exception=lambda *a, **k: None)

    async def send(self, dest, msg):
        self.sent.append((dest, msg))


def _run(ctx, text="hi"):
    msg = ChatMessage(content=[TextContent(text=text)])
    asyncio.run(chat.on_chat(ctx, "agent1qsender", msg))
    return msg


def test_ack_first_then_reply():
    ctx = FakeCtx()
    msg = _run(ctx)
    assert len(ctx.sent) == 2
    assert isinstance(ctx.sent[0][1], ChatAcknowledgement)
    assert ctx.sent[0][1].acknowledged_msg_id == msg.msg_id
    assert isinstance(ctx.sent[1][1], ChatMessage)
    assert ctx.sent[1][1].text()


def test_reply_even_when_router_crashes(monkeypatch):
    def boom(_):
        raise ValueError("x")

    monkeypatch.setattr(chat, "route", boom)
    ctx = FakeCtx()
    _run(ctx)
    assert ctx.sent[1][1].text() == router.FALLBACK


def test_empty_message_gets_help():
    assert router.route("") == router.HELP
