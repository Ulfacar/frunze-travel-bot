# Stateful web applications / SaaS / CRM

- Map the user journey across UI, API, persistence, and any background jobs.
- Cover fresh and existing records; refresh/reopen must show the actual saved state.
- Check loading, empty, permission-denied, validation, network-error, and success states.
- For access changes, verify server enforcement, direct API calls, foreign IDs and tenant isolation.
- Consider double-click, concurrent edits, retries, stale tabs, and partial persistence.
- Preserve compatibility with existing data and clients; identify migrations explicitly.
- Test the user's actual role, not only an administrator path.
- Verify mobile/keyboard behavior for changed UI and representative navigation/regression paths.
- Distinguish notifications being queued, delivered, and the business operation completing.
- Use synthetic/approved fixtures; do not copy production personal data into the repository.

Example: an authorized user edits a record and sees it after refresh; a different tenant cannot
read or mutate that record by guessing its ID; a failed save leaves recoverable state.

Authentication/authorization changes, money, sensitive data, and real-data migration are CRITICAL.
