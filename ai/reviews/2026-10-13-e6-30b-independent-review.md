# E630B — independent implementation review

Reviewer: `calculation_review`, CRITICAL / solo, local synthetic target. This is
the independent review of the source catalogue/policy/reconciliation and the
connected decision/evidence/quote journal. It is not production authority, source
approval, whole-B release approval, or completion of J01/J02.

Status: **SCOPED APPROVE — exact R16 domain/source/quote integration**. All six
findings raised by this reviewer are corrected and independently retested. The
separate auditor's additional nested quote/link temporal defect is also closed
on R16: both original negatives, recovery and the equality boundary pass. No
open material finding remains in this reviewed domain scope. Whole-B acceptance
and the separate final audit remain separate gates; this is not their substitute.

## Identity and independence

Requirements and actual implementation were inspected before builder conclusions:
the E630B task and source-first pre-audit, original PDF/catalogue and fixed scope,
then the new pure components (R3) and connected journal (R8). The later corrective
rounds retain the original failures and distinguish harness errors. No runtime
file was edited by the reviewer.

Base: `ad9e0bd4d7403f05cb8e7178a0d5f738a0cd4356`. Application imports/tests ran only
inside fresh Git-archive copies with verified frozen overlays and no `.env`.
Original PDF SHA256:
`141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2`.

The six-test and real-capacity corrective target is `runs/e6-30b-review-r12`, all 32 overlays verified;
manifest LF SHA256
`0cc222e18d06d73ea247eac83c68321ffd9f2a53d0e76feaf004afa592f10408`.
R12 through R14 have identical domain/source/migration code. Their differences
are confined to the native handler/template/test. The six component files checked
on R4 are still identical on R14: quote seam, specialist facts/policy/catalogue,
catalogue JSON and deterministic catalogue builder.

Final domain target is **R16**, independently reconstructed at
`runs/e6-30b-review-r16`: all **36/36 overlays verified**, manifest LF SHA256
`04b43bb7d2ddb4cc75323046e23cdefb424013289d354cb0cfdde953e7f8e399`.
All 15 scoped domain/source/migration files were also compared to root and match.
The only R15-to-R16 runtime delta is the precommit temporal guard in
`specialist_decisions.py`, LF SHA256
`755abbddc3b073877cc913010abd3888862db403cd3494f208178bbd925c2f40`.
It requires `decision.created_at <= quote.created_at <= outer_link_time` within
the transaction. The R12 source/capacity/read/old-replay checks map unchanged;
the quote/link success-and-rollback control was executed again on exact R16.

Reviewed domain scope: `specialist_decisions`, `specialist_evidence`,
`specialist_interruptions`, `specialist_facts`, `specialist_policy`,
`specialist_catalog`, source catalogue/builder, default-empty configuration,
specialist model and migration0039, private same-session quote seam, and the
bounded subject/prefix additions to the existing dialogue/stop readers. Native
source was inspected for context; its independent UI acceptance belongs to the
separate native review. No production, live data, messages, provider calls or
PostgreSQL were used by this reviewer.

## Confirmed findings and corrections

1. **Conditional source literal broadening.** A normally validated full bundle
   could change blocked `KG.VF.GCC.value` from null to an explicit IND country
   set, update all applicable pins and keep the original condition catalogue.
   `source_scope` accepted this contradictory literal source shape. R4 rejects
   any non-null typed outcome for the six originally blocked conditional units.
   Original failure retained; same test now passes.
2. **Conditional source literal narrowing.** The corresponding ARE-only value
   was also accepted despite the unchanged retained conditional semantics. This
   is a separate negative input to the same missing literal-value guard, closed
   by the same conservative R4 correction. The complete 18-regime census remains
   present; the test did not delete hard regimes or invent real approval.
3. **Missing current publication authority broke safe historical display.**
   `read_decisions(... publication_policy=None)` raised through the outer storage
   wrapper instead of returning the immutable receipt with unusable current
   status. R9 converts absent basis authority into the controlled permission
   result consumed by the current overlay. Exact receipt and restored positive
   authority controls pass. The observed exception was `EntryStorageInvalid`,
   not an uncaught AttributeError.
4. **Rehashed historical interview omission.** A legitimate `needs_evidence`
   record could be rewritten with retained interview absence, adjusted context,
   reasons and hashes even though an interview predated it. R9 checks the actual
   retained header timestamp and refuses omission at or before observation time.
   This was a false historical evidence acceptance, not a demonstrated positive
   eligibility or consent bypass.
