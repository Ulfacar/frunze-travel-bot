# E6-26 — current route check of an older saved profile

STATUS: DONE for reviewed local correction, codebd572ed04f0227960bac2c280708359ca04c6ccd.
Independent review and separate final audit APPROVE; handoff
`ai/handoffs/2026-10-12-2031-e6-26-route-profile-compatibility.md`.

CRITICAL / solo, reviewed local correction; parent authorized PDF/CRM work.
Base693d683b9a0adcb8f76d5551bf0f121ca6824fec. Preserve E6-25/UI work.

Independent E6-24 reviewer used the actual archived intake handler and runtime
fingerprint to save count1.0 plus one child. Its historical receipt is valid,
but the corrected current semantic check raises QualificationError. The route
page returned generic503. Return an explicit RU/EN profile-conflict fallback
with no candidate, quote, eligibility or write. Catch only the fresh semantic
evaluation error; stored integrity/infrastructure failures remain errors.

Pre-audit: do not rewrite old input/results, weaken current validation, hide
integrity errors or infer a successful qualification. Actual source/policy
authority and complete C05 remain open. Verify exact old-handler native repro,
valid-route positive control, translated explanation, stored history equality
and existing access/source failures. Independent review and separate audit on
the exact frozen scoped files before completion; no deploy or messages.
