# E630C — remaining actual anchors and conditional deadline consumers

Independent source-first design pre-audit, 2026-10-13. Reviewer: `calculation_review`.
Risk/mode/target: **CRITICAL / solo / reviewed local implementation**, once implemented and independently verified.
This report is a design recommendation, **not implementation APPROVE, source/legal approval, whole-C completion or J-point evidence**.

## Result and recommended boundary

Proceed with one bounded, connected capability: **record or resolve actual own-person anchor evidence → evaluate an explicitly delegated source-specific internal reminder → retain the calculation and reconcile an existing CRM task**. Cover the source families in the matrix below as one acceptance target. Missing authority, missing actual facts and unsupported legal applicability must remain visible uncertainty.

The smallest coherent architecture is a compact typed anchor-evidence stream for facts the CRM genuinely does not retain, plus a versioned conditional-review branch in the existing `EntryDeadlineRevision` / `EntryDeadlineTask` path. Reuse the task lifecycle and calendar arithmetic. Do not add another parallel reminder/task journal, manufacture an official manual due date, or broaden the existing UZ-only work-review journal by changing an enum.

Preserve the current UZ conditional EP reminder unchanged initially. Its existing adapter can later be shared mechanically after compatibility evidence; migrating its historical rows is unnecessary for this capability. New and old task bindings must have unambiguous ownership and duplicate suppression.

## Source and inspected code

Source was read before builder conclusions: original PDF in `runs/e6-30c-r40/runs/specialist-source.pdf`, SHA256 `141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2`; especially §19.9–19.12, printed pages 81–83, physical PDF pages 82–84, with §13.2 and the existing draft units checked for mapping. The PDF is the requested product source, not evidence that its legal statements are currently approved.

Read-only checkpoint: `runs/e6-30c-r40`. LF-normalized manifest SHA256 `3d37dff31339b61b9dc08449e7eec371ac3788824cdc57ed759b1aefdced0b39`. File identities are retained in `runs/review-remaining-deadlines-r40-evidence.json`, produced by the stdlib-only `runs/review_remaining_deadlines_inventory.py`. No root application import, private environment, DB, external service or runtime edit was used. New runtime tests/PG: **N/A for this pre-implementation design review**, not a waiver for the implementation.

Actual source inspected: `entry_deadlines.py`, `entry_deadline_sources.py`, `entry_deadline_tasks.py`, `work_review_tasks.py`, `work_review_policy.py`, `work_deadlines.py`, `entry_issued.py`, `entry_issued_rules.py`, `entry_process_rules.py`, `entry_process_evidence.py`, relevant models, the deadline arithmetic/schema and interview catalog/reconciliation. This is source inspection; no new execution or migration PASS is claimed.

## Confirmed design gaps

1. `entry_deadline_sources.summary` exposes `operational_due_on` only from explicit official manual evidence. Recalculation produces a draft candidate. Current bound anchors are own application events or own issued travel, not visa/EP/RES/REG expiry, payment-code availability or changes of address/passport/purpose. Putting a calculation into `manual.due_on` would change the meaning of an existing trusted field.
2. `entry_issued._approval` supports only `visa` / `exit_visa`. Its `validity=True` review check does not record dates. The immutable reducer has visa-shaped review/delivery semantics and no general period-withdrawal contract. Merely allowing additional procedures would not provide trustworthy EP/RES/REG anchors.
3. Interview `registration.until` and profile `registration_until` / `current_basis_until` are recorded assertions. Their presence, format or equality does not make them an official document period. They are useful prefills and conflict checks only.
4. Work-v2 `resident_registration_basis_reviewed` already carries actual linked RES `valid_from/valid_until` and REG `registration_from/registration_until`, own approval IDs and proof. It is a useful narrowly typed provider. Its current readiness consumer requires a currently running REG period; directly copying that boolean gate would incorrectly erase an overdue-reminder anchor after expiry. The new consumer must independently validate the retained fact and current withdrawal/source state, while preserving the distinction between an expired document and an invalid fact.
5. `EntryWorkReviewEvent` is one chain per application and DB-constrained to `unified_permit`; its authority/semantic report is the single UZ visa-free EP rule. Several independent rule tracks and EP/RES/REG source documents do not fit that contract. `EntryDeadlineRevision` already has application+rule tracks and `EntryDeadlineTask` generations, making it the better reuse point.
6. All **22** existing deadline units have `value=null`, `confirmation_status=needs_verification`. None may acquire an executable approved value merely because a source number was found. EAEU REG reminder and absence-30 are not dedicated existing `KG.DL` units. A new source-clause mapping is required for those cases.

