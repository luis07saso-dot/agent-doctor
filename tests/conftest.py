"""Shared test defaults. Q11: the LLM follow-up is off and keyless in every test unless a test
opts in, so a shell that exports ASI1_API_KEY never makes the suite call the live API."""
import pytest


@pytest.fixture(autouse=True)
def _llm_off(monkeypatch):
    monkeypatch.setenv("LLM_FOLLOWUP", "0")
    monkeypatch.delenv("ASI1_API_KEY", raising=False)
