# SELF_REVIEW — E5-04A

- Codex, same builder/context; not independent review/final audit.
- Base 46284fb, target `56f84e0db3ba5817f6fa4dad6030e891eaf2b0e4`, CRITICAL / solo.
- Status PARTIALLY_READY: required independent gates and PostgreSQL runtime UNKNOWN.

Separate pass over task A1–7, complete new routes/form/template/tests, shared integration
and existing source/storage/auth paths. Original PDF physical pages 29 and 88 directly read.

## Findings / design decisions

1. Contact comes from a checked existing visa case, not request body. Existing ORM fixes
   case contact/product/workflow after creation. Named full-admin guard is retained and
   checked server-side even when the older live-authz flag is OFF. No manager permission added.
2. HMAC must use server session_secret, not public CSRF token. The session token, login,
   case and all source/base/as-of/key fields are bound; tampering and another session reject.
3. Shared per-contact profile is labelled explicitly. No separate applicant/application,
   E6 workflow or new visa_inbound access matrix has been fabricated.
4. Preserve condition facts from the signed immutable base, not browser JSON. Explicit clear
   makes a new version; old data remain. Known abroad location removes stale current-stay
   fields; known non-visa basis removes stale visa type. Unknown is not coerced to false.
5. After uncertain commit, error re-render can also lose access to DB. Added a retryable
   fallback with the user's escaped values and same signed envelope; source verification
   still occurs on retry. It must not falsely claim successful save or trusted country data.
6. Incomplete/outdated/unconfirmed trip history must be visible, not hidden by "attached".
   Added human-readable notes. Old report date and new review date are shown separately.
7. First HTTP run: 37 passed / 1 failed. Test looked for any submit button in the full page
   and caught global logout; the actual historic interview had no submit. Scoped parser to
   the actual kg-entry-form, then repeated tests. Requirements were not relaxed.
8. Browser inspection: current CRM look reused, all inputs labelled; old version disables
   fields, native form works with no JS, small-screen layout has no horizontal overflow.
   Existing global UI was not redesigned. Synthetic fixture product name does not imply
   the old outbound service itself becomes an inbound process.
9. New flag OFF at model and Compose, existing workday/show and service/write gates reused.
   GET creates no domain rows. Errors/logs bounded, URL-encoded body/field count limited,
   unknown and repeated fields rejected; reflected values HTML-escaped.

## Evidence so far

- Related HTTP/CRM/storage suite: **187 passed / 1 warning / 156.80s**, before four additional negative/UI cases.
- Browser: **1 passed / 3 deprecation warnings / 31.82s**, mobile390 with JS, desktop1365
  without JS; save/reload/history/focus; outside requests aborted, screenshots inspected.
- Real country alias mapping: CHN→Китай, KGZ→Кыргызстан, RUS→Россия (draft source, not legal approval).
- `prod_traps_check --diff-base 46284fb --limit 1`: **FAIL**, 1 ERROR / 57 WARN, same
  existing ANTHROPIC_API_KEY Compose-forwarding gap; new flag forwarding present.
- Full suite: **3318 passed / 1 failed / 8 skipped / 1 warning / 605.66s**; only known
  test_facts_live_errors date baseline. During that run, body limit was tightened to reject
  a chunk before copying into memory; separate final HTTP gate: **42 passed / 57.58s**.
  No full-suite PASS claimed.
- Committed Git copy `56f84e0`, no `.env`/`prod.env`: **42 passed / 1 warning / 53.86s**
  (`python -m pytest tests/test_admin_kg_entry.py -q`). 13/13 LF manifest hashes match
  Git blobs and copy. Staged whitespace check passed; credential-shaped literal scan
  found 0 matches, not a comprehensive secret audit.

Not a release certification. Existing panel session lifetime/role revocation semantics unchanged;
privileged SQL tampering with all matching hashes is not prevented cryptographically.
No production deployment, migrations, real data, applicant workflow or client messaging performed.
