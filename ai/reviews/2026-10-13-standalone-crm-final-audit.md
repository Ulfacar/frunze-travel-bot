# Standalone CRM — separate critical audit

Auditor: `/root/e622_audit`, 2026-10-13. Protocol: solo / CRITICAL. Requirement: `ai/tasks/2026-10-13-standalone-crm-release.md`; prior source-first risk assessment: `ai/reviews/2026-10-13-standalone-crm-pre-audit.md`. **Final verdict: GO for the exact R9 reviewed technical candidate and its isolated verification deployment. Public release remains PARTIALLY_READY / UNKNOWN, not approved by this report.** Actual image integrity/kernel restrictions, PostgreSQL initialization/restore, exact signed recovery, concurrent intake, independent implementation review and final native evidence pass the scope below. Hostname, public TLS/proxy and a fresh live deployment still require their separate completion checks. Earlier interim dispositions/failures below are retained chronologically and are superseded only within this explicit final technical scope. Own and builder executions remain separately attributed.

## Scope, identity and independence

The task authorizes a new isolated authenticated CRM, with no old bot/database change, copied customer data or provider credentials, scheduler, webhook admission or sending. It does not grant source/legal/calendar/privacy policy approval or J05. The release task still records hostname/access selection as pending; the parent handles that decision.

I read the task, applicable instructions, existing startup/auth/router/schema/packaging and proposed standalone code before implementation verdicts. I independently prepared env-free copies from Git base `5200ac1bdec2faab82840e01e6372b33851b9a1d`, then verified and applied each frozen overlay. No root application import, root `.env` read, remote/server call, deployment, PostgreSQL operation or root runtime mutation occurred. Own test-only changes stayed in the audit archives, including temporary compose mutation restored in a `finally` block. Only reports were written under `ai/reviews`.

| Frozen candidate | Overlay count | Snapshot normalized-LF SHA256 |
| --- | ---: | --- |
| `runs/crm-standalone-r2` | 20 | `c7516572a1b43fe394590a031ffc075b26a72eed18c00217457c2070f8cf0a52` |
| `runs/crm-standalone-r3` | 23 | `b77e26a6b45cb96836e5c467a7238a9c851a98d5e714da433855e555331dba0f` |
| `runs/crm-standalone-r4` | 23 | `26738f6b704f9d300ab6b3f729dece3270ab7afb1a204222b000c54125fc97b8` |

Own preparation script: `runs/prepare_crm_audit.py`. Exact copied-file identities are in each `runs/crm-standalone-audit-rN/runs/audit-identity.json`. These are uncommitted snapshot identities, not invented commits. User UI changes remain preserved; their deployment acceptance depends on the actual native/browser review.

## Confirmed original defects and corrections

| Finding | Original observed failure | R4 corrective evidence |
| --- | --- | --- |
| SR-A1 — incomplete bootstrap reported ready | On R2, a rejected draft import after schema and inert-product creation left tables/product committed. Fresh initialization refused the nonempty DB, yet actual app lifespan and `/health` returned success. This is a real interrupted-bootstrap recovery/readiness failure, not an arbitrary damaged-table fixture. | The pending/ready `CrmBootstrap` marker prevents app readiness. Explicit resume accepts only the recorded incomplete bootstrap and required empty operational scope. My unchanged original negative now passes. A second control resumes the real source import, reaches ready, retries without duplicate product/workflow/source version, proves zero conversations and no active source version, and exercises authenticated intake-page access. |
| SR-A2 — fragmented request memory amplification | R2 buffered one list element per ASGI frame. A 256 KiB body supplied in one-byte frames consumed 23,554,457 bytes of measured Python allocations before delivery. The nominal total-byte limit did not bound fragment bookkeeping. | The bytearray accumulator uses 542,647 measured bytes for the same body/frame sequence and still delivers exactly 262,144 bytes. The original resource oracle passes; no request/domain limit was lowered for the test. |
| SR-A3 — unverified deployment bytes retained the same release identity | On R3, changing frozen compose's loopback mapping from 8078 to 8878 was accepted by the packager. Both releases had identical manifest bytes/hash despite different actual compose bytes. | R4 verifies frozen overlay hashes before packaging and hashes actual deployment helper/compose bytes in the release manifest. The unchanged altered-compose negative is rejected. The complete actual R4 bundle is separately verified against the independently reconstructed archive below. |

