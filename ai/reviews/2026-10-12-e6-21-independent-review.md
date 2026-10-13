# REVIEW: E6-21 approved knowledge answers

- Task: `ai/tasks/2026-10-12-e6-21-grounded-answers.md`.
- Class/mode: CRITICAL / solo. Completion target: reviewed local change, no release.
- Base: `f06f5eacef734bfde625813c663bc91815fe01bc`.
- Final target: uncommitted frozen `runs/e6-21-r5`; manifest `ai/reviews/2026-10-12-e6-21-snapshot-r5.json`.
- Reviewer: fresh agent `/root/e621_review`; builder: root agent. INDEPENDENT, not SELF_REVIEW. Same available provider; no claim of provider diversity.
- First assessment without builder conclusions: YES. Read task, actual source/dependencies and exact r1 snapshot before first verdict. No builder handoff or earlier audit verdict was used.
- First verdict: FIX_REQUIRED. Final verdict: APPROVE for the bounded local target below.

## Findings and resolution

| Severity | Location / trigger / consequence | Independent evidence | Final disposition |
|---|---|---|---|
| P2 | `app/admin/templates/kg_answers.html` inherited external HTMX/font/preconnect resources from `base.html`, contrary to AC6. Even an empty answer page attempted third-party assets. | Actual r2 native HTML probe found four external resource declarations; `runs/e6-21-reviewer-r1/probes-r2.xml`: this test FAIL. Browser tests which merely abort external traffic cannot establish absence of attempted requests. | FIXED in r3. Base resources now have overridable blocks; answer child overrides both with empty blocks. Own final HTML probe PASS and Chromium asserts zero attempted answer-page external requests/no preconnects. Defaults remain available to other pages. |
| P2, test evidence | r1 mixed-rejection test recomputed the withdrawal manifest after review rejection instead of retaining the lifecycle manifest; version test assumed the first fact was a numeric value despite canonical key ordering. These prevented the required acceptance tests from completing. | Own r1 focused execution: 57 PASS / 2 FAIL, `focused-rerun.xml`. Traces independently examined against publication logic and value normalization. | FIXED in r2; both cases PASS in the final-runtime focused run. No runtime publication defect inferred from these test mistakes. |
| P2, test evidence | r3 condition-catalog fixture placed `conditions.json` inside a strict three-file source bundle, so the import was correctly rejected before the intended acceptance scenario. | Static discovery plus own r3 execution reproduced rejected import; `final-r3.xml`: 62 PASS / 1 FAIL. | FIXED in r4 by placing the catalog beside the bundle. Exact-r4 corrected scenario PASS in `catalog-r4.xml`. Runtime unchanged. |

No unresolved runtime defect found in the reviewed scope. Source approval, deployed behavior and business/legal correctness were not inferred from synthetic checks.

## Acceptance coverage

| Criterion | Evidence status | Evidence / boundary |
|---|---|---|
| AC1 | PASS | Actual approved publications produce RU/EN answers with all structured leaves, source excerpt, source/version hashes and references. Kind and registration-country scope are explicit; zero/false values and qualifiers survive. No personal eligibility, final price or exact date is inferred. |
| AC2 | PASS | Actual unpublished/rejected/withdrawn/expired/policy-mismatched sources are withheld. Projection corruption also returns specialist fallback; denied authority remains an exception. Legacy publication regression covers conflict/evidence guards. |
| AC3 | PASS | Mixed selections return approved facts only and list the unanswered rule IDs. Imported draft condition catalog case withholds the conditional rule while retaining the independent deadline rule. |
| AC4 | PASS | Version switch, review change, expiry and withdrawal rechecked on each request; request cannot supply policy authority. Own actual PostgreSQL race observed withdrawal waiting on the held read transaction lock, then fresh read withheld all values after withdrawal commit. Retrograde-review probe did not resurrect approved values. |
| AC5 | PASS | Domain authorization and native manager/pilot/workday gates reject before source access. Duplicate/malformed selections denied; read-only SQL capture has no source mutations. No send path is connected. |
| AC6 | PASS | Native empty/error/hostile markup cases; mobile 390px with JS and desktop 1365px without JS; escaped source text, no-store, no-referrer, zero attempted external answer-page resources. Own screenshots and both print pages inspected. |
| AC7 | PASS | Null/unknown values, conditional catalogs, catch-all country scope, missing numeric counting basis, placeholder templates, unavailable template translation and oversize answers fall back. Every supported fully specified family exercised through actual publication. |

## Snapshot identity and checks actually performed

Windows / Python 3.12, env-free frozen archives, synthetic SQLite, local Chromium and explicitly isolated PostgreSQL on loopback. No production connection, real personal data or external messaging used. PostgreSQL credentials were consumed only by the existing guarded local fixture; not printed or copied into this report.

