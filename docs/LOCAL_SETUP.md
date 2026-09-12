# Local setup / 本地运行

The primary [README](../README.md) and [English README](../README.en.md) install the
[0.3.0rc2 Alpha candidate from PyPI](https://pypi.org/project/commerce-agent-eval/0.3.0rc2/).
Python 3.10+ is required. The wheel includes built UI assets and demo data;
Git and Node are not required for package users.

## Virtual environments

Create a virtual environment in a working directory. Windows PowerShell can
invoke executables directly without changing the machine's script execution policy:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install "commerce-agent-eval==0.3.0rc2"
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

## Source installation

For development, use Git and a separate environment. Do not install an editable
checkout into the environment used to verify a PyPI release.

```bash
git clone https://github.com/will7780/Ecommerce-eval.git
cd Ecommerce-eval
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\commerce-eval.exe demo
```

On macOS/Linux, substitute `.venv/bin/python` and `.venv/bin/commerce-eval`.
The repository includes built UI assets. Node is needed only to change/rebuild
the frontend, or to use the separate Skills CLI installation route.

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