All original failing XML/artifacts remain. The R2 source-loader test also contained an auditor harness error (`load_catalog` instead of the actual specialist loader `load`), which failed before its intended assertion; it is not a fourth runtime defect. The corrected loader test passes R3/R4. No failure is silently recounted as PASS.

## Own execution evidence

All commands below ran in the corresponding env-free audit archive with SQLite/TestClient or pure local source/packaging. SQLite fixtures construct domain metadata and the expected version row; these checks do **not** prove actual PostgreSQL migrations, DDL constraints or deployed role behavior.

| Candidate / command | Actual result | JUnit |
| --- | --- | --- |
| R2: `python -X utf8 -m pytest tests/test_audit_crm_boundary.py -q --tb=short --junitxml=runs/audit-boundary-r2.xml` | 2 PASS; 2 genuine failures; 1 harness failure; 16.415 s | `runs/crm-standalone-audit-r2/runs/audit-boundary-r2.xml`, raw SHA256 `0e2f3dc3e4acc3e93f0eb08f48c7261d92cc4e94a54328fa356070afc0e88d78` |
| R3: `python -X utf8 -m pytest tests/test_audit_crm_boundary.py -k 'not fragmented' tests/test_audit_crm_bundle.py -q --tb=short --junitxml=runs/audit-bootstrap-bundle-r3.xml` | 4 PASS; 1 genuine failure; 1 deselected; 15.898 s | `runs/crm-standalone-audit-r3/runs/audit-bootstrap-bundle-r3.xml`, raw SHA256 `8171112fe477669c5d8558d02425506a4ffb61577473ef5c8988a682e0b20385` |
| R4: `python -X utf8 -m pytest tests/test_audit_crm_boundary.py tests/test_audit_crm_bundle.py tests/test_audit_crm_resume.py -q --tb=short --junitxml=runs/audit-corrective-r4.xml` | **7 PASS**, no failure/skip; 21.245 s; existing dependency deprecation warning | `runs/crm-standalone-audit-r4/runs/audit-corrective-r4.xml`, raw SHA256 `26d9d9e2a558edd89d624721a32bf9a3048561f9c3209fe19abb07574832d62b` |

The seven R4 controls cover the two bootstrap scenarios, fragmented body bounds, frozen bundle mutation refusal, actual catalog loaders, live account/role removal and reserved-name authorization/Host refusal, and oversized login/ambiguous-origin refusal. The retained work/package/specialist/source loaders run from the copied candidate. Peer native controls are separate evidence; I do not count them as my tests.

## Release bundle verification

Command from repository tooling context, without importing the root application: `python -X utf8 runs/verify_crm_audit_bundle.py r4` — **PASS**.

The verifier checked all **420** actual file contents against both their release hashes and the independent Git-base-plus-23-overlays archive. It also checked the embedded frozen manifest, exact tar membership/content, no duplicates or nonregular/link members, and absence of environment files, credential artifacts, test/run evidence and unexpected paths. The source PDF hash matches the pinned original. Verification was over actual file bytes, not merely agreement between two builder-generated lists.

- Release manifest raw SHA256: `870fdda25720e3fd060f7972c9d2ed5a032787b2495198c15b83fc8fd6f681ab`.
- Tar SHA256: `49659a04b6c955e35241587779422bb8a23a469f8ea34f58b0c1b6b0e36779a5`.
- Evidence: `runs/crm-standalone-audit-r4/runs/audit-bundle-verified.json`, raw SHA256 `9902a7e11a012876462659eb0f28660eee3f3b73ccbd7c2162ba4ad514e23d57`.

