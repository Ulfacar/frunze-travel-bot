# Bots, conversations, and AI assistants

- Define conversation states, supported intents, reset/resume rules, and human takeover.
- Check duplicate/out-of-order events, retries, edited/deleted messages if supported, and delivery errors.
- Separate provider acknowledgement, message delivery, and completed business action.
- Establish allowed tools/actions and required confirmation from actual business requirements.
- Treat retrieved text and user messages as untrusted input to tools; test prompt-injection attempts.
- Test malformed model output, tool timeout, unavailable model/provider, and safe fallback/escalation.
- Isolate users/chats/tenants; do not leak another conversation's history or private tool results.
- Do not invent prices, eligibility, refunds, visa/admission rules, or business promises.
- Use approved examples to evaluate task success, grounded answers and escalation behavior.
- Test with sandbox accounts or explicitly authorized recipients; do not message real clients to test.

Maintain a small representative evaluation set: input/context, expected decision/tool action,
forbidden behavior, observed result. Include a successful path, ambiguous request, unsupported
request, duplicate event, hostile instruction, missing knowledge, and human takeover.

Example: after human takeover the bot stops automated sales replies until the approved resume
condition; a repeated webhook does not create a duplicate CRM lead.