## Source-to-anchor matrix

Offsets below describe the PDF and proposed supported internal calculations under separate delegation; they are not current legal advice or automatic filing permission.

| Source behavior | Existing source identity / missing mapping | Required real anchor and result |
|---|---|---|
| §19.11 visa renewal/change, at least 5 working days before visa ends | `KG.DL.VISA_EXTENSION`, §13.2 p61, null | Actual issued visa period end, own person/passport/document and latest official application approval. Review current visa type, current/new purpose and inviter applicability; TS/TR/R or unknown applicability must not yield an allowed in-country route. Result: conditional internal review date and within/past-date status. |
| §19.9 W14/W16, §19.11 RES after EP, −10 working days | `KG.DL.RC_BEFORE_EP_END`, §13.2 p61, null | Actual EP end. EP issuance/approval timestamp, a visa end or REG end is not the substitute. Keep W16 preparation −15 separate from filing −10; the former needs its own pinned SOP clause if implemented. |
| §19.9 W21, §19.11 new EP before RES ends, −7 working days | `KG.DL.EP_BEFORE_RC_END`, §13.2 p61, null | Actual RES card end, linked own RES approval. Do not use its associated REG expiry or create a new EP application automatically. |
| §19.11 visa-free EP, −10 working days | `KG.DL.EP_BEFORE_VISA_FREE_END`, §13.2 p61, null | Existing delegated UZ actual lawful visa-free end path. Its narrow source/current-stay policy remains separate and unchanged; no new general nationality coverage inferred. |
| §19.10 EAEU worker, tax pending → 60-day REG; later confirmation → up to one year; reminder −10 working days | No dedicated existing deadline unit for this reminder. Add a pinned §19.10 clause/catalog entry with explicit internal scope; suggested new identity is provisional, not an existing approved unit. | Record the **actually issued** 60-day certificate period and explicitly reviewed EAEU employment/tax-pending classification. Calculate from its real end. Tax confirmation permits a review of the next step, not `+365`, `+12 months`, a new certificate or an automatic right to stay. Family evidence is distinct. Existing REG remains the anchor until replaced/withdrawn. |
| §19.12 payment by code within 3 working days | `KG.DL.REGISTRATION_CODE_PAYMENT`, §13.2 p62, null | Typed dated official payment-code availability evidence for the own REG attempt. Source text alone does not settle issuance versus receipt as the counting anchor; delegation must choose the supported meaning, and the UI must state it. Do not use application submission or generic service-payment date. No payment execution or amount approval. |
| §19.11–12 REG renewal no later than last day | `KG.DL.REGISTRATION_EXTENSION`, §13.2 p62, null | Actually issued REG `valid_until`; conditional last-day review date equals that date. No implicit working-day shift. Expiry makes it overdue, not silently absent. |
| §19.12 address/passport/purpose change → 10 working days | `KG.DL.REREGISTRATION`, §13.2 p62, null | Typed effective change event with date, kind, before/after references and proof. The time a manager edits a profile, passport expiry, or a newly planned purpose is not the effective change date. Keep concurrent unresolved changes; never reset an earlier obligation by recording a later one. |
| §19.12 absence abroad 30+ days → new REG | No dedicated deadline unit. Pin exact §19.12 clause and explicit calendar-day/endpoint interpretation. | Actual same-person exit and return evidence, passport/history consistency. At 29/30/31 days show the explicitly delegated threshold result. A planned exit/return cannot satisfy it. This is a **review trigger**, not a filing due date at exit+30. With no actual return, show the conditional risk; do not assert completed re-entry or a newly valid registration. |

`KG.REG.TERM.UZB`, country exemption periods and `KG.VF.EAEU` do not describe the §19.10 actually issued employment registration. They are not substitute mappings. Registration never silently extends visa-free stay in this adapter.

## Minimal implementation contract

### 1. Small typed anchor store and existing providers

Add one bounded append-only anchor evidence model/service, rather than broadening visa delivery or procedural-stage reducers. Its responsibility ends at attestation/currentness; it does not calculate a deadline or create a task. Existing typed providers can be referenced without copying their journal: work-v2 RES/REG basis, actual stay exit/return, existing issued document/version, and current own application approval.