This establishes the R4 context, not a later build's image digest or runtime dependency identity. Later Docker/compose changes require their own manifest/image mapping.

## Source assessment and residual gates

The dedicated entry point does not use the old bot lifespan. It validates standalone configuration before native router setup, provides current-roster-bound sessions, a host-only Secure/HttpOnly cookie, exact-origin checks on unsafe requests, bounded bodies and an explicit write-route/module admission set. Strict standalone manager scope removes the old reserved-display-name privilege shortcut. Provider/send endpoints are excluded. Manual intake retains an immutable request receipt and exact phone identity; the standalone quick-task branch uses exact `manual_visa:` identity rather than the legacy suffix lookup. The latter suspected suffix concern was examined and is **not** a standalone finding.

Bootstrap now separates completed readiness from partial initialization, seeds only the explicitly inert intake product/workflow, and leaves imported knowledge inactive/unapproved. Compose and the environment generator use an independent owner and nonsuperuser runtime role, volume and internal network, loopback application port and no published database port. These are source facts; actual role/network/schema behavior still requires the image/PG checks.

The independent native reviewer reported residual Sortable CDN/unsupported stage behavior in the R3/R4 board; that correction and the reviewer's complete final HTTP/browser verdict were pending when this interim report was written. Existing read-only route admission is broader than individual routes; the actual admitted route table and no-side-effect sentinels remain important final checks. No hypothetical unseen route exploit is asserted here.

Required remaining evidence before release GO:

1. Actual final image and installed asset/loaders/timezone identity; final source/bundle/image mapping; absence of private files and unsupported external resources.
2. Actual fresh PostgreSQL schema/head and both metadata families, runtime-role permissions/composite constraints, interrupted initialization/retry, concurrent intake and exact-retry behavior where relevant.
3. New-service-only restart persistence and fresh backup restore, preserved historical receipts/IDs and one new allowed operation; old bot identity/data remain unchanged.
4. Final native authorization/denied endpoints/no outbound effects, real manual intake through case/profile/documents/internal tasks, mobile/no-JS/print behavior, and final independent reviewer approval.
5. Confirmed hostname and intended access roster, TLS/proxy/forwarded-header limits, cookies/security headers and timeout/rate behavior at that hostname; explicit rollback to only the new route/app with volumes retained.

## Host no-new-privileges compatibility addendum (design only)

