# B1 final audit (r4)

Отдельный контекст `codex-auditor`, 14.10.2026, только чтение, без сервера. Записать файл агент не мог,
текст по его итоговому ответу записал builder; вердикты, таблицы и блокеры сохранены.

## Verdict
- **(a) B1 r4 as reviewed local change: GO.** B1–B3, B5–B7 closed in code; B4 closed by the hotfix logically.
  R9 and bot-panel template output unchanged.
- **(b) Production sequence: NO-GO** — blockers P1–P6. Enabling `CRM_BOT_SEND_ENABLED=true` — separate NO-GO
  until S1–S3.

## Auditor's own runs
| Check | Result |
|---|---|
| Snapshot vs working tree (LF-sha256) | 29/30; only `ai/reviews/…rehearsal-evidence.md` differs (text appended after freeze). 1543 tracked files equal `git show 779ed81` |
| Bundle r4 | identity `a90bea9ffd9ec0de2b32` confirmed; 422/422; content equals snapshot |
| pytest from snapshot, 9 files | **121 passed** (191 s) |
| `test_crm_bot_mode_postgres.py` on PG16 | **1 passed**; mutant without advisory lock **1 failed, `assert 8 == 1`** |
| Hotfix echo tests | **25 passed**; hotfix full suite **2251 passed / 1 failed / 8 skipped**; same failing test on clean 913feab (`test_facts_live_errors::test_still_reads_a_plain_request`) — pre-existing |
| Template renders 779ed81 vs r4, 8 contexts × crm_bot_mode unset/False | **80 renders, 0 differences** (non-empty check: with True resend/suggest/hx-on disappear, send_key appears) |
| `prod_traps_check --diff-base HEAD` (B1 tree) | **3 ERROR**: NOT_IN_COMPOSE `CRM_BOT_SEND_ENABLED`, `CRM_DATA_MODE` (new), `ANTHROPIC_API_KEY` (local .env, unrelated) |
| `prod_traps_check` hotfix | 0 ERROR, passed |

## Pre-audit blockers / round-1 vs r4
B1 DONE · B2 DONE · B3 DONE (code; see S2) · B4 PARTIAL (Wappi echo id == send id UNKNOWN) · B5 DONE · B6 DONE
· B7 DONE (DB) / accepted risk (Redis). R1-1 DONE · R1-2 DONE (code; Playwright only builder-reported)
· R1-3 DONE (tests; PG16 role run builder-reported) · R1-4 DONE · R1-5 DONE · R1-6 DONE · R1-7 UNKNOWN
(compose never run) · R1-8 DONE (docstring; operator discipline) · R1-9 PARTIAL · R1-10 OPEN · R1-11 DONE
(in file) · R1-12 OPEN (read_back must be a separate commit).
Bot↔CRM cross-version: state/intercept/db/store/live_assign/services/permissions/calendar_tasks unchanged
913feab→779ed81. **Bot 913feab reading a CRM-written intercept was not runtime-tested** (rehearsal bot ran
with memory state).

## Production blockers (each NO-GO)
- **P1** Live-DB migration without `lock_timeout`/`statement_timeout`; 34 migrations in one transaction;
  ACCESS EXCLUSIVE on `calendar_tasks` until commit. Need a rehearsed method under load
  (`alembic --sql` + `SET lock_timeout` + `psql -1`, or a stop window).
- **P2** No fresh `pg_dump` right before migration with restore check (count+md5 7 tables). Fix-forward
  schema → restore is the only way back; data loss window — Alan's decision.
- **P3** `compose.crm-bot.yaml` never run: port 8079, forwarded-allow-ips, no-access-log, kernel checks,
  prod `crm-bot.env` (no template). Possible safe refusal if PUBLIC has CREATE on `public`.
- **P4** Prod `REDIS_URL` / `STATE_TTL_SECONDS` of the bot not measured.
- **P5** nginx/TLS for bot mode untested; `crm.frunzetravel.kg` now points to R9; switching exposes ~4000
  dialogs behind login — manager access is Alan's decision.
- **P6** Hotfix not committed; B1 traps gate failing.
- **S1** real send on a test number (raw Wappi JSON, echo id equality, number of manager rows);
  **S2** `BOTS` must be explicit in `crm-bot.env` (else `DEFAULT_BOTS` hardcoded profiles); **S3** hotfix on
  prod and verified before enabling send.

## Notes
1. Compose comment claimed egress only with send enabled — false (bot network not internal). NEEDS_HUMAN_DECISION.
   *(builder: comment corrected 14.10.)*
2. Round-2 review file missing *(builder: saved as `…-b1-independent-review-r2.md`)*.
3. Known limitation `pending`+`duplicate` accepted. 4. M2/M3 unchanged. 5. stage/outcome check visibility
   only (same as current panel). 6. Check `SHOW log_statement` before role creation. 7. Flag defaults consistent.

## Required before rollout (order) and rollback
1 Alan's word per step · 2 prod measurements (REDIS_URL, TTL, log_statement, ACL public, port 8079, gateway)
· 3 fresh dump + restore check · 4 migration with timeouts at night, verify version + count/md5 · 5 role via
pipe, `\dp`, negative SQL · 6 hotfix commit → hash → deploy → call in container · 7 compose with image
`a90bea9ffd9ec0de2b32` (sha `c3ee75f0…`), send OFF, takeover → Redis key → bot 913feab silent in that dialog
· 8 nginx backup → `nginx -t` → reload → HTTPS login → X-Forwarded-For real IP.
Rollback: stop `frunze-crm-bot`, nginx back to R9, release intercepts; hotfix `rollback_prod.sh 913feab`;
schema fix-forward, data via dump of step 3.
