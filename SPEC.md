# Personal assistant on Attedra: first-slice specification

Status: draft for review, 2026-11-11. Design rationale lives in the proposal document "Personal assistant on Attedra: architecture proposal". This file states what the first slice does, precisely enough that an implementer makes no judgment calls. Rule numbers such as (6.3.1) refer to `Attedra_Specification.md` 0.1.0.

## 1. Scope of the first slice

In scope:

1. A ledger (application tables) that is the source of truth for everything the assistant extracted, and a projection into an Attedra store built from it.
2. Deterministic GitHub ingestion: pull request and issue events.
3. Mail ingestion through a frontier-model extractor, a deterministic audit, and entropy-based resolution confidence.
4. A morning list built from the `what_remains` read, with every line grounded in exact references.
5. Self-correction: rewrite of claims, merge of Items, rebuild of the projection.
6. The identity gardener's detection pass and merge application.
7. Your acts: snooze (ignore) and withdraw.

Out of scope for this slice: Slack, calendar, story detection (conflict and change stories), drafting and sending, triage model, hosting. Story detection is application policy (7.2.8) and comes with the calendar connector, where it first matters.

## 2. Deviations from Attedra 0.1.0

| ID | Deviation | Where implemented |
|---|---|---|
| D1 | The assistant rewrites its own extraction through the ledger and a rebuild; no correction record remains in the store | `ledger.py` (`supersede_claim`, `drop_claim`), `projector.py` (`rebuild`) |
| D2 | Items are merged through the identity map at rebuild | `ledger.py` (`merge_items`), `projector.py` |
| D3 | Your acts survive a rebuild by meaning (target keys), not by Assertion reference; an act whose target no longer exists is dropped and logged | `projector.py` (`project_owner_act`), `app.py` (`owner_act`) |
| D4 | Eligibility criteria will gate delegated actions (no actions in this slice) | not yet |
| D5 | The source of a message's statements is its producer's correspondence stream. A GitHub repository's event log is one source with many producers (the self-description's `@producer` is each event's actor) | `ingest_mail.py` (`record`), `projector.py` (`project_message`) |
| D6 | A rebuild erases what was known when. Each projection shows the ledger's current reading of every message as if it had been read that way from the start; the history of readings lives only in `revisions` | `projector.py` (`rebuild`), `ledger.py` (`revisions`) |
| D7 | The store is a filtered record. A proposal the audit refuses never reaches it, so if a sender revises a value and the revision is refused, the earlier position stays in force (5.2.1) | `ingest_mail.py` (`audit`) |
| D8 | A best reading is recorded as the source's statement. A `low_confidence` claim is asserted with the producer's stream as source like any other; the doubt is the assistant's and lives in the ledger flag, not in the store | `ingest_mail.py` (`_write`) |

Each projection is built only through `attedra_ref.api.Session`, and `rebuild` runs the `transition_check` read (9.5.8) afterwards. A non-empty difference list fails the rebuild and keeps the previous projection.

## 3. Identifiers

All Item ids are deterministic so that a rebuild reproduces the same store from the same ledger.

| Item | Id | Kind |
|---|---|---|
| Person with an email address | `person:<lowercased address>` | `person` |
| Person on GitHub | `person:gh:<login lowercased>` | `person` |
| The owner (you) | `config.owner_id`; every identifier in `config.owner_identifiers` maps to it | `person` |
| Correspondence stream of a person | `corr:<person id>` | `correspondence` |
| GitHub repository event log | `ghlog:<owner>/<repo>` | `event_log` |
| Event context of a message | `ev:<provider>:<provider message id>` | `event` |
| Mail thread | `thread:gmail:<thread id>` | `thread` |
| Pull request / issue | `pr:<owner>/<repo>/<n>` / `issue:<owner>/<repo>/<n>` (no `#` or `|` in any id: they are the compact-reference separators) | `pr` / `issue` |
| Item created by resolution | `<kind>:<slug of label>-<first 6 hex of sha256(message id + label)>` | from the proposal |
| Expectation context of a claim | `expctx:<claim id>` | `expectation_context` |
| Establishing act of a claim | `act:<claim id>` | `commitment` |
| Eligibility Item of a person | `elig:<person id>` | `eligibility` |
| Setup context / config source | `ev:setup` (at `config.setup_at`) / `src:assistant-config` | `event` / `config` |
| Scope Item | `scope:owner` | `scope` |
| Your acts | item `act:human:<act id>`, context `ev:human:<act id>`, source `src:owner-review` | `owner_act` / `event` / `review_log` |

