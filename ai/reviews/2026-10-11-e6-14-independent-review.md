# E6-14 independent CRITICAL implementation review

Reviewer: `/root/portal_pre_audit`, independent of builder and final auditor.
This review concerns local synthetic implementation only. No actual provider,
client, Telegram, Bitrix, production database, credential or activation policy
was used. Frozen sources were not edited.

## r1 target and first verdict

**FIX_REQUIRED** on `runs/e6-14-review-r1`, base
`3efe3b6040a054d01159e04958a5267de711d0ce`. Manifest
`ai/reviews/2026-10-11-e6-14-snapshot-r1.json`, SHA-256
`64cdff5f66050090463df74d9b3e2967e61883a6d608b896a399a6ab4cf0e45d`.
Manifest digest and all 24 LF-normalized source hashes independently verified.
Execution uses the separate ignored `runs/e6-14-reviewer-r1` copy, with distinct
pytest outputs and recovery artifacts.

The task, pre-audit, contract and actual policy/registry/guard/binding code were
read before builder conclusions; an initial source assessment was sent before
execution. PDF-derived Appendix B.4/B.6 and the unchanged B04/H04 definitions
were also inspected. All evidence here is from the reviewer's own executions.

### F1 / P2 — policy clock is captured before blocking case/Dialog acquisition

`app/domain/entry_channel_stops.py`, `bind_stop.write`: `at=_now()` occurs before
`_context(..., at=at, lock=True)` waits for the case and Dialog locks and rereads
source history. Policy validity, preview day, and persisted event/binding dates
all use that old time. Authority can expire while the writer waits, yet the
handoff and stop commit using a timestamp from before lock acquisition.

Independent synthetic boundary probe changes the clock to an expired policy
date immediately after the actual `_case(..., lock=True)` returns. Expected:
controlled permission rejection and no new handoff/stop. Actual: successful
binding. Reproduced on SQLite and actual isolated PostgreSQL. This probe controls
the clock at the lock boundary; it is not claimed as a wall-clock midnight test.

Correction: obtain one fresh timestamp after all case/Dialog lock waits and
source rereads, recheck policy and preview day there, and use that timestamp for
both atomic records. Preserve old exact retry before current policy/time checks.
Builder acknowledged the finding; a root fix is not evidence for frozen r1.

### V1 — two provided semantic-tamper tests fail before tampering

`tests/test_entry_channel_stops.py:223` uses
`deepcopy(dict(row.source_pin))`; nested immutable service JSON raises
`DomainError` during copying. Both bool-pin and card-fact cases therefore fail
before reaching the mutation or registry rejection, including their PostgreSQL
wrappers. This is a test setup defect, not proof that runtime replay failed.
Use the established plain conversion in the test setup and rerun exact frozen
corrected tests. The reviewer did not edit those tests; separately authored
`runs/e614_semantic_independent.py` reaches both rehashed corruptions with SQL
Core and verifies rejection even for an unrelated negative route lookup.

### Source assessment and claim limits

The bounded architecture is appropriate: explicit private WhatsApp enrollment,
actual captured Wappi HTTPS origin/profile/private recipient, supported suffix
normalization only, separate default-empty deployment activation and authority
policy, immutable exact handoff pins, shared-session atomic handoff+binding,
current full-admin enforcement and exact retry, and no reset operation.
The sender owns a non-retrying transaction and holds the deterministic route
advisory lock through the callback; binding also serializes global capacity.
Full bounded registry validation protects negative lookups from moved routing
columns. Registry corruption/overflow intentionally blocks activated scopes.

Installed call-site inventory was re-run on the frozen snapshot. Autonomous
orchestrator replies flow through `_reply`/`_deliver_reply` and the final guard;
scheduled and manual-triggered automated followups use
`send_automated_to_client`. Human sends in admin router lines 2031/2059 remain
`send_to_client`. Awaiting/watchdog destinations are staff alerts; calendar and
morning briefs are staff paths. Existing inbound/legacy CRM/tool effects and
every historical escalation trigger are explicitly outside this stop boundary.
Provider invocation is not a promise of exactly-once remote delivery or recall.