5. **Future decision reported currently usable.** Advancing a valid decision's
   timestamp by one hour on the same day and recomputing its hash left current
   `usable_for_internal_quote=True`. R12 compares the latest journal head to
   fresh time; public preview also checks that head and `_preview` checks the
   active decision timestamp. The unchanged original negative passes. The old
   append guard already prevented a newly committed backward-time link; that
   distinction was preserved in the finding.
6. **Valid administrator growth exhausted withdrawal envelope.** With 140
   canonical configured full administrators, an ordinary record succeeded but
   withdrawal failed the 8192-byte terminal limit because every administrator was
   retained again. R12 rechecks current access immediately before append and
   captures only the acting administrator's verified membership. The historical
   validator still reads old full lists. Both the original negative and actual
   old-writer byte-boundary compatibility pass.

The separate auditor independently found equal-time omitted stop evidence and
validation truncated before a corrupted later C event. Actual R9 code was
inspected: omission comparisons are now `<=`; the full observed C event prefix
is validated before retaining stop pins. Auditor originals/corrections and the
legitimate late-outcome control are recorded separately in
`2026-10-13-e6-30b-interruptions-audit.md`; they are not counted as this reviewer's
own tests.

## Independent verification

All commands below ran in the named env-free copy, using Python 3.12/SQLite,
`python -X utf8 -m pytest`, `-p no:cacheprovider`, private `--basetemp` and the
specified JUnit output. No test limits were lowered.

| Copy / JUnit | Scenario | Result |
| --- | --- | --- |
| `e6-30b-review-r3/review-component-corrected.xml` | 22 independently authored pure source/input/reconciliation controls | 20 PASS, 2 genuine source-literal FAIL, 5.551 s |
| `e6-30b-review-r4/review-component.xml` | Same corrected 22 controls | 22 PASS, 7.074 s |
| `e6-30b-review-r8/review-domain.xml` | Original connected authority, rehashed omission, atomicity controls | 2 genuine FAIL and 1 reviewer exception-oracle error, 120.293 s |
| `e6-30b-review-r8/review-atomic-corrected.xml` | Correct storage-wrapper oracle; injected failure after quote flush | 1 PASS, 59.060 s |
| `e6-30b-review-r9/review-domain.xml` | Three original corrections plus future-decision negative | 3 PASS, 1 genuine FAIL, 202.668 s |
| `e6-30b-review-r9/review-reserves.xml` | Real 64-record limit and 140-admin withdrawal | 1 PASS, 1 genuine FAIL, 60.657 s |
| `e6-30b-review-r12/review-domain-reserves.xml` | Four domain controls plus both real reserve controls | 6 PASS, 297.362 s |
| `e6-30b-review-r12/review-bytes.xml` | Archived R9 writer at exact real byte allowance; current upgrade/withdraw/retry | 1 PASS, 38.52 s |
| `e6-30b-review-r16/review-atomic-final.xml` | Actual quote flush fault, atomic rollback, same request recovery, withdrawal and exact old retries on final temporal guard | 1 PASS, 3 deselected, 80.90 s |

R12 six-test command:

```text
python -X utf8 -m pytest tests/test_review_specialist_domain.py tests/test_review_specialist_reserves.py -q --basetemp .pytest-review-final --junitxml=review-domain-reserves.xml -p no:cacheprovider
```

R12 byte-boundary command:

```text
python -X utf8 -m pytest tests/test_review_specialist_bytes.py -q -s --basetemp .pytest-review-bytes --junitxml=review-bytes.xml -p no:cacheprovider
```

The count test writes 63 ordinary records, denies ordinary record64, then writes
withdrawal64 with no current policies; exact terminal/original retries survive.
The byte test uses the actual archived R9 writer and valid configured administrator
lists. It writes **40 valid ordinary records totaling exactly 4,186,112 bytes**
(`4 MiB - 8192`), without fabricated hashes or padding. Current code reads every
original receipt unchanged, denies another ordinary record, and appends a
**1238-byte withdrawal**, yielding **4,187,350 bytes** within the real 4 MiB limit.
Both withdrawal and original-record retries return exact receipts. Archived
writer LF SHA256:
`91ae8c61ba3b9a7307c947db06a687b28baa2a1e055f10226c009c1c22e2ee63`.

Final own XML identities: `review-domain-reserves.xml`
`6f3840336045253edac2abfc96ba3a5b98a2b264dd684bb6a633061b9b388f57`;
`review-bytes.xml`
`e6e2f0ba5fd352f3eee6931cd1fb6cbb1a69fea731deef782717d872933543bf`.
Exact R16 `review-atomic-final.xml`:
`8b43007d5e2716cfb8e9da38dc1f5d376c94f6195425728499232131bc11563e`.
Machine-readable local evidence is
`runs/e6-30b-review-r12/review-evidence.json`.

