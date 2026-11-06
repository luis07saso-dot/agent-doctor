"""Shared test defaults. Q11: the LLM follow-up is off and keyless in every test unless a test
opts in, so a shell that exports ASI1_API_KEY never makes the suite call the live API."""
import pytest


@pytest.fixture(autouse=True)
def _llm_off(monkeypatch):
    monkeypatch.setenv("LLM_FOLLOWUP", "0")
    monkeypatch.delenv("ASI1_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def _fresh_latest(monkeypatch):
    """Q18: the per-chat "what was seen last" marker is module state; start each test empty."""
    from collections import OrderedDict

    from agent import service
    monkeypatch.setattr(service, "_LATEST", OrderedDict())
    monkeypatch.setattr(service, "_LAST_FIX", OrderedDict())


@pytest.fixture(autouse=True)
def _fresh_probe_caps(monkeypatch):
    """Q20a: audit + scout probe caps are module state; each test starts with fresh budgets."""
    from agent import scout
    caps = scout.Caps()
    monkeypatch.setattr(scout, "CAPS", caps)
    monkeypatch.setattr(scout, "AUDIT_CAPS", scout.Caps(per_hour=scout.AUDIT_PROBES_PER_HOUR,
                                                        shared=caps))