An additional identity timing boundary was initially raised from source:
the guard's descriptor recheck precedes the callback, but the orchestrator
callback awaits panel logging before actual `adapter.send`. The separate
auditor reproduced this as A1. The reviewer subsequently also reproduced it
independently, as recorded below; it is no longer merely a source suspicion.

### F2 / P1 — actual Wappi destination can change after admission (auditor A1)

The r1 orchestrator retains mutable adapter/message objects across the awaited
pending log. Start with an activated unbound destination; mutate the original
adapter origin/profile and the original message recipient to an already stopped
route while that log awaits. The guard has admitted the old route, but actual
`WappiAdapter.send` assembles a request for the new stopped route.

`runs/e614_transport_independent.py` uses the real Wappi `send` implementation
with a fake HTTP client and changes all three fields together. This reviewer
authored and ran it on both unchanged snapshots. r1: **1 FAIL, 13.87 s** — the
recorded HTTP request targets the stopped synthetic route. r2: **1 PASS, 12.86 s**
— the recorded request uses only the originally admitted route. No provider
network call occurred. The three individual mutation hypotheses were initially
reproduced by the separate auditor; this combined reproduction is the reviewer's
own independent evidence.

Correction assessed in r2: snapshot the Wappi instance's scalar route fields and
the Message before awaits, then use those same captured objects for admission
and actual provider invocation. Automated outbound captures its adapter too.

Commands from the respective isolated reviewer copies:

```text
python -m pytest -q ../../runs/e614_transport_independent.py --basetemp=runs/reviewer-own-route-tmp --junitxml=runs/reviewer-own-route.xml --tb=short
# r1: 1 FAIL, 13.87 s
python -m pytest -q ../../runs/e614_transport_independent.py --basetemp=runs/reviewer-r2-own-route-tmp --junitxml=runs/reviewer-r2-own-route.xml --tb=short
# r2: 1 PASS, 12.86 s
```

Probe SHA-256:
`64caa0c26bd48a58f2a1fbcd572feb98c21999ca777f64e22ad0f9cde2704b25`.
Isolated r1 `runs/reviewer-own-route.xml` SHA-256:
`193d67b51b1f73ce45708c4f4e1177c48ab3727a1651c549127341d4a7ffd615`.
Isolated r2 `runs/reviewer-r2-own-route.xml` SHA-256:
`7e58f1c98f56418455cd1015c32955cf6e273a12991a70ebd388a77f3b7cf5ea`.

## Independent r1 executions completed so far

Commands without the PG helper run from `runs/e6-14-reviewer-r1`; PG helper
commands run from repository root and use guarded temporary loopback databases.
All provider and LLM boundaries are synthetic fakes.

```text
python -m pytest -q ../../runs/e614_independent.py --basetemp=runs/reviewer-own-tmp --junitxml=runs/reviewer-own.xml --tb=short
1 FAIL (F1), 2 PASS, 14.41 s

python runs/e610_legacy_pg_probe.py runs/e6-14-reviewer-r1 ../../runs/e614_independent_pg.py --basetemp=runs/reviewer-own-pg-tmp --junitxml=runs/reviewer-own-pg.xml --tb=short
1 FAIL (F1), 14.79 s

python -m pytest -q ../../runs/e614_semantic_independent.py --basetemp=runs/reviewer-own-semantic-tmp --junitxml=runs/reviewer-own-semantic.xml --tb=short
2 PASS, 9.71 s

python runs/e610_legacy_pg_probe.py runs/e6-14-reviewer-r1 tests/test_entry_channel_postgres.py --basetemp=runs/reviewer-pg-tmp --junitxml=runs/reviewer-pg.xml --tb=short
24 PASS, 2 FAIL (V1 setup), 100.50 s

python -m pytest -q tests/browser_kg_channel_stops.py --basetemp=runs/reviewer-browser-tmp --junitxml=runs/reviewer-browser.xml --tb=short
2 PASS, 24.35 s
```

