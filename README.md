# Tend

A personal assistant built on [Attedra](https://github.com/ND-AAD/Attedra).

Tend is an application on Attedra 0.1.0 that reads your GitHub activity and mail, records what each source
established, and gives you a morning list of what remains: your commitments, what is overdue, what
you are waiting on from others, and what is coming up. Every line of the list carries the exact
Attedra references it relies on.

`SPEC.md` is the implementation contract. The design rationale and the decisions taken on
11 November 2026 are in the proposal document linked from the pull request.

## How it is put together

- **Ledger** (`ledger.py`): the application's own tables, and the source of truth. Messages,
  claims, recorded names, links, holds, your acts, and a revision log.
- **Projection** (`projector.py`): an Attedra store built from the ledger through the reference
  engine (`attedra_ref.api.Session`). New messages are appended live; corrections and merges
  rebuild a fresh schema, check it with `transition_check`, and swap it in.
- **GitHub** (`ingest_github.py`): deterministic, no model.
- **Mail** (`ingest_mail.py`, `pack.py`, `llm.py`, `confidence.py`, `deadlines.py`): Claude
  proposes claims and resolves references against a context pack; code audits every proposal and
  decides whether a resolution is confident enough to write, using vote entropy weighted by
  structural support. An uncertain resolution is written at once as a flagged best reading, shown
  as "my best reading", and re-checked by later messages and a nightly review queue that rewrites
  it when the answer changes. The queue is entered on contrary evidence as well as on doubt, so a
  confident wrong pick is found too. You are never asked what is what.
- **Gardener** (`gardener.py`): finds Items that may be one thing, asks a judge, merges, rebuilds.
- **Morning list** (`brief.py`): the `what_remains` read, grouped and grounded.

## Deviations from Attedra 0.1.0

Apache 2.0 allows changes with the deviations noted. They are listed in `SPEC.md` §2 (D1 to D8):
Tend rewrites its own extraction by rebuild rather than by correction records (so a rebuild erases
what was known when; the history of readings stays in the ledger), merges and unmerges Items
through an identity map, keeps your acts by meaning across rebuilds, uses one correspondence
stream per producer as the source, keeps a filtered record (refused proposals and set-aside
records never reach the store, and the list names them), and records a best reading as the
source's statement with the doubt kept in the ledger.

## Running

```sh
uv venv .venv && uv pip install -p .venv -e vendor/attedra -e '.[test]'
createuser tend --createdb -P        # password: tend (local development only)
createdb -O tend tend_dev
.venv/bin/python -m pytest -q        # real PostgreSQL; each test creates its own database

cp config.example.toml config.toml   # then edit owner_id and owner_identifiers
tend init
tend github pull_request payload.json
ANTHROPIC_API_KEY=... tend mail message.json
ANTHROPIC_API_KEY=... tend nightly   # release holds, review queue, gardener, one rebuild
tend brief
```

Mail input is JSON: `{"id", "thread_id", "from", "to", "cc", "sent_at", "body", "url"}`. The body is
read and discarded; only the quoted evidence of each claim is kept.

## Attedra

`vendor/attedra` holds Attedra 0.1.0 (specification, reference engine, schema) unmodified, pinned
in `vendor/attedra/PINNED`. Tend reaches the store only through `attedra_ref.api.Session`.

## License

Apache License 2.0; see `LICENSE` and `NOTICE`.
