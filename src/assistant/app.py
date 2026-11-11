"""Wiring: one connection, the ledger, the projection, and the owner's acts."""
from __future__ import annotations

import psycopg

from . import brief, ids
from .config import Config
from .ingest_mail import MailIngest
from .ledger import Ledger
from .projector import Projector


class App:
    def __init__(self, cfg: Config, conn=None) -> None:
        self.cfg = cfg
        self.conn = conn or psycopg.connect(cfg.database_url, autocommit=True)
        self.ledger = Ledger(self.conn)
        self.ledger.install()
        self.projector = Projector(self.conn, self.ledger, cfg)
        self.projector.initialise()

    @property
    def session(self):
        return self.projector.session

    def mail(self, extractor, resolver) -> MailIngest:
        return MailIngest(self.cfg, self.ledger, self.projector, extractor, resolver)

    def brief(self, cutoff: str = "now") -> brief.Brief:
        """The morning list. Pending corrections, merges and out-of-order arrivals are applied by
        one rebuild first, so the list never shows a reading the assistant has already revised."""
        self.projector.refresh()
        return brief.build(self.session, self.ledger, self.cfg, cutoff)

    def owner_act(self, kind: str, claim_id: str, at: str, until: str | None = None,
                  note: str | None = None) -> str:
        """Your snooze or withdraw of an expectation (SPEC §8.3). Targets the claim, not the
        Assertion, so it survives a rebuild that rewrites the claim (deviation D3)."""
        if kind not in ("snooze", "withdraw"):
            raise ValueError(kind)
        act_id = "oa-" + ids._h(kind, claim_id, at)
        self.ledger.add_owner_act(act_id, kind, {"claim": claim_id}, at, until, note)
        self.projector.project_owner_act(self.ledger.owner_acts_by_id(act_id))
        return act_id

    def close(self) -> None:
        self.conn.close()
