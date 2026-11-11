# Attedra Specification

**Version 0.1.0 (preliminary)**

Attedra is a data model that follows the changes and conflicts in what several sources assert about the same things, and from those assertions builds the record of a project. It stores every statement with three coordinates (what it describes, when it applies, who says so), neither overwrites statements nor ranks their sources, and derives from that structure answers to the questions that matter in multi-party work: what changed, who disagrees, what was reviewed, what was expected, what was fulfilled, what was withdrawn, and what still needs attention.

This specification defines the model's three primitives, its value and time semantics, its expectation and story semantics, its write and lifecycle operations, the reads a conforming implementation must provide, its integrity rules, and its conformance and version claims. Rule identifiers of the form **n.m** are stable and are the targets of the conformance fixtures that accompany this document.

The words MUST, MUST NOT, SHOULD and MAY have their customary normative meanings. Examples are illustrative; a rule is stated in its numbered paragraph, never only in an example.

---

## 1. Purpose, supported scope, and a short three-primitive example

**1.1 Purpose.** In multi-party work, several documents, communications and people describe the same things, on different clocks, and disagree for long periods while the work proceeds. Attedra treats that duplication as the record itself. It stores assertions, not values: every statement keeps its author and its position in time, agreement is computed rather than assumed, and disagreement, expectation, review and withdrawal are addressable records in the same structure as the data they concern.

**1.2 Three commitments.**

1. *Disagreement is data.* Comparing two assertions is one operation. The same source differing from its own earlier position is a change; two sources differing at one moment is a conflict; two requirements for different values of the same thing are a conflict; a required state that no qualifying evidence yet meets is an outstanding expectation.
2. *The record never ranks its authors.* When sources disagree, the model keeps every position and reports the disagreement. A decision is a recorded act of review; it does not make a value true, and it does not end a disagreement. Only aligned source evidence (aligned under the comparison that applies to it, 7.2.4, 7.3.8), the end of one side's position (by withdrawal or, for a requirement, by fulfillment), or a correction showing that the disagreement was never in the record does that.
3. *The record grows; it does not rewrite.* A later assertion never erases an earlier one. Withdrawal, correction, reconciliation and review are new attributed records. The single exception is the permanent removal of a misrecorded entry that nothing yet depends on. It requires an explicit direction and a confirmation, and nothing of the entry remains afterwards (§8).

**1.3 Supported scope.** This release supports: the three primitives and their identity rules (§2); source attribution, evidence and eligibility (§3); dated events, participant-bound milestones, distribution histories and explicit evaluation frames (§4); typed values with per-property carry-forward, explicit emptiness and whole-value replacement of structured properties (§5); expectations with timing, value and source qualification, independent support, fulfillment and explicit withdrawal (§6); change and conflict stories, recorded review, related stories, reconstructed history, project-wide normalization, the recorded beginning and end of every unit of work, and ending policies (§7); writes, genuine revision, correction, confirmed removal and relationship lifecycle (§8); the required reads (§9); integrity, validation, extension handling and conformance (§10).

Not supported in this release, and declared as limitations in §11: one expectation shared by several obligated sources as a single record; identity continuity when a thing is replaced, transformed or reassembled; any universal personal-identity, organizational authorization, notification or full-history replay facility.

**1.4 Three primitives, one example.** A door schedule issued by an architect says Door 101 has a painted finish. The finish specification says stain. A client instruction, recorded in meeting minutes, requires the schedule to show stain by the next issue.

- *Items* are the things: Door 101, the schedule, the specification, the minutes, the architect's milestone, the instruction.
- *Connections* are untyped directional links between Items: the schedule lists Door 101; the project contains the schedule.
- *Assertions* are the statements. Each is identified by three Item references and carries values:

```
(Door 101, Architect 100% DD, Schedule A-601)      values: { finish: "paint" }
(Door 101, Architect 100% DD, Specification 09-91)  values: { finish: "stain" }
(Door 101, Expected by next issue, Schedule A-601)  values: { finish: "stain" }
(Instruction 1, Meeting 14 May, Minutes 14 May)     values: { @action: "establish",
                                                               @targets: [ the expectation above ],
                                                               @basis: [ the minutes document, as issued ],
                                                               @party: client, addressed_to: architect }
```

From these four records the model derives: a conflict between the schedule and the specification at the DD issue; an expectation on the schedule, established by the minutes, outstanding until a qualifying schedule issue shows stain; and, when that issue arrives, a change in the schedule's own position and the end of the conflict by alignment. The minutes remain the source of the instruction; the client remains the instructing party; nothing is overwritten.

**1.5 A story, end to end.** A *story* is the history of one detected disagreement or one detected revision, held as an Item. The detection opens it. Later evidence and recorded acts (reviews, directives, withdrawals, reconciliations) attach to it. Its standing (open or ended, reviewed or not) is derived from that evidence and those acts (§7). A requirement for a future state is held the same way, as an *expectation*: an Assertion about the same subject in an expectation context, whose standing is derived from its supports and from the evidence that fulfills it (§6). The beginning and end of each story, and of each expectation property's requirement, are recorded as begin and end acts as the record establishes them. They must equal what the rules derive, so that what is unfinished is what has a beginning and no end (7.6). Together they let the record show, at any moment:

1. what has been asserted, by whom, and when;
2. the actions taken with regard to those assertions;
3. the actions still required;
4. the future states that have been required;
5. what is still unfinished: open stories and outstanding expectations (9.5.7).

Because disagreements, requirements and their endings are records in the same structure as doors and documents, errors and omissions can be listed, counted, referenced and traced like any element of the project. An error is a document that disagrees with another document or with what was required. An omission is information that was required and has not been supplied.

*Example.* Door 101 appears on the architect's door schedule A-601. The architect issues the 50% CD set on 2 June and the 100% CD set on 16 June. A-601 is re-issued on its own on 20 June.

```
1  (Door 101, Arch 50% CD, A-601)                 values: { finish: "paint" }
2  (Door 101, Arch 100% CD, A-601)                values: { finish: "stain" }
3  (Story 1, Detection 16 Jun, Story 1)           values: { @action: "detect",
                                                             @story: { kind: "change", subject: Door 101 },
                                                             @transitions: [ finish: record 1 → record 2 ] }
4  (Door 101, E-lacquer, A-601)                   values: { finish: "lacquer" }
                                                   E-lacquer: an expectation context, timing "by 27 June", fresh
5  (Decision 1, Owner review 17 Jun, Minutes 17 Jun)
                                                   values: { @action: "review", @targets: [ record 3 ],
                                                             @outcome: "change_required", @establishes: [ record 4 ],
                                                             @party: owner, @basis: [ the minutes, as issued ] }
6  (Door 101, A-601 re-issued 20 Jun, A-601)      values: { finish: "lacquer" }
```

Read at the end of each day, the same records answer the five questions:

| At the end of | 1 Asserted | 2 Actions taken | 3 Actions required | 4 Future states | 5 Unfinished (9.5.7) |
|---|---|---|---|---|---|
| 2 June | A-601: paint (record 1) | none | none | none | nothing |
| 16 June | A-601: stain (record 2); paint at 50% CD retained | the change paint → stain is detected (Story 1) | review Story 1 | none | Story 1, awaiting review |
| 17 June | unchanged | the owner reviews Story 1 and directs lacquer, establishing E-lacquer (record 5) | A-601 to show lacquer by 27 June | Door 101 finish: lacquer, by 27 June (record 4) | E-lacquer, outstanding. Story 1 has ended: the directive is its ending, although the expectation it created is open |
| 20 June | A-601: lacquer (record 6) | E-lacquer is fulfilled, on time, by record 6, and its period ends with an end act citing record 6. The ending is derived from the record and recorded when it occurs; no one enters it | review the 20 June revision, if the application records it as a change story | none outstanding | nothing required; the 20 June change story awaits review, if recorded |

Nothing in the record was overwritten. The paint and stain positions, the owner's directive and its basis, the requirement and the evidence that met it all remain readable. Maintenance records each beginning and end as it occurs (7.6.9). Story 1's period begins with a begin act citing record 2 and ends with an end act citing record 5. E-lacquer's period begins with a begin act citing record 5; because the review of Story 1 began it, the period is nested under Story 1 (7.6.15), and its begin and end acts are recorded on Story 1's Item, as part of that story (7.6.7). Column 5 is the what-remains read (9.5.7) at each cutoff. A frame set at any earlier moment (4.6) returns that moment's row.

---

## 2. Items, Connections, Assertions, identity, and exact references

### 2.1 Items

**2.1.1** An Item is the single kind of entity. Every thing the record describes, every document or communication that describes things, every point in time or interval, every participant or party, every expectation context, and every recorded act (a decision, a withdrawal, a reconciliation, a story) is an Item.

**2.1.2** An Item has:

| Field | Meaning |
|---|---|
| `id` | A stable identifier assigned by the implementation. It never changes for a known same thing (2.1.4). |
| `kind` | The Item's type identity, from an application-defined vocabulary (for example `door`, `schedule`, `submittal`). The model reserves no `kind` values and never treats an Item differently because of its kind (2.1.6). |
| `label` | Optional display text for human readers. It is not identity and is never compared, except to recognise an identical re-creation of the Item (8.1.5). |
| `definition` | An object of definitional metadata: what the Item is, not what anyone says about it. Reserved members begin with `@` (2.4.4). It is set when the Item is created and is never changed afterwards; a misdescribed Item is corrected (8.3.8). |

