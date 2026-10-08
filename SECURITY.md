# Security

## Reporting

Please report vulnerabilities privately through GitHub's **Report a vulnerability** (Security → Advisories) rather
than in a public issue.

## Security model

The Build Manager runs coding agents on your machine, so its local control surface is guarded:

* **Dashboard:** binds to `127.0.0.1` only, checks the `Host` header (DNS rebinding), requires a per-process CSRF
  token on every POST, refuses to be framed by other sites (`X-Frame-Options: SAMEORIGIN`,
  `frame-ancestors 'self'`), only redirects to same-host paths, and serves model-generated files under
  `Content-Security-Policy: sandbox`.
* **WebSocket:** origin-checked, and the token is required in the hello message.
* **Workers:** an allow-listed environment (no `ANTHROPIC_*` / `OPENAI_*` keys), subscription auth only by default,
  paid overage stopped immediately, an isolated `git worktree` per task, and orphan-proof process groups.
* **Secrets:** logs and events are redacted. A key entered in the dashboard is stored only in the macOS Keychain.
* **Graph access:** public HTTPS endpoints only. Loopback, private-network and plain-HTTP addresses are rejected,
  nothing is configured by default, and the client cannot write.
* **Static files:** paths are resolved and must stay inside their root. Upload names are sanitised.
