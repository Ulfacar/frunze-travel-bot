# Automations, jobs, imports, and synchronization

- Identify trigger, input source, target, affected records, and expected invariant.
- Provide preview/dry-run where a mutation can affect multiple records; state what preview does not prove.
- Handle duplicate triggers, retries, overlap, interruption, and partial success.
- Use explicit matching keys; ambiguous matches require review, not guessed merges.
- Bound batches, concurrency, timeouts, rate limits, and retry behavior to current requirements.
- Validate inputs before committing changes. Report rejected/skipped records without exposing private data.
- Record counts, operation identifiers, failure details and a reconciliation path.
- Define timezone/DST behavior for schedules where relevant.
- Verify credentials by name/location only; constrain permissions to the authorized operation.
- Test recovery on representative safe data before real bulk updates or destructive work.

Example: if row N fails, committed/skipped/failed records are identifiable; retry does not duplicate
earlier effects; totals reconcile with source input and the documented rejection policy.

Real-data bulk operations, deletion, financial reconciliation, and irreversible migrations require
CRITICAL handling, concrete recovery evidence and the applicable human authorization.
