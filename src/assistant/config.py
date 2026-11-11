"""Configuration (SPEC §11). The Anthropic key comes only from ANTHROPIC_API_KEY."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field


@dataclass
class Config:
    owner_id: str
    owner_identifiers: list[str] = field(default_factory=list)
    database_url: str = "postgresql://assistant:assistant@localhost/assistant_dev"
    setup_at: str = "2026-01-01-00:00"
    extractor_model: str = "claude-opus-5-5"
    gardener_model: str = "claude-opus-5-5"
    triage_model: str = "claude-opus-5-5"
    effort: str = "high"

    def owner_for(self, person_id: str) -> str:
        """Every configured owner identifier maps to owner_id."""
        return self.owner_id if person_id in self.owner_identifiers else person_id

    @classmethod
    def load(cls, path: str) -> "Config":
        with open(path, "rb") as f:
            d = tomllib.load(f)
        m = d.pop("models", {})
        return cls(**d, extractor_model=m.get("extractor", cls.extractor_model),
                   gardener_model=m.get("gardener", cls.gardener_model),
                   triage_model=m.get("triage", cls.triage_model),
                   effort=m.get("effort", cls.effort))