Positive own controls establish that the registry byte cap blocks a negative
activated lookup without callback, and policy removal plus ACK, a new interview
and a freshly constructed adapter cannot resume the old stopped route.
Actual PostgreSQL passes include both initially absent route lock orderings,
observable advisory-lock waiting, global capacity competition across routes,
callback exception/timeout/cancellation/cleanup uncertainty, lock timeout, stable
fresh-process lock key, atomic rollback, exact commit-uncertainty retry, migration
parity/empty cycle/populated downgrade refusal and recovery.

The reviewer visually inspected its own 390-pixel preview and the sole page of
its own `runs/e6-14-reviewer-r1/runs/e6-14-channel-browser/stop-demo.pdf` (923 text
characters, nonblank). The page shows exact synthetic recipient/account, explicit
unchecked permanent-stop confirmation, distinction from owner ACK, and the
private WhatsApp limitation. Browser executions cover mobile with JavaScript,
1365-pixel no-JavaScript flow, ambiguous save plus failed read, original retry,
saved stop and print.

Independent recovery JSON:
`runs/e6-14-reviewer-r1/runs/channel-postgres-recovery.json`, SHA-256
`ca8ec583528c7871ee494f6805ee20815c3f234e113f91aea0de7fc54480683c`.
It records binary COPY into a fresh Alembic schema with FKs and restored sequence
state, 29,273 backup bytes, backup hash
`bf180b200ea6cc2eb7206f99c2702f412ec2619c5c19bea96ada0d5c7de99957`,
old stop after ACK/recovery, old exact retry after policy removal, a new binding,
and native read. Native `pg_dump` certification remains **UNKNOWN** because of
Windows App Control 4551; these checks do not alter that control.

Evidence hashes under the isolated copy's `runs/`:

| Artifact | SHA-256 |
|---|---|
| reviewer-own.xml | 1f16d6315bbc385e446e79ec3ab5f9dd22e095cf3fc0f204b0d10375af114b26 |
| reviewer-own-pg.xml | 84d09d692e4027d70bd6056ed8231f7a02e9f8d3eef1b4ca72971143a55d83df |
| reviewer-own-semantic.xml | e0d977c629b71120a36baf7eefcdc14fdec5d85c0dc969f082201882057fd28d |
| reviewer-pg.xml | a63cbf7e17a2086f6142b86118815b2815443ed8e52e7b370934404e9d4ed509 |
| reviewer-browser.xml | 00f7f13cb079946ec41581633393223ca9e196e7d207d19c9480b1fe219c56fb |

Probe source hashes:

- `runs/e614_independent.py`:
  `e8487221974a81e483c82301a6426cfb8e49deb77c0b6f685042057450f99b18`.
- `runs/e614_independent_pg.py`:
  `e058f797299ba11cbd6514b1623c52fb13199f8c69555e8273c97ef7d7d7afb4`.
- `runs/e614_semantic_independent.py`:
  `839ec999f2141ba59611e30dcfefeea4d139ca7056bc3efce33f59cee946d186`.

The broad core/shared-interview regression subsequently completed:

```text
python -m pytest -q tests/test_entry_channel_stops.py tests/test_admin_kg_channel_stops.py tests/test_kg_channel_guard_paths.py tests/test_followup.py tests/test_entry_interviews.py tests/test_service_cases.py tests/test_alembic_domain_migration.py --basetemp=runs/reviewer-core-tmp --junitxml=runs/reviewer-core.xml --tb=short
200 PASS, 2 FAIL (V1 setup), 2 opt-in PostgreSQL SKIP, 312.20 s
```

`runs/e6-14-reviewer-r1/runs/reviewer-core.xml` SHA-256:
`3996891e0393f3542096b2d4598fdf9c1310a5d994a0cf17cd411b9ce13ee09c`.
Shared interview public-wrapper and helper regressions passed. The 2 optional
skips are not counted as passes; actual PostgreSQL evidence is separately
recorded above. All 24 file hashes in both frozen r1 and the reviewer execution
copy were reverified after completion with no mismatch.

## B04/H04 applicability

