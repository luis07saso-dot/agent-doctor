import os

import pytest

from agent import config

SEED = "s" * 40


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    keys = ("ENV_FILE", "RUN_MODE", "AGENT_SEED_PHRASE", "AGENT_HANDLE", "FET_NETWORK", "AGENT_PORT")
    for k in keys:
        monkeypatch.delenv(k, raising=False)
    yield
    for k in keys:  # load_dotenv writes os.environ directly, outside monkeypatch
        os.environ.pop(k, None)


def test_dev_mode_refuses_prod_env_file(monkeypatch):
    monkeypatch.setenv("AGENT_SEED_PHRASE", SEED)
    with pytest.raises(RuntimeError, match="prod seed"):
        config.load()  # default ENV_FILE=.env, default RUN_MODE=dev


def test_dev_env_file_loads_with_dev_handle(tmp_path, monkeypatch):
    f = tmp_path / ".env.dev"
    f.write_text(f"AGENT_SEED_PHRASE={SEED}\n")
    monkeypatch.setenv("ENV_FILE", str(f))
    s = config.load()
    assert s.run_mode == "dev" and s.handle == "agent-doctor-dev" and s.seed == SEED


def test_prod_mode_uses_injected_env_and_prod_handle(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "prod")
    monkeypatch.setenv("ENV_FILE", "/nonexistent")
    monkeypatch.setenv("AGENT_SEED_PHRASE", SEED)
    s = config.load()
    assert s.handle == "agent-doctor" and s.port == 8001 and s.fet_network == "testnet"


def test_missing_seed_fails(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "prod")
    monkeypatch.setenv("ENV_FILE", "/nonexistent")
    with pytest.raises(RuntimeError, match="SEED"):
        config.load()


def test_bad_run_mode_fails(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "staging")
    with pytest.raises(RuntimeError, match="RUN_MODE"):
        config.load()


def test_dev_mode_refuses_seed_that_derives_prod_address(tmp_path, monkeypatch):
    f = tmp_path / "copy.env"
    f.write_text(f"AGENT_SEED_PHRASE={SEED}\n")
    monkeypatch.setenv("ENV_FILE", str(f))
    monkeypatch.setattr(config, "PROD_ADDRESS", config.derive_address(SEED))
    with pytest.raises(RuntimeError, match="prod seed"):
        config.load()