A claim id is `c-<sha256 of (message id, ordinal of proposal in that message, extractor version)>`, first 16 hex.

## 4. Ledger

PostgreSQL schema `ledger`. All tables are mutable by the application; every mutation that changes what the projection would contain is written to `revisions` in the same transaction.

| Table | Columns | Notes |
|---|---|---|
| `meta` | `key text pk, value text` | `projection_schema` names the live projection schema |
| `items` | `id pk, kind, label, keys jsonb, merged_into text null, created_at` | `keys`: exact keys (URLs, PR refs, addresses). `merged_into` is the identity map |
| `names` | `item_id, name_norm, name, message_id, stream_id`, pk `(item_id, name_norm, message_id)` | Recorded names (§7.5) |
| `links` | `from_id, to_id, at`, pk `(from_id, to_id)` | Projected as Connections |
| `messages` | `id pk, provider, provider_id, thread_id, stream_id, producer_id, recipients jsonb, sent_at text, artifact jsonb` | `sent_at` is an instant in 4.2.1 form with the sender's offset |
| `claims` | `id pk, message_id, ordinal, kind, subject_id, property, value jsonb, form, obligated_id, party_id, deadline text null, quote text, confidence real, flags jsonb, status, extractor` | `kind`: `statement`, `commitment`. `form`: `value` or `ask`. `status`: `active`, `superseded`, `dropped` (an uncertain claim is `active` with flag `low_confidence`, §7.3) |
| `holds` | `claim_id pk, mention jsonb, options jsonb, hold_until text` | Held resolutions (§7.3). `mention` carries the excerpt (the claim's quote), so no message body is stored. `options` is the current q |
| `owner_acts` | `id pk, kind, target jsonb, at text, until text null, note text` | `kind`: `snooze`, `withdraw` |
| `revisions` | `id bigserial pk, at timestamptz, agent text, action text, reason text, detail jsonb` | The history D1 relies on |

## 5. Mapping to Attedra

### 5.1 Fixed records

At projection creation: Items `ev:setup`, `ev:eligibility`, `src:assistant-config`, `scope:owner`, `src:owner-review`, the owner person.

### 5.2 A message

For message M with producer P, stream S = `corr:P` (or the repository log for GitHub), context E = `ev:<provider>:<id>`:

1. Create E with `{"@context": {"role": "event", "at": M.sent_at}}`.
2. Assert the self-description `(S, E, S)` with `@producer: P`, `@distribution: recipients`, `message_id`, `provider`. The artifact reference goes in `@basis` of acts only (3.2.1); the self-description carries `artifact` as an ordinary value.
3. Connect `thread → subject` for every subject of an active claim of M, and `scope:owner → subject`.

### 5.3 Statement claims

All active statement claims of M about one subject X form one Assertion `(X, E, S)` whose values are `{property: value}` for each claim. Two claims of M with the same subject and property: the claim with the lower ordinal wins and the other is set `dropped` with a revision (`reason: "duplicate property in one message"`).

### 5.4 Commitment claims

For commitment claim C (obligated O, instructing party A, subject X, property p, value v or ask, deadline d):

1. Ensure `elig:O` exists with `{"@eligibility": true}` and criteria `(elig:O, ev:eligibility, src:assistant-config) {"@eligible": {"party": O}}`. `ev:eligibility` is dated `1970-01-01+00:00` so that evidence of any date qualifies (3.3.2); dated at `setup_at` it would reject evidence older than the installation.
2. Create `expctx:C` with `{"@context": {"role": "expectation", "timing": T, "fresh": true}}`. `fresh` (6.2.2) makes only evidence at or after this establishment count, so a review requested again after an earlier review is open again, T = `{"type": "by", "instant": d}` when d exists, else `{"type": "any"}`.
3. Assert the expectation `(X, expctx:C, elig:O)` with `{p: v}`, or `{p: {"@ask": true}}` for an ask.
4. Assert the establish act `(act:C, E, S)` with `@action: establish`, `@targets` the expectation, `@party: A`, `@issuance: E`, `@basis: [M.artifact]`.

### 5.5 GitHub events

Deterministic, no model. Source is `ghlog:<repo>`; the self-description's `@producer` is the actor.

| Event | Records |
|---|---|
| PR opened / reopened | statement `(pr, E, log) {state: "open", title, author}` |
| PR closed (merged / not merged) | statement `{state: "merged"}` / `{state: "closed"}` |
| Review requested of the owner | commitment: obligated owner, party the requester, subject the PR, property `review_by_owner`, value `"submitted"`, no deadline |
| Review submitted by the owner | statement `{review_by_owner: "submitted"}` |
| Review request of the owner removed | withdraw of the open review commitment, recorded as a `withdraw` act sourced from the log with `@party` the actor |
| PR closed or merged | withdraw of every open commitment of the owner on the PR, `@party` the actor |
| Issue unassigned from the owner | withdraw of the open `resolved` commitment |
| Issue reopened | statement `{state: "open", resolved: false}` |
| Issue assigned to the owner | commitment: property `resolved`, value `true` |
| Issue closed | statement `{resolved: true}`, and `{state: "closed"}`. Closed by someone other than the owner: also withdraw the owner's open commitments on it, since the log's statement is not the owner's evidence |

An open commitment is an active commitment of the owner on the subject with no later owner statement of the same property and value and no withdrawal of it.

Events not in this table are stored in `messages` and produce no claims.

## 6. Mail extraction

### 6.1 Proposal format

The extractor returns JSON matching `llm.PROPOSAL_SCHEMA`: a list of proposals, each

```json
{"kind": "statement" | "commitment",
 "mentions": [{"text": "the deck", "resolution": "existing" | "new" | "unsure",
               "item_id": "...", "kind": "deliverable", "label": "Acme Q4 deck", "why": "..."}],
 "subject": 0,
 "property": "delivered", "value": true, "form": "value" | "ask",
 "obligated": "<person id>", "party": "<person id>",
 "deadline": {"text": "by Friday", "value": "2026-11-13"} | null,
 "quote": "I'll send the revised deck by Friday"}
```

`subject` indexes into `mentions`.

### 6.2 Context pack

Built per message, in this order, deduplicated, at most 40 Items:

1. Items linked from the message's thread.
2. Items hit by an exact key found in the body (URL, `owner/repo#n`, email address).
3. Items whose recorded names occur in the body (normalised, §7.5), longest name first.
4. Items that are subjects of claims in the last 30 days whose messages share a participant with M.

Each entry: id, kind, label, up to 5 recorded names, up to 3 latest claims (property and value), open expectations with their claim ids. The pack also carries the property schema (`schema.PROPERTIES`) for every kind present.

### 6.3 Audit

Applied to each proposal in order. Failure codes are logged to `revisions` with `action: "audit_refused"`.

| Check | Rule | Failure |
|---|---|---|
| `quote` | `quote` occurs in the message body after quoted-reply lines (`>` prefixed, and everything after an `On … wrote:` line) are removed, comparing with collapsed whitespace | drop |
| `kind` | `kind` and `form` take only the listed values; `form: ask` only on commitments | drop |
| `property` | `property` is in `schema.PROPERTIES[subject kind]`, and `value` matches its type | drop; log `vocabulary_gap` with the property and kind |
| `people` | on a commitment, `obligated` and `party` are person ids from the message's producer or recipients, or the owner. A bare address is read as `person:<address>`. On a statement both are ignored | drop |
| `existing` | `item_id` is in the pack | treat the mention as `unsure` |
| `new` | no Item has an exact key in the mention's text, and no Item of the same kind has a recorded name equal to the normalised `text` or `label` | first time: re-ask the resolver with the matching Item added; second time: treat as `unsure` |
| `deadline` | see §6.4 | drop the deadline, keep the claim, flag `deadline_unchecked` |

### 6.4 Deadlines

The value is an instant in 4.2.1 form. The audit converts the extractor's `value` with the message's UTC offset: a date `YYYY-MM-DD` becomes `YYYY-MM-DD±hh:mm`; a minute `YYYY-MM-DDTHH:MM` becomes `YYYY-MM-DDTHH:MM±hh:mm`. Checks on `text`:

- No digit followed by `:`, and none of `am`, `pm`, `noon`, `eod`, `morning`, `afternoon`, `evening`: the value must be a date.
- A weekday name: the value's weekday must equal it, and the value must fall within 13 days after the sent date.
- `today`, `tomorrow`: the value must be the sent date, or the next day.
- A month name with a day number, or `m/d`: the value must have that month and day.
- `eod`, `end of day`: date value, the same day as the check above implies.

## 7. Resolution

### 7.1 Mentions settled by code

A mention whose text contains an exact key of exactly one Item resolves to that Item with confidence 1, whatever the model said.

### 7.2 Confidence

For every other mention, the resolver runs k = 5 times with the pack's candidate order shuffled with seeds 0 to 4 (`confidence.K`). Votes over candidates plus `new` give p. Structural support s for a candidate c is the share of the message's anchors that lie within two hops of c in the ledger graph. Anchors are: the thread, the producer, the recipients, and the Items linked from the thread. Edges are `links`, plus subject–producer and subject–thread pairs from active claims. `new` has s = 0.

```
q_i = p_i (ε + s_i) / Σ_j p_j (ε + s_j),    ε = 0.05
H   = −Σ q_i log2 q_i / log2 n,              n = number of options with p > 0, H = 0 when n = 1
```

Write when H ≤ 0.35 and either the winner is `new` or its s > 0. Otherwise hold.

What this owes to SENATOR, stated plainly: the write rule is self-consistency voting with a structural prior, which is not in the paper. SENATOR's self-information (Eq. 1) and weighted degree (Eq. 2) do real work elsewhere: they order the review queue (§8.4) and the gardener (§9). Its structural entropy (Eq. 3) is reported, not used.

Implementation rules that the formula leaves open:

- Candidates are the pack's Items of the mention's audited kind only, so a property is never written on an Item whose vocabulary lacks it.
- The winner is the option with the most votes; structural support shapes q and breaks ties among the most-voted, but never lets a minority win.
- Name check (your mechanism of flagging an existing Item and checking it against the nomenclature): a winning existing Item must share a word, other than articles and words such as "revised" or "draft", with one of its recorded names or its label, or already be linked from the message's thread. A pick that fails is logged `name_check_failed` and is not confident.
- The extractor's `resolution` is a hint carried into the resolver's input; the K votes decide. An `existing` hint whose id is not in the pack is downgraded to `unsure` before the votes.
- The `existing` and `new` audit checks of §6.3 apply to every vote. A vote naming an id outside the candidates is discarded and logged `invented_id`. A `new` vote whose text or label collides with an exact key or a recorded name of the same kind is discarded on the first round, the colliding Items are added to the candidates, and all K votes are re-run. On the second round a `new` vote counts: the resolver has seen the colliding Item and still says new (two things can share a name).
- No valid votes at all: a new Item from the extractor's label, as a best reading. A claim is never dropped for lack of a subject.
- The owner is excluded from the anchors and from the graph. The owner is adjacent to nearly every Item, so including the owner would give every candidate support and make s meaningless.
- The label and kind of a `new` winner are the most common pair among the `new` votes.

### 7.3 Best readings and holds

Every audited claim is written at once. A resolution that does not meet the rule of §7.2 is written as the best reading: the most-voted option, except that when it is an existing Item with no structural support or a failed name check and `new` received votes, the new Item is chosen (a duplicate is repaired by a merge; a wrong pick puts another thing's evidence on an Item). The claim carries flag `low_confidence`, is shown in the morning list with "(my best reading)", and gets a `holds` row (`hold_until` = sent time + 72 hours) and a revision `uncertain_write` with q.

Each new message in the same thread re-resolves the thread's open holds (§8.4). `release_holds(now)` only stops watching a thread after `hold_until`; the claim stays written and flagged and remains in the review queue.

### 7.4 Owner escalation

None in this slice. A `low_confidence` claim is marked in the morning list with "(my best reading)".

### 7.5 Names

`normalise(name)`: lowercase, strip punctuation, drop a leading `the`, `a`, `an`, `our`, `my`, collapse whitespace. Every written mention records `(item, normalise(text), text, message, stream)` in `names`. A new Item also records its label.

## 8. Self-correction and rebuild

### 8.1 Operations

| Operation | Ledger effect |
|---|---|
| `supersede_claim(id, new_fields, agent, reason)` | old claim `superseded`, a new claim with the new fields, revision logged |
| `drop_claim(id, agent, reason)` | claim `dropped`, revision logged |
| `merge_items(survivor, absorbed, agent, reason)` | `absorbed.merged_into = survivor`; names and links move to the survivor; revision logged |

Any operation marks the projection stale. `rebuild()` runs after a batch of operations, not after each one.

### 8.2 Rebuild

1. Create schema `proj_<n+1>` and apply `reference/schema.sql` inside it.
2. Create the fixed records (§5.1).
3. Replay, in order of instant (ties by id): every message with its active claims, mapping every Item id through `merged_into` to its root; and every owner act (§8.3).
4. Create Connections from `links`, mapped through `merged_into`, at the earliest message instant that produced them.
5. Run `transition_check` on `scope:owner`. Any difference: drop the new schema, log the failure, keep the old projection.
6. Set `meta.projection_schema`, drop the old schema.

Appending a new message (`append`) runs step 3 for that message only, against the live schema. Reads at "now" are then correct. Two cases also mark the ledger stale (`meta.stale`, with `stale_reason`): a message older than the latest one projected, whose live Connections would keep a later first-seen instant, and a failed append, which re-raises with the message kept in the ledger. Supersessions, drops and merges mark it stale too. Nothing rebuilds inside ingestion: a rebuild costs a full replay. `refresh()` rebuilds when stale and runs before every morning list and at the end of the nightly batch. Any exception during a rebuild, not only a write error, restores the previous projection.

### 8.3 Owner acts across rebuilds (D3)

An owner act's `target` is a key: `{"claim": <claim id>}` for an expectation. At replay the claim id is mapped to its current active successor (following `superseded` revisions). If none exists, the act is skipped and a revision `owner_act_dropped` is logged. A snooze is an `ignore` act with `@until`; a withdraw is a `withdraw` act targeting the whole expectation.

### 8.4 Noticing and rewriting errors

`reresolve(claim)` re-runs §7.2 for a claim's mention with a fresh pack. A confident answer naming a different Item supersedes the claim onto it (§8.1); a confident answer confirming the subject clears `low_confidence`; an answer still short of the rule updates the hold's q.

Triggers:

1. A new message in the thread of an open hold (§7.3).
2. The review queue, run nightly (`review(limit=20)`): every active mail claim that is a best reading, or whose resolving name is now recorded on more than one active Item of its kind (how a confident pick becomes doubtful), ordered by self-information I = −log2 q, highest first (SENATOR Eq. 1).
3. The gardener's merges (§9).

The nightly batch is: `release_holds`, `review`, gardener `run`, then one `refresh`.

## 9. Gardener

`detect()` returns candidate pairs of active Items of one kind, ranked:

1. Shared recorded name (score 1.0).
2. Neighbourhood Jaccard ≥ 0.6 over two-hop neighbours (score = the Jaccard), only for pairs whose recorded names or labels share a word other than articles and words such as "revised". Sharing a correspondent alone makes every Item from that person a neighbour of every other, so it is not evidence of identity.
3. Each best reading (`uncertain_write`, `hold_released` revisions), as the pair (its subject, its runner-up option) (score 0.5).

Pairs are then ordered within equal scores by uncertainty mass, SENATOR's weighted degree (arXiv 2505.07184, Eq. 2) applied to resolutions. Each active claim gives its subject the self-information I = −log2 q of its winning resolution (q from §7.2; 0 for code-settled mentions). An Item's uncertainty is d_u = Σ I over its claims, and a pair's mass is d_a + d_b. The gardener therefore spends its judge calls where the store's identity is least certain. `uncertainty_entropy()` reports the total mass vol and SENATOR's H¹ = −Σ (d_u / vol) log2 (d_u / vol). H¹ measures how evenly doubt is spread, not how much there is: it is 0 both when nothing is uncertain and when one Item holds all the doubt. Neither number drives a decision.

`run(judge, limit=10)` asks `judge.same(a, b, evidence)` for the top pairs. On `same`, it merges into the older Item (smaller `created_at`, then smaller id), with the judge's reason. A pair judged different is not asked again until the two Items' claim count changes (revision `judged` records it). Merges mark the store stale; the batch `refresh` applies them.

## 10. Morning list

`brief(now)` runs `what_remains` on `scope:owner` at cutoff `now` with `attention_filter: "ignore"` (so a snooze in effect hides its line), and `upcoming` as returned. Sections, in order:

1. **Overdue**: expectation entries with `overdue: true`, obligated on the owner.
2. **Your commitments**: other open entries obligated on the owner (`elig:<owner>`), asks first.
3. **Waiting on others**: open entries obligated on anyone else.
4. **Coming up**: `upcoming` entries.

Each line: label of the subject, the property in words, the deadline, who asked, and `(my best reading)` for low-confidence claims. Grounding: every line holds the unit reference and the `began.record` reference. Both must resolve through the `exact` read; a line whose references do not resolve is omitted and logged.

## 11. Configuration

`config.toml`: `owner_id`, `owner_identifiers` (addresses and logins), `database_url`, `setup_at`, `models.extractor`, `models.gardener`, `models.triage`, all `claude-opus-5-5` by default, and `models.effort` (`high`). The resolver uses the extractor model. Calls use structured JSON output, explicit effort, and server-side fallback on refusal (`fallbacks: "default"`); a refusal that survives the fallback raises and the message is retried later, never written partially. Cheaper models are a cost option to confirm after measuring the audit's refusal rate on real mail. The Anthropic key is read from `ANTHROPIC_API_KEY`; it is never stored.

## 12. Tests

Real PostgreSQL, no mocks of the engine. Model calls go through `llm.Resolver` and `llm.Extractor` interfaces with scripted fakes. Required cases:

1. The commitment walkthrough: a mail commitment opens an expectation; a later sent mail fulfils it; the brief shows it, then does not.
2. GitHub: review requested appears under your commitments; review submitted removes it.
3. Audit refusals: quote not in body, quote only in quoted text, property outside schema, invented id, `new` colliding with a recorded name.
4. Deadline checks of §6.4, both passing and failing.
5. Confidence: unanimous supported votes write; split votes are written at once as a flagged best reading shown in the list; a later message re-points it; a minority never wins.
6. Rebuild reproduces an identical store (same Items, Assertions and Connections) from an unchanged ledger.
7. Merge: two Items split across two threads are merged by the gardener; after rebuild one expectation is fulfilled by evidence that was attached to the other.
8. Owner acts survive a rebuild that supersedes the target claim, and are dropped when the target is dropped.
9. Rebuild failure of any kind keeps the previous projection; a failed append is repaired by the next refresh; out-of-order arrival gives the same store as a rebuild.
10. From the second review: a re-requested review reappears; a merged PR, or an issue closed by someone else, leaves the list; a reopened and reassigned issue returns; evidence before `setup_at` qualifies; candidates are filtered by kind; a colliding name never drops a request; the review queue rewrites a confident pick made doubtful; the gardener ignores a shared correspondent and remembers its verdicts.