R16 final command:

```text
python -X utf8 -m pytest tests/test_review_specialist_domain.py -k rollback -q --basetemp .pytest-review-atomic-final --junitxml=review-atomic-final.xml -p no:cacheprovider
```

Atomicity injection occurs after actual quote flush and before decision-link
append. The transaction leaves zero quotes and only the original decision.
Removing the fault and retrying the same command creates one quote/one link;
later withdrawal and removal of all current policies preserve the two original
receipts without restoring current usability.

Original R3 `review-component.xml` (19 PASS / 3 FAIL) is retained separately:
one real source finding, plus an invalid overlapping BRN fixture and a future
evidence-date oracle corrected before the unchanged 22-control rerun. Original
R8 atomicity expected RuntimeError rather than the existing translated
EntryStorageUnavailable; only that test oracle was corrected. Neither harness
failure is presented as a runtime defect.

## Contract assessment and scope limits

The narrow B plan has separate explicit specialist/source-clause delegation,
current configured full-admin authority, exact source identities and 18-regime
shape, current per-person profile/history/interview/ACK, explicit host/purpose/
nonemployment evidence and recipe delegation. Historical receipts reconstruct
their original facts and authority; later changes affect a separate current-use
overlay. The actual quote is saved and linked in the same transaction. The model
and migration provide subject/application/quote FKs, revision/request uniqueness,
bounded append-only history and conservative populated downgrade refusal.

The original public quote v1 contract and calculations remain unchanged; the
private save extraction was compared to the old transaction body and public
preflight. Existing NO_VISA and interview reducers are not broadened by this
specialist helper. Pending documents, registration, passport/calendar checks and
processing remain explicit, with no delivery, signed contract, payment, lawful
entry/stay/work or government approval written by this operation.

The separate nested-quote clock probe confirmed an R14 defect: an actual clock
reversal between the nested quote and outer link commits two decision rows and
one quote, but subsequent historical read refuses their timestamp order. No
stored-record tampering was involved. Auditor evidence is
`runs/e6-30b-audit-r14/audit-quote-clock-r14.xml`, 1 FAIL / 70.84 s.
The reverse direction also fails on R14: a quote timestamp after its application
event but before its specialist decision commits and then fails replay. Auditor
evidence: `audit-quote-before-decision-r14.xml`, 1 FAIL / 60.57 s. The required
precommit ordering is decision time <= quote time <= link time, with rollback
on either violation and exact equality allowed. The inspected R16 guard enforces
exactly this before commit. The auditor's unchanged originals now give **2 PASS /
127.75 s**, `runs/e6-30b-audit-r16/audit-quote-clock-r16.xml`: rollback leaves only
the original decision; the same command then saves once; old replay without
current policies is exact; decision == quote == link also succeeds. The XML and
both test identities were independently parsed. The R16 own atomic control
separately verifies the normal quote path and injected link failure recovery.
Auditor corrective XML SHA256:
`d7f674f1fc5784aae41b604daabb4517a9798f519671b9ce4ef0a5d1677373ba`.

Required final actualPG locks,
migration/recovery and native browser evidence are parent/auditor work. After the
source assessment I independently parsed the builder's R10 actualPG XML:
**11 PASS / 685.241 s**, `runs/e6-30b-r10/runs/specialist-postgres.xml`, SHA256
`c775c5500444aa2ac963cdc26e4346d7f8ef3f9a246856ecce7e88cac81d75e5`.
The reviewed test source observes actual Lock waits for competing commands,
quote/withdraw and profile/history/interview/source writers; tests cancellation,
after-wait clock, migration parity, cross-scope constraints and populated
downgrade refusal. R15 COPY recovery/CAS is **3 PASS / 199.103 s**,
`runs/e6-30b-r15/runs/specialist-recovery-concurrency.xml`, SHA256
`1b5ae7f0b21a6522020eaf043f6abe18d3a64d89feb681fb3a05070ad1112e28`.
These are inspected builder evidence, not this reviewer's own PG runs or an
exact-final full suite. The final temporal guard has its own focused correction
evidence. Separate native review records scoped R15 APPROVE; its UI files are
unchanged on R16. No full-repository suite was run. Real authorities remain empty;
the exact India/business/ten-day example is a synthetic internal-planning path.
Other SOPs and the remaining golden cases are outside this slice. **J01/J02 and
whole PDF/CRM completion are not awarded by this review.**