For missing facts support only these initial shapes: `issued_period` (visa/EP/RES/REG), `registration_payment_code_available`, and `registration_change` (address/passport/purpose). Require canonical case, applicant and source application; actor; actual effective date; source kind; bounded official reference; proof digest; immutable relevant source row IDs/hashes; exact own saved profile and document/passport identity where applicable; and explicit correction/withdrawal. Define the material profile fields consumed by each shape; changed material facts require renewed reconciliation. All IDs and schemas must be strict, not coerced.

An issued period stores actual document kind and `valid_from/valid_until`, not presumed lawful-stay or work permission. A separate `lawful_until` cannot be inferred from document validity. A visa may have different validity and allowed stay; retain that distinction. Require its own latest official approval and document/version binding. Imported/external current documents require an explicit supported evidence-import contract, not a fabricated CRM approval event; until supported, show a reasoned fallback.

A period fact does not cease to be an accurate expiry anchor merely because its end has passed. It becomes unusable when withdrawn, corrected, superseded, mismatched, revoked, future-observed or no longer supported by current evidence/delegation. Keep those states separate from `overdue`.

Prefer `attest` / `correct` / `withdraw` with exact retries and bounded payloads. For repeat changes, each effective event has stable identity; a latest-value reducer must not lose older unresolved obligations. One per-rule task may represent the earliest unresolved due date while retaining the full bounded selected event set. If that set cannot be safely resolved, require operator review rather than selecting the newest date.

An adapter for existing work-v2 basis must validate exact latest attestation/withdrawal, actual linked RES and REG approval IDs, current catalog/authority and source hashes. It may read the recorded expired period for a reminder; it must not revive a withdrawn fact or convert an old stage receipt into current legal clearance. Interview/profile dates prefill only, with explicit reconciliation of conflicts.

### 2. Version the existing deadline and task contracts

Add a distinctly named `conditional_review` format/action to the existing per-application/per-rule deadline journal. Retain v1 parsing, replay and exact receipts. Store selected anchor references, original authority document/digest, source-clause/rule hashes, calculation/calendar interpretation and currentness observation in the new receipt. Old `manual` continues to mean an actually confirmed official due date.

Keep a conditional `review_due_on` separate from old `operational_due_on`. Extend the existing task projection to select it only under the new internal-reminder authority, with a comment stating it is a date for specialist review. Do not route it through the old official-manual summary. The old task binding/action identity must validate the new source variant explicitly; do not silently accept any new snapshot shape.

Bind the reminder to the **source application** whose actual document/event drives it; report target intent such as RES preparation separately. A future target application need not exist, and must not be created by the calculation. Any cross-application evidence must still resolve to the same case/person and correct role/attempt. Add composite scope/FK constraints if the chosen storage representation introduces cross-application references.

For absence30 use an explicit `review_trigger` mode. Reuse an existing task projection only after its identity admits this mode; schedule operator review on an explicitly chosen observed/handling date, never label it a statutory filing deadline. Do not coerce a trigger into an invented `KG.DL` arithmetic result just to satisfy a schema.

Reuse `CalendarTaskService`, current owner handling, manual-date conflict/restore behavior, claimed/completed protection, CAS/idempotency and generic task ownership guards. Extract small shared helpers if necessary; copying the full work-review journal into a third module is not justified. Source facts can feed several rule tracks through one anchor identity.

### 3. Explicit authority, unchanged draft source

Default configuration remains empty. A server-only immutable authority must bind exact permitted operators, validity/review dates, source PDF/bundle/projection/catalog/rule-or-clause hashes, publication-policy digest and the required current publication/review identities, supported product/intent/anchor kind, allowed source attestations, calendar content and validity, timezone, anchor-day counting and deadline boundary inclusivity. Validate current publication for the executable dependencies the contract requires; do not pretend a null deadline unit was published as executable. Its separate delegated interpretation must retain the exact original null row and source-clause identity. Unknown clauses, additional arbitrary offsets, altered literal country/product scopes or rehashed source variants must be rejected.

Use exact source-compatible rule shapes; authority is not permission to supply arbitrary numbers. Last-day renewal is an identity-date operation, not an offset-zero workaround in arithmetic that expects positive durations. For working days require complete coverage of every traversed year, including anchor and any shift. No weekday fallback, weekend shift, month-to-year assumption or hidden endpoint default.

EAEU employment/tax/family facts need typed, current, separately reviewed scope. A purpose/inviter attestation is not auto-eligibility. The native form must distinguish an internal conditional calculation, an official portal date and missing applicability. Preserve `permission_to_remain`, `permission_to_work`, filing/action permission and client delivery as unevaluated/false as appropriate; do not silently elevate them from date availability.

### 4. Currentness, invalidation and withdrawal

