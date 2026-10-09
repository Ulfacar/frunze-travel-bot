# E5-03E — сохранение квалификации

- Date: 2026-10-09; branch `fix/tours-search-quality`, base `6d24227b2e206308bb8921dc8efc5130c5174c7a`.
- CLASS: **CRITICAL**, mode **solo**; completion target: local change with review packet.
- Builder: Codex; independent reviewer / final auditor: **UNKNOWN**.
- Request: Алан — «Окей продолжай и пдф тоже нужно сделать». Сохраняется разрешение на commits/push рабочей ветки. Уточнение отдельного PDF задано; исходные требования продолжаем.

## Goal and scope

Сейчас E5-03D строит отчёт без сохранения. Добавить неизменяемые версии частичной
анкеты и отчёта с восстановлением последней версии, контролем конфликтов и replay.
Только существующий named full-admin domain API; без HTTP/LLM/production и новых прав.
Одна additive migration; только synthetic local DB. Полная collecting/handoff анкета,
передача менеджеру, утверждение норм и клиентская eligibility остаются отдельными этапами.

## Risk pre-audit

Анкета содержит чувствительные факты. Не принимать имена/номера документов/контакты,
произвольный текст и готовые решения; строгая схема E5-03D. Не записывать содержимое
в логи, fixtures или handoff. История только по тому же contact_id. Сохранение и
проверка источников в одной транзакции; повторный ключ возвращает исходный снимок,
иная нагрузка с тем же ключом отклоняется. CAS защищает от потери обновлений.
Read проверяет источники/хеши; replay дополнительно проверяет версию алгоритма.
ORM неизменяемость не является защитой от администратора БД; хеши не подписи.
Откат пустой новой таблицы разрешён локально, заполненной — отклоняется до удаления.
Production/реальные клиентские данные требуют отдельного release, retention policy
и независимых CRITICAL review/audit; ни один из этих gates не считается закрытым.

## Acceptance

| ID | Scenario | Expected evidence |
|---|---|---|
| A1 | Save partial profile, close session, read latest/id | Same input/report, revision and pinned sources |
| A2 | Resume with full replacement, passport/purpose changes | New revision; old immutable; no stale derived result |
| A3 | Duplicate, changed key payload, concurrent writers, lost commit reply | No duplicate; conflict or safe same-key recovery |
| A4 | Non-admin, foreign contact/history, forged result/PII | Rejected before persistence; bounded errors |
| A5 | Source/result/link corruption, algorithm drift | Read fails on corruption; replay refuses drift; old valid report readable |
| A6 | Migration SQLite cycle, PG offline DDL | Additive only, model parity, populated downgrade refused |
| A7 | Shared domain changes | Relevant checks + full suite; known baseline failure reported separately |

## Plan / evidence

Implement domain snapshot + migration → negative/concurrency/recovery tests → separate
SELF_REVIEW → review packet/handoff/STATE → authorized commit/push. Independent review
and PostgreSQL runtime unavailable so status **PARTIALLY_READY** until those gates close.
CI/deploy/production acceptance N/A for local completion target; no release claimed.

## Final worktree evidence

- Related checks: 233 passed / 2 skipped / 115.29s, before eight additional cases.
- Full final code: **3276 passed / 1 failed / 8 skipped / 1 warning / 490.61s**. Known
  date-dependent tour parser baseline only; all new storage/migration cases passed.
- Original PDF + real bundle/catalog, synthetic contact: three revisions, resume and replay PASS;
  six source inputs SHA/mtime unchanged. New two-page progress report prepared.
- Separate SELF_REVIEW + packet prepared; independent review/audit and PG16 UNKNOWN.
- Status **PARTIALLY_READY**. Full suite is not reported as green.