Manifest verification: r1 9/9, r2 11/11, r3 12/12, r4 12/12 and r5 14/14 matched SHA-256 file hashes. Compared the frozen snapshots directly:

- r3 -> r4: only the condition-catalog fixture path line in `tests/test_knowledge_answers.py` changed.
- r4 -> r5: only two legacy test allowlists gained the pilot-gated answer route, with explanatory comments. Dedicated answer-page ON/OFF/role tests retain gate coverage.
- All final application/runtime files are byte-identical between r3, r4 and r5. Earlier runtime checks therefore apply to r5 by verified identity; this is not represented as a single full-suite r5 execution.

All XML/private probes below are under `runs/e6-21-reviewer-r1/`:

| Snapshot | Reviewer command/scenario | Actual result / artifact |
|---|---|---|
| r1 | `python -B -m pytest tests/test_knowledge_answers.py tests/test_admin_kg_answers.py tests/test_knowledge_publication.py -q -p no:cacheprovider --basetemp ../e6-21-reviewer-r1/tmp2 --junitxml ../e6-21-reviewer-r1/focused-rerun.xml` | 57 PASS / 2 FAIL, 80.93s. Both failures recorded above. |
| r2 | `python -B -m pytest -p tests.conftest -p no:cacheprovider ../e6-21-reviewer-r1/test_review_probes.py -q --basetemp ../e6-21-reviewer-r1/probes-r2-tmp --junitxml ../e6-21-reviewer-r1/probes-r2.xml` | 2 PASS / 1 FAIL, 14.09s. Actual stored projection corruption and retrograde review PASS; external resources FAIL. |
| r3 | Focused command as r1, using `final-r3-tmp` / `final-r3.xml` | 62 PASS / 1 FAIL, 127.39s. Sole failure was the then-invalid catalog fixture. |
| r3 | `python -B -m pytest -p tests.conftest -p no:cacheprovider ../e6-21-reviewer-r1/test_review_postgres.py ../e6-21-reviewer-r1/test_review_probes.py -q --basetemp ../e6-21-reviewer-r1/own-r3-tmp --junitxml ../e6-21-reviewer-r1/own-r3.xml` with the explicit isolated connection file configured | 4 PASS, 35.14s. Includes own actual PostgreSQL concurrency probe, not inherited builder results. |
| r3 | `python -B -m pytest -p tests.conftest -p no:cacheprovider ../e6-21-reviewer-r1/test_review_browser.py -q --basetemp ../e6-21-reviewer-r1/browser-r3-tmp --junitxml ../e6-21-reviewer-r1/browser-r3.xml` | 2 PASS, 37.77s. Browser source copied unchanged except artifact directory to avoid shared outputs. Artifacts: `browser-r3/`; mobile answers/fallback and both PDF pages visually inspected. |
| r4 | `python -B -m pytest tests/test_knowledge_answers.py::test_imported_draft_condition_catalog_cannot_be_quoted -q -p no:cacheprovider --basetemp ../e6-21-reviewer-r1/catalog-r4-tmp --junitxml ../e6-21-reviewer-r1/catalog-r4.xml` | 1 PASS, 12.40s. Corrected scenario exercises imported catalog, publication and selective fallback. |
| r5 | `python -B -m pytest tests/test_admin_shell_and_direction_split.py tests/test_admin_new_look.py -q -p no:cacheprovider --basetemp ../e6-21-reviewer-r1/shell-r5-tmp --junitxml ../e6-21-reviewer-r1/shell-r5.xml` | 42 PASS, 23.08s. Exact final two changed legacy files; confirms shared shell defaults remain compatible. |

An initial r1 test launch used a nonexistent basetemp parent and produced 21 PASS / 38 setup errors (`focused.xml`); that was reviewer harness setup, not application evidence. Corrected rerun is listed above. Deprecation warnings from installed Starlette/websockets packages do not change these results.

The PostgreSQL probe held the answer read after journal validation, started withdrawal through a separate connection, observed `pg_stat_activity.wait_event_type='Lock'`, resumed the reader, awaited withdrawal commit, and verified a new answer request returned `specialist_required` with no answers. This confirms coherent transaction ordering; it does not promise that a displayed historical response automatically updates without a new request.

## Verdict and limits

APPROVE for reviewed local E6-21 / H03 adapter and native full-admin screen on exact r5. All task acceptance rows have evidence, mapped across byte-identical final runtime snapshots and the explicitly rerun changed tests. This supplies independent review only; separate critical final audit remains the auditor's responsibility.

The fixed H03 wording is supported for this internal answer surface. This review does not establish installed-channel dialogue integration, H02/J02 completion, personal immigration eligibility, source/legal approval, owner acceptance or production readiness. No deployment is approved. Actual sources/policies remain subject to existing human gates. Reviewer did not run a full repository suite or the complete PostgreSQL scenario matrix.
