# E6-24 — reviewed source archive and saved qualification

DONE for local A01/A02/A03/A04/B01 review. CRITICAL / solo.
Code693d683b9a0adcb8f76d5551bf0f121ca6824fec, branch fix/tours-search-quality.
Six scoped R2/root/staged/commit identities PASS; manifest
`ai/reviews/2026-10-12-e6-24-snapshot.json`.

The actual pinned 94-page PDF now has an additive reproducible raw-text and
position archive: 3,006 ordered blocks, 8,820 raw text lines, all page/block/top
hashes verified against the actual PDF independently twice. The original PDF
and previous Markdown/208 typed units remain intact. Extraction is evidence,
not approval or complete typed interpretation. The generator pins PyMuPDF1.27.2.3
and MuPDF1.27.2; `python scripts/build_kg_full_source_archive.py --source
'../Kyrgyzstan-visa-knowledge-base-v1.1.pdf' --check` verifies identical bytes.

JSON Schema accepts integral floats. Two former int-only semantic guards missed
large groups and inconsistent family counts; both now handle validated integral
numbers. Native forms render those numbers as canonical digits while the POST
parser still rejects manually submitted decimals. Old saved inputs, immutable
results, exact retries and replay-runtime mismatch behavior are preserved.

Builder: R1 related139PASS/184.84s; finalR2 native/domain75PASS/207.37s.
Reviewer: baseline213sourcePASS/1optionalPDFskip (actual PDF checked separately),
39native/storagePASS,4actualPGPASS,1actualChromiumPASS; R1fix23focusedPASS and
3PG upgradePASS; finalR2 own21PASS/40.16s. Auditor: actual94page archive equality,
13numeric/archivePASS,10source/corruptionPASS; original native2FAIL preserved,
correctedR2 own24PASS/32.18s. These overlap and are not a whole-suite count.
Independent APPROVE and separate GO:
`ai/reviews/2026-10-12-source-profile-independent-review.md` and
`ai/reviews/2026-10-12-source-profile-final-audit.md`.

Full C05 remains open. A separately discovered old-profile route503 is tracked
under E6-26; it does not invalidate source/profile persistence acceptance.
E6-25 is correcting dated document/issued receipt facts before its review gate.
All208 real source units remain drafts. No production, live migration, real
source/privacy/policy approval, remote push or external message. Existing UI
changes and CRM demo remain preserved.
