# E6-26 — historical profile conflicts in current route checking

DONE, reviewed local CRITICAL / solo correction. Code
bd572ed04f0227960bac2c280708359ca04c6ccd, exact3 scoped root/frozen/staged/commit
identities PASS (`ai/reviews/2026-10-12-e6-26-snapshot.json`).

An older valid saved profile with count1.0 and a child conflicts with the newly
corrected family-count check. Current route evaluation now gives an explicit
RU/EN profile-conflict fallback, rather than generic503. Catch only fresh
QualificationError from evaluate. No candidate/eligibility/quote or data write;
corrupt stored profile/source, unexpected runtime and constructor errors still
fail as before. The historical receipt remains unchanged.

Builder31PASS/76.97s on isolatedR1. Independent reviewer9PASS/28.67s plus5authority
checksPASS/7.97s: actual archived handler/fingerprint, RU/EN native fallback,
positive candidate, corruption/errors and no DML. Separate auditor6PASS/19.38s
with its own archived-handler native probes. Independent review and final audit
both APPROVE: `ai/reviews/2026-10-12-route-profile-compatibility-review.md` and
`ai/reviews/2026-10-12-route-profile-compatibility-audit.md`.

PostgreSQL N/A for this narrow delta: after removing only the new try/catch,
propose_route AST matches the reviewed base; SQL/locks and upstream storage are
unchanged. No full-suite claim, actual policy approval or release. C05 is still
open: personal history/calculation, registration and interview reconciliation.
