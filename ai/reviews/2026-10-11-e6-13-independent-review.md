# E6-13 independent CRITICAL implementation review

Reviewer: fresh independent agent `/root/portal_pre_audit`. Scope is bounded, local,
synthetic internal quotation calculation and immutable receipts. This report is
not a production release approval or a final auditor's opinion.

## r1 target and verdict

**FIX_REQUIRED** for frozen `runs/e6-13-review-r1`, base
`e37749a07023aabfa1134602ee6c384254eafcfd`. Manifest
`ai/reviews/2026-10-11-e6-13-snapshot-r1.json`, SHA-256
`987bb02e7a3b0e3581c7265338c3c7a3271b093141b0e5cf94c6621cc40705d7`.
All 19 LF-normalized source hashes independently verified before execution and
again after execution, in both frozen archive and isolated reviewer execution
copy `runs/e6-13-reviewer-r1`. No reviewed product source was edited.

The task, pre-audit, PDF-derived original price sections 12.1–12.9 (physical pages
56–60), contract, actual rules/policy/domain/migration/native UI, and tests were
read before builder conclusions. An initial source assessment was sent before
execution. Evidence below is from the reviewer's own runs; builder results are
not used to establish this verdict.

### Findings requiring correction

1. **F1 / P1 — retained calculator changes historical output when the active
   version changes.** `app/knowledge/quote_rules.py:157` returns global `VERSION`
   from `_calculate_v1`. Retaining v1 in `CALCULATORS` while activating v2 changes
   the result of the retained v1 function. Reading a previously saved v1 quote
   consequently raises `quote_integrity_failed`; exact retry shares the same
   failing replay path. Independently reproduced on SQLite and actual PostgreSQL.
   Make historical reducers return immutable literal version identifiers, select
   the active version dynamically for new previews, require the exact preview
   version on save, and preserve old receipts with a separate current-version
   usability overlay. Add version-switch read/retry/new-preview coverage.
2. **F2 / P2 — declared native body bound is enforced after full consumption.**
   `app/admin/kg_quotes.py:64` calls `await request.body()` before checking 16 KiB.
   An independent ASGI stream probe delivered 32 × 8192-byte chunks and all 256
   KiB were consumed before rejection. Bound streaming accumulation and stop as
   soon as the limit is exceeded, including a chunked request without a trusted
   Content-Length. This is an authenticated endpoint availability/input-bound
   defect, not evidence of unauthorized quote creation.
3. **F3 / P2 — malformed Unicode security fields raise HTTP 500.**
   `app/admin/kg_quotes.py:71–72` compares untrusted strings with
   `hmac.compare_digest`; a non-ASCII `_q_csrf` or `_q_sig` raises uncaught
   `TypeError`. Independently reproduced for both fields through the native
   endpoint. Validate token representation before constant-time comparison and
   return a controlled 403/422 with no mutation.
4. **F4 / P1 — rehashed source-head rewind passes semantic replay.** The separate
   auditor identified this hypothesis; this reviewer independently reproduced it.
   After two quotes observe application event revision 2, rewrite the second
   quote to pin revision 1 and recompute its preview/request/snapshot hashes.
   `app/domain/entry_quotes.py:98–123` accepts the impossible backwards observation.
   Validate monotonic observed application event revisions across quote history;
   preserve legitimate old quote reads after later application events arrive.
5. **F5 / P2 — rehashed boolean expected revision passes semantic replay.** Also
   first identified by the separate auditor and independently reproduced here.
   Replace the second quote command's `expected_revision=1` with `True`, recompute
   hashes, then read: replay accepts it because Python dictionary equality treats
   `True == 1`. Validate the stored command's exact revision type before equality.
   Apply corresponding strict identity/pin validation where equality could hide
   booleans. The public save preflight already rejects boolean revisions.

The last two probes intentionally use SQL Core in isolated synthetic databases
to bypass ORM append-only protection; they test the specified semantic integrity
replay, not an exposed route that writes arbitrary stored JSON.

### Independent evidence

Environment: Windows/Python 3.12, synthetic SQLite, guarded local PostgreSQL 16
loopback 55971 with fresh UUID databases, local Chromium. All commands below run
from `runs/e6-13-reviewer-r1`, except the guarded PostgreSQL commands run from the
repository root. Unique pytest output directories avoid builder/auditor overwrite.

