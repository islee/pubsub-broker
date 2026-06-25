# Security Policy

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Report vulnerabilities privately via GitHub's
[private vulnerability reporting](https://github.com/islee/pubsub-broker/security/advisories/new)
(the **Security → Report a vulnerability** tab). Include a description, affected version/commit, and
reproduction steps if possible. You can expect an initial response within a few days.

## Scope

This project is a single-instance broker. A few properties are intentional, not vulnerabilities:

- **Wildcard topics are open by design.** `0.<receiver>.*` accepts publishes from any authenticated
  `user` (fan-in) and `<sender>.0.*` is readable by any authenticated `user` (broadcast). Restrict
  with authentication, the per-topic rate limit, and topic naming — see [DESIGN.md](DESIGN.md) §2.
- **Ephemeral mode is not durable.** With `persist=none`, messages live only in the SQLite cache and
  are lost on restart. Durability requires the Postgres backend (DESIGN.md §6).

Things that **are** in scope: auth bypass (e.g. token validation flaws, structural-authz bypass via
crafted topics/principal ids), credential leakage, and cursor/epoch correctness issues that could
expose another principal's messages.
