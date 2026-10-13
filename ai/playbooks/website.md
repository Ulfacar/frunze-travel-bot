# Websites and landing pages

For a relevant UI/content task, check:
- Real content and navigation: links, anchors, phone/email actions, routes, missing pages.
- Narrow and wide screens, long headings, large text, no unintended horizontal scroll.
- Keyboard focus, semantic controls, labels, contrast, useful alternative text.
- Loading/error/empty/success states for forms and dynamic content.
- Form validation and server-side handling where present; prevent duplicate submissions as needed.
- Images/fonts and their layout impact; avoid broken assets and unnecessary large downloads.
- Requested metadata, indexing rules, canonical URLs, sharing previews and redirects.
- Consent/analytics only under actual project requirements; never invent legal text or consent policy.
- Visual inspection in a real browser when available. Report when it was not performed.

Example: submit the contact form with valid/invalid input, confirm where the request arrives,
and verify the success state does not claim delivery after an upstream failure. Use a safe test
recipient/environment. Sending real messages still requires task authorization.

Pure text/style edits can be LIGHT. Payment, authorization, or sensitive-data behavior is CRITICAL.