```text
python -m pytest -q tests/test_quote_rules.py tests/test_entry_quotes.py tests/test_admin_kg_quotes.py tests/test_entry_quote_migration.py tests/test_alembic_domain_migration.py tests/test_service_cases.py --basetemp=runs/reviewer-core-tmp --junitxml=runs/reviewer-core.xml --tb=short
137 PASS, 2 opt-in PostgreSQL SKIP, 151.30 s

python runs/e610_legacy_pg_probe.py runs/e6-13-reviewer-r1 tests/test_entry_quote_postgres.py --basetemp=runs/reviewer-pg-tmp --junitxml=runs/reviewer-pg.xml --tb=short
17 PASS, 78.32 s

python -m pytest -q tests/browser_kg_quotes.py --basetemp=runs/reviewer-browser-tmp --junitxml=runs/reviewer-browser.xml --tb=short
2 PASS, 29.50 s

python -m pytest -q ../../runs/e613_independent.py --basetemp=runs/reviewer-probes-tmp --junitxml=runs/reviewer-probes.xml --tb=short
4 FAIL (F1/F2/F3), 1 PASS (27 independent Fraction-oracle combinations), 27.37 s

python runs/e610_legacy_pg_probe.py runs/e6-13-reviewer-r1 ../../runs/e613_independent_pg.py --basetemp=runs/reviewer-own-pg-tmp --junitxml=runs/reviewer-own-pg.xml --tb=short
1 FAIL (F1 on actual PostgreSQL), 24.67 s

python -m pytest -q ../../runs/e613_independent.py -k rehashed --basetemp=runs/reviewer-rehashed-tmp --junitxml=runs/reviewer-rehashed.xml --tb=short
2 FAIL (F4/F5: expected rejection did not occur), 5 deselected, 12.31 s
```

The rehashed probes were appended to `runs/e613_independent.py` after its first
five-test execution. Their provenance is explicitly recorded in the probe file.

Evidence SHA-256 (all XML/JSON below are under `runs/e6-13-reviewer-r1/runs/`):

| Artifact | SHA-256 |
|---|---|
| reviewer-core.xml | bdc0b2aa6dfb28b16a0a427529acee761a7e6ca10ba83753bea3168d91ee7475 |
| reviewer-pg.xml | 779946781ea549209d82314129fe8f67508fb8b189f784844372d47bb7bf0589 |
| reviewer-browser.xml | 2fd5c3d3652eb0efcd537577277951de1d37ded59f8ca7a4969e8eb19151ad90 |
| reviewer-probes.xml | 4d524af5a7921a4b24a4f8bf211225b43dfcf9869d431994c99c188f5b6175f0 |
| reviewer-own-pg.xml | 7ed3e4ff0aab778856aad358fe249adffa043d78e8394f2d59aa5570a4fb4eb1 |
| reviewer-rehashed.xml | c9c24fd050375de6d813bab23c8b96407a0dec68bf203e91767290d50f762ce9 |
| quote-postgres-recovery.json | b5bcaacc86554dafdc631e8b221e7fac8cac9564867e9788fcf6f1a7fa1e7c66 |

Own probe source SHA-256:
`runs/e613_independent.py` =
`823bd54d02b2135ed2d482aa39a0ce6410fde0bb7977ab36922950b9cd38dd4e`;
`runs/e613_independent_pg.py` =
`5925cc7d1c6d2b32c298c65cf3bb77bb7a7f18eafb291f45c0b517546aff8c47`.

PASS evidence covers exact Decimal arithmetic and independent Fraction oracle,
whole government base-plus-block urgency, no service/bank multiplication,
currency separation, blocked total for unknown/sub-cent/unrepresentable values,
explicit proved zero/NA, read-only preview and no other-domain/ledger writes,
current identity revocation before engine access, scope/procedure/key ownership,
policy/source/clock/CAS changes, rollback and ambiguous commit retry, count/byte
limits, actual PostgreSQL competing quote saves and ordinary application writer
serialization, schema/FK/unique constraints, populated downgrade refusal, and
synthetic recovery. These passes do not negate the targeted failures above.

Recovery independently executed binary COPY backup (16,036 bytes), fresh Alembic
schema restore with foreign keys and restored sequences, equal history and old
exact receipt retry, current authority denial, native read and a new revision.
Backup SHA-256 recorded by the isolated harness:
`21054b355e4a2f0e3160208e472eaad53deeb10e9595840a4b8009dd0d5afbb5`.
Native `pg_dump`/`pg_restore` remains **UNKNOWN** due Windows App Control 4551;
this evidence must not be relabelled as native dump certification.

