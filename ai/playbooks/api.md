# APIs and services

- Inspect actual consumers and the existing contract before changing request/response shape.
- Validate input types, empty/missing values, limits, malformed payloads and unsupported operations.
- Check status codes, stable error structure, and client-visible behavior on failures.
- Verify identity, action permission, resource ownership and tenant scope on the server.
- Consider idempotency, concurrency and timeout-after-commit behavior for mutations.
- Exercise pagination/order/filter boundaries where affected.
- Use bounded timeouts/retries and documented failure behavior for external calls.
- Avoid leaking credentials, stack traces or personal data in errors/logs.
- Record contract changes and migration/deprecation requirements when applicable.
- Verify persistence and consumer behavior; response status alone is insufficient.

Example: repeating the same approved operation after a timeout must not create two business
effects; an invalid request returns a useful error without partial data changes.

Use the project's existing API description/test framework. Do not add a new framework solely
for this checklist. Security boundaries and sensitive mutations require CRITICAL handling.