No PASS is awarded to r1 while F1 and required test evidence remain unresolved.
The intended complete slice can supply B04 durable pinned facts/gaps/owner/stop
and H04 owner/card ACK plus autonomous-reply suppression **only for explicitly
activated and bound private WhatsApp routes**. This is a full-admin enrollment
entry point. It does not integrate every PDF B.6 trigger, every legacy handoff,
every applicant contact, Telegram, Bitrix, or global CRM side effects. Default
empty real activation/policy means no production protection was activated.
Real recipient, account activation, privacy/business authority, deployment and
real user acceptance remain **UNKNOWN / outside this review**. Separate final
audit remains required.

## Corrected r2 final independent review

**APPROVE for the reviewed local synthetic scope** on exact immutable
`runs/e6-14-review-r2`, same base
`3efe3b6040a054d01159e04958a5267de711d0ce`. Manifest
`ai/reviews/2026-10-11-e6-14-snapshot-r2.json`, SHA-256
`6dd95fe0b77f6fcd33d25c859da670d0db899d08a679b28cd294df240448b882`.
All 26 LF-normalized manifest hashes independently matched before execution and
after the final check, in both frozen source and isolated
`runs/e6-14-reviewer-r2`. No frozen or root implementation file was modified.

Source delta was read before considering builder results: fresh timestamp after
case/Dialog acquisition, adapter/message capture at installed send entry points,
semantic-tamper fixture correction, explicit migration tests, four row-lock clock
boundary tests, actual Wappi/fake-HTTP route tests, followup-tail fixture adapter,
and contract clarification. The interview service/helper, models, migration and
native form/template source are unchanged from assessed r1. Shared interview
regression evidence remains the explicit r1 run, not a relabelled r2 execution.

**F1 CLOSED:** original unchanged independent SQLite and PostgreSQL expiry probe
now passes. The `_context` timestamp is sampled after case and Dialog locks and
source reread; validity and preview day are checked there, and that same instant
is supplied to the handoff and binding. Four additional cases distinguish case
versus Dialog acquisition and expired authority versus a new day with still-valid
authority. They pass on SQLite and actual PostgreSQL. Exact retry still precedes
current policy/time checks.

**F2 / auditor A1 CLOSED:** the actual Wappi request uses the same captured scalar
configuration and copied Message destination that were admitted by the guard.
The independent combined mutation probe is unchanged between the recorded r1
failure and r2 pass. Three separate recipient/profile/origin mutations also pass
in the installed-path suite. HTTP assembly uses the real Wappi method with a
synthetic HTTP client; no provider was contacted. Automated followups capture
the adapter before awaits as well.

**V1 CLOSED:** provided tamper tests now convert frozen values with `_plain`,
reach their mutations and pass rejection assertions on both databases. The
reviewer's separate bool-pin/card-fact probes also pass unchanged. This does not
discard or rewrite the original r1 setup failures.

### Independent exact-r2 evidence

Commands use the same isolated-working-directory convention as r1:

```text
python -m pytest -q ../../runs/e614_independent.py ../../runs/e614_semantic_independent.py tests/test_entry_channel_stops.py tests/test_admin_kg_channel_stops.py tests/test_kg_channel_guard_paths.py tests/test_entry_channel_migration.py tests/test_followup.py tests/test_pipeline_tails.py --basetemp=runs/reviewer-r2-core-tmp --junitxml=runs/reviewer-r2-core.xml --tb=short
118 PASS, 261.58 s

python runs/e610_legacy_pg_probe.py runs/e6-14-reviewer-r2 tests/test_entry_channel_postgres.py ../../runs/e614_independent_pg.py --basetemp=runs/reviewer-r2-pg-tmp --junitxml=runs/reviewer-r2-pg.xml --tb=short
31 PASS, 188.36 s

python -m pytest -q tests/browser_kg_channel_stops.py --basetemp=runs/reviewer-r2-browser-tmp --junitxml=runs/reviewer-r2-browser.xml --tb=short
2 PASS, 35.38 s

python -m pytest -q ../../runs/e614_transport_independent.py --basetemp=runs/reviewer-r2-own-route-tmp --junitxml=runs/reviewer-r2-own-route.xml --tb=short
1 PASS, 12.86 s
```

