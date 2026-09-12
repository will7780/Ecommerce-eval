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

Status: Complete. GitHub's pypi environment is restricted to main.

The first [publication workflow](https://github.com/will7780/Ecommerce-eval/actions/runs/34708139125)
published both distributions and their attestations successfully. The source
commit is 3aa4afe. Hosted release regression: 1575 passed, 2 skipped.
The [source CI](https://github.com/will7780/Ecommerce-eval/actions/runs/34708127454)
also passed Python 3.10, Python 3.12, web and wheel jobs.

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

Status: Complete.

- [PyPI 0.3.0rc2](https://pypi.org/project/commerce-agent-eval/0.3.0rc2/)
  contains the wheel and sdist, neither yanked. Both downloaded artifacts passed
  the allowlist/content audit and matched PyPI and the release build hashes.
- A second fresh environment installed the pinned version from the official
  PyPI index with caching disabled. Non-editable imports, no-key seeding, the
  API, frontend assets, demo traces and 32 cases passed again. The installed CLI
  also initialized a separate demo database successfully.
- Both GitHub READMEs now lead with pinned pip installation and link to source
  setup. Python package and Skill installation remain separate. The Alpha
  candidate label is preserved.
- Documentation regression: 49 focused tests passed. Eight rendered README
  views (Chinese/English, desktop/mobile, light/dark) had no broken images,
  missing local links or horizontal page overflow, including expanded details.
  These are local GitHub-style previews, not a claim of pixel-identical GitHub
  rendering. No new paid model tests were run.

Published artifact SHA256:

```text
commerce_agent_eval-0.3.0rc2-py3-none-any.whl
7d72da64006cd5a8de0817f9a3656896ea3ba10728348dda3a420cd82049abe3
commerce_agent_eval-0.3.0rc2.tar.gz
f3d4836dd9ed3670589c4be7dbf2a1bbe8573b87caea5418125ca4be153eeaf2
```

Verification procedure: after PyPI confirms the upload, install the exact candidate from PyPI into another
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
