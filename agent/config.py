"""Settings loaded from .env. Never log secret values."""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    seed: str
    port: int
    handle: str
    fet_network: str  # "testnet" | "mainnet" — payment ledger only


def load() -> Settings:
    seed = os.getenv("AGENT_SEED_PHRASE", "")
    if len(seed) < 32:
        raise RuntimeError("AGENT_SEED_PHRASE missing or too short in .env")
    fet_network = os.getenv("FET_NETWORK", "testnet")
    if fet_network not in ("testnet", "mainnet"):
        raise RuntimeError("FET_NETWORK must be 'testnet' or 'mainnet'")
    return Settings(
        seed=seed,
        port=int(os.getenv("AGENT_PORT", "8001")),
        handle=os.getenv("AGENT_HANDLE", "agent-doctor"),
        fet_network=fet_network,
    )
