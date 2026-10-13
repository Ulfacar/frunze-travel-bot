# Universal project checklist

Use only items relevant to the task. A checklist does not change risk, scope, or authorization.

1. Identify the actor, starting state, action, and observable outcome.
2. Inspect the existing implementation before proposing a replacement.
3. Find project commands and record baseline failures before changing behavior.
4. Deliver one complete useful path; include error handling and recovery appropriate to the risk.
5. Check boundaries: inputs, permissions, external systems, persistence, duplicate actions.
6. Capture evidence in the actual environment; separate mocks from real integration checks.
7. Close applicable review/acceptance requirements, report unknowns, and leave the next action.

Choose an additional checklist when useful:
- [Website](website.md): content, responsive layout, navigation, forms.
- [Web application](webapp.md): stateful workflows, roles, persistence.
- [API](api.md): contracts, failures, clients, resource boundaries.
- [Bot](bot.md): conversations, tools, delivery, human takeover.
- [Automation](automation.md): scheduled work, retries, reconciliation, recovery.

Example acceptance: “From a fresh local environment, the documented command starts the
application; the chosen user action produces the expected persisted result; an invalid action
fails without changing unrelated data.” Replace this with the project's actual scenario.
