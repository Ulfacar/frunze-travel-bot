# B1 independent review — round 2 (snapshot r3)

Отдельный контекст `codex-reviewer`, 14.10.2026, только чтение. Записать файл агент не мог, текст по его
итоговому ответу записал builder; находки и вердикт сохранены.

**Verdict: APPROVE** for the reviewed local change (snapshot `b1-r3`); no blockers/majors. Not release evidence.

## Ran
- From `b1-r3`: bot mode, role, standalone ×4, chat redesign, new look — **117 passed**.
- `tests/test_crm_bot_mode_postgres.py` on local PG16 — **1 passed**.
- Hotfix: echo dedupe + echo capture — **25 passed**.
- Own Chromium check of the `base.html` script with bundled htmx 1.9.12 under the CRM CSP (mock backend,
  localhost): 0 console/CSP errors; key set on load and survives `hx-preserve` swap; polling 2 unfocused /
  0 focused; `sent` resets text and rotates key; `duplicate` did neither.
- Startup role query executed on PG16: valid, one 7-column row.

## Round-1 findings
1 FIXED · 2 FIXED · 3 FIXED (SQLite; PG16 role run only in builder evidence; two loose assertions:
stage 200|400, task 200|303) · 4 FIXED (import-order nit remains) · 5 FIXED (not run against the real role)
· 6 FIXED · 7 ACCEPTED-RISK (gateway IP asserted only by comment) · 8 NOT FIXED (password to file)
· 9 ACCEPTED-RISK (ping needs a dialog key) · 10 PARTIAL (`conv.phone` fixed; strict extractor unchanged,
real Wappi shape not captured) · 11 FIXED · 12 NOT FIXED (read_back in same change; `is_file()` bundling; M2).

## New findings (all minor)
1. After `duplicate` the key is not rotated and text not cleared → a new message typed in the same box is
   silently dropped as another `duplicate`. Fix: treat `duplicate` like `sent`.
2. Process death between key claim and Wappi call leaves `pending`; every retry returns `duplicate`.
3. `_set_intercept(True)`/`assigned_to` run before `add_message_once` → a late duplicate re-intercepts a
   dialog the manager already released. Fix: only when `created`.
4. `has_schema_privilege(public, CREATE)` also counts PUBLIC CREATE → possible safe crash-loop on prod; check ACL.
5. UNKNOWN: rehearsal evidence (per reviewer) covered r1 only; Wappi echo id == send id unproven.

## Builder disposition (r4)
1, 3, 8 fixed in r4 (+ test `test_duplicate_retry_does_not_reintercept_released_dialog`); 2 accepted as known
limitation (auto-resend is riskier); 4 — startup check passed on the restored prod copy (r3/r4 stand);
5 — r3 and r4 stands ran under the real role (see rehearsal evidence rounds 2–3); Wappi id remains open (S1).
