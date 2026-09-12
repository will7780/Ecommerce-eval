# Commerce Agent Eval contributor instructions

- Read `docs/design/PUBLIC_ARCHITECTURE.md` before architectural changes.
- Public core modules must not import product runtimes or agent frameworks.
- Persist normalized, redacted contracts only; never store raw payloads or hidden reasoning.
- Metric changes require a version, applicability rule, N/A rule and evidence source.
- Active experiments are dry-run or sandbox only. A child process is not a security sandbox.
- Keep the UI compact, evidence-first, accessible and usable in both supported themes/locales.
