"""Settings loaded from env (and an optional dotenv file). Never log secret values.

Prod (Docker on VPS): compose injects `.env` via env_file and sets RUN_MODE=prod.
Local dev: `ENV_FILE=.env.dev python -m agent.main` (separate dev seed).
Guards: outside RUN_MODE=prod, the prod seed file (`.env`) and any seed that
derives the live address are refused, so a local run can never start a second
instance of the live agent.
"""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

PROD_ENV_FILE = ".env"
# Live agent address (derived from the prod seed). Public; safe to commit.
PROD_ADDRESS = "agent1qwm50eahtwxe2jsjnqqgj3yqmcrpft3rkd42g8frh9twvdwugazfg3897tp"


def derive_address(seed: str) -> str:
    """Same derivation uagents.Agent uses (Identity.from_seed(seed, 0))."""
    from uagents_core.identity import Identity

    return Identity.from_seed(seed, 0).address


@dataclass(frozen=True)
class Settings:
    seed: str
    port: int
    handle: str
    fet_network: str  # "testnet" | "mainnet" — payment ledger only
    run_mode: str  # "prod" | "dev"


def load() -> Settings:
    env_file = os.getenv("ENV_FILE", PROD_ENV_FILE)
    run_mode = os.getenv("RUN_MODE", "dev")
    if run_mode not in ("prod", "dev"):
        raise RuntimeError("RUN_MODE must be 'prod' or 'dev'")
    if run_mode != "prod" and os.path.basename(env_file) == PROD_ENV_FILE:
        raise RuntimeError(
            "Refusing to load the prod seed outside RUN_MODE=prod. "
            "Run locally with ENV_FILE=.env.dev"
        )
    load_dotenv(env_file, override=False)

    seed = os.getenv("AGENT_SEED_PHRASE", "")
    if len(seed) < 32:
        raise RuntimeError("AGENT_SEED_PHRASE missing or too short")
    if run_mode != "prod" and derive_address(seed) == PROD_ADDRESS:
        raise RuntimeError("This is the prod seed. Refusing to run it outside RUN_MODE=prod.")
    fet_network = os.getenv("FET_NETWORK", "testnet")
    if fet_network not in ("testnet", "mainnet"):
        raise RuntimeError("FET_NETWORK must be 'testnet' or 'mainnet'")
    default_handle = "agent-doctor" if run_mode == "prod" else "agent-doctor-dev"
    return Settings(
        seed=seed,
        port=int(os.getenv("AGENT_PORT", "8001")),
        handle=os.getenv("AGENT_HANDLE", default_handle),
        fet_network=fet_network,
        run_mode=run_mode,
    )
