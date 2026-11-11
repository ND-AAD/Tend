"""Command line: `tend --config config.toml <command>`.

Commands: init | github EVENT PAYLOAD.json | mail MESSAGE.json | release [NOW] | garden | nightly | rebuild |
brief [CUTOFF] | snooze CLAIM UNTIL | withdraw CLAIM. Mail and garden call Claude and need
ANTHROPIC_API_KEY in the environment."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from . import gardener, ingest_github, instants, llm
from .app import App
from .config import Config


def _now() -> str:
    return instants.from_datetime(datetime.now(timezone.utc).astimezone())


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="tend")
    p.add_argument("--config", default="config.toml")
    p.add_argument("command")
    p.add_argument("args", nargs="*")
    a = p.parse_args(argv)
    cfg = Config.load(a.config)
    app = App(cfg)
    try:
        cmd, args = a.command, a.args
        if cmd == "init":
            print(app.ledger.meta("projection_schema"))
        elif cmd == "github":
            with open(args[1]) as f:
                print(ingest_github.ingest(args[0], json.load(f), cfg, app.ledger, app.projector))
        elif cmd == "mail":
            with open(args[0]) as f:
                m = json.load(f)
            ing = app.mail(llm.ClaudeExtractor(cfg.extractor_model, cfg.effort),
                           llm.ClaudeResolver(cfg.extractor_model, cfg.effort))
            out = ing.ingest(m)
            print(json.dumps(out.__dict__, indent=1))
        elif cmd == "release":
            ing = app.mail(None, None)
            print(ing.release_holds(args[0] if args else _now()))
        elif cmd in ("garden", "nightly"):
            # nightly: stop watching expired holds, re-resolve the review queue, merge, rebuild once
            if cmd == "nightly":
                ing = app.mail(None, llm.ClaudeResolver(cfg.extractor_model, cfg.effort))
                print("released:", ing.release_holds(_now()))
                print("corrected:", ing.review())
            judge = llm.ClaudeJudge(cfg.gardener_model, cfg.effort)
            for s, b, why in gardener.run(app.ledger, cfg, app.projector, judge):
                print(f"merged {b} into {s}: {why}")
            print("rebuilt:", app.projector.refresh())
            print("best readings outstanding:", sum(gardener.doubt(app.ledger).values()))
        elif cmd == "rebuild":
            print(app.projector.rebuild("owner", "requested from the command line"))
        elif cmd == "brief":
            print(app.brief(args[0] if args else "now").render())
        elif cmd in ("snooze", "withdraw"):
            print(app.owner_act(cmd, args[0], _now(), until=args[1] if cmd == "snooze" else None))
        else:
            p.error(f"unknown command {cmd}")
    finally:
        app.close()


if __name__ == "__main__":
    main()
