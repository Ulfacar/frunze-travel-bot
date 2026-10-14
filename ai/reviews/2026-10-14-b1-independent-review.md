# B1 independent review — round 1

Reviewer: отдельный контекст `codex-reviewer`, 14.10.2026, только чтение. Записать файл ревьюер не мог,
текст по его итоговому ответу записал builder: находки и формулировки сохранены, сокращено оформление.

**Verdict: FIX_REQUIRED.** R9 mode intact; pre-audit B1–B3 and B5–B7 closed in code. Send-path
idempotency is not real, composer likely broken under CRM CSP; several required evidence items missing.

## Ran by reviewer
- Snapshot `%TEMP%\crm-accept\b1-r1` vs `snapshot.json`: 26/26 LF-sha256 identical.
- `pytest tests/test_crm_bot_mode.py tests/test_standalone_crm*.py tests/test_admin_chat_redesign.py`
  (from the snapshot): **90 passed**.
- Hotfix worktree (913feab + change): `test_echo_cross_process_dedupe.py test_manager_echo_capture.py`: **24 passed**.
- No browser, no real Postgres, role SQL not executed.

## Findings
1. **major.** `_conversation.html:1-12`, `router.py:2068-2082`. Key regenerated in `htmx:configRequest`
   on every request, so dedupe never fires from the UI. Pre-check is not atomic with `add_message`
   (non-unique index `messages.idempotency_key`, `add_message` returns the existing id without a
   "created" signal), so concurrent same-key requests both reach `WappiAdapter.send`.
   Fix: key per composition, rotated only after sent/failed; atomic claim
   (`pg_advisory_xact_lock(hashtext(key))` or "created" flag); concurrency test.
2. **major (browser).** `_conversation.html:256,511` `hx-on::after-request` and filtered
   `hx-trigger="every 4s [...]"` (lines 58, 277) need `new Function` → blocked by CRM CSP
   (`script-src 'self' 'unsafe-inline'`). Composer reset and chat polling likely dead under CRM.
   Fix: non-eval inline listeners; prove with Playwright under `crm_bot_mode`.
3. **major (evidence).** No tests for allowed non-send routes in bot mode (takeover, release, reassign,
   set_stage, set_outcome, task_*, calendar_task_*); no parallel CRM-takeover vs bot-turn test with a
   shared fake Redis; no test for `scripts/crm_bot_role.py`; role grants never exercised against these
   routes on PG16 (static trace found no gap).
4. **minor (hotfix).** `_already_recorded` text fallback also matches `failed` CRM rows → genuine
   phone/Bitrix reply with the same text within 2 min is skipped in panel and Bitrix mirror.
   Fix: match text only on `pending`. Hotfix relies on Wappi echo id == send response id (unproven,
   same assumption as `is_own`). Nit: import order.
5. **minor.** Superuser check by username only; verify `pg_roles` flags and
   `has_table_privilege(DELETE messages)` at startup.
6. **minor.** `strict = crm_data_mode == "bot"` (router.py:1897, 2050) does not require
   `crm_standalone_enabled`; gate like `_chrome`.
7. **minor.** `--forwarded-allow-ips 172.20.0.1` unverified; wrong value collapses all users onto one
   IP for the login rate limiter.
8. **minor.** `crm_bot_role.py` prints plaintext password into a `.sql` file; pipe into psql or use SCRAM.
   `GRANT SELECT ON ALL TABLES` wider than routes need (design accepted).
9. **minor.** `RedisStateStore.ping` requires a dialog key → crash-loop on fresh/expired Redis; does not
   prove it is the bot's Redis; TTL parity not enforced. Document as precondition.
10. **minor.** Strict extractor returns "" for odd Wappi response shapes → "failed" for a delivered
    message → manager retypes → duplicate. Capture the real response on test-number rehearsal;
    `conv.chat_id or user_id` falls back to `bot:phone` — use `conv.phone`.
11. **minor.** uvicorn access log carries `/admin/conversation/getvisa:9967…` paths (phone numbers);
    use `--no-access-log` or a filter.
12. **nit.** read_back guard silent no-op and mixed into B1 (separate commit); bundle includes bot files
    only `if is_file()`; pre-audit M2 (Redis load-modify-save race) unchanged, not a regression.

## Required before APPROVE
Findings 1, 2, 3 (concurrency test, browser test, PG16 role run); 4 with the hotfix; 5–9 same cycle.