**2.1.3** Testimony belongs in Assertions, never in `definition`. A value that varies by time or by source (a door's finish, a milestone's publication instant and distribution list, a party's current numbering of a door) is asserted. A fact that defines the Item (a context's role, a dated event's instant, a milestone's schedule and ordinal, an Item's role as an eligibility Item) is definitional.

**2.1.4 Stable identity.** When the same underlying thing has already been identified, renaming or renumbering it does not change its `id`. A number or label that a source assigns to the thing is that source's dated assertion about it (for example `{ mark: "201" }`), compared like any other value. Equal labels alone never merge two Items; differing labels alone never split one.

**2.1.5 Scope.** Every read names the scope within which it compares and counts (§9.1). A scope is identified either by a scope Item or by an explicit list of Items supplied with the read. A scope Item's members are the scope Item itself and the Items reached from it by following Connections in their forward direction (2.2.3), transitively, using the Connections active at the frame's cutoff (8.6.4). A cycle adds nothing further. An Item that only points at a member, reached backwards, is not thereby a member. An expectation is in scope when its subject (`item`) is a member, and a story when the subject in its detection (7.2.1) is a member. Acts are not members; a read applies every act that targets an in-scope record, or that targets an act it applies, and every normalization that applies to an in-scope Item, even when the scope Item it targets is not itself in the read's scope (7.3.8). Scope never establishes authority or qualification (3.3.5).

**2.1.6 What the model reserves.** The model's own vocabulary lives inside records, never in `kind`. It consists of:

- the `@` members of values and definitions (2.4.4);
- the context roles (4.1.1);
- the `@action` values (2.4.4);
- the Connection lifecycle properties (2.2.4).

Whether an Item serves as a context, an eligibility Item, a story or an act is declared by reserved members in its `definition` (4.1, 3.3.2), or by the act Assertions about it (§6–§9). An application may name its kinds freely, and renaming a kind changes nothing in the model's behaviour.

### 2.2 Connections

**2.2.1** A Connection is a directional link from one Item to another. There is at most one Connection per ordered pair of Items; implementations MUST enforce this at the storage layer. Creating a Connection for a pair that already has one, active or disconnected, is a successful no-op; it does not reconnect a disconnected Connection (8.6.3).

**2.2.2** A Connection carries no relationship type and no role. The meaning of a Connection follows from the kinds of the two Items it joins. Where the two endpoint kinds cannot distinguish the roles of two relationships, the roles are stated in Assertions, not in Connection properties.

**2.2.3** Direction is a convention: a container or authority points at what it contains or describes (project → document, document → thing described, schedule → milestone), and a recorded act points at what it concerns. Readers traverse in both directions.

**2.2.4 Lifecycle properties.** A Connection's `properties` object is reserved for relationship lifecycle. The defined members are:

| Member | Meaning |
|---|---|
| `connected_at` | Instant the Connection was first created. Changed only by recomputation after a correction (8.3.9). |
| `disconnected` | `true` while the Connection is inactive. |
| `disconnected_at` | Instant of the most recent disconnection. Retained after reconnection. |
| `disconnect_reason` | Optional free text recorded at the most recent disconnection. |
| `reconnected_at` | Instant of the most recent reconnection, if any. |

The properties hold the current state and the most recent cycle. The complete history is reconstructed from the disconnect and reconnect acts, which are mandatory (8.6). A disconnected Connection is excluded from active adjacency but remains a retrievable record.

### 2.3 Assertions

**2.3.1** An Assertion is the complete record identified by three Item references and carrying values:

| Field | Meaning |
|---|---|
| `item` | The Item the Assertion describes. |
| `context` | The Item that supplies the temporal and interpretive setting (§4): for a statement, the dated event or milestone publication at which its source issued it (4.2.4); for an expectation, its expectation context; for an act, the dated event at which it was taken. |
| `source` | The Item that makes the statement: the communication carrying it (§3), or the act or story Item itself for a self-attributed record (3.1.4). |
| `values` | An object of property values and reserved members (§5, 2.4.4). |
| `recorded_at` | Optional bookkeeping: when the implementation recorded the Assertion. Never used to order, select or rank Assertions. |
| `recorded_by` | Optional bookkeeping: the operator or process that recorded it. Never used as the source. |

**2.3.2 Identity.** The triple (`item`, `context`, `source`) is the Assertion's sole identity and MUST be unique, enforced at the storage layer. Every coordinate is a single Item reference. There is no fourth coordinate and no additional version dimension; an implementation that needs "the same triple twice" needs a different context or source, both of which are Items and can be created.

**2.3.3** Shared coordinates are ordinary: many Assertions share a source, many share a context, and distinct contexts may carry equal instants (4.5). None of those shared values identifies an Assertion.

**2.3.4** An Assertion is a statement, not a fact. The model stores what the source says, with attribution, and computes agreement between statements. An expectation does not become a submission when fulfilled; a decision does not become a source value when recorded.

### 2.4 References and reserved members

**2.4.1 Exact Assertion reference.** An Assertion is referenced by all three of its coordinates:

```
{ "@ref": "assertion", "item": "door-101", "context": "arch-100dd", "source": "a-601" }
```

A reference resolves to exactly that record. It never resolves to a value-equal Assertion, to another source's Assertion about the same subject, or to a replacement. Implementation row identifiers MAY exist as aliases that resolve to the triple; they are not a public identity.

**2.4.2 Item, artifact and connection references.**

```
{ "@ref": "item", "id": "a-601" }
{ "@ref": "artifact", "id": "a-601-rev-3.pdf", "edition": "2026-05-14" }
{ "@ref": "connection", "from": "room-12", "to": "door-101" }
```

An artifact reference identifies a retrievable supporting document at a specific edition. A mutable location alone is not an artifact reference. Artifacts are held outside the store; the model does not resolve them. A connection reference identifies the Connection for an ordered pair (8.6).

**2.4.3 Selectors.** An Assertion reference MAY narrow its target:

- `"property": "finish"` selects one named property of the referenced Assertion.
- `"support": { ...expectation reference... }`, on a reference to a supporting act, selects that act's support of the named expectation (6.3). When `support` is present, `property` names a property of the supported expectation, and the reference selects the act's support of that one property.

**2.4.4 Reserved members.** Object keys beginning with `@` are reserved for the model. The defined members, and where each may appear, are:

| Member | Appears in | Defined in |
|---|---|---|
| `@ref` | any reference object | 2.4.1–2.4.2 |
| `@action` | act Assertions; values `establish`, `reaffirm`, `withdraw`, `review`, `detect`, `reconcile`, `reinterpret`, `correct`, `ignore`, `disconnect`, `reconnect`, `begin`, `end` | §6–§9 |
| `@targets` | every act | 6.3, 6.7, 7.3, 7.4, 7.6, 7.7, 8.3, 8.6, 9.5.6 |
| `@basis` | every act | 3.2, 5.5.5, 7.2, 7.4 |
| `@party` | every act | 3.2.1 |
| `@outcome` | review (`change_required`, `no_change`); reconcile (`split`, `continuous`, `boundary`, `reconstructed`, `revise`, `adopt_policy`); correct (`replace`, `erroneous`, `relocated`) | 7.3, 7.4, 7.6.10, 7.7.3, 8.3 |
| `@corrected` | correct | 8.3 |
| `@effective` | establish, reaffirm, withdraw, review, ignore, reinterpret; reconcile with outcome `adopt_policy` | 7.3.8, 7.7.3, 8.4 |
| `@establishes`, `@reaffirms` | review | 7.4.1 |
| `@frame` | detect, review, reconcile; its keys `policy` and `policy_version` on detect and reconcile only; its key `normalization` only beside a `null` interpretation, for an interpretation in force that was ambiguous | 5.5.5, 7.7.2, 7.7.3 |
| `@interpretation` | reinterpret | 7.3.8 |
| `@period` | begin (`cause` `disagreement`, `revision`, `review_withdrawn`, `in_force`); end (baseline `cause` `alignment`, `withdrawal`, `fulfillment`, `correction`, `normalization`, `interpretation`, `review`, `reconstructed`, or a cause its policy defines); reconcile with outcome `revise` | 7.6.4–7.6.6, 7.6.10, 7.7.5 |
| `@story` | detect | 7.2.1 |
| `@transitions` | detect of a change story; reconcile with outcome `reconstructed` | 7.2.3, 7.3.7 |
| `@relates_to` | detect | 7.3 |
| `@successor`, `@representative` | reconcile | 7.3.3, 7.3.4 |
| `@until` | ignore | 9.5.6 |
| `@producer`, `@agent`, `@distribution` | a communication's self-description; a milestone publication; a later distribution | 3.1.2, 4.4 |
| `@issuance` | a later distribution of a communication's issuance; an act recorded from a communication | 3.2.1, 4.4.1 |
| `@published` | a milestone publication | 4.4.1 |
| `@eligible` | Assertions about an eligibility Item | 3.3.2 |
| `@ask`, `@suggested` | property values of an expectation | 6.4 |
| `@after` | any Assertion | 4.5.2 |
| `@context`, `@eligibility` | Item `definition`; on an expectation context, `@context` may carry `interpretation` and `policy` | 4.1, 3.3.2, 7.6.13, 7.7.2 |

For `@producer`, `@agent`, `@distribution` and `@issuance`, the records the table names are recognised by their coordinates and members, never by kind (2.1.6): a *self-description* is a statement whose `item` and `source` are the same Item (3.1.2); a *milestone publication* is a statement whose `item` and `context` are the same milestone and which carries `@published` (4.4.1); a *later distribution* is a statement at an event context that carries `@distribution` and either is about a milestone or names `@issuance` (4.4.1). Any act may carry `@issuance` (3.2.1). On any other record these members are invalid (10.2.4).

The keys of an object that is the value of a defined member (for example the keys inside `@frame` or `@story`) are defined by the rule for that member. They are not otherwise `@`-prefixed, except that such an object may contain references (2.4.1–2.4.2) and, inside `@corrected`, the members its target allows (8.3). A defined member used where this table does not allow it, or with a shape its rule does not define, is invalid (10.2.4). An object containing an undefined `@` member, or an `@action` string not listed above, is an extension (10.4).

**2.4.5 Discovery.** A reference is discoverable only in the form of 2.4.1 and 2.4.2. Implementations MUST find every reference by scanning Assertion `values` and Item `definition` recursively for objects carrying `@ref`. A string that resembles an identifier is not a reference and creates no dependency.

**2.4.6** A reference inside `values` or `definition` never creates a Connection. Connections are created only by the Connection operation (8.6).

**2.4.7 Reserved members are not properties.** Reserved members carry model semantics, not domain values. They never take part in per-property carry-forward (5.2), source positions (9.2), comparison (5.5, 9.4) or change detection (7.2.3). The rules that give them meaning read them directly: eligibility criteria (3.3.2), communication attribution (3.1.2), publication and distribution (4.4, 9.7), sequence evidence (4.5.2), expectation value forms (6.4) and acts (§6–§9).

---

## 3. Source attribution, evidence, and eligibility

### 3.1 The source is the communication

**3.1.1** The `source` of a submitted Assertion is the communication that carries the statement: the drawing, schedule, specification, email, meeting minutes or other document or message. It is not the party that produced the communication and not the person who entered it into the record.

**3.1.2** The producing or instructing party is provenance, recorded as values. A communication Item describes itself with a self-attributed Assertion whose context is the dated event of its issuance (4.2):

```
(A-601, A-601 issued 2026-05-14, A-601)
values: { "@producer": { "@ref": "item", "id": "architect" },
          "@agent":    [ { "@ref": "item", "id": "spm-jones" }, { "@ref": "item", "id": "role-spm" } ],
          "@distribution": [ { "@ref": "item", "id": "contractor" }, { "@ref": "item", "id": "client" } ],
          "edition": "rev 3" }
```

`@producer` names the party on whose behalf the communication was issued. `@agent` lists the individuals or roles who issued it, where that is germane (3.3); a communication may name both the person and the role in which they acted. `@distribution` lists the participants it was sent or made available to (4.4). Each issuance of a communication has its own self-description, at that issuance's context, and the attribution and distribution of an Assertion are those of the issuance that carried it. For a statement, that is the self-description of its source at the statement's own context. For an act recorded from a communication, it is the self-description at the context named by the act's `@issuance` (3.2.1). For a communication published within a milestone publication, `@producer` and `@agent` come from its own self-description at the milestone context; if there is none, its attribution is missing (3.3.2). The publication supplies the instant and the distribution (4.4).

**3.1.3** Meeting minutes are the source of the instruction they report. The instructing party and the addressed party are values of that account; recording the account does not assert that every party agrees with it.

**3.1.4 Self-attributed records.** An act or story that originates in the application rather than in a communication (a detection, a reconciliation, an application-recorded review) uses its own Item as `source`. It MAY instead name as its source the party or process Item that performed the act, when that attribution is germane. A recording principal (3.2.2) is never the source.

### 3.2 Evidence

**3.2.1** An act recorded from a document (any act whose source is minutes, a letter, a contract, an instruction or another communication) MUST carry in `@basis` an artifact reference (2.4.2) to that document at the edition relied on. It MUST identify the instructing or deciding party with `@party`. It MUST name in `@issuance` the context of the issuance of that communication which carries it: for minutes, the issuance of the minutes, not the meeting. Any other act MAY carry `@party`. It need not identify the individual who wrote the document or the individual who entered the record. This rule binds writers; because the model cannot always tell a document source from a party or process source, write validation (10.2) does not enforce it.

**3.2.2** People and parties MAY be Items when their identity is germane to a question in the record. Recording principals (user accounts, operators) are not required to be Items and are never substituted for the source.

**3.2.3** Enough context MUST be retained to reconstruct a recorded question or decision as it stood: the subject and frame, the exact evidence referenced, the applicable expectations or interpretation, and the relevant party and timing context. A review act records this in its `@basis` and `@frame` (7.4). Reconstructing unrelated parts of the record at a past moment is not required.

### 3.3 Eligibility

**3.3.1** When a requirement names a particular communication as its obligated source, only that communication's Assertions can fulfill it.

**3.3.2** When a requirement names a party but no particular communication, it is expressed with an *eligibility Item* in the expectation's source coordinate (6.1.3). An eligibility Item is marked by `definition: { "@eligibility": true }`. Its criteria are asserted on it, so that they are dated, attributed and amendable:

```
(Elig-arch, Criteria set 2026-05-01, Contract 7)
values: { "@eligible": { "party":  { "@ref": "item", "id": "architect" },
                         "agents": [ { "@ref": "item", "id": "role-spm" }, { "@ref": "item", "id": "role-principal" } ] } }
```

- *Matching.* A communication qualifies under a set of criteria when its `@producer` is the named party and, where `agents` is stated, at least one Item in its `@agent` list is among `agents`. Matching is by identity only. The model holds no link between a person and a role, so a communication that should qualify through a role names that role in `@agent` (3.1.2).
- *Attribution.* The `@producer` and `@agent` matched are those of the issuance that carried the evidence (3.1.2).
- *Criteria in force.* The criteria in force at an instant are, for each source that has asserted `@eligible` on the eligibility Item, that source's most recent `@eligible` at or before the instant (4.2.5) that has not been withdrawn with effect at or before it. Withdrawing a source's criteria ends them without reviving its earlier criteria. The applicable instant is the evidence Assertion's occurrence time (4.2.4). When the criteria of different sources give different results for one piece of evidence, its qualification is `ambiguous` (4.5.3), listing each source's criteria; the model does not choose between them.
- *Missing attribution.* Evidence whose issuance names no `@producer`, or no `@agent` where `agents` is stated, does not qualify; the read reports the unmet criterion. This is an ordinary outcome, not a limitation.
- *No criteria in force.* Evidence at whose occurrence time no source has criteria in force on the eligibility Item (none has yet been asserted, or every source's latest criteria have been withdrawn with effect at or before it) does not qualify, and the read reports that no criteria were in force. An eligibility Item with no criteria in force names no party; it is not an absence of restriction. This is an ordinary outcome, not a limitation.

**3.3.3** Eligibility is qualification, not ranking. A qualifying communication from a senior agent does not outrank another qualifying assertion, and no title or role confers authority over a disagreement.

**3.3.4** Any source kind is comparison-eligible by default. The model has no allowlist of document types; a valid Assertion from a newly encountered kind of communication participates in reads from the moment it is recorded. Expected and act content is kept out of submitted-value reads by its context and reserved members (4.1, 9.2), not by excluding kinds.

**3.3.5** Connection reachability never establishes authority or qualification. A document connected under a party is not thereby the party's communication; an Assertion is qualified by its own attribution and the applicable criteria.

---

## 4. Contexts, time, milestones, distribution, and evaluation frames

### 4.1 Context Items

**4.1.1** A context is an Item whose `definition` carries a `@context` object declaring its role and the members that role requires. Four roles are defined:

| Role | Definition members | Meaning |
|---|---|---|
| `event` | `at` (instant) | A dated occurrence: a communication sent, a meeting held, an act taken. |
| `milestone` | `schedule` (Item reference), `stage` (text), `ordinal` (integer) | A named position in one participant's or schedule's progression. Its publication instant is asserted (4.4.1), not defined. |
| `phase` | `schedule`, `starts`, `ends` (each a milestone reference or an instant) | A bounded period on one schedule, start-inclusive and end-exclusive. A phase is used in expectation timing (6.2); it is never an Assertion's context. |
| `expectation` | `timing` (6.2), `schedule` (optional), `fresh` (boolean, optional; omitted means `false`, 6.2.2), `interpretation` (optional, 7.6.13), `policy` (optional, 7.7.2) | The interpretive setting of an expected state. |

```
definition: { "@context": { "role": "milestone",
                             "schedule": { "@ref": "item", "id": "arch-schedule" },
                             "stage": "100% DD", "ordinal": 300 } }
```

**4.1.2** A context whose definition changes meaning is a different context and MUST have a different `id`. A definition that misdescribes its context (a wrong instant, a wrong schedule) is corrected under 8.3.8; it is never edited.

### 4.2 Instants, occurrence and recording time

**4.2.1** An instant carries an explicit UTC offset and is written at the precision the record supports: a date, in the date-with-offset form of XML Schema `date` (`2026-05-14-07:00`); a time of day to the minute, in ISO 8601 extended format with an offset (`2026-05-14T09:45-07:00`); or a time of day to the second or finer, in RFC 3339 form (`2026-05-14T09:45:00-07:00`). It is retained at the precision written. An instant denotes the interval its precision covers, which includes its start and excludes its end: a date covers that whole local day, up to but not including the start of the next day; a minute covers that whole minute, up to but not including the next minute.

**4.2.2** Three times are distinct and MUST NOT be conflated: the *occurrence* time of an event or publication; any *effective* time an act declares for itself (`@effective`, 8.4); and the *recording* time at which the implementation stored the record (`recorded_at`). Recording time is bookkeeping and is never used to order evidence, select an applicable value, break a tie or establish precedence.

**4.2.3** Importing a communication late does not make it late. Its occurrence time is the time it was issued.

**4.2.4 Occurrence time of an Assertion.** A statement's context is the occasion at which its source issued it: the dated event at which the communication was issued, or the milestone publication in which the communication was published. The Assertion's occurrence time is that context's instant: the event's `at`, or the milestone's publication instant (4.4.1). Occurrence time governs cutoff inclusion (4.6.1), carry-forward order (5.2), timing and freshness (6.2), eligibility (3.3.2), fulfillment and lateness (6.5). An Assertion at a milestone that has no publication instant has no occurrence time; reads report it as a limitation (9.6), except that, as evidence for an expectation, it does not yet qualify (6.5.5). An Assertion whose context Item, as corrected (8.3.8), has no `@context` has no occurrence time; reads report it as a limitation (9.6). An expectation's times come from its timing and supports (6.2, 6.3.3); an act's time is its context's occurrence time (8.4).

**4.2.5 Comparing instants.** For instants A and B:

- A is *before* B when A's interval ends no later than B's begins, so that every moment of A precedes every moment of B, and *after* B when A's interval begins no earlier than B's ends. Intervals that meet are therefore ordered: a date is before the next date, and 09:45 is before 09:46.
- A is *at or before* B when A's interval ends no later than B's interval ends, and *at or after* B when A's interval begins no earlier than B's interval begins.
- When neither the relation a rule needs nor its opposite holds, the order is unspecified and 4.5.3 applies. *The later of* two instants is defined only when they are ordered or equal; otherwise it is unspecified in the same way.

A letter dated 14 May and an email at 09:45 on 14 May are unordered. The email is at or before a deadline written as 14 May. The letter is neither at or before nor after a deadline of 14 May at 17:00.

### 4.3 Milestones, schedules and order

**4.3.1** A milestone belongs to exactly one schedule, and a schedule belongs to a participant or to the project. A milestone label (a stage name, a percentage) identifies nothing by itself: two participants may both have a "50% CD", at different times, and neither is a universal project clock.

**4.3.2** Within one schedule, milestones have distinct ordinals and are ordered by ordinal (10.2.3). Distinctness is evaluated in the corrected account: a milestone being created, like one being corrected (8.3.8), is checked against the corrected definitions of the schedule's other milestones. A planned milestone has an ordinal and no publication instant. Where the publication instants of two milestones of one schedule are equal or unordered (4.2.5), their ordinals order them and the Assertions at them; the ordinal is explicit sequence evidence (4.5.2).

**4.3.3** Across schedules, and between milestones and dated events, order is by occurrence instant (4.2.5): a milestone's publication instant and an event's `at` instant lie on one chronology. A planned milestone has no chronological position; a read that needs one reports the limitation rather than inventing a date.

**4.3.4** When a declared ordinal order and the publication instants of the same schedule disagree, the read reports the discrepancy and uses instants for chronology. The declaration is not silently corrected.

**4.3.5** A source MAY reference another participant's milestone: in an expectation's timing (6.2), or as a reference in values. Such a reference does not make that milestone the Assertion's context. A submission's context remains the occasion at which its own communication was issued (4.2.4), which is another participant's milestone only when the communication was itself published in that milestone's publication. The schedule that owns a milestone is determined by the milestone's definition, never by the source.

### 4.4 Publication and distribution

**4.4.1** A milestone's publication is recorded by an Assertion whose subject and context are the milestone, whose source is the issuing communication or log, and whose values carry the publication instant in `@published` and the initial distribution in `@distribution`:

```
(Arch-50CD, Arch-50CD, Architect-issue-log)
values: { "@published": "2026-05-13T11:45:12-07:00",
          "@distribution": [ { "@ref": "item", "id": "contractor" }, { "@ref": "item", "id": "client" } ],
          "edition": "set 4" }
```

The milestone's occurrence instant is its `@published` value. Publication instants asserted by different sources are consistent when one's interval contains the other's, and the milestone's instant is then the finer one. Otherwise its chronological position is ambiguous (4.5.3), and reads list the competing Assertions. A later distribution of the same unchanged publication is a new Assertion about the milestone at a dated-event context:

```
(Arch-50CD, Distribution 2026-05-16, Architect-issue-log)
values: { "@distribution": [ { "@ref": "item", "id": "consultant-mep" } ], "edition": "set 4" }
```

Both Assertions are retained. A read of the milestone's distribution history returns each dated distribution and its recipients; no cumulative or latest-only list substitutes for that history. A later distribution of one issuance of a communication is recorded the same way, as an Assertion about the communication at a dated-event context, naming the issuance it redistributes in `@issuance` (a reference to that issuance's context):

```
(A-601, Distribution 2026-05-20, Transmittal 22)
values: { "@distribution": [ { "@ref": "item", "id": "consultant-mep" } ],
          "@issuance": { "@ref": "item", "id": "a-601-issued-2026-05-14" } }
```

Publication, distribution and self-description Assertions are records of what happened to a communication. A mistaken one is corrected (8.3); none of them is withdrawn (6.7.9).

**4.4.2 Distribution coverage.** An Assertion is distributed to a participant at a cutoff when, at or before the cutoff, the participant is listed in a `@distribution` of the issuance that carried it: (a) the self-description of its source at the issuance context (3.1.2), meaning the statement's own context or the act's `@issuance`, or a later distribution naming that issuance; or (b) the publication of its milestone context, or a later distribution of that publication (4.4.1). An issuance is always available to its own `@producer`. A self-description, publication or later-distribution Assertion is covered for the participants it lists; a publication is also covered through later distributions of it, under (b). Distribution records that information was sent or made available to the named participants. It does not establish receipt, reading or comprehension; those are separate evidence if recorded at all. Absence of a distribution record is absence of evidence, not proof that a participant could not have obtained the information.

**4.4.3** Labels such as pricing set, progress set or permit set are values on the publication, not model categories.

### 4.5 Equal instants and ambiguity

**4.5.1** Equal instants are valid. Distinct events that happen at the same moment keep distinct context Items; implementations MUST NOT shift a timestamp, add precision a record does not have, assign an artificial ordinal or use arrival order to make instants unique.

**4.5.2** Where explicit sequence evidence exists, it orders tied or unordered records. The defined forms are the `@after` member in an Assertion's values, carrying an exact reference to the record it follows, and the ordinals of milestones of one schedule (4.3.2). Absent such evidence, the relative order of tied or unordered records is unspecified.

**4.5.3** When unspecified order would change a result (which of two tied Assertions by one source supplies the current value, which of two tied acts took effect first, whether a date-only letter falls before a cutoff), the read returns the result as *ambiguous*, listing the records concerned, rather than choosing. Ambiguity is a first-class result (9.6).

### 4.6 The evaluation frame

**4.6.1** Every read that computes a current or historical value, comparison, standing or count takes an explicit frame and returns the frame it used:

| Frame input | Meaning |
|---|---|
| `scope` | The scope Item or explicit member list (2.1.5). |
| `cutoff` | An instant, a milestone reference, or `"now"`. Evidence whose occurrence time is not at or before the cutoff (4.2.5) is excluded; evidence whose relation to the cutoff is unspecified makes the affected result ambiguous. `"now"` resolves once, to the evaluation instant at a precision no coarser than the second, which the result reports. A milestone cutoff resolves to its publication instant; a planned milestone, or one with competing publication instants, cannot be a cutoff, and the read returns a limitation. |
| `perspective` | `"record"` (default: the complete record) or a participant Item reference. With a participant, only what had been distributed to that participant by the cutoff (4.4.2) is considered. That covers statements: every Assertion that is neither an act nor an expectation. It also covers acts whose source is a communication, which count only once that communication's issuance had been distributed to the participant. An act is recognised as recorded from a communication by its `@issuance` (3.2.1). An act without `@issuance` is evaluated as one recorded without a communication, whatever its source, so a writer who omits a required `@issuance` makes the act count in every perspective. Expectations follow their supports, which are acts. Acts recorded without a communication (self-attributed, or sourced from a party or process Item, 3.1.4) are evaluated as in the record perspective. So are corrections, detections and reconciliations, whatever their source. Begin and end acts are not read in a participant perspective; reads compute the periods in it (7.6.14). A distributed act applies at its own effective time. A later distribution of earlier evidence or acts changes the participant's account as backfill does. The result identifies what it excluded. Perspective restricts which statements and acts count; it does not restrict chronology. A milestone's publication instant, and with it the occurrence time of the Assertions at that milestone, a milestone deadline (6.2.4) and a milestone cutoff, are the same in every perspective; the publication Assertion's own property values count in a participant's view only once it was distributed to them (4.4.2). |
| `interpretation` | Optional. Either a named application interpretation, applied to every comparison of the read at every instant (5.5), or `"literal"`, which requests literal comparison (5.5.1) for every comparison of the read at every instant, whatever normalizations apply (7.3.8). No application interpretation is named `literal`. Where a rule speaks of the interpretation a frame names, a frame that requests literal comparison names literal comparison. The resolved frame returns a named interpretation, or a request for literal comparison, as given. When the frame names none, each comparison uses the interpretation that applies to it (7.3.8): the interpretation in force for its subject at the comparison's time, except that an expectation is evaluated under its own interpretation (7.6.13) and two expectations are compared under theirs (7.2.4). The resolved frame then returns the interpretation in force for the read's scope at the cutoff: for a scope Item, the one in force for that Item; for an explicit list, the one in force for every listed Item, or ambiguous (4.5.3) when they differ, listing the normalizations concerned. A resolved frame of this kind identifies the normalizations that put that interpretation in force, or that none applies, so that it is never mistaken for a frame that names the interpretation or requests literal comparison, which would apply it at every instant. Each comparison result still identifies the interpretation it applied (5.5.4). |

**4.6.2** Due work is never derived from submitted data alone. An expectation whose timing scope is reached at the cutoff is outstanding at that frame whether or not any submission exists (6.5).

**4.6.3** A historical frame answers what the record, interpreted at event time, says about that moment. A participant-perspective frame restricts statements and communication-sourced acts to what had been distributed to the participant. A withdrawal not yet distributed to them leaves the requirement in force in their view while the record view dates the withdrawal by its occurrence (6.7.5). The frame makes no claim about what anyone read or knew. Neither replays the record's state at a past recording time: corrections and recorded interpretations apply at every cutoff, normalizations and `adopt_policy` reconciliations apply from their effective times whenever they were recorded (8.4.1), and what a recorded act relied on is its recorded basis (7.5).

---

## 5. Values, omission, explicit emptiness, structured replacement, and comparison

### 5.1 The value space

**5.1.1** A property value is a JSON value: a string, a number, a boolean, `null`, an array, or an object. Arrays are ordered and may contain duplicates. Objects are unordered; an object with a duplicate key is invalid and MUST be rejected on write.

**5.1.2** Numbers are exact decimals. Every implementation MUST store exactly, without rounding, any number with at most 34 significant decimal digits whose exponent in scientific notation is between −999 and +999. Every implementation MUST reject any other number (10.2.4). A record that is valid in one implementation is therefore valid in all. The digits and exponent are those of the number's value, not its spelling: the coefficient is taken without leading or trailing zeros, so `1.50`, `15E-1` and `1.5` each have two significant digits and exponent 0, and `1` followed by forty zeros has one significant digit and exponent 40. Zero is always valid. Two spellings of one value are valid or invalid together. Numeric strings are strings.

**5.1.3** Round trip. Writing an Assertion and reading it back MUST return the same keys, the same types, the same numeric values, the same array order and multiplicity, and the same references. Normalization is limited to 5.3.2.

### 5.2 Carry-forward and omission

**5.2.1** Each named property of a subject, per source, carries forward from the Assertion that last asserted it, ordered by occurrence time (4.2.4) and, within one schedule, by ordinal where publication instants are equal or unordered (4.3.2), until a later Assertion by that source asserts it again, or an explicit withdrawal ends it (6.7). A later Assertion that omits a property does not retract it.

**5.2.2** An effective position is therefore assembled property by property, and every property in it retains the context and source of the Assertion that supplied it. A read MUST NOT present an assembled position as one submitted Assertion.

**5.2.3** Omission is distinct from a submitted blank. A field present with no value is an explicit empty assertion (5.3). A field absent from the submission is silence about that property.

**5.2.4** Reserved members are not properties and never carry forward (2.4.7).

### 5.3 Explicit emptiness

**5.3.1** `null` is a value: it asserts that the property is empty. It carries forward like any value and participates in comparison.

**5.3.2** On write, the empty string `""` is normalized to `null` at any depth of a value, except inside reference objects. No other representation is empty by implication: whitespace, placeholder words, zero, `false`, an empty array and an empty object are ordinary values. An application that treats a particular text as empty applies that interpretation before writing, or declares it as an interpretation (5.5).

**5.3.3** An explicit empty is a change when the property was previously populated by that source, and it is an answer to an information request only where an applicable interpretation declares that meaning acceptable (6.4.4).

### 5.4 Structured values

**5.4.1** A supplied object or array replaces that property's complete value. Members omitted from the new value are not inherited from the earlier one. After

```
dimensions: { width: 900, height: 2100 }   then   dimensions: { height: 2200 }
```

the current value of `dimensions` is `{ height: 2200 }`, and `width` is absent from it. The earlier value remains historical evidence.

**5.4.2** Omitting the whole property is different: `dimensions` absent from a later Assertion carries the earlier complete value forward (5.2.1).

**5.4.3** Separately named properties are separate carry-forward units. If `width` and `height` are two properties, a later Assertion of `height` alone carries `width` forward. Submitting them in the same Assertion does not couple them.

**5.4.4** A member absent from a structured value is neither an explicit empty nor a withdrawal. Whether its absence matters is decided by an applicable expectation (6.4), not by the value rule.

### 5.5 Comparison

**5.5.1** The default comparison is literal and typed: strings are equal only when identical; numbers are equal when their decimal values are equal (`1` equals `1.0`); booleans and `null` equal themselves only; arrays are equal when equal element by element in order, with duplicates counted; objects are equal when they have the same keys and equal members, in any key order; references are equal when they identify the same target: the same Item, the same Assertion with the same selectors (2.4.3), the same Connection, or the same artifact at the same edition; a reference with a selector never equals one without. A value of one type never equals a value of another type.

**5.5.2** The model infers no conversions: no unit conversion, no trimming, no case folding, no numeric coercion of strings, no synonym matching.

**5.5.3** An application MAY supply a named *interpretation* with a read. An interpretation declares domain equivalence (for example that `"90 min"` and `"1.5 h"` are equal fire ratings, or that a particular list property is a set in which order and duplicates are ignored). An interpretation can make two values equal or unequal; it cannot union successive submissions of a list, waive source or timing qualification, or rank sources. An interpretation applies to a comparison when the read's frame names it (4.6.1), when an expectation's context names it and the expectation is evaluated under its own interpretation (7.6.13, 7.6.14), including where that expectation is compared with another (7.2.4), or when a normalization puts it in force for the subject compared and neither the read's frame nor the context of an expectation compared names one (7.3.8). A read that requests literal comparison applies none (4.6.1).

**5.5.4** Every comparison result identifies the interpretation it applied, or that it applied none. When a requested interpretation is unavailable or does not cover the values compared, the result says so and reports the literal comparison as a separate, labelled result; it does not silently substitute one for the other. When values that are unequal under literal comparison are equal under an interpretation that a normalization put in force (7.3.8), the comparison is a match, not a conflict, a transition or a change, and its result reports that normalization as the reason the values match.

**5.5.5** A recorded comparison (a detection, 7.2; a review, 7.4; a reconciliation, 7.3) retains the exact Assertions compared in `@basis`, and the frame in `@frame`: its `scope`, `cutoff`, `perspective`, and the `interpretation` name and `interpretation_version` of the interpretation it applied (or `null` for none), so that the result can be reconstructed. Where the comparison named none, the interpretation it applied is the one in force (7.3.8). Where the comparison named none and the interpretation in force was ambiguous (7.3.8), `interpretation` and `interpretation_version` are `null`, and the frame also carries `normalization`: `{ "ambiguous": [ ... ] }`, listing exact references to the normalizations concerned, ordered as in 7.6.6, so that it is never read as literal comparison. Write validation checks a recorded frame's shape only, never whether it agrees with the interpretation in force (7.2.4). A detection's or reconciliation's `@frame` may also carry `policy` and `policy_version`, naming an ending policy (7.7.2, 7.7.3).

### 5.6 Read classification of a property

**5.6.1** For one source, one subject and one property at a frame, a read returns exactly one of:

| Classification | Meaning |
|---|---|
| `never_asserted` | No Assertion by that source within the frame carries the property. |
| `asserted` | A current value exists; the result carries the value (possibly `null`) and the origin Assertion. |
| `withdrawn` | The most recent Assertion carrying the property was explicitly withdrawn and nothing later re-asserted it (6.7.4). No current value. The result carries the withdrawing record. |
| `ambiguous` | Tied or unordered Assertions assert different values and no sequence evidence orders them (4.5.3). |

`withdrawn` is never serialized as `null`, and `never_asserted` is never serialized as a value.

**5.6.2** Transitions between two frames, or between two of a source's Assertions (7.1.1), compare the property's classification (5.6.1) in the first with its classification in the second. What happened between them is not examined. The first cutoff is at or before the second (4.2.5); a read given them in the other order, or given two cutoffs whose order is unspecified, returns a limitation.

| First \ Second | `asserted` | `withdrawn` | `never_asserted` |
|---|---|---|---|
| `never_asserted` | `introduced` (an explicit `null` included) | `withdrawn` | not reported |
| `asserted` | `unchanged` when the values are equal under the interpretation the comparison applies (4.6.1), including carry-forward by omission; `cleared` when the second is `null` and the first is not; otherwise `changed` (`null` to a populated value included) | `withdrawn` | cannot arise |
| `withdrawn` | `reasserted` | `unchanged` | cannot arise |

When either classification is `ambiguous`, the transition is `ambiguous`, with both classifications as candidates (4.5.3). Each side is reported as its classification: an asserted side with its value and origin, a withdrawn side with its withdrawing record. A side with no value has no origin. A value withdrawn and asserted again between the two frames is therefore `changed` or `unchanged`, never `reasserted`.

When both values are objects other than references, the result additionally lists member-level differences, one per top-level key that differs: `member_added`, `member_removed` or `member_changed`. A difference inside a nested value is `member_changed` of its top-level key. This lets a missing member be identified and addressed (6.4.2). Arrays are compared as whole values (5.4.1) and list no member differences, under any interpretation.

---

## 6. Expectations, qualification, support, fulfillment, and explicit withdrawal

### 6.1 What an expectation is

**6.1.1** An expectation is an Assertion whose context has the `expectation` role. It describes the same subject Item as the submitted Assertions it will be compared with, with the same property names, in a distinct context:

```
(Door 101, E-finish-by-next-issue, A-601)   values: { finish: "stain" }
```

**6.1.2** The `source` coordinate names the obligated source: the particular communication whose Assertions can fulfill it.

**6.1.3** When no particular communication is required, the source coordinate names an eligibility Item (3.3.2). Fulfilling evidence is then any Assertion whose source qualifies against that Item's criteria at the evidence's occurrence time.

**6.1.4** One expectation has one obligated source. A requirement that two named documents each show the same value is two expectations, one per source, each fulfilled by its own evidence. One act may establish both (6.3) and one act may withdraw both (6.7).

**6.1.5** An expectation is retained after fulfillment, after withdrawal and after it ends. It remains referenceable by its exact triple and inspectable in historical frames.

### 6.2 Timing scope

**6.2.1** The expectation context's `timing` member declares when qualifying evidence must occur, when the scope is reached, and when outstanding work is overdue. Each is evaluated at the frame's cutoff:

| `timing.type` | Members | Qualifying evidence | Scope reached | Overdue |
|---|---|---|---|---|
| `at` | `milestone` | An Assertion whose context is exactly that milestone. | When the milestone is published. | From publication, while unfulfilled. |
| `during` | `phase` | An Assertion whose occurrence time falls within the phase: at or after its start and before its end. | At the phase's start. | From the phase's end, while unfulfilled. |
| `by` | `instant` or `milestone` | An Assertion whose occurrence time is at or before the deadline (inclusive). Evidence after the deadline still qualifies, with its lateness reported (6.5.4). | At establishment (6.3.3). | After the deadline, while unfulfilled. |
| `any` | none | Any occurrence time. | At establishment. | Never. |

**6.2.2** `fresh: true` additionally requires the evidence's occurrence time to be at or after the establishment time of the in-force period in which the property is fulfilled (6.3.3, 6.5.1). With `fresh: false` (the default), existing applicable evidence qualifies, and an expectation about the current state is satisfied at its establishment when such evidence exists.

**6.2.3** An optional named issuance is expressed as `by` or `any` timing together with an informative `preferred_issuance` reference. The preference has no effect on qualification: if the named issuance never occurs, another qualifying submission from the obligated source fulfills the expectation, subject to the stated timing.

**6.2.4** The context's optional `schedule` names the schedule whose milestones or phase the timing refers to. A deadline given as a milestone is the milestone's publication instant (4.4.1); before publication the deadline has not been reached.

### 6.3 Establishment, support and reaffirmation

**6.3.1** An expectation is in force at an instant while at least one support covers at least one of its properties (6.3.3). A support is an Assertion whose values carry `@action: "establish"` or `@action: "reaffirm"` with an exact reference to the expectation in `@targets`, or a review whose `@establishes` or `@reaffirms` lists the expectation (7.4.1). A support whose target, or whose `@establishes` or `@reaffirms` entry, carries a property selector (2.4.3) covers only that property. A support takes effect at its context's occurrence time, or at `@effective` (8.4):

```
(Instruction 1, Meeting 14 May, Minutes 14 May)
values: { "@action": "establish",
          "@targets": [ { "@ref": "assertion", "item": "door-101", "context": "e-finish-next-issue", "source": "a-601" } ],
          "@basis":   [ { "@ref": "artifact", "id": "minutes-2026-05-14.pdf", "edition": "issued 2026-05-15" } ],
          "@issuance": { "@ref": "item", "id": "minutes-14-may-issued-2026-05-15" },
          "@party":   { "@ref": "item", "id": "client" } }
```

**6.3.2** Supports are independent. Withdrawing one support, or one support's coverage of one property (6.7.2), leaves the expectation or property in force while another support covers it. A later decision that reaffirms an unchanged expectation references the same expectation; it does not create a duplicate.

**6.3.3** The writer of a support states whether it establishes a new expectation or reaffirms an exact existing one; the model does not infer reuse from equal values. Both have the same effect on standing; the declared intent is retained for history. A support covers an expectation, or a property of it, from the support's effective time (8.4.1) until a withdrawal of the support, or of the expectation, takes effect (6.7.2). An *in-force period* for a property is a continuous period in which at least one support covers it. Its *establishment time* is the effective time at which it begins. If every support has been withdrawn and a later support covers the property again, a new in-force period begins.

**6.3.4** Competing expectations coexist. Two in-force expectations about the same subject and property that require unequal values are a conflict, whatever their timing, found by the same comparison as any conflict (7.1.5). Recording order elects no winner and nothing supersedes automatically.

### 6.4 Value requirements

**6.4.1** Each property of an expectation's values is one of:

| Form | Meaning |
|---|---|
| a plain value, e.g. `finish: "stain"` | A required value. Evidence qualifies when its value equals this under the expectation's interpretation (5.5, 7.6.13). |
| `{ "@ask": true }` | An information request. Evidence qualifies when it supplies a non-empty value for the property. |
| `{ "@ask": true, "@suggested": 90 }` | An information request with a suggestion. Any qualifying answer fulfills it, including one that differs from the suggestion; the suggestion, the answer and their difference are retained. |

**6.4.2** A required value is a complete value under 5.4: a required `dimensions: { width: 900, height: 2100 }` is not met by `{ height: 2100 }`.

**6.4.3** A suggestion is not a requirement. It never keeps a request open on its own and never establishes a violated requirement.

**6.4.4** An explicit empty answer (`null`) does not fulfill an information request unless the interpretation applied to the expectation (7.6.13) declares that an empty value is an acceptable answer for that request (for example "not rated"). An empty answer never fulfills a required non-empty value. A required `null` is met by an explicit `null`.

**6.4.5** An expectation about several properties is evaluated per property. A property that no support has covered at or before the cutoff (`not_in_force`, 6.6.1) does not count toward the expectation's overall standing. The expectation remains open while any covered property is `outstanding` or `not_yet_due`; it is closed when every covered property is `fulfilled` or `withdrawn`; it is reported as fulfilled only when every covered property is `fulfilled` (6.6.2). An expectation with no covered property is none of these; it is not in force (6.3.1).

### 6.5 Fulfillment

**6.5.1** Fulfillment is derived from the retained record. A property is fulfilled at its *qualifying moment*: the earliest instant t, at or before the frame's cutoff, at which all of the following hold:

- (a) the expectation is in force for the property at t (6.3.3);
- (b) an Assertion about the subject meets all of these conditions. It comes from the obligated source, or from a source that qualifies against the eligibility Item at the Assertion's occurrence time (3.3.2). Its occurrence time is at or before t. It falls within the timing scope (6.2.1). It meets the value requirement in the corrected account (8.3.3), under the expectation's interpretation at t (7.6.13);
- (c) where `fresh` is set, that Assertion's occurrence time is at or after the establishment time of the in-force period containing t;
- (d) that Assertion has not been withdrawn with effect at or before t. For `by` and `any` timing, it must also not have been superseded for the property, by a later Assertion of the same source, at or before t. For `at` and `during` timing the evidence is fixed by its target, so later supersession does not disqualify it.

The qualifying moment is the latest of the evidence's occurrence time, the establishment time of the in-force period in which the evidence stands, and, for evidence that meets the value requirement only under an interpretation that a normalization put in force (7.3.8), the instant from which that interpretation is in force for the subject, when those instants are ordered (4.2.5). Such evidence meets the requirement only from that instant, so its qualifying moment is never earlier, and fulfillment never reaches back before the normalization. When two of them are unordered and every condition holds under either order, the qualifying moment is the one whose interval ends later, which is the earliest instant that both are at or before (4.2.5). The standing is not ambiguous on that account. When whether the conditions hold depends on instants whose order is unspecified, the standing is `ambiguous` (4.5.3). The result references the fulfilling Assertion exactly; where several qualify at t, it is the earliest by occurrence time, and where several earliest share one occurrence time with no sequence evidence ordering them (4.5.2), it references all of them (7.6.6). Where the evidence meets the requirement only under an interpretation that a normalization put in force, the result also references that normalization, beside the evidence (5.5.4). Later events never move the qualifying moment (6.5.2). It changes only when the account of what happened before it changes. That happens through a correction (8.3.3), through backfilled evidence that occurred earlier, or, in a participant perspective, through a later distribution of earlier evidence or acts (4.6.1).

**6.5.2** Fulfillment, once it occurs, is not reversed by anything that happens after the qualifying moment: a later contrary Assertion, withdrawal of the fulfilling Assertion, withdrawal of the expectation or of its supports, or a later lapse and re-establishment. The property reads as fulfilled at every later frame, with its fulfilling evidence, while the source's current position reads from its later Assertions. Only a correction showing that the fulfilling Assertion misrecorded what the source said (8.3) removes it as evidence, because a correction applies at every cutoff.

**6.5.3** A frame earlier than the qualifying moment shows the property outstanding or not yet due. Fulfillment does not backdate.

**6.5.4** With `by` timing, evidence after the deadline fulfills the property as `late`, and the result reports the deadline, the evidence's occurrence time and their difference. The difference is derived; it is not stored as a separate record. When the evidence and the deadline are unordered (4.2.5), the property is still fulfilled, because late evidence qualifies, and its timeliness is `ambiguous`. With `at`, `during` or `any` timing, qualifying evidence lies within the timing scope by 6.2.1, so a fulfilled property is `on_time`. Lateness and its difference apply only to `by` timing.

**6.5.5** Evidence does not qualify when no instant satisfies 6.5.1 for it. Examples: evidence withdrawn before the expectation came into force, whatever the timing; evidence for `by` or `any` timing superseded for the property before then; evidence whose corrected account shows a different value or no such Assertion (8.3.3). A withdrawal that takes effect after the qualifying moment does not disqualify it (6.5.2). Evidence that has no occurrence time (4.2.4), such as a statement at a milestone that is not yet published, satisfies no instant while it has none. Until then the property's standing is derived without it, `not_yet_due` or `outstanding` by its timing scope (6.2.1), and no ending is recorded for it (7.6.6). Once the milestone's publication gives the evidence an occurrence time, it qualifies under 6.5.1, and the property is fulfilled at its qualifying moment.

**6.5.6** Where a property is not yet fulfilled, the expectation is in force and the obligated source has withdrawn its latest value, the property remains open: `outstanding` once its timing scope is reached (6.2.1), `not_yet_due` before then. In both cases the source position reads `withdrawn`, and the read reports the missing information as actionable once due (5.6.1). Where the property was already fulfilled, it stays fulfilled; the source position reads `withdrawn`, and any continuing need for the information is separate work: another expectation (6.1) or a story (§7). The model never supplies a replacement value.

### 6.6 Standing of a property

**6.6.1** At a frame, each property of an expectation has exactly one standing:

| Standing | Condition |
|---|---|
| `not_in_force` | No support had covered the property at or before the cutoff (6.3.3). This includes an expectation whose only supports were withdrawn before they took effect; the result lists those withdrawals. |
| `fulfilled` | Its qualifying moment (6.5.1) is at or before the cutoff. Carries `on_time`, `late` or, when the evidence and the deadline are unordered, `ambiguous` (6.5.4), the fulfilling evidence and, where the evidence meets the requirement only under an interpretation that a normalization put in force, that normalization (6.5.1). |
| `withdrawn` | Not fulfilled before the withdrawal took effect, and at the cutoff no support covers the property because the property, the expectation, or every support covering it was withdrawn (6.7.2). Carries the withdrawing records: for each support that covered the property during its last in-force period (6.3.3), the withdrawal that ended that coverage, whether it targeted the support, the support's coverage of the property, the property, or the expectation (6.7.2). |
| `outstanding` | Covered by a support, not fulfilled, and its timing scope reached (6.2.1). Carries `overdue` when the overdue condition holds. |
| `not_yet_due` | Covered by a support, not fulfilled, and its timing scope not yet reached. |
| `ambiguous` | The standing depends on an order that is unspecified (4.5.3). Carries the candidate standings and the records concerned. |

When one property meets more than one ending, the first ending to take effect governs its standing, and the later ending is reported alongside it: a property fulfilled on Tuesday whose requirement is withdrawn on Thursday reads `fulfilled`, with the later withdrawal noted.

**6.6.2** Mixed standings are reported as mixed. A property withdrawn after another was fulfilled does not read as fulfilled, and an expectation with no remaining open work is not reported as "all fulfilled" when some properties were withdrawn.

### 6.7 Explicit withdrawal

**6.7.1** Withdrawal is an Assertion whose values carry `@action: "withdraw"` and a fixed list of exact targets:

```
(Withdrawal 3, Meeting 2 June, Minutes 2 June)
values: { "@action": "withdraw",
          "@targets": [ { "@ref": "assertion", "item": "door-101", "context": "e-finish-next-issue", "source": "a-601", "property": "finish" } ],
          "@effective": "2026-06-05-07:00",
          "@basis":   [ { "@ref": "artifact", "id": "minutes-2026-06-02.pdf", "edition": "issued 2026-06-03" } ],
          "@issuance": { "@ref": "item", "id": "minutes-2-june-issued-2026-06-03" },
          "@party":   { "@ref": "item", "id": "owner" },
          note: "Finish to be resolved under the revised specification." }
```

**6.7.2** A target may be: a whole Assertion; a named property of an Assertion; one act's support of one expectation; or one act's support of one property of an expectation (2.4.3).

- Withdrawing a statement, or a property of it, ends that statement (6.7.4).
- Withdrawing a support, or a support's coverage of one property, ends that support only. The expectation or property remains in force while another support covers it.
- Withdrawing an expectation, or one of its properties, ends that requirement outright, whatever other supports exist. It withdraws every support that covers the requirement at the withdrawal's effective time. It also withdraws every support that occurred at or before the withdrawal and takes effect later. Only a support that occurs after the withdrawal and takes effect after the withdrawal's effective time begins a new in-force period (6.3.3). The other properties remain open and are reported as the remaining open work. Once every property has been withdrawn, the expectation is not in force, although its supports are not themselves withdrawn.

**6.7.3** One withdrawal may target several Assertions about several Items. The withdrawal's own triple has one Item in each coordinate; the multiplicity is in `@targets`. The target set is fixed when the withdrawal is recorded; it never grows to include later records.

**6.7.4** A withdrawal may target a statement. When the most recent Assertion carrying a property is withdrawn and no later Assertion re-asserts it, the property has no current value from that source (5.6.1 `withdrawn`). An older superseded value is not revived; reinstating it requires a new Assertion. Withdrawing an already superseded Assertion changes no current value.

**6.7.5** A withdrawal takes effect at its context's occurrence time, or at `@effective` when stated (8.4). It is dated by when it occurred, never by when a recipient opened or read it. Effective time follows the same instant rules as any context (4.2).

**6.7.6** Withdrawal is an ending distinct from fulfillment. It does not assert a value, does not establish agreement, and does not fulfill anything. It records why only as optional free text; the model defines no vocabulary of reasons and no distinct withdrawal types.

**6.7.7** Suppressing a story from an attention view (9.5) is not a withdrawal and ends nothing.

**6.7.8 Authority.** The model applies every recorded withdrawal according to its targets, scope and effective time. It does not evaluate whether the withdrawing party had standing to withdraw the target; that is application policy. A withdrawal is an attributed Assertion, and every read that reports its effect identifies it.

**6.7.9 What can be withdrawn.** A withdrawal may target statements (other than publication, distribution and self-description Assertions, 4.4.1), `@eligible` criteria (3.3.2), expectations, supports, reviews, ignores and extension acts (10.4.1).

- Withdrawing a review returns the story to `unreviewed` from the withdrawal's effective time, unless another review of the story remains in effect at that time (9.5.2). Where the review was a support (6.3.1), the withdrawal also ends that support. A change story that a review ended is open and awaiting review again from then only when no other review of it remains in effect at that time, and the interpretation in force then leaves its revision changing a property (7.2.7, 7.6.2). Where no other review remains in effect and that interpretation leaves the revision changing no property, the story stays ended, and from then its ending is the normalization that put that interpretation in force (7.6.2).
- Withdrawing an ignore ends it.
- The following are never withdrawn: detections, reconciliations (`revise` and `adopt_policy` included), normalizations (7.3.8), corrections, withdrawals, begin and end acts (7.6), disconnect and reconnect acts, and publication, distribution and self-description Assertions. A misrecorded one is corrected (8.3), except that a begin or end act, or a `revise`, is never corrected: a transition that changes is revised (7.6.10). One that was intended when it occurred and is later judged mistaken is answered by a new act: a new statement or support, a reconnect or disconnect, a new distribution, a later `adopt_policy`, or a later normalization.
- A withdrawn statement or requirement is reinstated by a new Assertion or a new support, never by withdrawing the withdrawal.

---

## 7. Changes, disagreements, recorded review, related stories, and reconstructed history

### 7.1 Two comparison paths

**7.1.1** Holding subject and property fixed, a *change* compares one source's applicable position across two frames or two of its own Assertions. A *conflict* compares two sides' applicable values: two sources' positions at one cutoff, or two expectations in force at once (7.1.5).

**7.1.2** One new issuance supports both. When a consultant issues a revised set on Thursday, comparing it with the consultant's prior applicable position reports changes; comparing it with the architect's documentation applicable on Thursday reports conflicts. The two comparisons answer different questions, and both answers are returned when asked. A Wednesday comparison recorded before the Thursday issue is not altered by it.

**7.1.3** Both comparisons assemble applicable values per property under 5.2 and respect withdrawals under 6.7.4 and corrections under 8.3.3. They apply the frame's interpretation or, where it names none, the interpretation that applies (4.6.1, 7.3.8), which for two expectations is their own (7.2.4). They retain each property's origin Assertion. Recency grants no authority: the newest document is not preferred, and a value is not assumed to originate in the newest document.

**7.1.4** Silence is not disagreement. A property one source never asserted does not conflict with another source's value. An explicit empty does: `null` against a populated value is ordinary inequality.

**7.1.5 Expectations are compared the same way.** An expectation is an ordinary Assertion, and incompatible expectations are found by the same comparison. Two expectations about one subject conflict on a property when both are in force for it and not yet fulfilled for it at the same time, and require values that are unequal under their interpretations (7.2.4), whatever their timing: an expectation of "a" at 50% CD and one of "b" at 100% CD conflict. The model does not judge whether the difference is intended sequencing. A party that considers it intended may ignore the story (9.5.6) or review it (7.4); neither changes its standing. When one expectation was fulfilled before the other came into force, the two never conflict. Only required values (6.4.1) are compared; information requests and suggestions are not. The two sides are the two expectation Assertions, which may name the same obligated source or different ones. Comparing an expectation with submitted evidence is fulfillment (6.5), never a conflict, and expected content never enters a submitted-value comparison (9.2.2).

### 7.2 Stories

**7.2.1** A story is an Item that records one detected disagreement or one detected revision, so that its evidence, review and ending can be followed over time. A story is opened by a *detection*: an Assertion on the story Item, self-attributed or sourced from the process that ran it (3.1.4), whose values carry `@action: "detect"`; `@story`, naming its `kind` (`conflict` or `change`), its `subject` and, for a conflict, its `property`; the compared Assertions in `@basis`; and the frame in `@frame`:

```
(Story 17, Detection 2026-05-14T16:02-07:00, Story 17)
values: { "@action": "detect",
          "@story": { "kind": "conflict", "subject": { "@ref": "item", "id": "door-101" }, "property": "finish" },
          "@basis": [ { "@ref": "assertion", "item": "door-101", "context": "arch-100dd", "source": "a-601", "property": "finish" },
                      { "@ref": "assertion", "item": "door-101", "context": "arch-100dd", "source": "spec-09-91", "property": "finish" } ],
          "@frame": { "scope": { "@ref": "item", "id": "project-scope" }, "cutoff": "2026-05-14T16:00-07:00",
                      "perspective": "record", "interpretation": null, "interpretation_version": null } }
```

**7.2.2 Conflict stories.** A conflict story concerns one subject, one property and one unordered pair of sides: two sources, or two expectation Assertions (7.1.5). The pair identifies the *family* of stories about that disagreement; it does not identify a story. Several stories may exist in one family over time (7.3). A story's identity is its Item.

**7.2.3 Change stories.** A change story concerns one source's revision of one subject at one issuance. Its detection lists in `@transitions` each property transition, each entry giving the `property`, the `transition` (5.6.2) and exact references to the `prior` and `new` Assertions. Every entry's `new` references the same Assertion: the revised Assertion of that issuance. The story count is the number of change stories: one for each revision detected, and one more each time a change of the interpretation in force makes a revision a change again after a normalization ended its latest change story (7.3.8); the transition count is the number of properties listed. A read reports the two counts separately. Properties whose value is unchanged (including by carry-forward) are not transitions of the revision: they are not listed in `@transitions` and are not counted. A changes read (9.4.1) still reports them, as `unchanged` (5.6.2).

**7.2.4 Interval and interpretation.** A story's event-time interval is derived from its basis evidence, in the corrected account (8.3.3), not from when its detection was recorded. A conflict story begins at the later of its two sides' times of first disagreement and lasts until its ending (7.2.6). A statement side's time is its occurrence time. An expectation side's time is the establishment time of its in-force period for the property (6.3.3). A change story begins at the occurrence time of the revised Assertion and lasts until its ending (7.2.7). A story appears in event-time reads at every cutoff within its interval, whenever it was detected. A story's interpretation at an instant is the interpretation in force for its subject at that instant (7.3.8), and its comparisons at each instant use it, including the judgement whether a side has issued a different value or its evidence has changed (7.2.5, 7.3.1, 7.3.5): a value equal to the earlier one under that interpretation is not a change. A conflict story whose sides are two expectations instead compares each side under that expectation's own interpretation at the instant (7.6.13). When the two are the same, as when both contexts name one interpretation or neither names any, that one is the story's interpretation. When they differ, the story's interpretation is the pair: the sides are equal when they are equal under both, unequal when they are unequal under both, and otherwise their comparison is ambiguous (4.5.3), listing the two expectations. A detection's `@frame` records the interpretation under which the detection was made (5.5.5), which for the detections that maintenance records is the one in force at their cutoff (7.2.8); it does not set the story's interpretation. A detection whose `@frame` names an interpretation other than the story's is valid, and its frame is recorded basis only (7.5.1). A read under a different interpretation reports, alongside the story, whether its sides match under that interpretation, without changing the story's standing. The interpretation in force is set only by normalizations (7.3.8), never by a reader's choice.

**7.2.5 Unreviewed evidence change.** When the evidence of an unreviewed conflict story changes (one side issues a different value and the sides still disagree, with no ending in between), the story continues. The new evidence is recorded as a new dated detection Assertion on the same story Item, with the new basis. The earlier detection is not overwritten. Two detections do not make two stories.

**7.2.6 Endings of a conflict story.** A conflict story ends at the first of:

- (a) *alignment*: the two sides' applicable values become equal under the story's interpretation (7.2.4), at the occurrence time of the Assertion that produced alignment, which is the ending record. Where they are equal only under an interpretation that a normalization put in force, the ending also cites that normalization (5.5.4);
- (b) *withdrawal of a side*: a statement side's applicable value is withdrawn (6.7.4), or an expectation side ceases to be in force for the property (6.7.2), at that withdrawal's effective time. The withdrawal is the ending record. Withdrawing an Assertion that is not the side's applicable value ends nothing. When a side's applicable value comes to be withdrawn only because a correction changed the account (8.3.3), the correction case below applies instead;
- (c) *fulfillment of an expectation side*: the property of either expectation is fulfilled (6.5.1), at its qualifying moment. Fulfillment is evaluated as for the expectation's own unit, under the expectation's interpretation (7.6.13), so the story and the expectation property end at the same instant. The fulfilling Assertion is the ending record. The other expectation keeps its own standing as ordinary work;
- (d) *normalization*: the story's interpretation changes while the sides disagree, because the interpretation in force for the subject changes (7.3.8), and under its interpretation from then (7.2.4) their applicable values are equal, at the instant of that change. The ending record is the normalization whose interpretation is in force from then, or, where none is in force from then because the subject left the normalized scope, the normalization in force until then (as for a beginning, 7.6.4). Where an Assertion at the same instant also produces equality, the ending is (a), citing that normalization where the values are equal only under its interpretation.

Endings and intervals are evaluated in the corrected account (8.3.3). Four cases follow:

- A correction can show that the sides never disagreed within the story's interval. The story then reads ended at every cutoff, with an empty interval and the correction as its ending record. 9.5.2 reports the correction's own time as provenance, not as an ending time. The detection keeps its recorded basis.
- A correction can leave a side with no applicable value from some instant, for example by showing that an Assertion which superseded a withdrawn value never existed. The story then ends at that instant (in that example, the withdrawal's effective time), with the correction as its ending record, of kind `correction`.
- A correction can leave the sides disagreeing in the corrected account. The story then continues, and its interval is recomputed under 7.2.4. A correction is not a new issuance for 7.2.5.
- The record that ended a story can itself be corrected away. The story then did not end at that record. When both stories are unreviewed, a story opened because of that ending is joined to it by a `continuous` reconciliation (7.3.4). Otherwise the later story remains a related story (7.3.1), and a `boundary` reconciliation records the reviewed story's recomputed interval (7.3.5).

A story whose sides, at the instant at which its interval would begin under literal comparison (7.2.4), are equal under its interpretation then never disagreed under its interpretation. It has no period, an empty interval and the ending of 7.6.12: as its ending record, the normalization that put that interpretation in force at that instant, or, where the expectations' own interpretations alone make the sides equal, those expectations. Where a normalization is its ending record, it reads `not_started` at a cutoff before that instant and ended from that instant; where the expectations are, it reads ended at every cutoff (7.6.12, 7.6.14). This is decided at that instant, and nothing later changes it. Like any ended story, it stays ended, and a later disagreement of its sides, through later evidence or a later normalization, is a related story (7.3.2, 7.3.8).

Permanent removal cannot affect a recorded story, because its basis and ending records have downstream impact (8.5.2). Once ended in the corrected account, a conflict story stays ended; a later disagreement is a new related story (7.3.2). A review never ends a conflict story (7.4.2), and neither does an ignore (9.5.6).

**7.2.7 Ending of a change story.** A change story ends at the effective time of a review that targets it and has not been withdrawn (7.4). The review is either an approval of the change (`@outcome: "no_change"`) or a directive for a different desired value (`@outcome: "change_required"`). On a change story, a directive MUST carry `@establishes` or `@reaffirms` naming the expectation for that value. The story ends even while that expectation remains open; the expectation's standing is its own (§6). Until such a review, and again from the effective time of a withdrawal that leaves no such review in effect (6.7.9), the change story is open and awaiting review, except where the interpretation in force at that withdrawal's effective time leaves its revision changing no property. The story then does not reopen, and from that instant its ending is the normalization that put that interpretation in force (7.6.2). In the corrected account (8.3.3), a change story whose revision no longer changes any property reads ended, with the correction as its ending record; one whose transitions change continues with its transitions recomputed. Likewise, a change story whose revision backfilled evidence shows to change no property reads ended, with the backfilled Assertion as its ending record (7.3.7). A change story's transitions are compared under the interpretation in force at its revised Assertion's occurrence time (7.2.4), or, for a related change story of 7.3.8, at its beginning. One whose revision changes a property under literal comparison but none under that interpretation also reads ended, with the normalization that put that interpretation in force as its ending record. When more than one of these endings applies, 7.6.12 says which governs. A change story that is open when the interpretation in force for its subject changes (7.3.8), and whose revision changes no property under the interpretation in force from then, ends at that instant, with the normalization whose interpretation is in force from then as its ending record. A change story whose ending is a normalization stays ended; when a later change of the interpretation in force makes its revision change a property again, that change is a related change story, awaiting review (7.3.8). A correction that changes a change story's transitions requires no recorded reconciliation: reads recompute the transitions in the corrected account (8.3.3), and a story read reports the corrections that apply to their prior and new Assertions.

**7.2.8 Detection and maintenance.** Reads that compute comparisons (9.4) do not create stories. Which comparisons an implementation first records as stories, and when, is application policy. Once a story is recorded, the implementation MUST maintain its family. Maintenance applies when any of these kinds of write occurs:

- a write that changes a side of a recorded conflict story: a statement or its backfill, a support, withdrawal or fulfillment that brings an expectation side into or out of force, or a correction (8.3);
- a write that changes a recorded change story's transitions: a backfilled issuance between its prior and revised Assertions (7.3.7);
- a write that changes the interpretation in force for a recorded story's subject at some instant: a normalization, or a Connection created, disconnected, reconnected or corrected that changes which normalizations apply to the subject (7.3.8). For a recorded change story whose ending is a normalization, maintenance applies to its revision as to a family: a related change story attaches to the latest change story recorded for that revision.

The implementation MUST then, in the same operation or before answering any later story read, record what the change requires: the continuation detection of 7.2.5, the related story of 7.3.1 or 7.3.2, the reconciliation of 7.3.3, 7.3.4, 7.3.5 or 7.3.7, or the related change story of 7.3.7 or 7.3.8. Continuations and related stories attach to the family's latest story that is not `continued_in` another; after a join (7.3.4), that is the representative. What a write requires is determined by the change that write makes to the event-time account. Maintenance records a continuation for the evidence the write brought into an unreviewed story (7.2.5). It records none for evidence changes that occurred before the story was first recorded or that an earlier write already covered, since a story's interval derives from its evidence, not from its detections (7.2.4). A reconciliation attaches to the story whose interval the change affects. Once recorded, a story's standing is derived (9.5).

Maintenance also records the begin and end acts of every unit of work a write affects, and revises them when the write changes them (7.6.9, 7.6.10). This applies to every expectation property from its first support, whether or not any story is recorded.

### 7.3 Related stories, review boundaries and reconciliation

**7.3.1 After review.** Once a conflict story has a review that has not been withdrawn (7.4), changed evidence does not continue it. The new disagreement is a new story in the same family, whose detection carries `@relates_to` with an exact reference to the prior story's detection. The reviewed story keeps its review on the evidence the review cited. Where a rule calls for an exact reference to a prior story's detection (`@relates_to` here and in 7.3.2, 7.3.3, 7.3.7 and 7.3.8, or a reconciliation's `@targets`), any of that story's detections identifies the story. Records generated by maintenance reference its first detection (7.2.1).

- *Backfilled changes.* A change that occurred before the review's effective time but was recorded after it also opens the related story when it changes the current comparison evidence (7.3.5). That story's interval begins at the review's effective time, so no cutoff shows two unreviewed stories for one disagreement.
- *Ties.* A change tied with the review's effective time, without `@after` evidence, is treated as after the review, and the story's standing at that instant is ambiguous (7.3.6).
- *Withdrawn reviews.* After a review is withdrawn, and no other review of the story remains in effect at the withdrawal's effective time (6.7.9), 7.2.5 governs changes from that time. They continue the family's latest story, and an earlier story stays as recorded. While another review of the story remains in effect, changed evidence still opens a related story as above.

**7.3.2 Return after an ending.** When a conflict story has ended (7.2.6) and the sides later disagree again, the later disagreement is a new story related to the earlier one in the same way.

**7.3.3 Backfilled evidence that splits a story.** When evidence added later shows that the sides agreed at a time inside what had been recorded as one continuous story, the event-time account becomes two related stories: the first ended at the agreement, the second began at the later disagreement. The implementation records a *reconciliation*:

```
(Reconciliation 4, Reconciliation 2026-05-22T09:10-07:00, Reconciliation 4)
values: { "@action": "reconcile",
          "@targets": [ { "@ref": "assertion", ...detection of Story 17... } ],
          "@outcome": "split",
          "@basis":   [ { "@ref": "assertion", ...the Tuesday evidence entered Friday... } ],
          "@successor": { "@ref": "item", "id": "story-21" },
          "@frame":   { ... } }
```

and opens the second story with `@relates_to` pointing at the first. Existing detections are retained unchanged. The boundaries are the evidence's occurrence times, derived under 7.2.4 and 7.2.6; the reconciliation's own time is provenance (8.4.1) and is not a boundary.

**7.3.4 Backfilled evidence that joins stories.** When evidence added later shows that an apparent intervening ending never occurred, two unreviewed stories are one continuous disagreement in the event-time account. The implementation records this reconciliation (7.2.8). It carries `@outcome: "continuous"`, targets both detections, and names the continuing story Item in `@representative`, which MUST be the story whose interval begins earliest. Both story Items and their detections remain. The other story reads `continued_in` the representative (9.5.2); it is not ended, and reads of open stories and attention count the continuous disagreement once.

**7.3.5 Reviewed stories are not merged.** A reconciliation never moves a review to evidence it did not cite, never merges a reviewed story into another, and never undoes an ending recorded by a review-cited basis.

- Backfilled evidence is evidence that occurred before a review's effective time but was recorded after it (7.3.1). If such evidence changes the event-time boundaries of a reviewed story (its start or its ending) without a disagreement on evidence the review did not cite, the reconciliation carries `@outcome: "boundary"` and the review stands. This includes evidence showing that the sides aligned before the review: the story ended at the alignment, and no story is opened.
- The *current comparison evidence* of a reviewed story has changed when its sides disagree at the cutoff and their applicable values differ from the values its review cited. Then 7.3.1 applies, and a new related story is opened, beginning no earlier than the review's effective time.
- If backfilled evidence shows that the sides aligned after the reviewed disagreement and later disagreed again, the later disagreement is a new related unreviewed story (7.3.2).

**7.3.6 Tied events.** Distinct real events keep distinct detections even when their instants are equal. A review and a revision recorded at the same instant are ordered only by `@after` evidence (4.5.2); otherwise the story's standing at that instant is reported as ambiguous. At that instant, the related story's open dimension reads `ambiguous`, and reads that list stories return it among their ambiguous entries (9.5.3, 9.5.4). The reviewed story's standing is unaffected. At later cutoffs, the change is after the review (7.3.1).

**7.3.7 Backfilled evidence inside a change.** When a backfilled issuance falls between the prior and revised Assertions of a recorded change story, the implementation records a reconciliation with `@outcome: "reconstructed"`. The reconciliation targets the change story's detection. It lists in `@transitions` the reconstructed transitions of the targeted revision, now from the backfilled issuance, with exact prior and new Assertions, omitting equal-value transitions. When none remains, the targeted revision changes no property: the reconciliation is still recorded, with an empty `@transitions`, and the targeted story has no period (7.2.7, 7.6.12). The backfilled issuance's own revision is a separate change story (7.2.3), related to the targeted one by `@relates_to` and awaiting review until an approval or directive (7.2.7). Where several change stories are recorded for the targeted revision (7.3.8), such a reconciliation is recorded for each of them, and the backfilled issuance's revision is still one change story, related to the latest of them (7.2.8). The targeted story keeps its detection and any review, and its counts do not grow. A story read of the targeted change story (9.5.1) reports the reconstructed transitions and identifies the reconciliation they come from. The backfilled issuance's own transitions are reported by its related change story. The changes read (9.4.1) compares positions and is not affected by stories (9.4.3). A review is never presented as having considered the backfilled issuance (7.4.5).

**7.3.8 Normalization.** A *normalization* records that, from when it takes effect, the values in a scope are compared under an application interpretation. It is an act whose values carry `@action: "reinterpret"`; exactly one target in `@targets`, an Item reference naming a scope Item (2.1.5); and `@interpretation`, naming the interpretation as `{ "name", "version" }`, or `null` for literal comparison (5.5.1):

```
(Normalization 2, Coordination meeting 2026-06-10, Minutes 10 June)
values: { "@action": "reinterpret",
          "@targets": [ { "@ref": "item", "id": "project" } ],
          "@interpretation": { "name": "fire-rating", "version": "2" },
          "@basis":   [ { "@ref": "artifact", "id": "minutes-2026-06-10.pdf", "edition": "issued 2026-06-11" } ],
          "@issuance": { "@ref": "item", "id": "minutes-10-june-issued-2026-06-11" },
          "@party":   { "@ref": "item", "id": "owner" } }
```

The interpretation's rules belong to the application (5.5.3); the act records only which interpretation applies. An implementation records a normalization only when it has the interpretation the normalization names, so that it can perform the maintenance the normalization requires (*Recording*, below). A normalization naming an interpretation the implementation does not have is rejected (10.2.9). An implementation reads as recorded (7.6.14) a normalization already in its store whose interpretation it does not have: one that another implementation, which had the interpretation, recorded there, or one that it recorded itself while it still had the interpretation. A normalization is attributed like any act (3.2.1). It takes effect at its context's occurrence time, or at `@effective` (8.4.1). It is an event in the work, not a recorded interpretation: it applies from its effective time, and the record's account before then is never rewritten by it. It is never withdrawn (6.7.9). A later normalization of the same scope Item supersedes it from that later act's own effective time; a misrecorded one is corrected (8.3).

- *Interpretation in force.* A normalization *applies to* an Item at an instant when the Item is a member of the normalization's scope at that instant (2.1.5, with the Connections active then). For one scope Item, the interpretation in force at an instant t is the one named by its latest normalization effective at or before t. When several of its normalizations are tied or unordered at t, with no `@after` evidence ordering them (4.5.2), and they name different interpretations, it is ambiguous (4.5.3); when they name the same one, that one is in force. For any Item at t, the interpretation in force is literal comparison when no normalization effective at or before t applies to it. Otherwise it is the interpretation in force at t for each scope Item whose normalizations apply to it, when those are the same, and it is ambiguous, listing the normalizations concerned, when they differ. Two interpretations are the same when they have the same name and version. The normalizations that *put* an interpretation in force for an Item at t are, for each such scope Item, its latest normalization effective at or before t, or each of its tied latest ones. Where a rule cites the normalization that put an interpretation in force, or the one in force, and several did, it cites all of them, as a list in the order of 7.6.6. A comparison about a subject at an instant uses the interpretation in force for that subject then, with three exceptions. A read whose frame names an interpretation, or requests literal comparison, uses that (4.6.1). An expectation whose context names an interpretation uses it at every instant wherever the expectation is evaluated under its own interpretation, as it is by every read whose frame names none (7.6.13, 7.6.14). Two expectations are compared under their own interpretations, in their story and by every read whose frame names none (7.2.4, 9.4.2). A normalization governs only what names no interpretation of its own. In a participant perspective, a normalization recorded from a communication counts only once that communication's issuance has been distributed to the participant, as any such act does (4.6.1). It then applies from its own effective time, and the interpretation in force in that perspective is the one these rules give from the normalizations that count in it.
- *When it takes effect.* Let T be an instant at which the interpretation in force for a subject becomes the normalization's: its effective time, or a later instant at which the subject comes under it, by joining its scope or by leaving a scope whose differing interpretation had made the interpretation in force ambiguous. Every story about the subject whose baseline period is open at T (7.6.3), and whose sides match under its interpretation from T (7.2.4), ends at T: a conflict story under 7.2.6(d), and a change story whose revision changes no property under the interpretation in force from T under 7.2.7. Its baseline end act has cause `normalization`, with as its record the normalization or normalizations that put that interpretation in force (7.6.5). Stories that still differ continue, and are compared under their interpretation from T. Stories that had ended at or before T, including stories with no period (7.6.12), are untouched. An expectation property whose period is open at T, whose interpretation is the one in force (7.6.13), and whose evidence meets its requirement only under the interpretation in force from T, is fulfilled no earlier than T, citing the normalization beside the evidence (6.5.1). Before T the earlier interpretation governs, so no transition before T changes.
- *After it.* From T, values whose comparison uses the interpretation in force alone (7.2.4, 7.6.13), and that are equal under it, are neither a conflict nor a transition, and a comparison that matches only because of that interpretation reports the normalization as the reason (5.5.4). An interpretation can also make values unequal (5.5.3). Sides that become unequal at T begin to disagree at T, and where their story had ended, the disagreement is a related story (7.3.2), whose beginning cites the normalization (7.6.4). Likewise, take the latest change story recorded for a revision (7.2.8), whose baseline ending is a normalization, as a period ending (7.2.7, 7.6.2) or as its no-period ending (7.6.12). When, at a later instant, the interpretation in force for its subject changes, through a later normalization, including one that returns to literal comparison, or through the subject joining or leaving a normalized scope, and the revision changes a property under the interpretation in force from then, maintenance records a related change story. Its detection carries `@relates_to` with an exact reference to the closed story's detection, and lists in `@transitions` the revision's transitions under the interpretation in force from that instant. Its period begins at that instant, it awaits review until an approval or a directive (7.2.7), and its beginning cites the normalization (7.6.4). The closed story stays ended, as a conflict story does (7.3.2), and nothing before that instant changes.
- *Recording.* Recording a normalization is a write that maintenance answers (7.2.8, 7.6.9). In the same operation, or before any later read that depends on it, the implementation records the end acts, at T, of the stories and expectation properties it ends, and every other transition it changes. This maintenance covers the units whose subjects are members of the normalization's scope at some instant from its effective time. It is bounded by that scope (9.10), not by the whole store, although for a project scope it may reach every unit of the project.

### 7.4 Recorded review

**7.4.1** A review is an Assertion whose values carry `@action: "review"`, exact targets, a basis, a frame and an outcome:

```
(Decision 6, Owner review 2026-05-20, Minutes 20 May)
values: { "@action": "review",
          "@targets": [ { "@ref": "assertion", ...detection of Story 17... } ],
          "@basis":   [ ...the exact Assertions the reviewer saw, and the minutes as an artifact reference... ],
          "@frame":   { ...the frame the reviewer saw... },
          "@outcome": "no_change",
          "@party":   { "@ref": "item", "id": "owner" },
          positions: { owner: "accepts the schedule as issued", architect: "objects; specification governs" },
          rationale: "Finish to be confirmed in the field." }
```

`@outcome` is `change_required` or `no_change`. A review of either outcome MAY carry `@establishes` and `@reaffirms`, listing the expectations it establishes or reaffirms, in which case it is also their support (6.3.1). On a change story, a `change_required` review MUST carry one of them (7.2.7). A review targets a story when its `@targets` include the story Item or any of the story's detections.

**7.4.2** On a conflict story, a review completes review. It does not end the story, does not make the sources agree, and does not imply that every party accepted the outcome; the parties' positions are retained as recorded. A conflict story that was reviewed with `no_change` remains a disagreement in disagreement reads and leaves pending-review reads. On a change story, a review is the story's ending (7.2.7).

**7.4.3** A review does not fulfill or withdraw any expectation. Independent obligations keep their own standing.

**7.4.4** A rationale SHOULD be recorded. Its absence does not make a review invalid; an application may require one.

**7.4.5** The basis of a review is the evidence it cites, retained by exact reference, together with its recorded frame. Later evidence that changes the event-time account (7.3) does not change what the review cited, and the review is never presented as having considered evidence recorded after it.

### 7.5 Recorded basis and reconstructed history

**7.5.1** Two accounts coexist and both are readable: the *event-time account*, derived from all retained evidence interpreted at occurrence time, with corrections and recorded interpretations applied at every cutoff and normalizations from their effective times (8.4.1); and each *recorded basis*, the evidence and frame a detection, review or reconciliation cited when it was made.

**7.5.2** Reads return reconstructed history separately from recorded bases, and never transfer an acknowledgment, review or decision from the evidence it cited to evidence it did not.

**7.5.3** A participant is not assumed to have had evidence before it was distributed to them. A participant-perspective frame (4.6.1) excludes evidence not distributed to them by the cutoff.

### 7.6 Recorded beginnings and endings

**7.6.1 Units of work.** Every piece of work the record tracks is a *unit of work*, with a recorded beginning and end. A unit is one of:

- a conflict story, identified by its story Item (7.2.2);
- a change story, identified by its story Item (7.2.3);
- one property of an expectation, identified by the expectation's exact triple and the property name. No Item is created for it; an act refers to it by an exact reference to the expectation with a `property` selector (2.4.3).

A story is a unit once it is recorded (7.2.8). An Item whose detections do not form one conflict story or one change story (7.2.2, 7.2.3) is not a unit; reads report it among their limitations (9.6.1). An expectation property is a unit from the first support that covers it (6.3.1).

**7.6.2 Open periods.** In the event-time account, each unit has a sequence of *open periods*. A period begins at an instant and either ends at an instant or remains open. The rules of §6 and §7 define every period, in the corrected account (8.3.3). Recording the periods (7.6.9) changes none of them.

- *Conflict story.* One period: its interval, from its beginning (7.2.4) to its ending (7.2.6). A story whose interval is empty has no period (7.6.12).
- *Change story.* Its first period begins at the occurrence time of the revised Assertion (7.2.4). A period ends at the earliest instant, at or after its beginning, at which a review that targets the story (7.4.1) is in effect and not withdrawn (6.7.9); that review ends it (7.2.7). A review already in effect when a period begins therefore ends it at its beginning. A period also ends, if that is earlier, at the instant from which the interpretation in force leaves the revision changing no property, with the normalization as its ending record (7.2.7, 7.3.8). A period so ended is the story's last: a later normalization leaves stories that had already ended untouched, and a later change of the interpretation in force that makes the revision a change again is a related change story (7.3.8). Once a period has ended, the next begins at the effective time of the first withdrawal of a review that leaves no review of the story in effect (6.7.9, 7.2.7). No period begins while another review remains in effect. Where the interpretation in force at that withdrawal's effective time leaves the revision changing no property, the period that begins then also ends then, with the normalization that put that interpretation in force as its ending record. That period has no length, is never open (7.6.3) and is the story's last: the story's ending is the review up to that instant, and the normalization from it (7.6.14). A change story whose revision a correction, backfilled evidence (7.3.7) or the interpretation in force at its occurrence time leaves changing no property has no period (7.2.7, 7.6.12). A related change story of 7.3.8 begins its first period at the instant from which the interpretation in force makes the revision change a property again.
- *Expectation property.* A period begins with each in-force period of the property (6.3.3), at its establishment time. It ends at the property's qualifying moment (6.5.1), or when the in-force period ends by withdrawal (6.7.2), whichever governs under 6.6.1. Fulfillment is terminal (6.5.2): once the property is fulfilled, a later in-force period begins no period. A support withdrawn before it took effect begins no period (6.6.1). An expectation that a correction shows `erroneous` or `relocated` contributes nothing to corrected reads (8.3.1), so its properties have no period.

**7.6.3 Open at a cutoff.** A unit is *open* at a cutoff when one of its periods began at or before the cutoff (4.2.5) and had not ended at or before it. When that depends on an order that is unspecified, the unit's open standing is ambiguous (4.5.3). Only beginnings and endings are recorded: whether an open expectation property is `outstanding` or `not_yet_due`, and whether it is overdue, is evaluated at the read from its timing scope (6.2.1).

**7.6.4 Begin acts.** A *begin act* is an Assertion whose values carry `@action: "begin"`, exactly one target in `@targets`, and `@period` (7.6.6). It records the beginning of one period of one unit. Its target is the unit: for a story, the story Item or any of its detections; for an expectation property, an exact reference to the expectation with a `property` selector naming the property. Its `@period` is `null` (7.6.6), or carries `at`, `record` and `cause`, where `cause` is one of:

- `disagreement`, for a conflict story. The record is the side Assertion, or the support, whose time begins the interval (7.2.4). Where the interval begins at a review's effective time because the change that opened it occurred before the review (7.3.1), it is that review. Where that change is tied with the review's effective time, with no `@after` evidence ordering them (7.3.1, 7.3.6), the record is that side Assertion, the disagreeing document's statement, and the review is listed in `tied` (7.6.6). Where the interval begins because the interpretation in force for the subject changed (7.3.8), the record is the normalization whose interpretation is in force from then, or, where none is in force from then because the subject left the normalized scope, the normalization in force until then.
- `revision`, for the first period of a change story. The record is the revised Assertion. For a related change story of 7.3.8, the record is the normalization whose interpretation is in force from its beginning, or, where none is in force from then because the subject left the normalized scope, the normalization in force until then.
- `review_withdrawn`, for a later period of a change story. The record is the withdrawal whose taking effect left no review of the story in effect (6.7.9, 7.6.2).
- `in_force`, for an expectation property. The record is the support whose effective time begins the in-force period (6.3.3).

A begin act names no ending policy. Periods begin as the model derives them; a policy decides only when they end (7.7.4).

**7.6.5 End acts.** An *end act* is an Assertion whose values carry `@action: "end"`, exactly one target in `@targets`, and `@period` (7.6.6). It records the end of one period. Its target is the begin act of that period, so that a period is open while its begin act has no end act that ends it. Its `@period` carries `at`, `record`, `cause` and `policy`. `policy` is `null` for an ending under the baseline, or `{ "name", "version" }` naming an ending policy (7.7). The baseline causes, with their records, are:

- for a conflict story: `alignment`, `withdrawal`, `fulfillment`, `normalization` or `correction`, with the ending record of 7.2.6; and, for a conflict story between two expectations with no period (7.6.12), `interpretation`, with those expectations;
- for a change story: `review`, with the review, or `normalization`, with the normalization (7.2.7); and, for a change story with no period (7.6.12), `reconstructed`, with the backfilled Assertion (7.3.7), `correction`, with the correction, or `normalization`, with the normalization;
- for an expectation property: `fulfillment`, at the qualifying moment, with the fulfilling Assertion (6.5.1); or `withdrawal`, at the effective time of the withdrawal whose taking effect ended the in-force period, with that withdrawal (6.6.1, 6.7.2).

An expectation property's `fulfillment` end also carries `timeliness` (`on_time`, `late` or `ambiguous`, 6.5.4) and `interpretation`: the interpretation under which the property was fulfilled, which is the expectation's interpretation at its qualifying moment (7.6.13), `null` for literal comparison or `{ "name", "version" }`. An `alignment` or `fulfillment` end whose record matches only under an interpretation that a normalization put in force also carries `matched_by`: an exact reference to that normalization, or to each of them where several put the interpretation in force (5.5.4, 6.5.1, 7.2.6, 7.6.6). The `normalization` end act of a story with no period also carries `since` (7.6.12). An end act under a non-baseline policy carries a cause that the policy defines (7.7.5). A begin act has at most one end act for each policy, the baseline included; an ending that changes is a revision of that end act (7.6.10).

**7.6.6 Period content.** The `@period` of a begin act, an end act or a revision (7.6.10) has one of four forms:

- *Definite.* An object carrying the members that 7.6.4 or 7.6.5 names, and `tied` where it applies. `at` is an instant (4.2.1), written as in the record that supplies it: an `@effective`, a `@published` or a context's `at`. It is `null` only in the end act of a story with no period, where the ending has no time (7.6.12); such an end act with cause `normalization` also carries `since`, an instant written in the same way (7.6.12). `record` is an exact Assertion reference without selectors (2.4.1), or a list of them: where several records cause one transition (below), and in the `interpretation` ending of 7.6.12, whose record is the two expectations, ordered as below. `matched_by`, where 7.6.5 gives it, is an exact Assertion reference without selectors, or, where several normalizations put the interpretation in force (7.3.8), a list of them in the order below.
- *`null`.* In a begin act, there is no period: the transition does not occur (7.6.10), the story's interval is empty (7.6.12), or the story continues in another (7.6.11). In a revision of an end act, the period does not end.
- *Ambiguous.* Where the derivation's result is ambiguous (4.5.3, 9.6.1), whether through an unspecified order, through criteria or publication instants of different sources that disagree (3.3.2, 4.4.1), through interpretations in force that differ (7.3.8), or through two expectations whose own interpretations disagree on whether their values are equal (7.2.4): `{ "ambiguous": [ ... ], "records": [ ... ] }`. `ambiguous` lists at least two distinct candidates. Each is a definite content, or `null` where under that candidate the transition does not occur. `records` lists exact references to the records concerned. A read evaluates the unit under each combination of candidates and returns the common result, or else the result as ambiguous, with its candidates (4.5.3).
- *Limitation.* Where the derivation yields a limitation (9.6.1): `{ "limitation": <reason>, "records": [ ... ] }`. The reasons are `relocated_reference`, where the result depends on a reference that a relocation left dangling, listing the correction and the uncorrected record (8.3.7); `no_occurrence_time`, listing the Assertions that have none (4.2.4); and `interpretation_unavailable`, where the unit's interpretation is not available to the implementation, which also carries `interpretation`, naming it (5.5.4, 7.6.14). A read reports the unit among its limitations. An expectation property's ending is never a `no_occurrence_time` limitation: evidence with no occurrence time gives the property no ending until its milestone is published, and the property is meanwhile `not_yet_due` or `outstanding` (6.5.5).

An end act's `@period` carries `policy` beside an ambiguous or limitation content too.

When several records cause one transition, being at one instant with no sequence evidence ordering them (4.5.2), and every order of them gives the transition the same time and cause, the transition cites all of them: `record` is the list of their exact references, ordered by `item` id, then `context` id, then `source` id, comparing ids by Unicode code point. Two sides reissued at the same milestone that together produce alignment, two sides that began disagreeing at the same milestone, and two qualifying Assertions at one issuance that both fulfill a property are examples. The list's order is for determinism only: it is not sequence evidence, and it ranks nothing (I-12). A transition caused by one record gives that record alone, not a list. Where an order of the tied records would change the transition's time or cause, or whether it occurs, as with two tied Assertions of one source that assert different values (4.5.3), the content is ambiguous instead.

Where a story's standing is ambiguous at the instant of a transition because the transition is tied with another record and no sequence evidence orders them (7.3.1, 7.3.6), the definite content carries `tied`: exact references to the records it is tied with. At a cutoff at which `at` is at or before the cutoff but not before it (4.2.5), whether the transition has occurred is ambiguous. Once `at` is before the cutoff, it has occurred.

**7.6.7 Where the acts are recorded.** A story's begin and end acts are Assertions on the story Item, self-attributed like the detections that maintenance records: `(story, <event context>, story)` (7.2.1, 3.1.4). An expectation property whose first period is nested under exactly one story (7.6.15), because a review of that story began it, is part of that story, its middle: its begin and end acts, and the revisions of them (7.6.10), are Assertions on that story Item in the same form, `(story, <event context>, story)`. Any other expectation property, such as one established directly from minutes (1.4), or one whose first period was begun by a review that targets several stories and so is nested under each, keeps acts of its own: each begin or end act is an Assertion on its own act Item, self-attributed like a reconciliation (7.3.3). The location is fixed when the property's first act is recorded, and every later act of the property, in any period, is recorded in the same place, even if backfill or a correction later changes which support began its first period. Where, when that first act is recorded, it is ambiguous whether the first period has exactly one parent, or the first period's beginning is a limitation (7.6.6), the property keeps acts of its own. Each act's context is a dated event, whose time is the act's provenance (7.6.8). An end act recorded under an ending policy (7.7.5) may be placed in any of these ways, or may name as its source the process that recorded it (3.1.4). Reads find every begin and end act, and every revision, by its target, so where an act is recorded never changes a result: reads, nesting (7.6.15) and what remains (9.5.7) mean the same wherever a property's acts are held.

**7.6.8 Recorded interpretations.** Begin and end acts are recorded interpretations of the record, like detections and the story reconciliations of 7.3 (8.4.1). Their content applies to event-time reads at every cutoff, and their own occurrence time is provenance, never a boundary. They carry no `@effective` (10.2.7). They are never withdrawn (6.7.9) and never targeted by a correction; a transition that changes is revised (7.6.10). They never contribute values (2.4.7, 9.2.2).

**7.6.9 Recording.** The implementation records the baseline begin and end acts as part of maintenance (7.2.8). It does so in the same operation as the write that requires them, or before answering any later read that depends on them. A write requires recording when it can change a unit's derived periods. Such writes are:

- a statement, or its backfill;
- a support, a withdrawal, a review, or a review's withdrawal;
- a correction of an Assertion, an Item or a Connection (8.3);
- a milestone publication, which fixes occurrence times (4.4.1), and a change to `@eligible` criteria (3.3.2);
- a detection: recording a story records its periods;
- a reconciliation: `continuous`, `split`, `boundary`, `reconstructed` or `adopt_policy`;
- a normalization, and a Connection created, disconnected, reconnected or corrected where that changes which normalizations apply to an Item (7.3.8).

Maintenance derives the periods of the units the write affects and compares them with those units' applicable recorded transitions, as the transition check does (9.5.8). It records what differs: a new begin or end act for a derived transition that no act matches, and a revision (7.6.10) of an act whose applicable content differs from the derived content, or that no derived transition matches while its applicable content is not `null`. Every expectation property is maintained from its first support; it needs no detection. Recording a story remains application policy (7.2.8); once a story is recorded, its periods are maintained. Under a non-baseline ending policy, the end acts naming that policy are recorded by whatever implements it (7.7.5). Maintenance never revises a recorded transition because its derivation needs an interpretation the implementation does not have (7.6.14). Maintenance, like story maintenance, is keyed by the affected subjects, sources, expectations and stories, and it MUST NOT traverse the whole store (9.10). A normalization, or a Connection write that changes which normalizations apply, affects the units whose subjects are members of the scope concerned (7.3.8). Its maintenance is bounded by that scope and reaches no record outside it, although for a project scope it may reach every unit of the project.

**7.6.10 Revision.** A write may change a recorded transition in the event-time account: its time or `since` (7.6.12), cause, record, tie, ambiguity or limitation, or whether it occurs at all. Backfill, a correction and a normalization (7.3.8), including one recorded after the transitions it changes, can change baseline transitions. So can any write of 7.6.9 when a transition was recorded ahead of its time: an end recorded at a withdrawal's later effective time changes when evidence written meanwhile fulfills the property first. An `adopt_policy` revises no recorded content: from its effective time it changes which policy's end act applies to a period, and the newly governing policy's end acts are recorded for the periods open then (7.7.3). Each change is recorded by a reconciliation with `@outcome: "revise"`. A revision has exactly one target, a begin or end act. Its `@period` is the revised content, in a form of 7.6.6, or `null` when the transition no longer occurs. A revision of an end act keeps its policy. Nothing is overwritten.

- A transition that newly occurs is recorded as a new act. A derived period that no begin act matches gets a new begin act, even when an earlier begin act of the unit was revised to `null`. A period's ending under a policy gets a new end act when its begin act has none for that policy; otherwise the existing end act is revised, including one that an earlier revision set to `null`.
- The applicable content of a begin or end act is that of its latest revision by occurrence time, or the act's own content when it has none. A tie without `@after` evidence is ambiguous, as for corrections (8.3.4).
- An implementation orders the revisions it records. A revision of an act that already has one is given an occurrence time that is not before that revision's, and, when the two are equal or unordered (4.2.5), carries `@after` referencing it (4.5.2).
- Revising baseline acts is maintenance. The end acts recorded under an ending policy are revised in the same way by whatever records them (7.7.5).

**7.6.11 Story reconciliations.** The story reconciliations keep their meaning (7.3), and the begin and end acts they imply are recorded or revised with them:

- `split` (7.3.3): the first story's period ends at the agreement, by a new end act or by revising its end act. The successor's begin act is recorded, and its end act where the first story's former ending now ends the successor.
- `continuous` (7.3.4): the representative's period covers the continuous disagreement, so its end act at the apparent ending is revised to `null` or to the later ending. The story that reads `continued_in` has no period of its own. Its begin act's content is `null`, by revision or as recorded, and any end act it had is revised to `null`. Its standing reads `continued_in` the representative (9.5.2), and reads count the disagreement once, as the representative (9.5.3).
- `boundary` (7.3.5): the reviewed story's begin or end act is revised to its recomputed interval.
- `reconstructed` (7.3.7): the targeted change story's periods do not change, unless its revision now changes no property, when it has no period (7.6.12). The related change story's begin act is recorded.

A normalization is not a reconciliation. The begin and end acts it implies are recorded or revised by maintenance like those of any write (7.3.8, 7.6.9).

**7.6.12 No period.** A story whose interval is empty (7.2.6), and a change story whose revision a correction, backfilled evidence or the interpretation in force leaves changing no property (7.2.7, 7.3.7), has no period. Its begin act's applicable content is `null`: revised to `null`, or recorded so when the story is first recorded in that state. One baseline end act targets that begin act and gives the ending. Its `at` is always `null`, because an ending without a period has no time:

- for backfilled evidence, cause `reconstructed`, with the backfilled Assertion as its record: the `@basis` of the latest `reconstructed` reconciliation that targets the story and lists no transition (7.2.7, 7.3.7);
- for a correction, cause `correction`, with the correction as its record (7.2.6, 7.2.7);
- for a normalization, cause `normalization`, with as its record the normalization or normalizations that put the story's interpretation in force: for a conflict story, at the instant at which its interval would begin under literal comparison (7.2.6), for each side compared under the interpretation in force (7.2.4); for a change story, at its revised Assertion's occurrence time (7.2.7). The end act also carries `since`: that instant;
- for a conflict story between two expectations whose contexts both name an interpretation, and whose sides, at that instant, are equal under those interpretations (7.2.4, 7.6.13), cause `interpretation`, with the two expectations as its record (7.6.6). Where either context names none, that side is compared under the interpretation in force, so the normalization case above applies instead.

When more than one of these applies to one story, the first that applies in that order governs. `reconstructed` applies when such a reconciliation exists. `correction` applies when, without the corrections, the story would have a period under its interpretation, or would have one under literal comparison while in the corrected account it has none under literal comparison. `normalization` and `interpretation` apply when, in the corrected account, the story would have a period under literal comparison, each in the case stated above.

Reads report the story as ended at every cutoff with an empty interval (9.5.2), except that a story whose ending is a normalization reads `not_started` at a cutoff before its `since`, and ended at a cutoff that its `since` is at or before (4.2.5). Where neither holds, its open dimension is ambiguous (4.5.3). A normalization is an event in the work (7.3.8), and before that instant nothing had begun; corrections, backfilled evidence and the interpretations that expectation contexts name apply at every cutoff. For a correction, reads report the correction's own time as provenance, not as an ending time (7.2.6). For backfilled evidence, a normalization and an interpretation, they report no ending time. A policy decides only when a period ends (7.7.4), so a story with no period has this ending under every policy.

**7.6.13 Interpretation of an expectation.** An expectation's context may name an interpretation in its `@context`, as `interpretation: { "name", "version" }` (4.1.1). An expectation's interpretation is the one its context names, at every instant, and no normalization changes it. When its context names none, it is, at each instant, the interpretation in force for its subject then (7.3.8), which is literal comparison (5.5.1) until a normalization applies. The expectation's recorded fulfillment uses its interpretation at each instant (6.5.1), and so does every read whose frame names no interpretation (7.6.14). A conflict story with the expectation as a side takes its fulfillment ending from the same evaluation (7.2.6(c)), so the story and the expectation property cannot end at different instants on that account. Two expectations are compared with each other under their own interpretations (7.2.4).

**7.6.14 Reads of recorded transitions.** In the record perspective, a read that reports whether a unit is open or ended reads the unit's applicable recorded transitions under its ending policy (7.7), instead of deriving them, when it evaluates the unit under the unit's own interpretation: the story's (7.2.4) or the expectation's (7.6.13). A read evaluates every story under its own interpretation. It evaluates an expectation under its own when its frame names no interpretation, whether the expectation's context names one or not, or when its frame names the interpretation that the expectation's context names. A frame that names another interpretation, or requests literal comparison (4.6.1), evaluates the expectation under that one at every instant. These reads are 9.3.1 to 9.3.3, 9.5.1 to 9.5.4, and 9.5.7.

- A story is `open` when it is open under its policy (7.6.3). It is `ended` when a period began at or before the cutoff and none is open, or when it has no period and an end act gives its ending (7.6.12), from that end act's `since` where it carries one. It is `not_started` when it has a period and none began at or before the cutoff, or when it has no period and the cutoff is before its end act's `since` (7.6.12). It is `continued_in` its representative under 7.3.4, except at a cutoff before the representative's period begins, where it is `not_started` (9.5.2). Its ending is that of its latest period that began at or before the cutoff: the end act of the policy governing that period's ending (7.7.3) gives the ending kind (the act's cause) and the ending record, and its time is the later of that act's `at` and the instant from which that policy has governed the unit without interruption up to that ending (7.7.3); the baseline end act gives the baseline ending.
- An expectation property's standing (6.6.1) is read from its baseline transitions. It is `fulfilled` when a period ended by fulfillment at or before the cutoff. Otherwise, consider its latest period that began at or before the cutoff: the property is `withdrawn` when that period ended by withdrawal at or before the cutoff, and `outstanding` or `not_yet_due`, by its timing scope (6.2.1), when that period is open. It is `not_in_force` when no period began at or before the cutoff. Whether the property is open work is decided under its policy (7.7.4).
- The other dimensions are derived as before: review, disagreement and attention (9.5.2), timing and lateness (6.2, 6.5.4), and the records each standing carries (6.6.1).

By I-17 the result equals the derivation, and an implementation MAY compute it instead, except for an ending under a non-baseline policy, which is read from its end acts (7.7.5), and for a unit whose interpretation the implementation does not have. In a participant perspective, and for an expectation read under an interpretation other than its own, reads compute the derivation of §6 and §7 and read no begin or end act. They compute an expectation that the frame evaluates under another interpretation (above) under that interpretation, and every other unit, stories included, under its own interpretation as it is in the read's perspective (7.3.8). Such a result applies the baseline endings, names the unit's ending policy, and identifies the interpretation that produced it (5.5.4). A story is always read under its own interpretation (7.2.4): a frame interpretation never changes how its standing is read, and the read reports whether the story's sides match under the frame's (9.5.1).

Where a unit's own interpretation at any instant, a story's (7.2.4) or an expectation's (7.6.13), is an application interpretation (5.5.3) that the implementation does not have, because an expectation's context names it or a normalization recorded elsewhere, or while the implementation had it, puts it in force (7.3.8), the implementation cannot derive the unit's transitions. One rule covers every result that needs that interpretation:

- *Recorded results are read as recorded.* A read that evaluates the unit under its own interpretation, including one whose frame names that interpretation, reads the unit's recorded transitions as recorded, as it reads the end acts of a policy it does not implement (7.7.5). A unit that it first records in that state gets a begin act whose content is the `interpretation_unavailable` limitation (7.6.6), and reads list the unit among their limitations. Its maintenance never revises the unit's transitions on that account (7.6.9), and records for the unit no story record (7.2.8) whose need depends on that interpretation. Its transition check lists the unit's begin and end acts as unverified (9.5.8).
- *Results it would have to compute are limitations.* Every other result that needs the interpretation is the `interpretation_unavailable` limitation (9.6.1), never a literal substitute: a conflict story's disagreement dimension, whether a story's sides match under a read's interpretation, a comparison read, a computed read in a participant perspective or under another interpretation, and the removal impact test for the unit, whose plan is then refused (8.5.2, 10.3).

I-17 holds only where the interpretation is available.

**7.6.15 Nesting.** An expectation property's period is *nested* under a story when a review of that story (7.4.1) that establishes or reaffirms the expectation, covering the property, took effect at the period's beginning, and so began it (6.3.3). That story is the period's *parent*; a review that targets several stories gives the period several parents. Stories have no parent. A story related through `@relates_to` (7.3.1, 7.3.2, 7.3.7, 7.3.8) succeeds the earlier story and is never its child. A period keeps its parent after the parent has ended, so a directive's open expectation is read beneath the change story that the directive ended (9.5.7). A property whose first period has exactly one parent is recorded on that story (7.6.7); nesting is read from the periods, not from where the acts are held.

### 7.7 Ending policies

**7.7.1 What a policy is.** An *ending policy* decides when each period of a unit ends. A policy is named and versioned, and its rules belong to the application, as an interpretation's do (5.5.3); the model records only which policy applies. The *baseline* policy is the kind-specific endings of §6 and §7 (7.6.5). It is named by `null`, and every implementation supports it.

**7.7.2 Where a unit's policy is named.** A story's policy is named in its first detection's `@frame`, by `policy` (the name) and `policy_version`. Both are absent, or both `null`, for the baseline. Continuation detections, and the detections and reconciliations that maintenance generates for the story under 7.3, carry in their `@frame` the policy governing the story at their cutoff. Begin acts name no policy (7.6.4), and a baseline end act names `null` (7.6.5). An expectation's policy is named in its context's `@context`, as `policy: { "name", "version" }` (4.1.1). Where no policy is named, the baseline applies. An `adopt_policy` changes it from its effective time (7.7.3): the policy governing a unit at an instant is the one named by its latest `adopt_policy` effective at or before that instant or, when it has none, the one named as above. When several of a unit's `adopt_policy` acts are tied or unordered, with no `@after` evidence ordering them (4.5.2), so that the latest is unspecified, and they name different policies, the policy governing the unit from then is ambiguous (4.5.3) among the policies they name; when they name the same policy, that one governs. A result that depends on an ambiguous governing policy is evaluated under each candidate, and is ambiguous where the candidates give different results, listing the tied acts. A read that reports a unit's ending policy reports the one governing it at the cutoff, or, where that is ambiguous, its candidates and the tied acts.

**7.7.3 Changing a unit's policy.** Changing the policy of a recorded unit is a recorded act, never a reader's choice. It is a reconciliation with `@outcome: "adopt_policy"` and exactly one target: a detection of the story, or the expectation. Its `@frame` names the policy by `policy` and `policy_version`; `null` for both adopts the baseline. It takes effect when it is made, at its context's occurrence time or at `@effective` (8.4.1), and it never rewrites an ending that occurred before then. Let T be its effective time:

- A period that had ended at or before T, under the policy then governing the unit, keeps that ending.
- A period open at T (7.6.3) is governed by the newly adopted policy from T, as is every period that begins later. It ends at the earliest instant at or after T at which the new policy's ending holds; where that ending already held before T, it ends at T.
- Each end act gives its own policy's ending of the period, and its content does not depend on when that policy governs (7.6.5). A period's ending under the unit's policies is therefore read from the end act of the policy governing the unit when the period ends, at the later of that act's `at` and the instant from which that policy has governed the unit without interruption up to that ending (7.6.14). A period's status at a cutoff before an `adopt_policy` takes effect is therefore never changed by it.
- The end acts of the newly governing policy are recorded for the periods it governs: those open at T and those that begin later (7.7.5). End acts of a policy that does not govern a period's ending stay recorded and do not apply to that period (9.5.8).

**7.7.4 What a policy may and may not do.** A policy decides only when a period ends. Periods begin as the model derives them (7.6.2), and a policy never changes a derived fact: whether sides disagree, whether evidence fulfills a requirement, when sides align, or what was reviewed. The endings of §6 and §7 are the baseline's, and so are their statements that an act does not end a unit, such as a review of a conflict story (7.2.6, 7.4.2). That an ignore ends nothing holds under every policy: a policy may not use an ignore, or any other attention preference (9.5.6), as the cause of an ending, and no policy end act gives an ignore as its record (10.2.9). A unit's ending under another policy is that policy's, recorded in its end acts (7.7.5).

- The baseline transitions are always recorded (7.6.9) and always reported (9.3.1, 9.5.1).
- A story ended under its policy while its sides still disagree reads `disagreeing` (9.5.2).
- A fulfilled property reads `fulfilled`, with its evidence, even while its policy keeps the unit open.
- A period is open under its unit's policies until the end act of the policy governing it ends it (7.7.3). While a non-baseline policy governs, a period that no end act naming that policy ends is open.

**7.7.5 Policy end acts.** Under a non-baseline policy, the end acts naming it are recorded by whatever implements the policy: the application, or the implementation for a policy it implements. Each carries the policy and a cause that the policy defines, in a form of 7.6.6. The model validates their shape, that their target is the begin act of a period that the policy governs at some instant (7.7.3), or is a candidate to govern where the governing policy is ambiguous (7.7.2), that no other end act naming that policy targets the same begin act, and that their content gives no ignore as a `record` (7.7.4, 10.2.9). Their correctness under the policy is the application's (I-17), except that an implementation that implements the policy rejects an explicit end act naming it, or a `revise` of one, whose content differs from its own derivation of that policy (10.2.9). Reading a recorded policy ending needs no policy code: an implementation that does not implement a unit's policy still reads the unit's recorded end acts, and its transition check lists them as unverified (9.5.8).

---

## 8. Writes, genuine revisions, error correction, deletion, and structural lifecycle

### 8.1 Ordinary writes

**8.1.1 Insert.** Writing an Assertion whose triple is unoccupied records it after validation (10.2).

**8.1.2 Identical replay.** Writing an Assertion whose triple is occupied by a record with identical content is a successful no-op with no effect. Content is identical when `values` are equal under literal comparison (5.5.1) after normalization (5.3.2), including every reserved member. Domain equivalence under an interpretation is not identity.

**8.1.3 Changed content at an occupied triple is rejected.** An ordinary write MUST NOT replace, merge into, or patch an existing Assertion. The implementation returns an explicit `occupied` failure identifying the existing record. Omitting properties in the incoming write is not permission to merge.

**8.1.4** A genuine revision by a source is a new Assertion at a new context: the dated event or milestone publication of the revised issuance. The earlier Assertion remains the source's position at its own context.

**8.1.5 Item creation.** Creating an Item records its `id`, `kind`, optional `label` and `definition`, after validation (10.2.3). The definition is never changed afterwards; a misdescribed definition is corrected (8.3.8). Creating an Item whose `id` already exists is a successful no-op when its `kind`, `label` and `definition` equal the existing Item's under literal comparison (5.5.1); otherwise it is rejected with an explicit `occupied` failure identifying the existing Item. Creation never replaces or merges an Item.

### 8.2 Revision is not correction

**8.2.1** Two cases are distinct and MUST be recorded differently:

| Case | What happened | Record |
|---|---|---|
| Genuine revision | The source issued changed testimony, or an instruction genuinely changed. | A new Assertion at the revision's own context (8.1.4); for a changed requirement, a new expectation and, where applicable, withdrawal of the old one (6.7). |
| Misrecording | The source did not change; the record misrepresented what the source said: wrong value, wrong property, wrong source or context. | A correction (8.3), or, when nothing yet depends on the record and the user explicitly directs it, permanent removal (8.5). |

**8.2.2** Correcting a misrecording never fabricates a source issuance. The real communication's edition and occurrence time are preserved; the correction's own time is the time of the correction.

**8.2.3** An instruction that was correct when issued and later ceases to apply is withdrawn (6.7). It is neither revised in place nor treated as a misrecording.

### 8.3 Correction

**8.3.1** A correction is an Assertion whose values carry `@action: "correct"`, exactly one target, and an outcome:

```
(Correction 9, Correction 2026-05-15T10:30-07:00, Import-review-log)
values: { "@action": "correct",
          "@targets":  [ { "@ref": "assertion", "item": "door-101", "context": "arch-100dd", "source": "a-601" } ],
          "@outcome":  "replace",
          "@corrected": { finish: "paint", hardware: "HW-2", dimensions: { width: 900, height: 2100 } },
          "@basis":    [ { "@ref": "artifact", "id": "a-601-rev-3.pdf", "edition": "rev 3" } ],
          reason: "Height dropped during extraction; see sheet 12." }
```

| `@outcome` | Meaning |
|---|---|
| `replace` | The record exists at the right coordinates but its content was misrecorded. `@corrected` carries the complete corrected `values`. |
| `erroneous` | The record should not exist (a duplicate, an entry that no communication supports). It contributes nothing to corrected reads. |
| `relocated` | The record exists but at the wrong coordinates. `@corrected` carries an exact reference to the replacement Assertion written at the correct coordinates. The original contributes nothing to corrected reads. The replacement contributes on its own terms: a statement from its occurrence time, an expectation through its supports. The two never contribute together. |

**8.3.2 The original is unchanged.** A correction never modifies the target; a Connection's materialized properties are recomputed (8.6.6). An exact read of the target returns its recorded content together with the corrections that target it (9.2.1).

**8.3.3 Corrected reads.** Every read that computes effective values, comparisons, fulfillment, detection or standing applies every applicable correction at every cutoff, before carry-forward and comparison. The corrected account replaces the misrecorded one for the whole period in which the original would have applied. A misrecorded latest value therefore exposes the real earlier Assertion, and an erroneous record is never evidence at any frame. The correction's own time is provenance: it is reported with the result and is never a boundary. What the record showed before the correction remains available through exact reads (9.2.1) and through the recorded basis of any act that cited the original (8.3.6).

**8.3.4 Several corrections.** When several corrections target one record, the applicable one is the latest by occurrence time; a tie without `@after` evidence is ambiguous. A correction that is itself mistaken is corrected in the same way, since a correction may target a correction. Corrections are never withdrawn (6.7.9).

**8.3.5** A correction is not a source position. It never appears as a value in a submitted-value read. Its source is the party or process Item that made the correction, or the document that shows the error, not the communication being corrected and never a recording principal (3.2.2).

**8.3.6** Reviews that cited the original keep their basis. A review is never rebound to corrected content; a read of the review shows what it cited and that a correction now applies.

**8.3.7 References to a relocated or erroneous original.** References are never redirected (2.4.1). A record that references a relocated or erroneous original keeps that exact reference. A reference to an erroneous original has no effect, because that original is not in the corrected account. For a relocated original, only *effective* references matter: the `@targets` of supports, withdrawals, ignores and reviews, and `@establishes`, `@reaffirms` and `@after`. A read whose result depends on such a reference returns a `limitation` in place of that result. The limitation names the correction and the uncorrected record, and holds until that record is itself corrected with `replace` to reference the replacement. The affected reads are the standing of the relocated original and of its replacement (6.6, 9.3), the source position where a withdrawal targets a relocated statement (9.2.2), and any order that depends on such an `@after` (4.5.2). Listing reads report such entries among their limitations (9.3.2, 9.5.3). References in `@basis` never trigger a limitation: a review that cited a relocated original keeps its basis and is reported as 8.3.6 describes.

**8.3.8 Correcting an Item.** A correction may target one Item instead of one Assertion. Its outcome is `replace`, and `@corrected` carries the complete corrected `kind`, `label` and `definition`. The corrected Item MUST pass the validation of 10.2.3 as if it were being created, with ordinal distinctness evaluated against the corrected definitions of the schedule's other milestones. Every read uses the corrected Item at every cutoff; the original remains visible in an exact read of the Item.

**8.3.9 Correcting a Connection.** A correction may target one Connection (2.4.2) with outcome `replace`, `@corrected` carrying a corrected `connected_at`. A misrecorded disconnect or reconnect act is corrected like any act (8.3.1); the Connection's state is then derived again (8.6.6).

### 8.4 Effective time of an act

**8.4.1** Establish, reaffirm, withdraw, review, ignore and normalization (`reinterpret`) acts, and reconciliations with outcome `adopt_policy`, take effect at their context's occurrence time, unless their values carry `@effective`, in which case they take effect at that instant. `@effective` never precedes the act's occurrence time. A write is rejected under 10.2.7 only when its `@effective` is before the occurrence time (4.2.5). An `@effective` whose order with the occurrence time is unspecified, such as the date of an act that occurred at 10:00 that day, is accepted at the precision written (4.5.1), and a read whose result depends on that order reports it as ambiguous (4.5.3). Disconnect and reconnect acts take effect at their context's occurrence time. Normalizations and `adopt_policy` reconciliations are events in the work: they apply from their effective time and never rewrite what preceded it (7.3.8, 7.7.3). Detections, the other reconciliations, corrections, and begin and end acts are recorded interpretations of the record, not events in the work: their outcomes apply to event-time reads at every cutoff (7.2.4, 7.3, 7.6.8, 8.3.3), and their own time is provenance and the time of their recorded basis.

### 8.5 Permanent removal

**8.5.1 Eligibility.** Permanent removal is available only for a misrecorded entry (8.2.1) that has *no downstream impact*, and only when the user explicitly directs it. Otherwise the entry is kept and corrected (8.3). An act that was intended when it occurred is never eligible, whatever was later concluded about it. It is withdrawn where 6.7.9 permits. Otherwise it is answered by a new act, as 6.7.9 states. Correction applies only to misrecordings and to recorded interpretations.

**8.5.2 Downstream impact.** A record has downstream impact when any of the following holds:

- (a) any surviving record references it exactly (2.4.5), including as a target, basis, support or `@after`;
- (b) any recorded detection, review or reconciliation lists it in its basis;
- (c) removing it would change, at any cutoff, a derived result that the model reports as standing. Such results include: the occurrence time of any other Assertion (4.2.4); the qualification (3.3.2) or distribution coverage (4.4.2) of any evidence; the in-force periods, fulfillment or standing of any expectation property (§6); and the interval, standing or ending record of any recorded story (7.2). The removed entry's own contribution to its source's position and to computed comparisons is not downstream impact. The plan evaluates this test over the records the target can affect. These are: its subject, its source's other Assertions, and the expectations and stories about its subject; for an act, its targets, their subjects, the expectations and stories about those subjects, and any story whose ending record it is; for a normalization, the units of work whose subjects are members of its scope at some instant from its effective time (7.3.8); for an `@eligible` Assertion, the expectations whose source is that eligibility Item and the evidence evaluated against them; and the Assertions that are at, carried by or covered by the target, including those of an issuance it describes or names. The test considers the record perspective; the perspective of every Item named as `@producer` or in a `@distribution` of the examined records, and of a participant named in none of them; and each unit's interpretation (7.2.4, 7.6.13). Where a unit the test examines is evaluated under an interpretation the implementation does not have, its dependency knowledge is incomplete and the plan is refused (7.6.14, 10.3). A recorded story ceasing to exist, because the removed record is its only detection, is a change to its standing;
- (d) for an Item, any Assertion uses it in any coordinate, any Connection touches it, any reference names it, including from an Item definition, or any distribution lists it;
- (e) a declared extension states that it holds references in a non-standard form (10.4.4).

Begin and end acts reference the records that began and ended their periods (7.6.4, 7.6.5), and those records therefore have downstream impact under (a). A begin or end act, and a `revise` reconciliation, is a recorded interpretation (7.6.8). Removing one is never eligible: the reads of its unit's standing read it (7.6.14), so its unit is a dependent under (c).

**8.5.3 Plan.** Removal is a two-step operation. The plan step takes the exact target and returns the complete set of dependents found under 8.5.2, computed within the managed store. If the set is non-empty, the plan is *refused*; the response lists the dependents, and the correction path (8.3) applies. If the set is empty, the plan is returned with an identifier.

**8.5.4 Confirm.** The confirm step takes the plan identifier. The implementation revalidates that the target still exists unchanged and that the dependent set is still empty, then removes the target atomically. If anything changed since the plan, the confirm step is rejected and a new plan is required. Cancelling, or a failure during removal, leaves the record untouched. Cancelling or confirming a plan ends it; a later confirm of that plan is rejected. Revalidation covers the target and every record the impact test examined (8.5.2(c)); a change to any of them rejects the confirm.

**8.5.5 After removal.** Nothing of the removed entry is retained: no values, identity, address, removal notice or flag. Its triple becomes unoccupied and may be written again. An exact reference to it held outside the store finds nothing, as for a triple that never existed (9.2.1). Because the entry had no downstream impact (8.5.2), reads computed from the record change only as if the entry had never been written.

**8.5.6** Removing one Assertion does not remove its subject, context or source Item. Removing an Item requires that no Assertion, Connection or reference involves it; otherwise the plan is refused.

**8.5.7** Applications MAY restrict removal further (a time window, a role) without changing this rule.

### 8.6 Connection lifecycle

**8.6.1 Create.** Creating a Connection sets `connected_at` to the occurrence time supplied with the operation. Creating a pair that already has a Connection is a no-op (2.2.1). A misrecorded `connected_at` is corrected under 8.3.9.

**8.6.2 Disconnect.** Disconnecting an active Connection sets `disconnected: true`, `disconnected_at`, and optionally `disconnect_reason`. The Connection leaves active adjacency and remains readable. Disconnection MUST also be recorded as an act Assertion with `@action: "disconnect"`, a connection reference in `@targets`, and the optional free-text reason as `reason`; the materialized `disconnect_reason` is derived from it.

**8.6.3 Reconnect.** Reconnecting the same ordered pair restores the existing Connection: `disconnected` becomes `false` and `reconnected_at` is set. `connected_at` and `disconnected_at` are retained. Reconnection MUST also be recorded as an act Assertion:

```
(Reconnection 2, Reconnection 2026-05-21T14:00-07:00, Site-instruction-12)
values: { "@action": "reconnect",
          "@targets": [ { "@ref": "connection", "from": "room-12", "to": "door-101" } ],
          "@basis":   [ { "@ref": "artifact", "id": "site-instruction-12.pdf", "edition": "issued 2026-05-21" } ],
          "@issuance": { "@ref": "item", "id": "site-instruction-12-issued-2026-05-21" },
          "@party":   { "@ref": "item", "id": "contractor" } }
```

Every cycle of disconnection and reconnection is therefore reconstructable from the acts, while the Connection's own properties hold only the most recent cycle.

**8.6.4 History.** A historical adjacency read at a frame (9.9) reports a Connection as active or inactive at the cutoff from `connected_at` and its disconnect and reconnect acts in occurrence order. Example: connected Monday, disconnected Tuesday, reconnected Thursday, disconnected Saturday, reconnected the following Monday. A Wednesday read reports inactive, a Friday read active, a Sunday read inactive. The original Monday time is never replaced.

**8.6.5** Reconnection concerns the relationship only. It does not revive withdrawn Assertions or reopen fulfilled or withdrawn expectations.

**8.6.6 State is derived.** A Connection's state at every cutoff, including now, is derived from `connected_at` and its disconnect and reconnect acts in occurrence order, in the corrected account (8.3.3). The `properties` are a materialization that MUST equal that derivation. They are recomputed after a correction, a removal, or a disconnect or reconnect act that is backfilled. Validation of a disconnect or reconnect (10.2.8) is against the derived state at the act's occurrence time, never against arrival order. A lifecycle act may cease to change the derived state after a correction or a backfilled act, for example a reconnect of a Connection that is already active. Such an act is reported by the history read and otherwise ignored; it sets no timestamp.

### 8.7 Retirement and renaming

**8.7.1** A label, mark or number assigned by a source is a value asserted by that source (2.1.4). Renumbering a known thing is an ordinary change by that source and a potential conflict with sources still using the old number.

**8.7.2** A "retired", "demolished" or similar status is a value asserted by a source like any other. Neither such a value nor a disconnection withdraws any source's Assertions or ends any expectation. An application that combines retirement with withdrawal or disconnection records each effect explicitly, with the acts this specification defines.

**8.7.3** A missing row in a later issuance is omission (5.2.3), never withdrawal.

---

## 9. Required reads, provenance, open standing, and attention filtering

### 9.1 Frame and scope

**9.1.1** Every read in this section takes the frame of 4.6 and returns it resolved. Reads that count or list across subjects take an explicit scope (2.1.5) and include only its members and the records in scope through them.

### 9.2 Submitted values

**9.2.1 Exact.** Given an exact reference, return the record as recorded, every correction that targets it in the corrected account (8.3.3), the withdrawals that target it, and the records that reference it (dependents under 8.5.2). The read identifies the applicable correction (8.3.4) or, where corrections are tied, that it is ambiguous. A reference to a triple that is not recorded, because it was never written or because it was permanently removed, returns `not_found`; the model does not distinguish the two (8.5.5).

**9.2.2 Source position.** Given a subject, a source and a frame, return the source's effective position: each property with its classification (5.6.1), value and origin Assertion, in the corrected account (8.3.3) and after withdrawals (6.7.4). Only Assertions at `event` and `milestone` contexts whose occurrence time is at or before the cutoff contribute. Assertions at `expectation` contexts, Assertions carrying `@action`, and reserved members (2.4.7) never contribute values. A statement with no occurrence time (4.2.4) cannot be placed against the cutoff or against the source's other statements. Each property it carries reads as a limitation, in place of its classification, naming that statement (9.6.1). The source's other properties are classified as usual.

**9.2.3 Resolved view.** Given a subject and a frame, return each property with every source's classification and value, with origins. The view never selects a winner; where sources differ it reports them side by side.

**9.2.4 By source or party.** Given a source or a party, and a frame, return what it said, with occurrence and effective times. For a source, it is every statement whose source is that Item, its self-descriptions, publications and distributions included, and every act whose source is that Item. For a party, it is: every statement whose issuance names the party as `@producer` (3.1.2); every act whose `@issuance` names an issuance that names the party as `@producer`; every act whose `@party` is the party; and every record whose source is the party Item itself (3.1.4). An act recorded in one party's communication on behalf of another appears in both parties' reads: minutes produced by the architect that record the client's instruction are in the architect's read through their issuance and in the client's read through `@party`. Recording principals are not parties (3.2.2).

### 9.3 Expectations

**9.3.1 Standing.** Given an expectation reference and a frame, return whether it is in force; its supports, meaning every support whose occurrence time is at or before the cutoff, each with the properties it covers at the cutoff and, for coverage that has ended or never began, the withdrawals that ended it (6.3.3, 6.7.2); and, per property: the standing of 6.6 with the fulfilling or withdrawing records and, where 6.5.1 gives one, the normalization that the fulfilling evidence is matched by, the timing scope, lateness where applicable, the interpretation applied, and the obligated source's current classification and value for the property (5.6.1), so that the difference between expected and actual is visible. Where the source coordinate is an eligibility Item (6.1.3), there is no single obligated source and no current classification is returned. The fulfilling evidence and the evidence that does not qualify (3.3.2) identify the sources concerned. The read also returns the expectation's ending policy at the cutoff (7.7.2) and, per property, its periods (7.6.2): each with its beginning and, where it has ended, its baseline ending and, under a non-baseline policy, its ending under that policy (7.7.4). In the record perspective, under the expectation's own interpretation (7.6.13), which every frame naming no interpretation uses, the standing and the periods are read from the recorded transitions (7.6.14). Under a frame that names another interpretation or requests literal comparison (4.6.1), or in a participant perspective, they are computed, and the result identifies the interpretation that produced them (7.6.14).

**9.3.2 Open work.** Given a scope and a frame, return every expectation with at least one `outstanding` property, listing its outstanding properties and, separately, its `not_yet_due` and `withdrawn` properties. Expectations whose only open properties are `not_yet_due` are returned in a separate list of upcoming work. An expectation with no outstanding or not-yet-due property is excluded; an earlier frame shows it. An entry whose inclusion depends on an `ambiguous` standing is returned in a separate list of ambiguous entries, with its candidate standings. One whose result is a `limitation` (8.3.7) is returned in a list of limitations. Neither is counted as included or excluded. A property is open work while its period is open under the expectation's ending policy (7.6.3, 7.7). Under the baseline, the open properties are exactly the `outstanding` and `not_yet_due` ones. Under a non-baseline policy, the lists follow open work rather than standing. A property that the policy keeps open although it reads `fulfilled` or `withdrawn` (7.7.4) is open work: its expectation is returned in the main list, with the property listed under its standing. A property whose period the policy has ended is not open work, whatever its standing. An expectation none of whose properties is open work is excluded. In the record perspective this read uses the recorded transitions wherever it evaluates an expectation under its own interpretation, as every frame naming none does (7.6.13, 7.6.14).

**9.3.3 Expectations about a subject.** Given a subject, return all expectations about it, in force or not, fulfilled or not, with their standing at the frame.

### 9.4 Comparisons

**9.4.1 Changes.** Given a source, a subject and two frames (or two of the source's Assertions), return the property transitions of 5.6.2 with prior and new origins, in the corrected account. Every property that the source asserted in a statement within either frame is reported, `unchanged` included. `unchanged` entries are not counted as transitions (7.2.3). Equality is under the frame's interpretation or, where it names none, under the interpretation in force for the subject at the second side's time: the second cutoff, or the later Assertion's occurrence time (4.6.1, 7.3.8). A property unchanged only under an interpretation that a normalization put in force names that normalization (5.5.4). Given two Assertions, distribution to a participant (4.4.2) is evaluated at the cutoff of the read's frame (4.6.1).

**9.4.2 Conflicts.** Given a subject and a frame, return, with both origins, each property on which two sources' applicable values differ under the frame's interpretation or, where it names none, the interpretation in force for the subject at the cutoff (4.6.1). The read also returns, with both origins, each pair of expectations that are both in force and not yet fulfilled for the property at the cutoff and that require unequal values under the frame's interpretation or, where it names none, under their own interpretations at the cutoff (7.1.5, 7.2.4). Pairs whose values differ under literal comparison but are equal under an interpretation that a normalization put in force are not conflicts; the read returns them separately, each with that normalization (5.5.4). A pair that conflicted only before the cutoff is not reported; its history is a story (7.2). A pair whose standing at the cutoff depends on an unspecified order is reported as ambiguous (4.5.3), and so is a pair of expectations whose own interpretations disagree on whether their values are equal (7.2.4). A `never_asserted` or `withdrawn` classification on one side is reported as absence, not as conflict.

**9.4.3** Comparison reads compute; they do not record stories (7.2.8). Each result identifies its frame and interpretation (5.5.4).

### 9.5 Stories, review and attention

**9.5.1 Story.** Given a story Item, return the following:

- its detections in occurrence order;
- the reviews, reconciliations and corrections that target it or its detections;
- its related stories: those its detections' `@relates_to` reference, those whose detections' `@relates_to` reference it or its detections, and those a reconciliation targeting it names (`@successor`, `@representative`, or another targeted story);
- for a change story, its transitions in the event-time account, identifying the detection or reconciliation they come from (7.3.7) and the corrections that apply to their prior and new Assertions (7.2.7);
- its event-time interval (7.2.4);
- its ending record or records (7.6.6), if it has ended under its ending policy, and, beside it, its baseline ending as a fact (7.7.4);
- its standing at the frame;
- its interpretation at the cutoff (7.2.4), with the normalization that put it in force, if any (7.3.8), or, for a conflict story whose sides are two expectations with different interpretations, each side's;
- when the read's interpretation differs from the story's, whether the story's sides match under the read's interpretation (7.2.4);
- its ending policy at the cutoff (7.7.2);
- its periods (7.6.2), each with its beginning, its baseline ending where it has ended and, under a non-baseline policy, its ending under that policy.

In the record perspective, the periods and the open dimension are read from the recorded transitions (7.6.14).

**9.5.2 Standing dimensions.** A story's standing at a frame has independent dimensions:

| Dimension | Values | Derived from |
|---|---|---|
| open | `open` / `ended` / `continued_in` / `not_started` | Its beginnings and endings under its ending policy, read in the record perspective from its recorded transitions (7.6.14, 7.7). Under the baseline these are, for a conflict story, its endings (7.2.6); for a change story, its ending (7.2.7), which a withdrawn review undoes when no other review of the story remains in effect and the interpretation in force then leaves its revision changing a property; where that interpretation leaves the revision changing nothing, the story's ending from then is the normalization that put it in force (7.6.2). `ended` carries the ending kind (alignment, withdrawal, fulfillment, normalization, interpretation or correction; for a change story, review, normalization, correction or reconstructed; under a non-baseline policy, the cause its end act names), exact references to the ending records (7.6.6), and its time, which a story with no period does not have; for a correction, the correction's own time is reported as provenance (7.6.12). `continued_in`, naming the representative, applies when a `continuous` reconciliation (7.3.4) makes another story the continuing representative. `not_started` applies at a cutoff before the story's interval begins (7.2.4), or, for a story with no period whose ending is a normalization, before that ending's `since` (7.6.12), including in a participant perspective whose account does not yet show the disagreement (4.6.1). Such a story is not listed by 9.5.3 or 9.5.4. |
| review | `unreviewed` / `reviewed` | A review targeting the story (7.4.1), effective at or before the cutoff and not withdrawn (6.7.9). |
| disagreement | `disagreeing` / `aligned` / `absent` | Conflict stories only: the current comparison of its sides at the cutoff, under the story's interpretation at the cutoff (7.2.4); a limitation where that interpretation is unavailable (7.6.14). Sides equal only under an interpretation that a normalization put in force read `aligned`, citing it (5.5.4). A side reads `absent` when it has no applicable value, or, for an expectation side, when it is fulfilled or not in force. |
| attention | `attended` / `ignored` | Ignore acts, only when an attention filter is requested (9.5.5). |

Change stories have no disagreement dimension. Any dimension reads `ambiguous` when it depends on an order that is unspecified (4.5.3), on an interpretation in force that is ambiguous (7.3.8), or on two expectation sides whose own interpretations disagree on whether their values are equal (7.2.4); the open dimension also reads `ambiguous` when it depends on an ambiguous governing policy (7.7.2). An empty interval (7.2.6, 7.6.12) has no start and no end.

**9.5.3 Open stories.** Given a scope and a frame, return every story that is `open`. A story that is `continued_in` another is not counted separately, so a continuous disagreement counts once (7.3.4). This read and its count include ignored stories, and so does anything an application exports from it; export is not an operation of the model (10.5.2). Stories whose standing at the frame is ambiguous (7.3.6) or a limitation are returned in separate lists, as in 9.3.2. A conflict-story family's disagreement (7.2.2) is counted once. When several stories of one family are open at the cutoff, only the latest one whose interval has begun and that is not `continued_in` another is listed and counted. The others keep their standing in story reads and are returned in a separate list of superseded stories. When the interval starts of two or more of those stories are equal or unordered (4.2.5), and no other story of the family began after them, none of them is chosen as the latest: they are returned among the ambiguous entries (4.5.3), and the family's other open stories among the superseded ones. Counting once applies to conflict-story families only: every open change story, including a related change story of 7.3.7 or 7.3.8, is listed and counted, and awaits its own review (7.2.7). In the record perspective, whether a story is open is read from its recorded transitions under its ending policy (7.6.14).

**9.5.4 Pending review.** The open stories listed by 9.5.3 that are `unreviewed`. A conflict story reviewed with `no_change` is not pending and remains open and disagreeing. A change story with a review that has not been withdrawn has ended and leaves both reads (7.2.7); when its ending policy keeps it open (7.7.4), it stays in 9.5.3, reviewed, and is not pending. Ambiguous and limitation entries are returned in separate lists, as in 9.5.3. Which stories are open is read as 9.5.3 reads it; the review dimension is derived (9.5.2).

**9.5.5 Attention.** An attention view is an explicitly requested filter over open stories, open work and upcoming work (9.3.2), and what remains (9.5.7). Only a request that names an attention filter excludes ignored entries, and the result states which filter it applied.

**9.5.6 Ignore.** Recording attention preferences is optional. When recorded, an ignore is an ordinary Assertion with `@action: "ignore"`, a fixed list of exact targets, and optionally `@until`. Its scope (personal, team, project), duration and resurfacing are application policy. Ignoring changes no standing: an ignored story is open, unreviewed or reviewed, and disagreeing or aligned exactly as before. An ignore applies to a story when its `@targets` include the story Item or any of the story's detections (as for a review, 7.4.1), and to an expectation when they include the expectation. An ignore's target list never extends to a related story. An ignore with `@until` is in effect from its effective time while the cutoff is at or before `@until` (4.2.5), and lapses once the cutoff is after it. Where they are unordered, attention reads `ambiguous` (9.5.2); under an attention filter, an expectation the ignore targets is then returned among the ambiguous entries of open work (9.3.2), unless an ignore in effect also targets it.

**9.5.7 What remains.** Given a scope and a frame, return every unit of work (7.6.1) in scope that is open at the frame under its ending policy (7.6.3, 7.7): every open conflict story, change story and expectation property. Each entry gives:

- the unit's kind and the unit;
- when its current period began, and the record that began it. The current period is the latest open period that began at or before the cutoff;
- its ending policy at the cutoff (7.7.2);
- its standing: for an expectation property, its standing (6.6.1), with `overdue` where it applies; for a story, its review dimension and, for a conflict story, its disagreement dimension (9.5.2);
- its parents (7.6.15), each with its open dimension at the frame, which may be `ended`;
- the stories it succeeds through `@relates_to` (9.5.1), which are never its parents;
- its open children: the open expectation properties whose current period it is a parent of.

The read also returns, for the entries it lists as open, counts by kind. As in 9.5.3, a conflict-story family is counted once, a story that reads `continued_in` is not listed, and the family's other open stories are returned in a separate list of superseded stories. Expectation properties that read `not_yet_due` are returned in a separate list of upcoming work (9.3.2). Entries whose list depends on an ambiguous standing, and entries whose result is a limitation, are returned in separate lists, as in 9.3.2 and 9.5.3. Superseded, upcoming, ambiguous and limitation entries are not counted. The read includes ignored entries unless an attention filter is requested (9.5.5). In the record perspective it uses the recorded transitions (7.6.14). A frame that names no interpretation reads every unit under its own interpretation, so it never lists as outstanding a property that is fulfilled under its own (7.6.13). In a participant perspective, and for an expectation read under an interpretation other than its own (7.6.14), it computes them, and each entry identifies the interpretation that produced it.

**9.5.8 Transition check.** Given a scope, compare, for every unit of work in scope, its applicable recorded baseline transitions (7.6.10) with the transitions derived from the record by §6 and §7, in the record perspective and under the unit's own interpretation. The check is an audit and records nothing. Transitions are compared whatever their times; the frame's cutoff determines only the scope's members (2.1.5).

- A unit's begin acts whose applicable content is not `null` are matched, in the order of their beginnings, with its derived periods in order. An ambiguous beginning is placed by the earliest of its definite candidates. The baseline end act of each matched begin act is matched with its period's derived ending. A story with no period has its derived ending matched with the baseline end act of a begin act whose content is `null` (7.6.12).
- A difference is one of: a derived transition that no act matches (`missing`), including the beginning of a recorded unit that has no begin act; a recorded act whose applicable content is not `null` and that no derived transition matches (`extra`), including a second baseline end act of one begin act; or a matched act whose applicable content differs from the derived content in its time, `since`, cause, record, timeliness, interpretation, tie, ambiguity or limitation (`different`). Two ambiguous contents are equal when they have the same candidates, in any order, and the same records.
- The result lists every difference, naming the unit, the act where there is one, and the recorded and derived contents. A conforming store returns no difference (I-17).
- A period's end act naming a non-baseline policy is examined only when that policy governs the unit at the period's ending (7.7.3), or is one of the candidates where the governing policy is ambiguous (7.7.2): it is then listed separately as unverified, unless the implementation implements that policy. The implementation then compares it with that policy's own derivation in the same way, and reports its differences with the others. End acts naming a policy that does not govern their period's ending are not compared and not listed.
- The transitions of a unit whose interpretation the implementation does not have (7.6.14) are not compared. Its begin and end acts are listed separately as unverified, as policy end acts are.

### 9.6 Ambiguity and limitation results

**9.6.1** A read returns `ambiguous` with the records concerned whenever unspecified order would change its result (4.5.3), when criteria, attribution or publication instants from different sources disagree in a way the result depends on (3.3.2, 4.4.1), when the result depends on an interpretation in force that is ambiguous, because normalizations tie or the normalized scopes of a subject name different interpretations (7.3.8), or when two expectations compared under their own interpretations are equal under one and unequal under the other (7.2.4). It returns `limitation` with the reason whenever it cannot evaluate as asked: a planned milestone, or one with competing publication instants, used as a cutoff; an Assertion at a planned milestone, or at a context that has no `@context` (4.2.4); a result that would have to be computed under an unavailable interpretation, where it is not read as recorded (7.6.14); dependence left dangling by a relocation (8.3.7). For an unavailable interpretation, the limitation takes the place of the interpreted result, and the read also returns the literal comparison as a separate result labelled as literal (5.5.4). Where an available interpretation does not cover the values compared, the comparison of those values says so and is given literally, labelled as such. Extension content that the implementation does not interpret is reported as `unsupported` (10.4.2).

### 9.7 Distribution and perspective

**9.7.1** Given a milestone or communication, return its dated distributions, the issuance each distributed, and their recipients (4.4.1). Given a participant and a frame, return the publications and communications distributed to them by the cutoff (4.4.2).

**9.7.2** A participant-perspective frame applies this coverage to every read in this section and lists the evidence it excluded.

### 9.8 History

**9.8.1** Any read may be evaluated at a past cutoff and returns the event-time account at that cutoff, with corrections and recorded interpretations applied at every cutoff, and normalizations and `adopt_policy` reconciliations applied from their effective times (8.4.1). A read of a detection, review or reconciliation returns its recorded basis and frame unchanged, and separately whether later evidence or corrections affect the event-time account of the same question.

### 9.9 Adjacency

**9.9.1** Given an Item and a frame, return its Connections active at the cutoff in both directions and, on request, each Connection's state history (8.6.4). Every Item that a Connection read surfaces is reachable by traversal, and every Item that traversal reaches is surfaced by the Connection read.

### 9.10 Cost

**9.10.1** A conforming implementation computes these reads from the records in the requested scope, the relevant sources, the relevant history and the acts that target them. In the record perspective, the reads that report open or ended standing read the recorded transitions of the units in scope (7.6.14), and the maintenance that records them is bounded by what each write can affect (7.6.9): for a normalization, the units in its scope. The normalizations that apply to an Item (7.3.8) are found from the normalizations recorded and the scopes they target, not by traversing the store. The implementation MUST NOT require a traversal of the whole store to answer a scoped read. This specification makes no claim about the time or resources a read takes; see §11.

---

## 10. Integrity rules, validation, extension boundaries, and conformance

### 10.1 Invariants

A conforming implementation upholds all of the following.

- **I-1 Three primitives.** Every record is an Item, a Connection or an Assertion. A new concept is a new kind of Item, never a new table, column or coordinate.
- **I-2 Triple uniqueness.** (`item`, `context`, `source`) is unique, enforced by the store.
- **I-3 Whole identity.** The triple is an Assertion's only identity. There is no version coordinate and no shadow key.
- **I-4 Untyped Connections.** One Connection per ordered pair, enforced by the store; no relationship type; roles live in Assertions; properties hold lifecycle only.
- **I-5 Recording time is never authority.** No read orders, selects or ranks evidence by `recorded_at` or by arrival. Occurrence and publication instants are the chronology.
- **I-6 Semantic separation.** Expectation contexts, act content and reserved members never surface as submitted values; submitted values never read as expected or decided.
- **I-7 Attributed source.** Every Assertion has a source Item. A recording principal is never the source.
- **I-8 Additive record with one bounded exception.** Assertions are never replaced or merged. Withdrawal, correction, reconciliation and review are new records. The only removal is 8.5: a misrecorded record with no downstream impact, on explicit direction, after which nothing of it remains.
- **I-9 Acts are records.** Decisions, withdrawals, corrections, reconciliations, normalizations, detections, ignores, and begin and end acts are Assertions on Items, with exact references, and their standing is derived from them, never from mutable side state.
- **I-10 Stories are not addresses.** A family is a lookup; a story is an Item; several stories may exist per family; a reviewed story never absorbs later evidence.
- **I-11 Decisions do not resolve.** Only aligned evidence (aligned under the comparison that applies to it, 7.2.4, 7.3.8), the end of one side (by withdrawal or, for an expectation, by fulfillment), or a correction showing there was no disagreement ends a disagreement. A review records action and is retained beside the evidence it cited.
- **I-12 No automatic authority.** No read ranks sources, elects a winner, supersedes an expectation by recency, or infers authority from adjacency, title or role.
- **I-13 Per-property carry-forward.** Values carry forward per named property with retained origin; omission never retracts; a supplied structured value replaces as a whole.
- **I-14 Empty and absent are distinct.** `null` is a value; `""` normalizes to `null`; nothing else is empty by implication; absence and withdrawal are classifications, never serialized as values.
- **I-15 Explicit frames.** Every evaluating read declares and returns its scope, cutoff, perspective and interpretation; ambiguity and limitation are results, not silent choices.
- **I-16 Corrections are not events.** A correction applies at every cutoff; a withdrawal takes effect from its own effective time.
- **I-17 Recorded transitions equal the record.** In the record perspective, whenever a read is answered, the applicable recorded baseline transitions of every unit of work equal those derived from the record by §6 and §7 (7.6). This holds wherever the implementation has the interpretation the unit is evaluated under; otherwise the unit's transitions are read as recorded (7.6.14). Transitions under an ending policy are attributed acts; their correctness under the policy is the application's (7.7.5).

### 10.2 Validation on write

An implementation MUST reject, with an explicit failure naming the cause, any write that:

- **10.2.1** repeats an existing triple with different content (8.1.3), or an existing Item `id` with a different `kind`, `label` or `definition` (8.1.5);
- **10.2.2** carries a reference to an Item, Assertion or Connection that does not resolve, including an Assertion coordinate (2.3.2); a `@targets`, `@basis`, `@establishes` or `@reaffirms` member that is not a list of references; or an `@after`, `@relates_to`, `@successor`, `@representative` or `@issuance` member that is not a single reference. Artifact references are not resolved by the store;
- **10.2.3** creates a context Item without a valid `@context` role and the members that role requires; a milestone that names no schedule, or whose ordinal duplicates another milestone of the same schedule; or an expectation context without a valid `timing`; or writes an Assertion whose context is a `phase` or an Item whose definition has no `@context`;
- **10.2.4** carries an instant that is not in the form of 4.2.1, a number outside 5.1.2, an object with duplicate keys, a defined reserved member where 2.4.4 does not allow it or with the wrong shape, a change-story detection whose `@transitions` entries name different `new` Assertions (7.2.3), or a normalization that carries no `@interpretation` (7.3.8). Undefined `@` members and undefined `@action` strings are extensions and are accepted (10.4);
- **10.2.5** carries a correction whose target is not exactly one Assertion, one Item or one Connection; a `replace` without `@corrected`; a `relocated` whose `@corrected` is not an Assertion reference; or a corrected Item that fails 10.2.3 (8.3.8);
- **10.2.6** carries a withdrawal, review, reconciliation or ignore with an empty target list; a normalization whose `@targets` is not exactly one Item reference (7.3.8); a withdrawal that targets a record that 6.7.9 says is never withdrawn; or a `change_required` review of a change story without `@establishes` or `@reaffirms` (7.2.7);
- **10.2.7** carries an `@effective` earlier than the act's occurrence time, or on an act that 8.4.1 does not allow it on;
- **10.2.8** reconnects a pair that is not disconnected, or disconnects one that is not active, in the derived state at the act's occurrence time (8.6.6);
- **10.2.9** carries any of the following (7.3.8, 7.6, 7.7):
  - a normalization whose `@interpretation` names an interpretation that the implementation does not have (7.3.8), or a `replace` correction whose `@corrected` values are such a normalization (8.3.1). An identical write of one already recorded is a replay (8.1.2);
  - a begin or end act that does not have exactly one target of the kind 7.6.4 or 7.6.5 requires, or whose `@period` does not have a form that 7.6.6 allows for it, each definite content carrying the members 7.6.4 or 7.6.5 requires and, for a begin act or a baseline end act, a cause that 7.6.4 or 7.6.5 allows for its unit;
  - an explicit baseline begin or end act (an end act whose `policy` is `null`), or a `revise` of one, whose content differs from the derivation (I-17) where the unit's interpretation is available (7.6.14), or whose transition another act already gives as its applicable content. An identical write of a generated act is a replay (8.1.2);
  - a `revise` without exactly one target that is a begin or end act, or whose `@period` is neither `null` nor a content that 7.6.6 allows for an act of its target's kind, carrying the target's policy when the target is an end act (7.6.10);
  - an end act naming a policy whose target is not the begin act of a period that the policy governs, or is a candidate to govern (7.7.2), at some instant (7.7.3), or whose target already has an end act naming the same policy (7.6.5); or such an end act, or a `revise` of one, whose content gives an ignore as a `record` (7.7.4);
  - an explicit end act naming a policy that the implementation implements, or a `revise` of one, whose content differs from the implementation's own derivation of that policy (7.7.5);
  - an `adopt_policy` whose `@frame` does not carry both `policy` and `policy_version` (both `null` adopting the baseline, 7.7.3), or that does not have exactly one target that is a detection of a story or an expectation (7.7.3);
  - a correction that targets a begin or end act or a `revise` (7.6.8).

A milestone cutoff that cannot be resolved is a read limitation (4.6.1), not a write failure.

### 10.3 Unsupported input

A read or write that cannot be evaluated as asked returns a `limitation` (9.6) rather than an empty or invented result, for example for an interpretation the implementation does not have. A normalization naming such an interpretation is instead rejected (10.2.9), because recording it requires maintenance that the implementation cannot perform (7.3.8). Unresolved ordering that affects a result returns `ambiguous` (4.5.3). A removal plan whose dependency knowledge is incomplete (8.5.2 with 10.4.4) is refused.

### 10.4 Extensions

**10.4.1** An extension is any object member beginning with `@` that this specification does not define, or any `@action` string it does not define. A record whose `@action` is a string this specification does not define is an *extension act*. It is an act for 2.4.4, so it may carry the members of every act (`@targets`, `@basis`, `@party`), `@issuance` (3.2.1) and, like any Assertion, `@after` (4.5.2). A member that 2.4.4 or 8.4.1 allows only on particular actions, such as `@outcome` or `@effective`, is invalid on it (10.2.4, 10.2.7). An extension that needs another meaning uses an undefined member. An `@action` that is not a string, and an undefined value of any other defined member (for example a review `@outcome` of `"approved"`), are wrong shapes, not extensions (10.2.4). A withdrawal may target an extension act; it changes nothing the model derives (10.4.2).

**10.4.2** Extension content is accepted on write and preserved through storage and round trip. It is not interpreted. A record carrying an unknown `@action` is not a withdrawal, a support, a review, a reconciliation, a correction or an ignore, and never counts as fulfillment, agreement, review or an ending. Reads that encounter it report it as `unsupported`.

**10.4.3** Ordinary domain content in new kinds of Items, new property names and new value shapes is not an extension; it is supported.

**10.4.4** An implementation that uses an extension holding references in a form other than 2.4.1–2.4.2 MUST declare it, and records carrying that extension have downstream impact by definition (8.5.2) and cannot be removed. While any record in the store carries that extension, a removal plan for an Item is refused: such a record may reference the Item in a form that discovery (2.4.5) does not find, so dependency knowledge is incomplete (10.3).

### 10.5 Conformance

**10.5.1** There is one baseline. A conforming implementation provides, for records in its store: the primitives and identity rules of §2; source attribution and eligibility evaluation of §3; contexts, instants, milestones, distribution and frames of §4; the value space, carry-forward, emptiness, structured replacement and comparison of §5; expectations, support, qualification, fulfillment and withdrawal of §6; stories, review, related stories, reconciliation, normalization, recorded beginnings and endings, and ending policies of §7; the write, correction, removal and Connection operations of §8; every read of §9; the invariants and validation of §10.

**10.5.2** Required operations: create Item, insert, identical replay, correct, withdraw, establish, reaffirm, review, detect, reconcile (`revise` and `adopt_policy` included), normalize (`reinterpret`), ignore, begin and end (recorded by maintenance for the baseline, 7.6.9, and written for an ending policy, 7.7.5), plan removal, confirm removal, create Connection, disconnect, reconnect; and the reads of 9.2 through 9.9, what remains (9.5.7) and the transition check (9.5.8) included.

**10.5.3** A conformance claim names this version. An implementation that provides a subset states which rules it does not implement; it does not claim conformance for the subset. Declared extensions (10.4) are listed with the claim and never redefine a baseline rule.

**10.5.4** The reference package accompanying this specification contains a reference schema, reference queries, worked examples and a conformance suite whose fixtures are keyed to the rule identifiers in this document, including the invariant identifiers I-1 to I-17 and the validation identifiers 10.2.1 to 10.2.9. A claim of conformance is supported by executing that suite against the implementation from a clean environment and publishing the results with the exact revision tested.

---

## 11. Version, stability, and declared limitations

**11.1 Version.** This is Attedra 0.1.0, a preliminary release. Breaking changes may occur in any later version. No compatibility guarantee is made for records, reads or conformance claims across versions.

**11.2 Deferred capabilities.** The following are not part of this release and are planned for the first revision after it:

- *Shared obligations.* A single expectation record obligating several named sources at once. This release represents the requirement as one expectation per obligated source (6.1.4). A compact syntax for grouped references is deferred with it.
- *Identity continuity.* Deciding when a thing that is replaced, transformed or reassembled is still the same Item. This release keeps a known thing's `id` through renaming and renumbering (2.1.4) and does not adjudicate replacement.
- *Ending policies in participant perspectives.* Applying an application's ending policy in participant perspectives. This release computes participant perspectives with the baseline endings (7.6.14), and names the unit's policy beside them.

**11.3 Not provided by the model.** A universal personal-identity registry; organization-wide authorization or role administration, including any rule about who may record or withdraw what; notification or reminder delivery; read receipts; a registry of units, mappings or domain equivalences; replay of the store's state at a past recording time. Applications may provide any of these; the model's rules do not depend on them. The event-time account at a past cutoff is not such a replay: in the record perspective, a unit's open or ended standing at any cutoff is a lookup of its recorded beginnings and endings (7.6.14), with corrections and recorded interpretations applied at every cutoff, and normalizations and changes of ending policy from their effective times (4.6.3).

**11.4 Performance.** This specification states no performance guarantee. Reads are scoped (9.10), and in the record perspective the reads of open standing read recorded beginnings and endings (7.6.14). The reference package reports what was measured in its documented environment; those measurements describe that environment and that revision only.

**11.5 Reference environment.** The reference package declares the database engine and runtime versions it was executed on, the exact artifact revision, and the results obtained. A conforming implementation is not required to use the reference engine.

**11.6 License.** This specification and the reference package are published under the Apache License, Version 2.0, as stated in the package's license and notice files.

**11.7 Known limitations.** This release defines the following cases only as far as the cited rules state, and makes no further claim about them:

- *Moving records between implementations.* Records whose beginnings and endings depend on an application interpretation that the receiving implementation does not have are read as recorded and reported as unverified (7.6.14), and a new normalization naming such an interpretation is refused (10.2.9). Transferring such records by ordinary writes, and later writes that bring units under such an interpretation, are not otherwise specified.
- *Literal comparison for one requirement.* An expectation context cannot name literal comparison (7.6.13). An application interpretation that declares no equivalences has the same effect.
- *Recorded frames.* A recorded `@frame` does not distinguish an interpretation that the comparison named from one that was in force when it named none (5.5.5).
- *Rare normalization cases.* A story whose sides never disagree under its interpretation, with no correction, normalization or context interpretation to account for it, has no defined ending (7.6.12). Neither has a related change story whose premise a later write removes (7.3.8). The generated detection of a related story opened by a normalization with a later effective time records the interpretation in force at the normalization's occurrence time (7.3.8).

---

## 12. Worked examples and the reference package

Each example states its inputs and its required outcome. The conformance suite contains an executable form of every example, keyed to the rules it exercises.

**12.1 Identity (2.3, 4.5).** Two doors receive the same mark `"101"` from two sources; they remain two Items. A door is renumbered from `"101"` to `"201"` by the architect while the consultant still writes `"101"`: one Item, two dated label assertions, one conflict on the `mark` property. A second write to an occupied triple with the same content succeeds with no effect; with different content it fails `occupied`. Two events at `2026-05-13T09:45:00-07:00` keep distinct contexts.

**12.2 Sparse carry-forward (5.2).** A-601 at DD asserts `{ finish: "paint", hardware: "HW-1" }`; at CD it asserts `{ finish: "stain" }`. The CD position is `finish: "stain"` (origin CD) and `hardware: "HW-1"` (origin DD). A door missing from the CD sheet keeps its DD values. A property never submitted reads `never_asserted`. The `@producer` and `@distribution` of A-601's self-description never appear in A-601's position for any subject (2.4.7).

**12.3 Structured replacement (5.4).** `dimensions: { width: 900, height: 2100 }` then `dimensions: { height: 2200 }` reads `{ height: 2200 }` with `member_removed: width`. Omitting `dimensions` entirely carries `{ width: 900, height: 2100 }` forward. With `width` and `height` as separate properties, a later `height: 2200` carries `width: 900` forward. A list `[ "a", "b" ]` followed by `[ "b" ]` reads `[ "b" ]`.

**12.4 Comparison (5.3, 5.5).** `null`, `""` and a blank cell all read `null` and compare equal. `null` against `"paint"` is a conflict; a never-asserted property against `"paint"` is not. `0`, `false`, `"N/A"` and `" "` are ordinary unequal values. `"90 min"` and `"1.5 h"` are unequal literally and equal under a declared fire-rating interpretation, which the result names. `1` equals `1.0`; `"1"` equals neither. An expectation requiring `hardware: null` is met by an explicit `null` and not by an omitted `hardware`.

**12.5 Withdrawal of a value (6.5, 6.7.4).** A-601 asserts `fire_rating: 60`, later `90`, then withdraws the `90` Assertion. The current classification is `withdrawn`, carrying the withdrawal, with no value; `60` is not revived; both earlier Assertions remain readable; a later `fire_rating: 60` Assertion reads `60`. If an in-force expectation requiring A-601's fire rating had not been fulfilled, it is `outstanding` after the withdrawal, once its timing scope is reached. If the `90` had already fulfilled an information request for it, the request stays `fulfilled` with the `90` as its evidence, while A-601's position reads `withdrawn`.

**12.6 Partial and bulk withdrawal (6.3, 6.7.2, 6.7.3).** Expectation E on A-601 requires `fire_rating: 90` and `finish: "stain"` with one support. A withdrawal targeting E's `finish` property leaves `fire_rating` outstanding and `finish` withdrawn; a later qualifying `fire_rating: 90` fulfills it; the final standing is mixed, not "all fulfilled". Supports D1 and D2 both establish E. Withdrawing D1's support leaves E in force through D2. Withdrawing D1's support for `finish` only leaves `finish` in force through D2. A withdrawal targeting E's `finish` property ends `finish` for both supports. When every support of E is withdrawn, each unfulfilled property reads `withdrawn` with the withdrawing records, not `not_in_force`. A property fulfilled before its supports were withdrawn, then reaffirmed later, still reads `fulfilled` at its original qualifying moment. A withdrawal of E at the 2 June meeting, effective 5 June, ends every support covering E on 5 June, including a reaffirmation that occurred on 3 June. It also ends a support D3 that occurred before it with a later `@effective`. A support D4 that occurs after the withdrawal and takes effect after 5 June begins a new in-force period, and freshness for properties not yet fulfilled is measured from D4. One withdrawal lists exact targets on Door 101 and Door 102 and ends both.

**12.7 Expectation identity and conflict (6.1, 6.3, 7.1.5).** `(Door 101, E1, A-601)` and `(Door 101, CD, A-601)` coexist. A reaffirming decision references E1 exactly rather than creating E1'. Two in-force expectations on A-601, `finish: "paint"` at the architect's 50% CD and `finish: "stain"` at 100% CD, are a conflict found by the ordinary comparison, whatever their milestones. Neither wins by recording order, and reversing the recording order changes nothing. When the 50% CD issue shows paint, the paint expectation is fulfilled and the conflict ends, while the stain expectation remains open work. Withdrawing either expectation also ends the conflict. A party that considers the two intended sequencing may ignore or review the story; neither changes its standing. A-601 and A-602 required to show `fire_rating: 90` are two expectations; A-601's `90` fulfills only its own.

**12.8 Source qualification (3.1, 3.3).** The door value's source is A-601; the architect is its `@producer`. The minutes are the source of the client's instruction; the client is its `@party`. A requirement naming the architect with no particular document is fulfilled by a qualifying architect email; an explicit A-601 requirement is not fulfilled by that email. Under criteria naming the SPM and principal roles, an email whose `@agent` lists only the intern does not qualify, and the read names the unmet criterion; an email whose `@agent` lists `role-spm` qualifies; a qualifying senior email does not outrank A-601 where they disagree. When a contract and an amendment letter assert different criteria on the eligibility Item and the two disagree about an email, the email's qualification is `ambiguous`. A newly encountered communication kind participates in reads without configuration.

**12.9 Fulfillment (6.2, 6.5).** Monday's `fire_rating: 90` from A-601 satisfies an expectation established Tuesday with `fresh: false`, at Tuesday; with `fresh: true` the expectation is outstanding until a new submission. Monday's evidence imported on Thursday gives the same Tuesday fulfillment. A suggested `90` answered `60` fulfills the request; a required `90` answered `60` does not. A blank answers a request only under an interpretation that accepts it, and never a required non-empty value. A letter dated the establishment day, against a `fresh` expectation established at 10:00 that day, is ambiguous. An `at 50% CD` expectation established after A-601 revised the value at 75% CD is still fulfilled at its establishment by the 50% CD issue, because the target fixes the evidence. One established after A-601 withdrew its 50% CD value is not fulfilled by it. A skipped optional 100% CD issuance does not block fulfillment by a later qualifying submission. A Friday submission against a Wednesday deadline fulfills `late`, with the two-day difference derived; a Thursday frame shows it `outstanding, overdue`. Evidence at exactly the deadline instant is on time. An A-601 issue dated only the deadline day, against a deadline of 17:00 that day, fulfills the requirement, and its timeliness is `ambiguous`. A `by Friday` requirement established Monday is `outstanding`, not overdue, on Tuesday; an `at 100% CD` requirement is `not_yet_due` until that milestone is published. After fulfillment, a later `60` leaves the expectation `fulfilled` while the source position reads `60`.

**12.10 Time and distribution (4.2, 4.3, 4.4).** The consultant's 50% CD and the architect's 100% DD coexist on different schedules; neither orders the other except by publication instants. A Tuesday 09:45 email precedes a Wednesday 11:45:12 milestone whatever their import order. A letter dated 14 May and an email at 09:45 on 14 May are unordered, and a read whose answer depends on their order is ambiguous. A set published Wednesday to the architect and contractor and redistributed Friday to a consultant has two dated distributions; a Thursday participant-perspective frame for that consultant excludes it. A withdrawal issued Wednesday and read Friday is dated Wednesday. A consultant submission issued Thursday that references the architect's 100% DD (published Wednesday) keeps its own Thursday context: a Wednesday frame excludes it, and against `by Arch-100DD` it is one day late. Two sources asserting different publication instants for one milestone make its chronological position ambiguous, unless one instant's interval contains the other's. Two milestones of one schedule published the same day are ordered by ordinal. A consultant listed only in the distribution of A-601 rev 1 is not covered for rev 3's Assertions. The owner's withdrawal at Wednesday's meeting is recorded from minutes issued Thursday, named in its `@issuance`, and distributed to the consultant on Friday. The requirement stays in force in the consultant's Thursday view. From Friday, the consultant's view shows it withdrawn as of Wednesday, and the record view dates it Wednesday throughout.

**12.11 Comparison paths (7.1).** The consultant publishes Tuesday, the architect Wednesday, the consultant again Thursday. A Wednesday-cutoff conflict read uses Tuesday's consultant evidence and Wednesday's architect evidence. A Thursday read returns the consultant's changes against Tuesday and the consultant's conflicts against the architect's Wednesday documentation. A due expectation with no submissions is `outstanding` at every frame after its scope is reached.

**12.12 Review and attention (7.4, 9.5).** The owner records `no_change` on a schedule-versus-specification story: the story is `reviewed`, `open`, `disagreeing`, and not pending; the architect's objection is retained. An independent expectation keeps its standing. An ignored open story appears in the open-stories read and count, and so in anything exported from them; only an attention view naming the ignore filter omits it. A read of what the owner said returns the owner's statements together with the reviews, decisions and withdrawals whose `@party` is the owner. A fire-rating story recorded under the literal comparison stays open for a reader using a "90 min = 1.5 h" interpretation, and that reader also sees that the values match under it.

**12.13 Story chronology (7.2, 7.3).**

- Identical replay opens no story.
- Monday paint/stain and Tuesday brown-paint/stain with no review are one story with two detections. The same change after a review opens a related story, which the implementation records when the brown-paint Assertion is written (7.2.8).
- Tuesday agreement entered Friday splits a Monday–Thursday story into two related stories, ending Tuesday and beginning Thursday, with Friday nowhere in the boundaries. A Thursday frame shows the second story even though it was detected Friday.
- A missing Tuesday issuance entered Friday that disproves an apparent agreement makes two unreviewed stories one continuous disagreement, counted once at every cutoff, with both records retained. The later story is `continued_in` the earlier, which is the representative. Reverse import order yields the same event-time account.
- Tuesday evidence backfilled on Friday, after a Wednesday review, that changes the current comparison opens a related story whose interval begins Wednesday.
- A-601's finish conflict with the specification ends when A-601 withdraws its finish value; the withdrawal is the ending record. A later A-601 finish that disagrees opens a related story.
- A change story on A-601 (paint Monday, stain Thursday) ends when it is approved; if the approval is later withdrawn, the story is awaiting review again. A directive for lacquer instead ends the change story while the lacquer expectation stays outstanding. A Tuesday A-601 issuance of lacquer entered Friday is reconciled: the Thursday revision's transition is now lacquer→stain, its approval keeps its basis, and the Tuesday revision (paint→lacquer) is a related change story awaiting review.
- A `replace` correction showing that the sides never disagreed ends the story at every cutoff, with the correction as its ending record.
- A `replace` that makes a later Assertion of one side equal to the other, after a genuine earlier disagreement, ends the story by alignment at that Assertion's occurrence time.
- A correction that leaves the sides unequal in the corrected record keeps the story open. Correcting one continuation basis as `erroneous` leaves the story open while its earlier, genuine disagreement remains.
- When the withdrawal that ended a reviewed story is corrected away, the story opened after it stays a related story, and a `boundary` reconciliation records the reviewed story's recomputed interval.
- A conflict review that is later withdrawn returns the story to `unreviewed`; a change after the withdrawal continues the family's latest story.
- A fire-rating story recorded under the literal comparison ("90 min" against "1.5 h") ends when a normalization of the project, effective Wednesday, names a fire-rating interpretation that equates the two: it ends on Wednesday, with the normalization as its ending record, and a Tuesday frame still shows it open (7.3.8).
- A review and a revision recorded at the same instant are ordered by `@after` when present; otherwise the story's standing at that instant is ambiguous.

**12.14 Recorded basis (7.5).** A Wednesday review that cited Monday's evidence keeps that basis after Friday's backfill reveals a Tuesday agreement. The event-time account shows the first story ended Tuesday; the review is not reassigned, and the participants are not assumed to have had the Tuesday evidence on Wednesday. The client's fire-rating instruction is reconstructable from the minutes, through the artifact reference and `@party`, without a record of who typed it.

**12.15 Error operations (8.1, 8.3, 8.5).** An identical re-import is a no-op. A genuine revision is a new Assertion at the revised issuance. An import that dropped `height` is corrected with `replace`: corrected reads show the height at every cutoff, including frames earlier than the correction; the exact read shows the original with the correction; a review that cited the original keeps its basis. An instruction meant for A-602 but recorded against A-601 is corrected `relocated`: the A-601 original contributes nothing at any cutoff, and A-602's standing is a limitation, naming the correction and D1, until D1 is corrected to target the A-602 expectation. A duplicate entry that nothing references is removed on direction after a plan with an empty dependent list; nothing of it remains, and its triple may be written again. A wrong-value entry that nothing depends on is removed on direction, and the true value is written at the same triple. The same entry with one review reference, or that is the fulfilling evidence of an expectation, is refused and corrected instead. So are the sole support of a fulfilled expectation, the publication of a milestone that Assertions are at, and the withdrawal that ended a recorded story. A confirm after an intervening change is rejected; a failed removal leaves the record intact.

**12.16 Structural history (8.6, 8.7).** Door 101 connected to Room 12 Monday, disconnected Tuesday, reconnected Thursday: one Connection, `connected_at` Monday, `disconnected_at` Tuesday, `reconnected_at` Thursday, a disconnect act and a reconnect act, and a historical read showing the three states. A second cycle (disconnected Saturday, reconnected the following Monday) leaves the properties holding the Saturday and Monday times, while a Wednesday read still reports inactive from the acts. A disconnect act later corrected as `erroneous` leaves the Connection active throughout, and its properties are recomputed. Thursday's reconnect then has no effect and sets no timestamp. A "demolished" status asserted by one source withdraws nothing. A door absent from a later issuance keeps its earlier values. A project scope includes Door 101 through Project → Door Schedule → Door 101. A door whose Connection from the scope chain is disconnected leaves later scoped counts and still appears at earlier frames, and none of its expectations ends. Two scopes with unrelated Items never compare across each other.

**12.17 Portability and extensions (5.1, 10.4).** Items, Connections and Assertions, including references, instants at every precision, exact numbers and extension members, read back as written (5.1.3), so copying them from one conforming implementation to another round-trips exactly. The exception is a normalization naming an interpretation that the receiving implementation does not have: writing it there is rejected (10.2.9), and so is writing any record that references it, such as an end act citing it, because the reference does not resolve (10.2.2). An implementation reads such a normalization as recorded only where it is already in its store (7.3.8, 7.6.14). A record with `@action: "escalate"` is accepted, preserved, reported `unsupported`, and counts as nothing. A removal plan for a record carrying a declared non-standard-reference extension is refused.

**12.18 The reference package.** The package accompanying this specification contains:

```
README.md                         orientation, quickest path to an example, how to run the checks
Attedra_Specification.md          this document
reference/schema.sql              reference schema with storage-level identity constraints
reference/queries.sql             reference queries for the reads of §9
examples/                         the worked examples above as records
conformance/                      fixture inputs, expected outputs and the runner
CONFORMANCE.md                    the tested environment, revision and results
CHANGELOG.md
LICENSE, NOTICE
```

**12.19 Recorded beginnings and endings (7.6, 7.7, 9.5.7, 9.5.8).**

- In the example of 1.5, maintenance records Story 1's begin act citing record 2 (`revision`, 16 June) and its end act citing record 5 (`review`, 17 June). It records the begin act of E-lacquer's `finish` citing record 5 (`in_force`, 17 June), nested under Story 1, and its end act citing record 6 (`fulfillment`, `on_time`, 20 June). Both acts are Assertions on Story 1's Item, because the review of Story 1 began the property's first period (7.6.7). A requirement established directly from minutes, or by a review that targets two stories, keeps acts of its own; the second is nested under both stories. What remains at the end of each day is that day's column 5. On 17 June it lists E-lacquer's `finish`, outstanding, with Story 1 as its parent, shown as ended.
- A Tuesday agreement entered Friday splits a Monday–Thursday story. The first story's end act gives Tuesday and the successor's begin act Thursday; Friday, when both are recorded, is provenance. Two unreviewed stories joined by a `continuous` reconciliation leave the later one with no period of its own: it reads `not_started` until the representative's period begins and `continued_in` from then, and what remains counts the disagreement once.
- A correction showing that the sides never disagreed revises the story's begin act to `null`; its end act has cause `correction` and no time. A story whose sides differ only literally, and only after a normalization that equates them took effect, has a `null` begin act too; its end act has cause `normalization`, cites the normalization and has no time, and its `since` is the instant its sides first differ literally, before which the story reads `not_started` (7.6.12).
- A withdrawn approval reopens a change story: a new period begins at the withdrawal's effective time, citing the withdrawal. An expectation property whose only support is withdrawn and that is established again has two periods. A fulfilled property begins no further period, and a withdrawal effective next month records an end act now, at next month's instant, while the property reads open until then.
- Under an ending policy that closes a change only when its directive's expectation has ended, the change story stays open after the directive, with the directive reported as its baseline ending, until the expectation's fulfillment ends it under the policy. A conflict story ended under a policy at its review still reads `disagreeing`.
- An explicit baseline end act whose time differs from the derivation is rejected (10.2.9); an identical write of a generated act is a replay. A withdrawal of a begin or end act is rejected (10.2.6). The transition check over the store returns no difference.
- Under the policy above, the change story whose directive was reviewed on Monday is still open on Thursday, its expectation outstanding, while another change story under the same policy ended on Tuesday. An `adopt_policy` of the baseline effective Thursday ends the first story on Thursday, because its baseline ending already held, and leaves the second story's Tuesday ending as it was (7.7.3). A Wednesday frame still shows the first story open.
- Under any ending policy an ignore ends nothing: a policy end act that gives an ignore as its record is rejected (7.7.4, 10.2.9), and the ignored story stays in the open-stories read.
- A-601's 100% CD issue changes Door 101's finish from paint to stain, and a 75% CD issue entered later already shows stain. The 100% CD change story has no period and reads ended at every cutoff: its end act has cause `reconstructed`, cites the backfilled 75% CD Assertion and has no time. The 75% CD change is a related change story awaiting review (7.3.7, 7.6.12).
- A change story approved by two reviews stays ended when one of them is withdrawn. No period begins until the other review is withdrawn too, and that later withdrawal begins it (6.7.9, 7.6.2).
- A story whose subject is under an interpretation the implementation no longer has, put in force by a normalization recorded while it had it, is read from its recorded acts. Later writes never revise them on that account, the transition check lists them as unverified, and the story's disagreement dimension reads as a limitation (7.6.14).
- An `at 100% CD` expectation whose only evidence is an A-601 statement at the still-planned 100% CD reads `not_yet_due`, and no ending is recorded. When 100% CD is published, an end act by fulfillment is recorded at the publication instant (6.5.5).
- A related conflict story whose beginning is tied with the review of the earlier story cites the disagreeing side Assertion and lists the review in `tied` (7.6.4).
- When A-601 and the specification, reissued at one milestone, both change their finishes to the same value, the conflict story's end act cites both Assertions, in identifier order (7.6.6). If only A-601's finish changed, its Assertion alone ended the story under either order, and the end act cites it alone.

**12.20 Normalization (7.3.8, 5.5.4, 6.5.1).** On Monday A-601 shows Door 101's `fire_rating` as "90 min" and the specification shows "1.5 h", and a conflict story is recorded. An expectation requires A-602 to show Door 102's `fire_rating` as "90 min", and A-602's Monday issue shows "1.5 h". On Wednesday the owner's normalization of the project, recorded from the meeting's minutes, names a fire-rating interpretation under which the two are equal.

- The Door 101 story ends on Wednesday, with cause `normalization` and the normalization as its ending record. A Tuesday frame still shows it open and disagreeing.
- Door 102's property is fulfilled on Wednesday, not on Monday, by A-602's "1.5 h", and the fulfillment cites the normalization beside that evidence.
- On Thursday A-601 shows Door 103 as "90 min" and the specification shows "1.5 h". The two values do not disagree. No story is opened, and the conflicts read returns the pair as matched by the normalization. A changes read of A-601 on Door 104, from "1.5 h" on Monday to "90 min" on Thursday, reports `unchanged` and cites the normalization.
- A read whose frame names no interpretation resolves to the fire-rating interpretation at a Thursday cutoff and to literal comparison at a Tuesday cutoff. A read whose frame names the fire-rating interpretation computes under it at every instant, so it reports Door 101's sides as matching on Tuesday too, without changing the story's standing.
- A story about Door 103 that an application records anyway has no period. Its ending has cause `normalization` and no time, and its `since` is Thursday, when its sides first differ literally: it reads `not_started` at a Wednesday cutoff and ended from Thursday (7.6.12).
- A later normalization of the project, effective Friday, names literal comparison. Door 101's sides disagree again from Friday: maintenance records a related story whose beginning, on Friday, cites the Friday normalization (7.3.2, 7.6.4). The Door 103 story stays ended with no period, and its sides' Friday disagreement is a related story in the same way (7.2.6). Door 102's property stays fulfilled at its Wednesday qualifying moment (6.5.2). Every standing, list and count at a Tuesday, Wednesday or Thursday frame is as it was before the Friday normalization was recorded.
- An expectation whose context names the fire-rating interpretation requires A-602 to show Door 105 as "90 min", and A-602's Monday issue shows "1.5 h". It is fulfilled on Monday, under its own interpretation, and neither normalization changes that. A read whose frame names no interpretation reads it from its recorded acts as fulfilled, and what remains never lists it (7.6.13, 7.6.14).
- Two expectations about Door 106 require "90 min", in a context that names the fire-rating interpretation, and "1.5 h", in a context that names none. Each side is compared under its own interpretation (7.2.4). At a Tuesday cutoff the first says the values are equal and the second, literally, that they differ, so the conflicts read returns the pair as ambiguous. At a Thursday cutoff both say equal, and the read returns the pair as matched by the Wednesday normalization. From Friday the pair is ambiguous again.
- A change story records A-601's Tuesday revision of Door 107 from "1.5 h" to "90 min". The Wednesday normalization ends it, with cause `normalization`. The Friday normalization makes the revision a change again: maintenance records a related change story whose period begins on Friday, citing the Friday normalization, and which awaits review. The Tuesday story stays ended (7.3.8).
- Had that story been approved on Tuesday evening, the Wednesday normalization would have left it ended by the approval. Withdrawing the approval on Thursday reopens nothing, because its revision changes nothing then: the story reads `unreviewed` from Thursday, its ending is the approval up to Thursday and the Wednesday normalization from Thursday, and it has a period of no length on Thursday (7.6.2). The Friday normalization then records the related change story as above.
- A read whose frame requests literal comparison computes every comparison literally at every instant. At a Thursday cutoff it reports Door 103's sides as a conflict and Door 102's property as outstanding, and it changes no standing and no recorded act (4.6.1).
- A normalization naming an interpretation that the implementation does not have is rejected (10.2.9).
