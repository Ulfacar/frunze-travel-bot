# HANDOFF: 2026-10-12-2025 — delegated specialist plan and linked quote

- STATUS: DONE — bounded reviewed-local scope, independent APPROVEs and separate final GO.
- CLASS / MODE: CRITICAL / solo.
- Task and project: `ai/tasks/2026-10-13-e6-30b-specialist-quote.md`, `ai/PROJECT.md`.
- Scope / branch / revision: `fix/tours-search-quality`, code `14583342ff53c099d720af4e52e59071510bfde9`, exact frozen R17 on `ad9e0bd4d7403f05cb8e7178a0d5f738a0cd4356`; 36/36 snapshot/root/index/commit LF identities match. R17 also contains two task/state documents outside the code index.
- Completion target: independently reviewed local change; no release or real approval.

## Outcome and files

An explicitly delegated existing full administrator can review the same applicant's
current profile, personal travel history, acknowledged interview, application and
source authority, record a bounded specialist conclusion, then save an internal
quote and its exact decision link in one transaction. The implemented positive
scope is the source-backed ordinary adult IND/business/single-entry/from-abroad
plan, at most30 days, with competing foreign-residence/long-visa facts explicitly
reconciled. The source B.8 ten-day example is exercised using synthetic approval.
This does not decide legal eligibility, accept documents, send an offer, create
payment, sign a contract or grant work/stay permission.

Separate specialist delegation defaults empty. Exact original source sections,
18 regime shapes and reviewed clause pins are retained; source evidence is not
source approval. Original ACK and questionnaire are not rewritten by later review.
Late unsafe/criminal/privacy evidence blocks current use even after an earlier ACK.
All records remain historically checkable, while changed facts/authority or a
withdrawal make current use unavailable. Exact old requests return original receipts
under current identity access without restoring authority.

Key files: `app/domain/specialist_{policy,facts,evidence,interruptions,decisions}.py`,
`app/knowledge/specialist_catalog.py`, `knowledge/kg_entry/specialist_catalog_v1.json`,
`scripts/build_kg_specialist_catalog.py`, `app/admin/kg_specialist.py` and its template.
Additive immutable journal migration0039 and model; narrowly extracted same-session
quote writer retains the existing v1 public schemas. Scoped optional legacy-reader
arguments retain their global defaults. Native RU/EN forms bind actor/session/
case/person/application/language and exact signed operation, with explicit
confirmation and original retry on409/422/503. Large valid recipes fit within the
bounded UTF-8/URL-encoded form budget.

## Evidence

Full commands, original failures, snapshot file identities and JUnit SHA-256/counters:
`ai/reviews/2026-10-13-e6-30b-snapshot-evidence.json`. Runs overlap; do not add their
counts as distinct coverage. All application imports ran only in environment-free
Git archives, with synthetic data. Original PDF SHA256:
`141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2`.

