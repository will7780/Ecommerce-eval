# Security Policy

## Reporting

Please report suspected vulnerabilities privately to the repository owner
before opening a public issue. Do not include credentials or customer data in a
report.

## Trust boundaries

- Incoming traces and remote target responses are untrusted.
- The server normalizes and redacts all persisted and presented data.
- Hidden reasoning fields are removed, not merely hidden in the UI.
- Active targets are accepted only when marked `safe_for_eval` and configured
  for `dry_run` or `sandbox` mode.
- Python targets run in child processes for lifecycle isolation. This does not
  prevent filesystem, network, or operating-system side effects.
- Non-loopback serving requires an API token unless explicitly overridden for
  development.
- Business evidence is authenticated by the registered collector boundary, not a
  trace-supplied trust flag. Imported traces cannot prove absence of external effects.
- Built-in file candidates are restricted to their experiment workspace and a
  registered synthetic backend. No arbitrary shell, code or external requests.
- Provider credentials are write-only through loopback, same-origin, CSRF-checked
  requests. Secrets persist only in the central environment file, never the database
  or browser storage. Disable does not delete shared credentials.
- Provider addresses are validated before credential transmission and redirects
  are forbidden. A public hostname resolving to private/reserved proxy Fake-IP
  addresses is rejected. Fix local DNS/proxy configuration; do not bypass validation.
- Saving configuration, importing, reading reports and regrading do not call models.
  Connection checks and native-model experiments/retries require explicit approval.

Never use the active experiment runner with a target that can perform real
business writes. Import already-redacted production traces instead.
