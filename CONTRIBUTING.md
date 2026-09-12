# Contributing

1. Read the active design document before changing contracts or architecture.
2. Keep the core free of product and agent-framework dependencies.
3. Add tests for every metric's formula, evidence, applicability and N/A rule.
4. Do not add real credentials, customer data, local paths or hidden reasoning.
5. Run Python tests, the frontend build and Playwright checks before submitting.

Metric behavior changes require a new metric version. Contract-breaking changes
require a new contract version and an explicit migration path.

