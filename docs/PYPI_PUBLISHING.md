# PyPI first publication

Package: commerce-agent-eval. First release: 0.3.0rc2 (Alpha candidate).
Repository: https://github.com/will7780/Ecommerce-eval
No platform, contract, bank or Skill version changes; no paid model calls.

## Phase 1: Prepare and audit

Status: Complete.

Local verification: 49 focused tests passed. Both distributions pass strict
Twine metadata checks and the public-content audit. A new non-editable wheel
installation serves the API, both frontend assets, demo traces and all 32 bank
cases; demo seeding is idempotent and makes no external model calls.

- Publish only from the curated public checkout, never the private development
  workspace or runtime data. Use an explicit sdist file allowlist.
- Add a PyPI-specific Markdown description with absolute documentation links;
  preserve the visual Chinese/English GitHub READMEs.
- Check wheel and sdist metadata, licenses, bundled frontend and demo resources.
  Validate artifact paths and scan text for private paths and credential patterns.
- Build the wheel from the sdist and install into a fresh environment. Seed an
  isolated no-key database and verify the API, frontend assets and 32-case bank.

## Phase 2: Trusted publication

Status: In progress. GitHub's pypi environment is restricted to main.

The user has registered a pending GitHub publisher with these exact fields:

| Field | Value |
| --- | --- |
| PyPI project | commerce-agent-eval |
| Owner | will7780 |
| Repository | Ecommerce-eval |
| Workflow | publish.yml |
| Environment | pypi |

Use manually dispatched GitHub Actions on main, separate build and publish jobs,
a main-only pypi environment, and job-scoped id-token permission. The official
PyPA action obtains short-lived credentials; no persistent PyPI token is needed.
Build/test must succeed before upload. Never overwrite an existing release or
silently skip a conflicting artifact. Publishing a candidate does not make it a
stable release.

## Phase 3: Verify installation and document

Status: Pending.

After PyPI confirms the upload, install the exact candidate from PyPI into another
clean environment, compare downloaded artifact hashes against the published
files, and repeat the no-key checks. Then update both READMEs and local setup to
lead with a version-pinned pip install; retain source and Skill installation.
Do not advertise pip availability or add a PyPI badge before publication succeeds.
Refresh the public manifest and publish documentation changes.

## Maintainer workflow

The manual workflow input must equal the version declared in package metadata.
Dispatch publish.yml from main only after reviewing changes. The build job runs
offline tests and distribution checks, uploads the checked distributions, and
installs a wheel in isolation. The publish job has no source checkout or build
step and consumes only those checked distributions. The pypi environment permits
main only. Future uploads require the same explicit dispatch.

References:
- [Create a project with a trusted publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
- [Publish with GitHub Actions](https://docs.pypi.org/trusted-publishers/using-a-publisher/)
