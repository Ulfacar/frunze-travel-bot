# E6-29C question adapter — independent component review

Reviewer `/root/calculation_review`, 2026-10-12. CRITICAL / solo.

**APPROVE exact frozen R2 for the pure question-adapter slice only.** No open
runtime finding. This is not approval of the full incoming dialogue task,
collection authority, persistent reconciliation or provider admission. H02
remains UNKNOWN and receives no points from this component.

## Requirement and inspected scope

Read `ai/tasks/2026-10-12-e6-29c-incoming-dialogue.md` and the final incoming
integration pre-audit in `ai/reviews/2026-10-12-e6-29-pre-audit.md`, then actual
new code and retained catalog/value validation/interruption triage before
builder conclusions. Reviewed files:

- `app/knowledge/dialogue_questions.py`;
- `tests/test_dialogue_questions.py`.

Actual new behavior is explicit RU/EN client wording and complete ordered
options for a closed field map, reconstruction of exact prompts, and strict
batch/field-labelled single-value parsing. It does not query current interview
state or prove that the caller supplied all current drafts. Its docstring
correctly leaves consent, actual accepted prompt and matching current head to
the future caller.

## Identity and environment

Base: `6775d30be496335fc0aad10f6d18e6debc98da25`.
Frozen candidate: `runs/e6-29c-r2`.
Manifest LF SHA256:
`0e990dcb767423a1f6c4245bae85b484a4e3cf2dea091208a7460fb0e8ac3182`.

All 14 frozen and root overlay hashes were verified. Nine are identical to
base, including the existing interruption runtime/migration/tests; three are
preserved unrelated UI files; only the two files above are new reviewed scope.
The scoped runtime LF SHA256 is
`0ba9d568b27635543dddeb735b143c9800cbb824dafd93cc9e9fa7a49443b0fb`;
the builder test LF SHA256 is
`72e6c8648cbd77020877730fd83d44ff4efdd32eeb58b116078c3ee0bb55fce9`.

Own env-free archive: `runs/e6-29c-review-r2`, constructed from Git archive and
verified overlays. All own probes are pure Python and synthetic. No environment
file, DB, real data, provider, external calls, runtime edits or source approvals.
PG/migration/concurrency/browser checks are N/A for these two pure files;
future connected integration still requires its own such evidence.

## Independent checks

Own test source: `runs/e6-29c-review-r2/tests/test_review_dialogue_questions.py`.
Command in that archive:

`python -X utf8 -m pytest tests/test_review_dialogue_questions.py -q --basetemp .pytest-review-corrected --junitxml=review-questions.xml -p no:cacheprovider`

**34 PASS**, console0.67s / XML0.634s, zero skipped/errors/failures. XML:
`runs/e6-29c-review-r2/review-questions.xml`, raw SHA256
`ba1c8870bf45023959e850cf336d9a4f7f552f14dbb4bda507575ef3b76d1d22`.

- Every mapped choice list in both languages matches the actual catalog after
  JSON serialization; all numbered values round-trip. The largest batch label
  works, and full displayed paths survive a partial answer.
- Rehashed replacement body, truncated options, hidden/reordered questions,
  changed kind, extra approval flag, catalog hash and renderer version are
  refused. Rehashing arbitrary wording cannot make it a valid retained prompt.
- Control, bidi, zero-width and surrogate characters, Unicode lookalike labels
  or boolean words, unlabelled/old-batch answers, extra prose, extra lines,
  alternate date formats, oversized option number and coerced booleans never
  become facts.
- Privacy takes priority over malformed prompt context even with overlength,
  control characters and unsupported voice/kind metadata. Whole-message human,
  privacy, unsafe and overstay statements override a valid-looking prefix.
- A normal boolean preserves every displayed field. A correctly parsed typed
  `risk.overstay=True` reaches the retained reducer's actual reported-risk
  stop. A conversational acknowledgement changes no facts.
- Internal consent/proof/reference and unsupported repeated-history questions
  cannot render. A changed catalog applicability condition is rejected.

The initial own run was **33 PASS / 1 oracle FAIL**: its proposed catalog
mutation assigned `passport_expiry.when='always'`, which was already the real
value. This was a reviewer test defect, not runtime failure. The corrected
probe first asserts that baseline and changes it to `in_kg`. Original XML and
test are preserved as `review-questions-initial.xml` and
`review-questions-initial-test.txt`; the complete small corrected suite passed.

## Builder evidence and contract assessment

Independently parsed `runs/e6-29c-r2/runs/e629c-r2-questions.xml`:
**110 PASS**, XML1.370s, no skipped/errors/failures; raw SHA256
`d25626c69c1ee83841775e28e521cd7e3fe5d28e665d46ff42a01ab83feb1bef`.
Inspected test source covers actual RU/EN enum/boolean/date progress through
saved/reloaded typed values, all retained source-exception examples, privacy,
envelope, invalid literals, unsupported fields and prompt/catalog tampering.
The original R1 setup issue described by the builder was an inapplicable
inviter answer under tourism; it is not counted as a runtime defect or as
reviewer-executed evidence.

The implementation meets the pure adapter contract: full raw triage occurs
before parsing, `uncertain_answer` does not bypass plain-text/envelope checks,
whole-input parsing selects exactly one explicit batch/field, and catalog
validation supplies canonical typed values. The prompt retains version/map/
catalog/body hashes, language, exact ordered paths, types, labels and options.
Unmapped technical fields fail closed. The supplied context is reconstructed
exactly; no stored arbitrary body is trusted.

Required integration gates remain outside this approval: prove the full current
drafts list and current head, unique durable batch/session identity, provider
acceptance before ordinary answers, subject/route scope, CAS and idempotency,
valid original attestation reconciliation, current stops, send admission and
recovery. Callers must handle `QuestionInvalid` without falling through to
legacy advice. A parsed answer or acknowledgement grants no permission to
collect, send, remain, publish a rule or resume a stopped dialogue. The full
E6-29C task still needs independent connected review and separate final audit.