After the R4 checks, the parent reported a built R5 image and a Snap Docker/AppArmor startup failure specifically when Docker-level `no-new-privileges` was enabled. I did not reproduce that server observation. The proposed absolute exec-form `ENTRYPOINT ["/usr/bin/setpriv", "--no-new-privs", "--"]` is a viable bounded application-process-tree design, subject to actual-image verification. The Linux kernel documents that the flag is inherited and irreversible, and explicitly warns of interaction with LSM transitions: [kernel no-new-privileges documentation](https://www.kernel.org/doc/html/latest/userspace-api/no_new_privs.html). This supports the mechanism; it does not prove the particular host result.

Acceptance requires the actual application process to show UID/GID 10001, `NoNewPrivs: 1`, zero inherited/permitted/effective/bounding/ambient capabilities, `Seccomp: 2`, and enforcing `docker-default` AppArmor. The fixed wrapper must be trusted, non-setuid, without file capabilities, and fail closed if absent. Keep nonroot/read-only/cap-drop/seccomp/AppArmor/network controls; do not use privileged or unconfined mode or alter host security policy.

Docker healthcheck and `docker exec` do not traverse ENTRYPOINT. Therefore the healthcheck and maintenance/bootstrap execution paths also need an explicit wrapper, or must use a run path that retains the entry point. A helper's own `/proc/self/status` is not evidence about PID1; inspect the target application process. There is a deliberate initial trusted-wrapper execution before it sets the flag, so this is not a claim that every container process starts with Docker-level NNP. **No final image approval or release GO is implied by this design assessment.**

At this checkpoint all auditor local tests are finished, no auditor process or PostgreSQL slot is active, and the three confirmed local findings are closed on exact R4. Final release status remains **PARTIALLY_READY** pending the listed concrete evidence.

## R6 local delta and peer-review checkpoint

Independently reconstructed and verified `runs/crm-standalone-r6`: base unchanged, **25 overlays**, manifest normalized-LF SHA256 `e136c9b982812d7c42ec00b3fb0cd48e28d8ffb416f08c5a855d4ae431b9e8b0`. R4→R6 changes are exactly the three standalone board/attention templates from R5, Dockerfile, compose and the dedicated entry point. Bootstrap/intake/router/domain/source bytes are unchanged. The Dockerfile now wraps both ENTRYPOINT and HEALTHCHECK, limits Uvicorn concurrency to16, and production `validate_configuration` refuses an unexpected Linux UID or missing kernel restrictions before application creation or bootstrap CLI operations.

Own command in `runs/crm-standalone-audit-r6`: `python -X utf8 -m pytest tests/test_audit_crm_kernel.py -q --tb=short --junitxml=runs/audit-kernel-r6.xml` — **8 PASS /8.110 s**, exit0. Seven negatives independently vary NNP, seccomp, effective/bounding capabilities, missing NNP, platform and UID; one positive retains all required settings. This is an injected `/proc`/identity unit check of fail-closed control flow with a syntactically valid synthetic production DSN, **not actual Linux kernel evidence or a PostgreSQL connection**. JUnit raw SHA256 `1e07bae84af570a0428284ac3c363e6acdc3091ce19240821714fd0800f126c3`.

Own `python -X utf8 runs/verify_crm_audit_bundle.py r6` also **PASS**: all420 actual files and exact tar contents agree with the independently reconstructed candidate. Release manifest SHA256 `4f23b8c189f1eccbf8131028630bebadfab6b443b0e02275613052d214f2099e`; evidence `runs/crm-standalone-audit-r6/runs/audit-bundle-verified.json` raw SHA256 `40e8b75728e69949c37a65292a0c575a5846582f07bd103bb6f1a4746a6d0c49`.

After the own initial assessment, I read `ai/reviews/2026-10-13-standalone-crm-independent-review.md` (reviewer `/root/publication_review`, local R5 **APPROVE**, LF SHA256 `e855f8ed2fa1f9950bb10f060d7979fb2d3ceb6eebb56ec85232b100fad2bdf0`). It preserves six original runtime/presentation findings, eight passing R4 controls plus the unchanged R5 card correction. The residual Sortable/unsupported control issue is closed on the mapped R5/R6 templates. The review explicitly excludes actual image/PG/browser/release approval; I preserve that boundary. No new confirmed local source defect remains at this checkpoint. The actual image/PID1/role/schema/recovery/browser/hostname gates above are still open; **no release GO**.

Three additional own R6 kernel checks ran separately: `python -X utf8 -m pytest tests/test_audit_crm_kernel.py -k 'sqlite_switch or missing_proc or malformed_capabilities' -q --tb=short --junitxml=runs/audit-kernel-extra-r6.xml` — **3 PASS /5.32 s, 8 deselected**, exit0. They prove the test switch cannot bypass a production DSN's kernel guard, unavailable `/proc` refuses startup, and malformed capability data refuses startup. The latter two preserve the raised startup exception rather than claiming an HTTP error contract. The peer's R6 mapping addendum independently confirms that outside `validate_configuration`/its `os` import, the HTTP code AST is unchanged; updated peer report LF SHA256 `7be56c8ceffeb8eb97cd714651a8134b35ef34facab91e1a69c3ace0cbcf871d`.

## Authorized actual image and PostgreSQL read-only audit

The parent subsequently explicitly authorized inspection of **only** the newly created `frunze-crm-check` service. This expands the later audit beyond the earlier local-only boundary; it does not retroactively change which evidence was local. I did not inspect old bot environment/data or change host security policy.

Own remote script `runs/crm_audit_host_read.py`, invoked through `ssh frunze python3 -`, checks the exact selected app/DB project identities and emits only nonsecret configuration facts, filenames/hashes, kernel flags and schema facts. It never outputs environment values, login credentials or customer rows. An initial probe assumed a Python `tzdata` distribution and stopped with a harness `PackageNotFoundError`; Linux actually uses system timezone files. This was corrected to record the actual provider and test `Asia/Bishkek`, without adding a package or changing the image.

Actual image: `sha256:4f00c47125d7456dcecb5205474eed2e3a96a2bad97e8538dafc386480d09e1a`. The captured container already used the parent's R7 **topology-only** replacement: private `172.30.78.10`, release environment identity `fd410f98913ad34ec81a`, same exact R6 image. The R6 loopback port publication had not provided host connectivity on the actual Docker internal bridge; the parent moved its dedicated host proxy upstream to the fixed private address. No published app or DB port is asserted for this final topology.

`python -X utf8 runs/verify_actual_crm_image.py` — **PASS** over the actual captured image data:

- All **417** files actually installed under `/app` match the independently verified R6 payload byte-for-byte (420 packaged files minus Dockerfile and the two external deployment files). Actual retained2 process versions,3 package versions, specialist catalog and source-search loaders succeed; the original source PDF/local HTMX hashes match.
- Actual PID1 and the explicitly wrapped probe show UID/GID10001, all five capability sets zero, NNP1, seccomp2, and `docker-default (enforce)`. `setpriv` is root-owned0755 with no file capabilities. Read-only root, cap-drop ALL, PID/memory bounds and wrapped healthcheck are present. This is actual kernel evidence, not the earlier injected unit test.
- Exactly the new internal bridge/volume is attached; no application bind mount, no app/DB published port, and no default IPv4 route. This is bounded network isolation evidence, not a claim that host-gateway communication is impossible.
- Runtime PostgreSQL role `frunze_crm` has no superuser/createDB/createRole/replication/bypassRLS privileges. Head0043, ready marker and original source SHA match. All declared DomainBase and LegacyBase tables/columns exist, **78 tables**. This reflection check alone does not prove constraint behavior; the fresh restore below separately validates those.
- No provider tokens/bot registrations; no root env/run/test/credential files inside the application payload; forbidden webhook/send/resend/followup/suggest/system/demo paths absent from the actual route table.

Actual image data: `runs/crm-standalone-audit-r6/runs/audit-host-image-r6.json`, raw SHA256 `750356228c46f65df224d41c0fd802d49bad88b85a9d9f5c5da16b88ef8a0577`. Machine verification: `runs/crm-standalone-audit-r6/runs/audit-image-verified.json`, raw SHA256 `c12d3cd8848825b7a41697fa8edc0592c09ec8de3c8d423873b1f683b682c455`. Actual runtime versions, route inventory and timezone observation are retained there; no Windows dependency identity is substituted for the image.

## Authorized R8 Linux backup/restore and actual HTTP recovery

The parent explicitly handed over the exclusive synthetic review-database write window after its browser finished. Exact source: `frunze-crm-check`, R8 image **`sha256:91ae4cd62466d54d6ca3ca3ee2b1be60c8b957bedcae70ead5d0eab92518b8fb`**, release `cc41d017fce97ec66d77`. The R8 sanitized bundle's420 files also independently verify against the own30-overlay archive: manifest `cc41d017fce97ec66d77f6c5809ef5c786516a7df6d9ab46b950c85a79474eea`; evidence `runs/crm-standalone-audit-r8/runs/audit-bundle-verified.json`, SHA256 `564d89a3619191c048838d6f116cd30fb861f16678b57c48fe60514077530c02`.

Own command: `Get-Content runs/crm_audit_recovery_host.py -Raw -Encoding UTF8 | ssh -o BatchMode=yes frunze python3 -`. The executable script and all bounds are retained. Only one explicitly synthetic source intake/case/internal task was added through real HTTP. Its original signed commands and session cookie stayed in a private0600 server file, never in this report or local evidence. The original service's other records were preserved. No contract signature, payment, legal/source approval or provider send was fabricated.

Recovery targets were named and approved before creation: directory `/root/frunze-crm-review/audit-recovery-r8`, internal network `frunze-crm-audit-recovery-r8` on unused `172.30.79.0/24`, new named volume `frunze-crm-audit-recovery-r8-pgdata`, and matching `-app`/`-db` containers. Each is explicitly checked by name/image/audit label; the clone's `db` alias exists only on its own network. No host ports were published. New clone DB credentials were generated privately. No old bot target was queried or mutated.

**PASS**, own actual Linux/PostgreSQL execution:

1. Source table/sequence fingerprints match before and after the custom-format `pg_dump`; no concurrent source write was accepted during this cut.
2. The exact application image successfully runs current Alembic migrations and both metadata families on a new empty PostgreSQL volume. Full `pg_restore --clean --if-exists --no-owner --no-acl` then replaces only that freshly created empty audit schema and restores the complete custom dump. The original source database/volume is never a restore target.
3. All **78 table hashes/counts and61 sequence states** match exactly after restore; all **160 foreign keys** are validated.
4. Real HTTP replay of the **original signed intake and original signed preliminary-case opening** returns the same original destinations/IDs. Reading the case and replaying both commands leave the complete restored table/sequence fingerprint unchanged.
5. Two concurrent actual HTTP submissions of the same new signed intake key both return303 and the same destination; exactly one Conversation and one intake receipt are added, with no extra case.
6. A new internal task for the original own person succeeds after restore, exercising restored sequences/role permissions. The original source fingerprint remains unchanged after all clone operations.
7. Only the two clone containers are stopped normally. The source stays running; every volume, backup and private recovery command remains retained. Exclusive window was explicitly released back to the parent.

One auditor harness error is preserved: the first attempt completed the source record/dump, then encountered Docker host/none network `IPAM.Config=null` while checking subnet collisions, before creating target resources. Iterating `(Config or [])` fixes that scan; durable phase state prevents duplicate source writes during continuation. `runs/crm-standalone-audit-r8/runs/audit-recovery-first.txt` records it. This is not a CRM or database runtime defect.

Sanitized evidence: `runs/crm-standalone-audit-r8/runs/audit-recovery-r8.json`, raw SHA256 **`f817929160bef75f3aa1f743b35065a467e62d84e9a1b994448092c105e45025`**. Source/restored fingerprint artifacts are independently downloaded and byte-identical, SHA256 **`2c99919d0011651bf61857d0f22dd7c61a7ff52e6c65e025787c8e71a9f89147`**. Dump remains only in the private server recovery directory,461229 bytes, SHA256 **`4347c63b6867f3fbf6b2cf59a6569b78dc58db004f2dae17ae56486f7ed0364d`**. No credential/cookie/request-body artifact was copied into the repository.

Recovery HTTP deliberately uses the isolated bridge with the original Host/Origin and private retained cookie. It is actual Uvicorn/HTTP/database behavior, **not public TLS or browser cookie-transport evidence**. The clone stop is not a production rollback execution. A future real operator deployment must explicitly identify its fresh volume rather than silently promote these preserved synthetic review datasets.

## Current remaining release boundary

The parent supplied actual R7 connected browser flows and R8 post-recreation authenticated GET evidence. I parsed `runs/crm-browser-r8/evidence.json` and personally viewed the dark390 login/profile and light1365 calendar screenshots. The login input/button contrasts are recorded above4.5 for both themes; profile uncertainty is visible. These remain builder browser executions, not my own automated browser run. The R8 calendar contrast correction is being finalized as R9; its exact image/template and final actual images still require mapping. User-initiated `tel:`/`wa.me` navigation links remain in the calendar; they are distinct from the excluded backend/automatic provider sending paths.

The substantive image/kernel/schema/recovery gates above now have actual evidence. At this intermediate checkpoint final R9 visual/identity mapping, confirmed hostname/access/real TLS and proxy/timeout checks, a concrete fresh live-volume plan and old-bot preservation evidence remained before a public-release GO. The final disposition below records which of those subsequently closed.

## Final R9 identity, native mapping and technical verdict

Final frozen source: `runs/crm-standalone-r9`, base `5200ac1bdec2faab82840e01e6372b33851b9a1d`, **30 overlays**, normalized-LF manifest SHA256 **`892f1bbe1578c9225722cf7d20d11ab1b8cf058569a21b68da1908b90a928d24`**. Independently verified all frozen/own overlays and all **28 current root code/test files** in the candidate; the two documentation overlays are not treated as deployment code. Full build bundle420 files/tar and actual installed image417 files each match independently reconstructed source.

| Final identity | Value |
| --- | --- |
| Release manifest SHA256 | `10dc6b02b0909c3042b07b229f87429e983d82b909f3445bb8b387c039ebe89b` |
| Actual image | `sha256:4f4afd16d8ef3198fb72ccfaae84b44394ec8d1cd3e6e65f6b85ca97e1df43bb` |
| Actual release environment | `10dc6b02b0909c3042b0` |
| Own actual image read | `runs/crm-standalone-audit-r9/runs/audit-host-image-r9.json`, SHA256 `8cce8daf4294dcc98a915020b5898ebbc8b3fcec799f72b377b045760b2ecd53` |
| Own final image verification | `runs/crm-standalone-audit-r9/runs/audit-image-verified.json`, SHA256 `0b177c4452146e5c256a6ebfc6fb65fdbaccb83dd95b2e72f1600d459fd0e7cb` |
| Final machine evidence inventory | `runs/crm-standalone-audit-r9/runs/audit-final-evidence.json`, SHA256 `e04f47503fa66e0151fae916db9f0ba7c008941923d3974009781cf722aee940` |

Own final image inspection reruns the actual kernel/UID/all capability/AppArmor, role/schema, complete file and retained-loader checks on this exact R9 image: **PASS**. R8→R9 is independently proven to change **only** `app/admin/templates/calendar.html`: standalone-only contrast styles and the manual-card link label. There is no Python/schema/driver/Docker/compose/recovery behavior change. Therefore the actual R8 full-database recovery and concurrent signed-command proof maps to R9; it is not falsely recounted as a second R9 restoration.

Final peer review: `ai/reviews/2026-10-13-standalone-crm-independent-review.md`, **APPROVE within its local implementation scope**, LF SHA256 **`44504594a79ba62b3e9817a692cd7a8fb955bedb87f53ba3347e91c91ec18b47`**. The reviewer independently maps all30 R9 overlays and the unchanged HTTP runtime, preserving the original six findings and all corrective evidence. My three independent bootstrap/body/bundle findings are separately closed. There is no known open runtime finding in the assessed candidate.

Final builder native evidence `runs/crm-browser-r9/evidence.json`, raw SHA256 **`998942ad5791bb2855b33bf6034ecf2e833280eb0c3f1044640448f2b6e58206`**, is parsed by my final inventory. Twelve authenticated page visits cover dark390 with JS and light1365 without JS, retained case/profile/task state after application replacement, no external asset requests or page errors. Actual login contrast is4.9458–14.1627; six calendar controls in both normal/hover states across both themes are4.9458–12.7684. I independently viewed both final `calendar-expanded-390.png` and `calendar-expanded-1365.png`: readable controls/text, contained mobile layout and visible form fields. Earlier login/profile images were also inspected as recorded above. These are builder browser executions with auditor artifact/visual verification, not my own Playwright runs. The initially dropped SSH tunnel was a browser harness connectivity failure, not a runtime correction.

I also parsed the builder's exact R8 `runs/crm-standalone-r8/runs/standalone-r8.xml`: **20 PASS /59.680 s**, no failure/skip, raw SHA256 `1d924b40be4a166ea4c98d240b3e0614f374109f22cbc92c60b9d8f491c43be3`. Those checks map through the calendar-only delta; they are additional builder evidence, not added to my own18 distinct local controls or the actual server recovery scenario.

Old-service preservation is evidenced by the builder's `runs/crm-final-server-observation.json` and its retained read-only collector: original bot/app/db/redis identifiers, images and running/healthy states are recorded; their start dates predate this release task. I did not access the old bot environment/data or assert an independent old-data checksum. My own bounded scripts provably select only the new review project and named clone resources. The artifact also records the private-only proxy and forwarded-for overwrite; it does not establish public TLS or production proxy limits.

The reviewed operations document `docs/standalone-crm-operations.md` explicitly requires a **fresh `frunze-crm` project/volume and new credentials**, never the synthetic review volume. Its subnet handoff was clarified after audit: tear down only `frunze-crm-check` without `-v`, verify its empty network/subnet is released, preserve volume/backup, then create the new project. Stopping containers alone was not claimed to release the subnet. Recovery rollback retains all data and does not use populated downgrade, bulk prune or volume deletion.

### Final gate matrix

| Gate | Result and limit |
| --- | --- |
| Requirement/source-first CRITICAL pre-audit | PASS; independent pre-audit and original failures retained |
| Dedicated no-bot entry point/auth/session/origin/body/manual scope | PASS for reviewed R9 code; own local and peer adverse controls mapped |
| Exact sanitized bundle and actual image | PASS;420 packaged/417 installed files, exact image identity and actual loaders |
| Actual kernel/network/role/schema bounds | PASS for the isolated review service; no generic guarantee about later changed deployment configuration |
| Fresh actual migrations, durable state and backup/restore | PASS;78 tables,61 sequences,160 validated FKs, original signed retries, actual concurrent intake and next write |
| Independent implementation review and separate audit | PASS; exact R9 mapping; different contexts and separately attributed evidence |
| Native persistence/readability | PASS within stated real browser cases and final visual/contrast checks; not a whole-site accessibility certification |
| Existing bot separation | PASS for bounded observed identity/health and no old-service actions; old data was not read or copied |
| Fresh real operator environment | **UNKNOWN / not deployed**; concrete separate-volume plan prepared |
| Confirmed public hostname/access roster, real TLS/proxy/rate/timeout and postdeployment acceptance | **UNKNOWN**; user hostname answer remains pending; private `crm.invalid` proxy is not a public release |
| Source/legal/privacy/storage/business approval and J05/pilot | **UNKNOWN / unchanged**; technical deployment does not supply these decisions |

**GO — exact R9 technical candidate and completed isolated verification. No public-release GO.** This is a usable reviewed handoff checkpoint, not a claim that the CRM is already published or that the entire user deployment request is complete. After the hostname decision, deploy the same reviewed image into the documented fresh environment and verify the actual public route, TLS/security behavior and unchanged old service before reporting release completion. New source, image or consequential topology/authority changes require an explicit evidence delta.

All auditor tests/SSH/PG work has ended. The recovery app/DB containers were stopped normally; their volumes, backup and private retry material are preserved; the original review app/DB remain healthy. No root runtime, business policy, existing bot data or host security policy was changed by the auditor.
