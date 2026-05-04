"""Load funds.yaml and .env."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Fund:
    code: str
    name: str
    kind: str
    manager: str
    parser: str
    url: str


@dataclass(frozen=True)
class Sanity:
    flag_daily_pct_above: Decimal
    max_staleness_days: int
    cross_validate_tolerance_pct: Decimal


@dataclass(frozen=True)
class Config:
    funds: list[Fund]
    sanity: Sanity

    def by_manager(self) -> dict[str, list[Fund]]:
        out: dict[str, list[Fund]] = {}
        for f in self.funds:
            out.setdefault(f.manager, []).append(f)
        return out


def load_config(path: Path) -> Config:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    funds = [Fund(**f) for f in raw["funds"]]
    sr = raw["sanity"]
    sanity = Sanity(
        flag_daily_pct_above=Decimal(str(sr["flag_daily_pct_above"])),
        max_staleness_days=int(sr["max_staleness_days"]),
        cross_validate_tolerance_pct=Decimal(str(sr["cross_validate_tolerance_pct"])),
    )
    return Config(funds=funds, sanity=sanity)


def load_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env
