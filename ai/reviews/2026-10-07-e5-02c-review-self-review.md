# SELF_REVIEW — E5-02C-REVIEW

- Task: `ai/tasks/2026-10-07-e5-02c-review-diff.md`; STANDARD / solo.
- Base: `653a20a`, target manifest `2026-10-07-e5-02c-review-snapshot.json` (7 files).
- Reviewer / builder: Codex / Codex. Independence: **SELF_REVIEW**.
- First assessment without builder conclusions: NO, один контекст. Это допустимый отдельный
  проход для STANDARD/solo; не одобрение предыдущих CRITICAL задач.

## Findings and corrections

1. Git core.autocrlf=true меняет raw bytes после checkout. Knowledge source-lock и synthetic
   source hash зависят от raw bytes. Добавлена узкая .gitattributes LF policy (коммит c8228e5).
   На извлечённом committed snapshot 653a20a builder --check прошёл с прежним bundle hash.
2. При чтении повреждённой даты SQLite SQLAlchemy result processor может бросить ValueError
   ещё до валидации снимка. Обнаружено при чтении кода; в финальном варианте это преобразуется
   в обезличенный SnapshotInvalid. Добавлены негативные сценарии для Unit, Version и Set;
   финальный targeted suite **28 passed**. Эта узкая финальная правка выполнена после старта
   полного suite: его результат 2735 относится к версии до этой правки, не к 2738 тестам.
3. Удалён неиспользуемый test helper. Pure diff не вызывает DB/config и предполагает заранее
   валидированные снимки; доменный вход всегда валидирует hash, schema и проекции.

## Checks / evidence

| Criterion | Result | Evidence / limitation |
|---|---|---|
| C1 accurate diff | PASS | add/remove/field values, metadata-only, aliases, key/unit order, absent vs null, true vs 1, no input mutation |
| C2 integrity | PASS | hash/source/metadata/typed projection/delete/active-pointer corruption; final invalid dates in 3 entity types; no payload in error |
| C3 access/scope/read-only | PASS | non-admin/system/bot/dict, invalid IDs before engine; foreign candidate/baseline; SELECT/PRAGMA only; CLI mode=ro |
| C4 actual draft | PASS | 208 added, 0 confirmed, 82 missing value, 6 conflict_ref; DB SHA unchanged before/after CLI |
| C5 Git portability | PASS | checkout-index with core.autocrlf=true, builder --check, unchanged normalized bundle hash |
| C6 commits | PASS for prior 4; final continuation in handoff | Explicit path staging, diff --cached --check; no unrelated artifacts |
| Initial module tests | PASS | 25 passed, 6.97 s |
| Broad regression | PASS | `python -m pytest tests -q`: **2735 passed / 8 skipped / 1 warning**, 278.16 s, before final date-exception hardening |
| Final module tests | PASS | `python -m pytest tests/test_knowledge_review.py -q`: **28 passed**, 6.58 s, after hardening |
| prod_traps | FAIL baseline | `--diff-base 4a22ecb --limit 1`: 1 ERROR / 57 WARN, missing ANTHROPIC_API_KEY compose forwarding |

## Limits / verdict

**APPROVE (SELF_REVIEW for STANDARD local comparison only).** Read-only comparison verifies
consistency, not authenticity or legal accuracy; a privileged SQL writer can change both data
and hash. Missing facts are reported without inventing DEC-07 approval/owner policy.

New code is not wired to HTTP/bot and cannot publish. API Actor must come from trusted server
authentication; CLI trusts the local operator with file access. PostgreSQL review runtime,
independent critical reviews/audit and production acceptance remain UNKNOWN for prior tasks.
No push/deploy/production write was performed. Commit IDs and final copied-snapshot checks
belong in the final handoff, not invented in advance here.
