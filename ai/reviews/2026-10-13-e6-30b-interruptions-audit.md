# E630B — independent scoped audit of retained interruptions

Auditor: `e622_audit`. CRITICAL / solo; reviewed-local target. This is a separate
source-first audit of the interruption consumer and its scoped legacy readers,
not a final verdict on the entire specialist decision/quotation feature.

Status: **APPROVE for the scoped R9 interruption consumer and reader changes**.
Both genuine R8 integrity failures are corrected and independently retested below.
All five final own controls passed; no auditor process remains. Whole E630B remains
outside this verdict. No release, actual policy
approval, activation, J01/J02 completion or whole-B GO is granted by this report.

## Requirements and scope

Read the E630B task and independent pre-audit before implementation conclusions.
The relevant requirement is that an old benign handoff/ACK cannot clear retained
unsafe, criminal or privacy evidence. Historical receipts and present usability
are separate. Specialist checks must use the same case/applicant/interview, with
bounded immutable provenance; mutable inbox availability and unrelated registry
rows are not authority. Root runtime, configuration and private `.env` were not
edited or imported. No PostgreSQL, external provider, live data or network used.

Audited source: `specialist_interruptions.py`; the optional subject filters in
`entry_channel_stops._registry` and `dialogue_stops._registry`; the bounded-prefix
and scoped legacy-link additions to `dialogue_journal.history`; the corresponding
historical omission rules in `specialist_evidence.py`. Full decision/money/native
integration, migration, recovery and total journal capacity are separate gates.

## Frozen identities and environment

- R8 base: `ad9e0bd4d7403f05cb8e7178a0d5f738a0cd4356`, 21 overlays. Manifest
  LF SHA256 `710cb0a5f7582487a8a28ba6e2cca758005d6d37860bdae39a4dd3b46e76163d`.
- R9 uses the same base, 27 overlays. Manifest LF SHA256
  `1f7d2c66b492162c902b196caae38c73bae63bf2f5e0fce1e441e23667edb163`.
  All listed overlay hashes were independently checked before importing code.
- Own archives: `runs/e6-30b-audit-r8` and `runs/e6-30b-audit-r9`, made from
  `git archive` plus the verified overlays. `.env` absence was checked. Original
  PDF copied from the frozen archive, SHA256
  `141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2`.
- SQLite tests use synthetic fixtures, real local domain transactions and the
  installed dialogue service. No root application imports or real credentials.
- R9 four scoped runtime identities also match the working tree at inspection:
  `specialist_interruptions.py`: `b9be5f41ea84818aa03565d6333f521e8f371b650d9b059a6546ac8393114fd3`;
  `dialogue_journal.py`: `0fc877778ccca463afe354bd1ae64b356f5d4bd1d5d40a11f5358fbabcffd6d8`;
  `dialogue_stops.py`: `073dab8113e1799329b7fe7eea85618e6b3ba0c9e77e62b3412e6d82f4621373`;
  `entry_channel_stops.py`: `ec50de9c3bf7dfa449b38d67979c9c67e864704a9c64415a22078b7c09a1d4c7`.

## Source assessment and lock boundary

The original interview card is deliberately retained by both A and C when an
interrupt arrives after native handoff/ACK. Consequently, consulting only the
card or ACK misses the separate causal journal. The new consumer selects actual
same-subject legacy causes and C headers/stops and validates their original
interview links. Only `manager_requested` is benign for this capability; other
retained causes and collection holds require review. This does not authorize
collection, restart the channel or treat ACK as clearance.

The helper takes no route/global advisory lock after the caller's case lock.
That is essential: STOP writers already acquire transport locks before the case
lock. Existing `record_outcome` deliberately does not acquire the case lock.
R9 therefore samples the session's maximum revision and validates that complete
immutable prefix, while retaining only header/STOP identities as personal facts.
An outcome appended later cannot change those pins. No new global registry or
mutable Inbox/Dialog dependency is introduced in this reader.

Compared with the base, legacy registry changes add optional case/applicant SQL
filters to both the predecode size queries and row queries. Calls without that
argument keep their original global behavior. The journal adds a validated
integer cutoff with exact row-count/chain checks and passes the same subject to
old linked-stop/cause validation. Core causal reducers, semantic checks and
default full-history callers remain unchanged. This is source inspection, not
a claim that the complete old-channel regression suite was rerun by this auditor.

## F1 — R8 missed corruption after the last recognizable STOP

**Confirmed FAIL on R8; corrected and independently PASS on R9.** The
peer first raised the source concern; this auditor constructed the actual probe.
R8 chose `max(revision WHERE kind='stop')` when any STOP existed. Altering the
latest STOP's discriminator therefore moved the validation cutoff backwards.