Browser PASS covers 390-pixel JavaScript and 1365-pixel no-JavaScript flows,
lost save acknowledgement, failed reread, exact original retry, historical
selection and print. Reviewer visually inspected its own mobile preview and
both rendered pages of its own two-page `quote-demo.pdf`: unknown bank blocks
the total; known USD subtotal is explicitly labelled; unavailable current policy
is visible; no payment/send action is introduced. Output lives under the isolated
`runs/e6-13-reviewer-r1/runs/e6-13-quote-browser/` directory.

### Requirement and C04 opinion

The bounded design is appropriate: one applicant/application attempt per receipt;
all service/government/bank/partner components accounted for; explicit reviewed
recipe/procedure authority; no invented exchange rate, settlement, discount,
refund, contract or payment operation. Empty production policy is preserved.
The PDF's unverified bank fees, price inclusion conflicts and dated permit amounts
must remain unapproved rather than converted into real defaults.

C04 is **not PASS on r1**, because retained version history and semantic integrity
are part of versioned quote calculation. Once the concrete defects are fixed and
independently verified, the exact criterion “Versioned quote calculation with
separate currencies/fees and unknown-price blocking” can be PASS for this bounded
local technical scope without real tariff approval. Real source authority,
production tariff validity, privacy decisions, settlement/payment approval,
deployment and real user acceptance remain **UNKNOWN / outside this review**.

No production or external source was contacted, no policy was approved, and no
release/deployment was performed. Final audit is separate.

## Corrected r2 re-review and final independent verdict

**APPROVE for the reviewed local synthetic scope** on exact frozen
`runs/e6-13-review-r2`, same base
`e37749a07023aabfa1134602ee6c384254eafcfd`. Manifest
`ai/reviews/2026-10-11-e6-13-snapshot-r2.json`, SHA-256
`91b2ecb93a91665ac33c7d80e46582a597425ad2830dd02d40ccd2f110d56e07`.
All 19 manifest source hashes verified in the frozen archive and separate
`runs/e6-13-reviewer-r2` execution copy before and after independent execution.
The reviewer read all eight changed files before builder result claims. The
remaining 11 manifest files, including models/migration/templates, are identical
to the r1 files already assessed; exact r2 PostgreSQL schema/recovery and browser
checks were nevertheless executed. Product source and both frozen archives
remain unchanged by this reviewer.

All five findings are **CLOSED** on r2:

- F1: v1 result version is literal, new calculation resolves the active version
  at call time, save requires the preview's explicit calculator version, and
  old receipt replay/retry remains exact with `quote_calculator_changed` in the
  current overlay. Original independent failure probe now passes on both SQLite
  and PostgreSQL. A retained v1 plus functioning synthetic active v2 also passes
  old read/retry and new preview/save in domain and actual PostgreSQL tests.
- F2: the parser stops before accumulating beyond 16 KiB, rejects excessive or
  malformed declared length before reading, and independently stops the original
  unknown-length 256-KiB stream after the third 8-KiB chunk.
- F3: both CSRF and HMAC values require 64 lowercase hex characters before
  comparison. Both original Unicode endpoint probes now return controlled
  rejection with unchanged database counts.
- F4: quote history rejects backwards observed application event revisions,
  while legitimate old history after later application growth remains readable.
  The original fully rehashed rewind probe now fails closed as required.
- F5: stored revision and calculator types are checked, and command, source pin
  and result equality uses canonical type-sensitive JSON. Original bool revision
  probe now fails closed; additional bool pin/result and null calculator cases
  also pass on SQLite and actual PostgreSQL.

The independent original probes were run **unchanged** against r2. Their source
hashes still match those recorded in the r1 section. A separate additional probe
`runs/e613_r2_independent.py` (SHA-256
`e63d84ca28f92bb0e42c48232f18aceeb702350dd46b4623c38a4149c305f8a4`)
exercised the native signed form across a version switch: a previously saved v1
SAVE retries without duplication, its receipt is unchanged and its current
status is stale; a v1 SAVE preview that was never committed is rejected after
switching; a fresh v2 preview carries v2 and saves a usable new revision. The
native stale-calculator explanation is visible. **PASS**.

Independent r2 commands and results (same working directory convention as r1):

