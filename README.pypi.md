# E-commerce Eval

**Business acceptance testing for everyday e-commerce agents.**

One business acceptance standard, multiple execution methods and verifiable
evidence. An agent saying "uploaded successfully" does not prove that the product
data is correct or that the approved revision was actually used.

- **32 starter cases across eight directions**: intent, company rules, business
  dependencies, parameters, artifact review, conversation, recovery and safety.
- **A local visual platform**: inspect traces, business conditions, artifacts,
  approvals, execution receipts, metrics and missing evidence.
- **An Onboarding Skill**: investigate a product and draft its cases, contracts
  and evidence gaps. The Skill is installed separately from GitHub.

## Install and run

Requires Python 3.10+. This is the **0.3.0rc2 Alpha candidate**, not a stable release.
In a virtual environment, install the exact candidate:

```bash
python -m pip install "commerce-agent-eval==0.3.0rc2"
commerce-eval demo
```

Open [http://127.0.0.1:8770](http://127.0.0.1:8770).
The built web UI and demo data are included. Git and Node.js are not required
for package installation. The no-key demo does not call a real model, run the
entire bank against an agent or write to a production store.

The Python distribution is named `commerce-agent-eval`; its command is
`commerce-eval` and its Python module is `commerce_eval`.

## What acceptance means

Business conditions and explicit constraints decide the result. Tool names and
counts are diagnostic by default, so packaged business tools and lower-level
file tools can be judged against the same business conditions. Required evidence
that is absent remains unverifiable, never an automatic pass.

Real integrations still need a controlled execution environment and evidence
collectors. No universal zero-adaptation integration or production success rate
is claimed. External model calls are explicit opt-in and may transmit inputs to
the configured provider and incur charges.

## Documentation

- [Chinese README and screenshots](https://github.com/will7780/Ecommerce-eval#readme)
- [English README](https://github.com/will7780/Ecommerce-eval/blob/main/README.en.md)
- [Local setup and source installation](https://github.com/will7780/Ecommerce-eval/blob/main/docs/LOCAL_SETUP.md)
- [Connect your agent](https://github.com/will7780/Ecommerce-eval/blob/main/docs/ONBOARDING.md)
- [Onboarding Skill installation](https://github.com/will7780/Ecommerce-eval/blob/main/docs/ONBOARDING_SKILL.md)
- [Security](https://github.com/will7780/Ecommerce-eval/blob/main/SECURITY.md)
- [MIT License](https://github.com/will7780/Ecommerce-eval/blob/main/LICENSE)
