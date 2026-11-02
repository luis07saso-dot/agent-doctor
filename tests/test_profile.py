"""L6: our own profile must pass our own rubric and the Agentverse field limits."""
import re

from agent import profile as P
from agent import rubric as R
from agent.extract import valid_checksum
from agent.router import classify
from agent.scorer import readme_sections_found, score
from tests.test_scorer import lk, perfect

README = P.README_PATH.read_text()


def test_readme_found_and_within_limits():
    assert P.readme_path() == str(P.README_PATH)
    assert R.README_MIN_CHARS <= len(README.strip()) <= 80_000  # AgentProfile.readme max_length


def test_readme_has_all_six_sections():
    assert readme_sections_found(README) == list(R.README_SECTIONS)


def test_keywords_max_ten_unique_and_in_readme():
    assert 1 <= len(P.KEYWORDS) <= 10
    assert len(set(P.KEYWORDS)) == len(P.KEYWORDS)
    text = README.lower()
    missing = [k for k in P.KEYWORDS if k.lower() not in text]
    assert not missing, missing


def test_field_limits():
    assert 1 <= len(P.NAME) <= 20  # docs: ideally under 20; registration max 32
    assert R.DESCRIPTION_MIN_CHARS <= len(P.DESCRIPTION) <= 300  # AgentProfile max_length
    assert re.fullmatch(r"https://[^\s]+\.(jpg|jpeg|png)", P.AVATAR_URL)
    assert valid_checksum(P.SELF_ADDRESS)
    assert P.SELF_ADDRESS in README


def test_no_medical_framing():
    blob = " ".join([P.NAME, P.DESCRIPTION, *P.KEYWORDS, *P.STARTER_PROMPTS]).lower()
    for word in ("health", "medical", "symptom", "patient"):
        assert word not in blob


def test_starter_prompts_each_get_a_useful_reply():
    kinds = [classify(p, ["agent-doctor"]).kind for p in P.STARTER_PROMPTS]
    assert "off_scope" not in kinds
    assert kinds == ["help", "need_target", "audit", "need_target"]


def test_our_profile_scores_strong_once_live():
    """With L6 fields published (and a live, active agent), only usage signals remain."""
    prof, alm = perfect()
    prof.update(readme=README, description=P.DESCRIPTION, handle="agent-doctor",
                avatar_href=P.AVATAR_URL, starter_prompts=list(P.STARTER_PROMPTS),
                rating=0, total_interactions=0, recent_success_rate=None,
                recent_eval_success_rate=None, domain=None)
    sc = score(lk(prof, alm))
    profile_rules = {"active", "chat_protocol", "readme_sections", "readme", "description",
                     "responsive", "handle", "avatar", "starter_prompts"}
    assert all(c.ok for c in sc.checks if c.rule in profile_rules), sc.checks