```text
python -m pytest -q ../../runs/e613_independent.py tests/test_quote_rules.py tests/test_entry_quotes.py tests/test_admin_kg_quotes.py --basetemp=runs/reviewer-r2-core-tmp --junitxml=runs/reviewer-r2-core.xml --tb=short
94 PASS, 197.07 s; includes all seven original independent probes

python runs/e610_legacy_pg_probe.py runs/e6-13-reviewer-r2 tests/test_entry_quote_postgres.py ../../runs/e613_independent_pg.py --basetemp=runs/reviewer-r2-pg-tmp --junitxml=runs/reviewer-r2-pg.xml --tb=short
24 PASS, 116.27 s

python -m pytest -q ../../runs/e613_r2_independent.py --basetemp=runs/reviewer-r2-native-version-tmp --junitxml=runs/reviewer-r2-native-version.xml --tb=short
1 PASS, 13.84 s

python -m pytest -q tests/browser_kg_quotes.py --basetemp=runs/reviewer-r2-browser-tmp --junitxml=runs/reviewer-r2-browser.xml --tb=short
2 PASS, 33.76 s
```

No r2 test failure or skip occurred in these four executions. Only pre-existing
dependency deprecation warnings were reported. The unchanged schema/service-case
baseline evidence is the explicit r1 execution above, not a claim of rerunning
that full command on r2. Actual PostgreSQL schema constraints, lock interactions,
populated downgrade refusal and recovery were rerun on exact r2.

Evidence SHA-256 under `runs/e6-13-reviewer-r2/runs/`:

| Artifact | SHA-256 |
|---|---|
| reviewer-r2-core.xml | 10200804068cc9cb7ee5c49d11b6ee4d2f9754be9142b32087f03941417a9fb8 |
| reviewer-r2-pg.xml | 344754e9d9776ec741119dd542c4babe40363ca07a4d0d653ef1df0bcf044d35 |
| reviewer-r2-native-version.xml | b59014c76110bebd5c9a0832b318e9c770a64ef76bc7156b91755a76fbc5b17f |
| reviewer-r2-browser.xml | 773db188d92aed27622452979ca8528c109fa69f793d7b76022001e0306dce98 |
| quote-postgres-recovery.json | 787dea9a0f6c7340f978a1a1129f1a867824adedd14c13acf84f29ba9178a697 |

The independently isolated r2 recovery artifact records 16,031 backup bytes,
backup SHA-256
`3f8cc99277d86bc6fabcb67593f4eb356703aedba2dd31f425fbcf1c30ff585b`,
equal historical receipts, exact old retry, current authority denial, native
read HTTP 200 and a new quote revision after recovery. This is binary COPY into
a fresh Alembic schema with foreign keys and sequences; native dump tooling
certification remains **UNKNOWN**, as stated above.

Reviewer visually inspected the exact r2 mobile preview and **both** pages of
its new two-page `quote-demo.pdf` under
`runs/e6-13-reviewer-r2/runs/e6-13-quote-browser/`. Both pages are nonempty/readable;
the unknown bank fee blocks a complete total, the USD subtotal is labelled as
known only, and current unavailable authority remains visible in print.

**Final C04 opinion: PASS for the fixed technical criterion in this reviewed
local synthetic scope**, subject to the separate final audit required by the
project protocol. The implementation now supplies persisted retained versions,
separate currencies and components, unknown-price blocking, native review and
print, current-status overlays, and independent SQLite/PostgreSQL/recovery
evidence. This verdict neither approves real prices nor expands the criterion
to settlement, payments, client offers, deployment or legal eligibility.
Real source/payment/privacy authority and production/user acceptance remain
**UNKNOWN / outside this review**. No remaining concrete blocker was found in
the reviewed bounded implementation.

## r3 whitespace-only final applicability review

**APPROVE applies to exact frozen `runs/e6-13-review-r3`** for the same bounded
local synthetic scope, with all limitations and the separate final audit gate
above unchanged. Manifest `ai/reviews/2026-10-11-e6-13-snapshot-r3.json`, SHA-256
`23472efaf061922632ee2c5b95c0750b82f6b1387a66bbb54b2f6a58ff0d6dd6`.

Independent Python `hashlib` verification: **PASS**, manifest digest and all 19
LF-normalized frozen file hashes match. Comparison of the r2/r3 manifests:
**PASS**, only `tests/test_quote_rules.py` differs; the other 18 files are identical.
Direct unified diff: one blank line moved from EOF to the boundary before
`test_retained_v1_does_not_read_active_version`; no executable text changed.
Independent `ast.dump(ast.parse(source), include_attributes=False)` comparison:
**PASS**, exact equality. Comparison after stripping whitespace: **PASS**.

No runtime change, new defect or new test requirement arises from this delta.
The preceding exact-r2 execution evidence remains applicable; it is not relabelled
as an r3 execution. No independent full test rerun was performed for this
whitespace-only delta, and no builder test outcome is claimed here. C04's bounded
technical acceptance opinion remains **PASS**.
