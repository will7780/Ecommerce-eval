# Local setup / 本地运行

The primary [README](../README.md) and [English README](../README.en.md) use source
installation. Python 3.10+ and Git are required. Built UI assets are included; Node
is only needed to change/rebuild the frontend. No published PyPI package is assumed.

## Virtual environments

Run commands from the repository root. Windows PowerShell can invoke executables
directly without changing the machine's script execution policy:

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\commerce-eval.exe demo
```

On macOS/Linux use `.venv/bin/python` and `.venv/bin/commerce-eval`.
For shorthand commands below, activate the environment first:

```powershell
.\.venv\Scripts\Activate.ps1
```

```bash
source .venv/bin/activate
```

If PowerShell blocks activation, keep using the full executable paths instead;
activation is optional.

## Separate data and ports

```bash
commerce-eval --database ./demo.db demo --seed-only
commerce-eval --database ./demo.db serve --port 8771
```

Open http://127.0.0.1:8771. Stop with Ctrl+C. The default database lives under
`~/.commerce-agent-eval/`. Use a separate database for public recordings, never
a private project's database. No-key demo setup does not run the real-model bank.

## Docker (alternative)

Requires Docker with Linux container support. From the repository root:

```bash
docker build -t commerce-agent-eval .
docker run --rm -p 127.0.0.1:8770:8770 -v commerce-eval-data:/data commerce-agent-eval
```

This is a local build, not a prepublished container image. The volume persists
records. Loopback port binding keeps the demo local. Do not expose a no-auth
instance; read [SECURITY.md](../SECURITY.md) before configuring remote access.
Provider credentials are separate server configuration, not repository files.

## Development

```bash
pip install -e ".[dev]"
pytest
cd web
npm ci
npm run build
npm run test:e2e
```

Browser tests may require a separately installed Playwright browser. Consult
[CONTRIBUTING.md](../CONTRIBUTING.md) and the CI workflow for environment setup.
Do not claim an unexecuted OS/container path was verified locally.

## Models and privacy

Opening the demo does not need a model key. Explicit real-model experiments and
connection tests may incur charges and send inputs to the selected endpoint.
See [Provider configuration](PROVIDERS.md). External agents retain their own
model and credentials. Never put secrets into traces, fixtures or screenshots.

中文提示：优先走 README 的无 Key 演示。录屏用独立数据库；不要为启动程序降低
PowerShell 全局安全策略。Docker 和网页开发是可选路径，不是体验平台的前置条件。

