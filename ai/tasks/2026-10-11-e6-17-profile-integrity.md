# E6-17 — strict applicant-profile integrity comparisons

CRITICAL / solo. Target: reviewed local corrective change for E6-04, no new
criteria points, migration, source approval or deployment. Parent overnight
deadline08:00 Asia/Almaty and final Telegram obligation apply.

Independent review of the previously partial profile module reproduced Python
equality coercion in three integrity comparisons: result replay accepts false→0,
provenance context accepts integer→float, and predecessor pins accept integer→float
after an attacker/test deliberately recomputes the row hash. This is a typed
semantic-consistency defect, not a demonstrated HTTP permission bypass or a
claim to resist complete database/asset forgery. The old browser selector also
uses a label changed by the later interview UI.

Required independent pre-audit GO was provided by package_review after examining
all comparisons, with evidence in `ai/reviews/2026-10-11-e6-04-independent-review.md`.
Use canonical JSON comparisons for result/context/previous/runtime; preserve
existing scalar checks, authority, person/payer separation and all source rules.
No automatic eligibility, new personal fields, publication or data rewrite.

Risk and acceptance: bool/int/float substitutions must fail the appropriate
replay/read/retry/new-write checks even with a recomputed checksum. The fix changes
the current profile code fingerprint, so prior valid receipts must remain readable
and exactly retryable; explicit replay after runtime change must still refuse.
Correct only the obsolete native browser locator, retaining all original flow
assertions. Check real SQLite and guarded actual PostgreSQL, person/family/payer
isolation, CAS/ambiguous commit, migration preservation and native mobile/no-JS.
An independent implementation re-review and separate final audit are required.

Status: implementation pending. No approval or whole-critical J03 credit inferred.