Actual sequence: enroll C; request manager; native ACK; record retained privacy
withdrawal with `authority=None`; verify two STOP pins and collection hold. Raw
SQL then changes only the latest event's `kind` from `stop` to `outcome`, leaving
its original document/hash untouched. R8 specialist observation accepts the
older prefix instead of rejecting the damaged journal. The probe restores the
row in `finally`. This is a proven journal-integrity gap, **not a demonstrated
complete privacy bypass**: the interview still retains `collection_blocked`.

R8 command in own archive:

```text
python -m pytest tests/test_audit_specialist_session_corruption.py -q --tb=short --junitxml=audit-c-prefix-r8.xml
```

Result: **1 FAIL, 80.87 s**, expected `EntryStorageInvalid` did not occur.
Artifact: `runs/e6-30b-audit-r8/audit-c-prefix-r8.xml`.
R9 always validates through the observed overall maximum revision. The same
unchanged test also checks restored original pins/errors after corruption refusal.

## F2 — R8 accepted an omitted cause at the exact observation timestamp

**Confirmed FAIL on R8; corrected and independently PASS on R9.** With a
real unsafe legacy cause stored after handoff/ACK, current observation returns
the required review reason. A historical empty cause pin at one microsecond
after that cause is rejected, but the same empty pin at exactly `created_at`
was accepted. The strict `<` omission check left equality unvalidated.

R8 command in own archive:

```text
python -m pytest tests/test_audit_specialist_omission.py -q --tb=short --junitxml=audit-omission-r8.xml
```

Result: **1 FAIL, 7.85 s**, expected integrity refusal did not occur. Artifact:
`runs/e6-30b-audit-r8/audit-omission-r8.xml`. An earlier harness-only failure is
preserved in `audit-omission-first.xml`: the test mistakenly supplied the string
returned by `_utc` instead of a datetime; it is not another runtime finding.

R9 rejects omitted causes, session headers and STOPs timestamped **at or before**
the retained observation. The related profile/history/interview/application/
publication omission checks use the same boundary. Equal timestamps have no
independent ordering proof and are deliberately refused; this does **not** claim
that every historical receipt with an ambiguous tied timestamp remains readable.
The probe establishes a historical semantic-validation defect, not an ordinary
API path that could create the forged omitted context without corruption.

## Independent verification

Supplied installed-C controls were executed independently on R8:

```text
python -m pytest tests/test_specialist_session_interruptions.py -q --tb=short --junitxml=audit-c-sessions.xml
```

**2 PASS, 157.58 s**, one existing Starlette deprecation warning. Artifact:
`runs/e6-30b-audit-r8/audit-c-sessions.xml`. Actual native handoff/ACK followed by
unsafe/criminal input retains the old card, changes interruption evidence and
blocks present use while the strictly earlier retained context reproduces.
The tests establish the review consequence; they do not assert that every
terminal C reason equals the incoming phrase's category after native head drift.

R9 corrective command in the own env-free archive:

```text
python -m pytest tests/test_audit_specialist_omission.py tests/test_audit_specialist_session_corruption.py tests/test_specialist_session_interruptions.py -q --tb=short --junitxml=audit-interruptions-r9.xml
```

**4 PASS, 313.65 s, exit 0**, one existing dependency warning. Artifact:
`runs/e6-30b-audit-r9/audit-interruptions-r9.xml`. Both original auditor test files
were copied unchanged from the corrected R8 probe harness. Corruption is now
rejected, restoration recovers the exact held context, equality omission is
refused, and both installed-C later-interruption controls still pass.

Supplementary independent R9 command:

```text
python -m pytest tests/test_audit_specialist_late_outcome.py -q --tb=short --junitxml=audit-late-outcome-r9.xml
```

**1 PASS, 114.64 s, exit 0**, one existing dependency warning. Artifact:
`runs/e6-30b-audit-r9/audit-late-outcome-r9.xml`. This appends an actual `unknown`
outcome for an issued claim after a manager STOP/ACK and verifies that it is the
latest journal event, the complete journal remains valid, the current STOP pins
and earlier retained observation remain unchanged, and exact outcome retry
returns its original hash. No provider callback is made. This is a sequential
late-outcome control, not an actual PostgreSQL overlap/lock-wait test.

Final own evidence is **5 PASS on R9**. The R8 baseline 2 PASS and two original
genuine failures remain separate; they are not recounted as final-snapshot tests.
Raw artifact hashes and probe identities are recorded in
`runs/e6-30b-audit-r9/audit-identities.json`.

## Limits

This audit covers already retained immutable interruption evidence. It does not
scan mutable inbox text or claim that a previously stopped dialogue collects all
later nonprivacy messages. No new collection or privacy policy is inferred.
Whole E630B native flow, actual PostgreSQL concurrency/recovery, decision/quote
capacity, full implementation review and final whole-feature audit remain
separate. Real authority is not supplied by these synthetic fixtures.