| Claim | Command/scenario | Environment / revision | Result | Limitation |
|---|---|---|---|---|
| Existing public quote behavior | `pytest tests/test_entry_quotes.py tests/test_admin_kg_quotes.py` | SQLite R2; quote seam unchanged through R17 | PASS50 /63.91s | Standalone quote compatibility |
| Source/facts, connected decisions and native workflow | `pytest tests/test_specialist_facts.py tests/test_specialist_decisions.py tests/test_admin_kg_specialist.py tests/browser_specialist.py tests/test_service_cases.py::test_migration_is_additive_empty_and_reversible` | Frozen R13 | PASS48 /647.47s | Later narrow corrections mapped separately below |
| Real competing writers and storage | `pytest tests/test_specialist_postgres.py` | Isolated PG16 loopback55971 R10 | PASS11 /685.24s | Five actual profile/history/interview/publication/review writers; observed lock waits, CAS, quote/withdraw, cancellation, post-wait clock, migration/parity/FKs/populated downgrade refusal |
| Recovery and compact-actor concurrency | `pytest tests/test_specialist_recovery_postgres.py tests/test_specialist_postgres.py::test_same_request_or_competing_revision_serializes` | Actual PG R15 | PASS3 /199.11s | Binary COPY,62 fresh-schema tables, foreign keys/sequences, unchanged history/retries and new decision4; native pg_dump not used |
| Nested clock rollback and recovery | Two `test_specialist_postgres.py::test_quote_*` temporal tests | Actual PG R16 | PASS2 /134.04s | Both decision/quote/link reversals; equality valid; no quote/link residue, original recovery/retry |
| Independent domain/source review | Reviewer source22, domain/reserve6, real-byte1, R16atomic1 | Independent frozen R4/R12/R16 | PASS, APPROVE | Includes actual63 ordinary +64th withdrawal; exact4MiB minus8192 ordinary bytes, compact1238-byte withdrawal and old authority receipts |
| Late interruption scope and history | Auditor original corrections, installed C cases, late ordinary outcome | Independent frozen R9 | PASS5 | Original R8 omission and corrupted tail-kind failures retained; equal-time omissions fail closed |
| Native negative/uncertain/large paths | Independent connected native5 + valid32-line/stream2 | R14/R15, identical UI in R17 | PASS7, APPROVE | Current identity/target/session, missing price, case lookup outage, healthy-reread lost ACK, exact retry and bounds |
| Final auditor temporal checks | Two unchanged original negative probes | Independent R16 | PASS2 /127.75s | Originally failed without SQL corruption on R14; final range guard prevents commit |
| Visual/no-JS acceptance | Browser flow in R13 core; all6 screenshots viewed by separate auditor | Mobile390 dark /desktop1365 light | PASS | Sticky header placement in long scrolled screenshots is a capture artifact, not a demonstrated runtime defect |
| Promoted regression collection | `pytest ... --collect-only -q` for five promoted test files | R17 | PASS10 collected /8.17s | Collection only; execution evidence is the mapped independent and PG runs |

## Review and remaining gates

- Independent implementation: `ai/reviews/2026-10-13-e6-30b-independent-review.md`, `calculation_review`, SCOPED APPROVE exact R16 domain/source/quote files.
- Independent native: `ai/reviews/2026-10-13-e6-30b-native-review.md`, `publication_review`, SCOPED APPROVE R15 UI mapped unchanged through R16/R17.
- Interruption audit: `ai/reviews/2026-10-13-e6-30b-interruptions-audit.md`, `e622_audit`, scoped APPROVE R9 runtime unchanged.
- Separate whole-B final audit: `ai/reviews/2026-10-13-e6-30b-final-audit.md`; GO for exact R17/36 staged files; committed bytes independently rechecked against the approved index.

No production deployment, live migration, real messages, real customer data,
source/business approval or pilot activation. Those are outside this local target.
J01/J02 are still open: one linked B example is not all fourteen SOPs or all three
B.8 goldens. J03 is whole-affected-work acceptance; J05 is actual owner approval
and authorized pilot, which cannot be earned by writing a review packet.
**Fixed technical score remains96/100.**

## Unknowns, risks and original failures

No full-project green claim. Source/authority defaults remain empty. Original
failures remain in immutable frozen runs: public preflight regression, conditional
source drift, domain-error translation, two harness fixtures, historical omission/
clock guards, oversized administrator membership, native labels/unknown totals/
outage/error class/form size and both nested quote clock reversals. Independent
reports separate real defects from harness/oracle errors and map each correction.

## Found out of scope

Unrelated existing edits in `app/admin/templates/base.html`, `boards.html`,
`tests/test_admin_new_look.py` and unrelated untracked user artifacts are preserved
and excluded from the36-file index. Old loopback CRM8765 is unchanged. Root `.env`
remains unread; no application import from root.

## Next action / resume

Code saved with36 exact approved identities. Save final documents and continue E630C.
Source-first C pre-audit is assigned to `publication_review`: actual14 SOPs and
remaining USA45/UZ garment-work goldens. Early source findings include real
visa-free entry evidence for W14→W15, distinct post-resident-card registration,
the stopped U06 registration branch and an exact approved-calendar EP deadline.
Do not invent a visa, automatic eligibility or policy approval to make tests pass.
All root/PG processes are finished; the isolated PG slot is free.
