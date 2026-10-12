# E6-25 — applications, documents and dated passport evidence

DONE for reviewed local E01/E02/E03/E05/E07/F01/F02/F03. CRITICAL / solo.
Codee01c5b0bbce264d918bec31eb34ca3c384129506, branch fix/tours-search-quality.
Eight scoped R3/root/staged/commit identities PASS; evidence
`ai/reviews/2026-10-12-e6-25-snapshot.json`.

Three independently reproduced defects were corrected: a document check dated
before a passport replacement could be attached to the new passport revision;
an old issued-document receipt could assert current identity after a passport
change/restoration; process evidence could bypass the first date correction.

Current document/package views and acceptance now use the maximum passport fact
date from validated journals, including legacy import and package withdrawal.
New earlier checks are refused. Old facts, snapshots and hashes stay intact;
current summaries can show a required recheck. Late issued receipts remain real
facts, but their date must reach the current passport boundary before their
identity status is current. A later distinct valid receipt can correct that.
Fresh process observations pin rules_version2; unversioned old observations
replay their original v1 interpretation. No schema migration or journal rewrite.

Builder finalR3:78PASS/595.69s,16new dated checks plus62connected process checks,
`runs/e6-25-r3/runs/e625-r3.xml`. R1:62PASS/1test-helperFAIL; R2:81PASS/1sameFAIL.
The helper erroneously recomputed the current approval state hash for an old
request; R3 resends exact original operation data. Failures are retained.

Independent reviewer: original124domainPASS,83nativePASS; actualPG24PASS plus
two corrected harness controls2PASS (not one green26 run). FinalR3 separate
groups14/11/7PASS include original failures, five Chromium flows, no-JS desktop,
print, strict version gates and replay. Independent APPROVE:
`ai/reviews/2026-10-12-applications-documents-independent-review.md`.

Separate auditor: own9SQLitePASS/44.45s and9actualPGPASS/80.63s, actual archived
693d service/reducer/Evidence handlers, old hashes/receipts, v1-to-v2 process
journals, legacy import/withdrawal and later valid correction. Original R1
consumer failure retained. FinalGO:
`ai/reviews/2026-10-12-applications-documents-final-audit.md`.
Counts overlap; this is not a whole-project suite or whole-project acceptance.

Fixed engineering score remains92/100. All21 earlier review gaps have now been
addressed across E6-22A/E6-23/E6-24/E6-25, but J03 whole affected-implementation
coverage is not inferred from an empty per-criterion gap list. C05/H02/J01/J02/
J03/J05 remain open. All actual source/business policies remain unapproved/empty.
No deployment, real-data migration, source approval, remote push or message.
UI changes and old CRM demo retained. PG55971 remains running for further tests.
