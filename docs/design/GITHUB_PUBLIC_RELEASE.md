# GitHub public source release

Status: preparing the first public source snapshot. This is not a stable release
or a PyPI publication. Platform 0.3.0rc2 and Skill 0.1.0 remain unchanged.

## Phase 1: Define the publication boundary

Publish one repository root containing README, LICENSE, source, built UI,
frontend source, anonymous examples, tests, Skill and public documentation.
Generate the root from an explicit allowlist with `tools/export_public_repo.py`.
Keep the development checkout, databases, credentials, historical model-run
handoffs and private engineering reports outside the exported root.
Do not mutate or remove the original records. Export to a new directory only;
refuse symlinks, secret-shaped values outside known security test fixtures,
personal paths and unexpected file types. The manifest records relative paths
and content hashes, not workstation paths or credentials.

## Phase 2: Verify distribution

Document the third-party Skills CLI GitHub installation route, preserving the
whole Skill folder and its resources. Test discovery and installation in an
isolated workspace; do not install globally or execute the onboarding workflow.
Keep platform installation separate. Do not claim universal host compatibility.
Run offline regression and check the exported links, package, anonymous images
and repository root before upload. No model calls or live-store activity.

## Phase 3: Publish and verify

Create the public `will7780/commerce-agent-eval` GitHub repository using the
authenticated owner's existing CLI session. Commit and push only the export,
without forcing history or publishing a stable tag/PyPI package. Verify remote
visibility, commit identity, README/Skill availability and a fresh public clone.
Record hosted CI results honestly; an unfinished or failing job is not a pass.

Future updates originate in the development checkout and pass the same export
boundary. Review the difference in the public checkout before committing. This
snapshot mechanism is not a second, independently edited product codebase.

## Distribution references

- [Skills CLI](https://github.com/vercel-labs/skills): GitHub source discovery,
  per-skill and per-agent installation, copy mode and installation scopes.
- [CLI documentation](https://skills.sh/docs/cli): installation commands.

## Progress

- The public directory is an allowlisted sibling of the development checkout;
  its children become repository-root entries, without an extra wrapping folder.
- Public-directory offline regression: 1551 passed, 3 platform-specific skips,
  2 upstream deprecation warnings. No real credentials or model calls.
- Skills CLI 1.5.26 on Node 24 installed all 18 Skill files in an isolated local
  project; file hashes match. The documented CLI requires Node 22.20 or newer.
- Public Markdown references resolve. Anonymous screenshots retained; private
  engineering handoffs, runtime databases, caches and old private assets excluded.
- Initial authentication verified; hosted publication and clone checks pending.