Take the current clock once after required locks. Resolve the current maximal validated source prefixes and all applicability evidence in the same transaction as the deadline receipt/task mutation. Reject future headers/tails and contradictory source chronology, including equal-time omission of already visible rows. A hash match alone is insufficient semantic evidence.

Changes to application status/attempt, approval, passport/document version, period or effective event, profile/material interview facts, privacy/collection block, source publication, authority or calendar must be visible in current reads. Original receipts and exact retries remain historical. The parent may reuse the existing source mutation hooks, adding missing bounded hooks for the new anchors.

Be explicit about task freshness: relevant writes can reconcile enabled tracks atomically; expiry or config changes without a write cannot magically cancel a stored task. Current views and pre-action checks must show it unusable, and a refresh may cancel an unclaimed projection. If automatic periodic reconciliation is later required, it needs a separately tested scoped mechanism. Never claim immediate automatic withdrawal from a read-only page.

Withdrawal/cancel must remain possible at actual count/byte limits and after current authority disappears, subject to the existing access boundary. Do not require fresh evidence for cancelling an old task. Restore/new generation require valid current evidence and owner. Claimed/manual/completed tasks require explicit conflict handling, not silent alteration or reopening. A terminal reserve may not permit arbitrary new facts or calculations.

## Required acceptance evidence for this connected capability

1. **Source-shaped positives:** real local case/person/attempt and explicit synthetic delegation for each matrix row, with retained original null source values. Include visa −5, EP→RES −10, RES→EP −7, EAEU actual 60-day REG −10 plus later actually issued replacement, REG payment +3, last-day renewal, each change kind +10, and actual absence29/30/31. Existing UZ path receives compatibility coverage, not another claimed implementation.
2. **No fact fabrication:** approval timestamp is not validity end; boolean validity is insufficient; client interview date alone remains uncertain; EAEU tax confirmation does not emit one year; REG end cannot substitute for EP/RES end; actual period with a passed end stays visibly overdue. Same-person but wrong attempt/product/role and other-person references are negative controls.
3. **Counting:** Friday/holiday/transfer-working days, year boundary and missing adjacent-year calendar, exact deadline day and next day, anchor inclusion choices, duplicate calendars and tampered calendars. Test due-before-today without moving it to today. Absence threshold is based on actual travel with explicit endpoints, not planned travel.
4. **Currentness:** correct/withdraw actual anchor; application superseded/revoked; package/document/passport revision; conflicting interview/profile; stopped/privacy-blocked dialogue; removed/expired authority; withdrawn source; future anchor/process/application/package heads and clock reversal. Preserve old exact receipt/replay and display its historic/current distinction.
5. **Atomicity/retries:** failure between fact/receipt/task writes rolls back; uncertain result with unreadable current helper still allows exact retry; duplicate keys cannot alter a request. Observe real PostgreSQL lock waits for competing source correction and action, both ordering directions; ensure one coherent task and no same-person cross-attempt mix. No provider, outbox or monetary mutation.
6. **Capacity/recovery:** real maximum record and serialized-byte boundary with a bounded terminal withdrawal/cancel; no lowered limits as proof. Archive-based legacy deadline/manual/task/UZ receipt compatibility, additive composite constraints, populated downgrade refusal and COPY recovery of new anchors, source references, receipts and tasks.
7. **Native:** source application/person, exact actual anchor and proof reference, conditional/official distinction, current stop/unknown reasons and date boundary visible in RU/EN; signed scope/CSRF/stale token/duplicate field/role tests; ordinary calendar actions cannot bypass new binding ownership. Mobile/dark/light/no-JS/keyboard/contrast and print retain the uncertainty and original/current distinction. No automatic contact messages or financial action.

## Decisions still requiring an explicit contract, not invented approval

The implementation can fix its technical structure now. Supported source interpretations must still be declared in a **default-empty** authority: payment-code issuance versus receipt, endpoint inclusion, evidence accepted for actual periods, EAEU branch/family scope, and absence counting/return semantics. An unsupported interpretation returns a precise unknown state. Synthetic fixtures may exercise an explicitly supplied interpretation; they are not owner approval.

Recommended implementation sequence inside the single acceptance target: typed anchor contracts/providers; strict source-clause mapping and pure calculations; versioned existing deadline/task integration; native recording/refresh/withdraw and independent adversarial/recovery review. Do not mark the target complete after arithmetic alone or after one UZ/EAEU fixture. This pre-audit authorizes no production action and awards no whole-C/J status.