No fail or skip occurred in these four exact-r2 executions. Existing dependency
deprecation warnings were the only warnings. Original own probe hashes in the
r1 section were rechecked unchanged. All provider/client/LLM calls remain fake.

| Artifact under `runs/e6-14-reviewer-r2/runs/` | SHA-256 |
|---|---|
| reviewer-r2-core.xml | 76773d29420133dd77aa67a2944859da17e4d6ec83d8ee99bd3f5cd8874eb910 |
| reviewer-r2-pg.xml | 58bd8fa0ec2bf11fb0bfbff3d56ba1f999ea02923ac7a0b22af5d5af66c8cdc8 |
| reviewer-r2-browser.xml | 824c4d71cc9a61497f65c9d407e0566b143699ead394aac3b30dd54c6284b39b |
| reviewer-r2-own-route.xml | 7e58f1c98f56418455cd1015c32955cf6e273a12991a70ebd388a77f3b7cf5ea |
| channel-postgres-recovery.json | 017d6fff0449d3bf7226fc07c6e922376f30f7bdacc41abcd7c6b2c334020940 |

The reviewer independently reran both PostgreSQL initially-absent-route lock
orderings, global capacity race, callback exception/timeout/cancellation/cleanup
uncertainty, lock timeout, atomic rollback, commit ambiguity retry and restoration.
Schema parity, empty migration cycle, populated/offline downgrade refusal and
additive SQLite schema preservation pass. SQL size checks, global registry
capacity, moved routing keys, malformed activation/recipient/schema and rehashed
semantic corruption deny autonomous provider invocation; unbound activated
routes and separate human sends remain usable in the tested scope.

Installed stale LLM and selected-before-bind followup scenarios, including
manual-triggered batches, pass with no provider call, outgoing pending/sent log,
reply-success marker, outbound mirror, followup count/touch or false promised-
reply manager notification. All ten supplied reply-branch scenarios use the
real final guard. The final send-call-site inventory preserves the r1 boundary;
the r2 change captures inputs without adding an autonomous send bypass.

Independent r2 recovery records 29,301 binary COPY backup bytes, backup SHA-256
`dd325fcfa90396ad35080c628231ea3041fcd94dffd35db29c6d2aa9bd710888`,
restoration into a fresh Alembic schema with FKs and sequences, old stop after
ACK/recovery, original retry after policy removal, a new binding and native
read. Native `pg_dump` certification remains **UNKNOWN**, not silently replaced
by this COPY evidence.

Reviewer visually inspected its exact-r2 mobile preview and the complete sole
page of `runs/e6-14-reviewer-r2/runs/e6-14-channel-browser/stop-demo.pdf` (923 text
characters). It is readable/nonblank, displays the correct synthetic account
and recipient, and separates saved stop from the owner's ACK. No new visual
blocker was found.

### Final B04/H04 opinion and exclusions

**B04 and H04: PASS for explicitly activated and explicitly bound private
WhatsApp routes in the reviewed local synthetic flow**, subject to the protocol's
separate final audit. B04 combines the retained interview facts/gaps/card and
named owner with this atomic durable stop. H04 retains the exact owner/card ACK
and independently verifies continued suppression before/after ACK, policy
removal, restart/recovery and later interview creation. A contact's route grants
no permission to disclose applicant facts; the binding sends no message.

This is not global multi-channel completion. Telegram, Bitrix, every legacy
handoff/PDF escalation trigger, every unbound interview/contact route and global
CRM/LLM/tool side-effect cessation remain **UNKNOWN / excluded from this credit**.
Deployment activation and authority policy still default empty. Removing an
activation scope deliberately disables enforcement and is outside this review's
operational authorization. Real privacy/business authority, accounts/recipients,
provider delivery, production migration, release and real user acceptance remain
**UNKNOWN**. No remaining concrete blocker was found in the reviewed bounded
implementation, and no production release is authorized by this verdict.
