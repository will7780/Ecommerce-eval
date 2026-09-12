# Connect and import

Start with an existing trace if you only need to inspect or evaluate an Agent's
past behavior. Connect a Target only when you explicitly want the platform to
invoke it in a dry-run or sandbox environment. Neither importing nor checking a
connection starts the Agent or calls a model.

For product investigation and question design before integration, see the
[onboarding Skill v0.1.0](ONBOARDING_SKILL.md). It pauses for confirmation of one
main workflow and answer-changing rules, then prepares a local handoff using the
`0.3.0rc2` / business contract `1.2` / bank `0.3.1` / verifier `1.1` baseline.
Its helper imports only into a disposable temporary database. It does not perform
the real-project imports, registration, connection checks or execution described
below. Import validity, rule conformance and actual business integration are
separate results; tailored rules need separately reviewed conformance fixtures.

## Current Business Acceptance Route

For the Skill baseline, select **bank `0.3.1` with business contract `1.2`**.
The older capability-mapping walkthrough below remains supported for `0.2.0`;
it is not a requirement that every new Agent expose those tool names.
`GET /api/v1/scenario-templates?template_version=0.3.1` selects the current
business questions explicitly. Some legacy endpoints default to `0.2.0`, so do
not omit the revision and assume that it selects the newer bank.

An explicitly authorized later `POST /api/v1/scenario-templates/bank/instantiate`
can use the following body to adopt an unchanged synthetic business case:

```json
{
  "project_id": "shop-eval",
  "dataset_id": "business-preview",
  "version": "1",
  "template_version": "0.3.1",
  "template_ids": ["I01"],
  "bindings": null,
  "assets": null
}
```

For contract `1.2`, business requirements and verifiable outcomes define the
answer; tool contracts/bindings describe the actual Target and experiment, not
one mandatory implementation path. Tailored inputs/rules require reviewed
fixtures; changing product assets alone does not establish a correct new oracle.
Prefer the Skill's reviewed Dataset handoff for custom questions. A successful
Dataset import/instantiation is not evidence that an external Agent is connected.
There is no public upload route that authenticates an external effect collector;
missing required evidence remains unverifiable, not a passing score.

## Legacy Browser Walkthrough (0.2.0)

Run `commerce-eval demo`, then open
[Connect & import](http://127.0.0.1:8770/onboarding). The demo needs no API key.
For an existing database, use `commerce-eval --database ./platform.db serve`.

1. **Project & mode:** select or create a project. Choose trace/data import,
   connection to your Agent, or **Try the standard bank**.
2. **Upload / connect:** for import, choose a data type and download its template.
   For a connection, supply an HTTP base URL or select a previously registered
   local Target. Only declare it safe when production writes are impossible.
   The built-in experience defaults to **Independent policy baseline**, a
   rule-based candidate using simulated tools and no LLM. **Reference traces**
   is an optional, unscored fixture mode.
3. **Validate & preview:** inspect normalized, redacted data and every reported
   file/line/field error. Invalid imports cannot be committed.
4. **Map capabilities:** for an Agent connection, map the selected scenarios'
   neutral capabilities to your actual tool IDs. Expand each capability to edit
   **Arguments & units** and **Output evidence** using structured field rows,
   including optional positive unit multipliers. Attach versioned product/rule
   asset references as needed; keep your original tool and field names.
5. **Cases & gates:** inspect and select scenarios. An explicit subset becomes
   one immutable Dataset; a missing template or invalid mapping is not skipped.
6. **Connection check:** run the non-executing check. A successful check does not
   run an experiment or verify the effectiveness of your sandbox.
7. **Confirm:** explicitly commit the import or connection setup. Connection
   setup prepares resources; configure and start the actual experiment separately.
   The built-in experience starts only after the final confirmation: either
   evaluate the independent policy or generate unscored reference traces.
   Policy scores describe that deterministic baseline in the synthetic sandbox,
   not your external Agent's capabilities.

For existing runs, use **Traces -> Import**. After import, open the trace and
choose **Evaluate** only after selecting the intended case and resource versions.

## Four data categories

| Category | Import `kind` | Public formats | Purpose |
| --- | --- | --- | --- |
| Execution evidence | `trace` | JSON / JSONL | Inputs, outputs, tool calls, interactions, timing and observable evidence from an actual run. |
| Tool contracts | `tool-contracts` | JSON / JSONL | Actual tool IDs, JSON Schemas, risk, confirmation requirements and sensitive-field declarations. Not executable tools. |
| Product data | `products` | CSV / JSON | Versioned business assets. Standard rows require a nonempty `sku`, positive `price` and uppercase three-letter `currency`. |
| Company rules | `rules` | Markdown / TXT | Versioned policy material, supplied as permitted assets rather than hidden evaluation answers. |

Datasets (`dataset`), evaluator manifests (`evaluator-set`) and Target definitions
(`target`) are separate platform configurations, also importable as JSON/JSONL.
Dataset cases define the questions and gates; evaluator sets select metrics;
Targets identify an existing runtime. They do not replace the four data categories.

Uploads are UTF-8 text, limited to **10 MiB per file, 50 MiB per import and 1,000
traces per import**. Archives, executable files and spreadsheets such as `.xlsx`
are rejected by the public importer. JSONL means one complete JSON value per
nonempty line. Downloaded contract examples use JSON; traces, cases and tools can
also be supplied as JSONL rows.

Do not upload real credentials, hidden reasoning, unauthorized customer data or
private documents. Export visible role-separated model messages only when they
were actually captured; missing historical system input stays unavailable.
Normalize and redact in your adapter before transport. The server redacts again,
including trace fields declared sensitive by pinned tool contracts.

Private adapters may read XLSX locally using their own approved libraries and
permissions. They must export supported normalized data/evidence; this does not
enable XLSX upload in the public UI or make private files a platform dependency.

## Templates and atomic imports

Platform API routes below use `http://127.0.0.1:8770/api/v1`. Examples assume local
access; if API authentication is enabled, use your configured authenticated client
without copying credential values into uploads, examples or logs.

Create a project with `POST /api/v1/projects`:

```json
{"project_id":"shop-eval","name":"Shop evaluation"}
```

`GET /api/v1/imports/templates?kind=trace` returns **`{filename, content}`**.
Download the `content` as `filename`, not the enclosing response. The same route
supports all seven import kinds. To obtain the raw attachment directly:

```bash
curl --fail "http://127.0.0.1:8770/api/v1/imports/templates?kind=trace&download=true" --output trace.json
curl --fail "http://127.0.0.1:8770/api/v1/imports/templates?kind=tool-contracts&download=true" --output tool-contracts.json
```

Submit file text, not multipart data, to `POST /api/v1/imports/preview`:

```json
{
  "project_id": "shop-eval",
  "kind": "trace",
  "files": [{
    "name": "trace.json",
    "content": "{\"trace_id\":\"imported-001\",\"project_id\":\"shop-eval\",\"target_id\":\"external-agent\",\"target_version\":\"1\",\"started_at\":\"2026-01-01T00:00:00Z\",\"input\":{\"message\":\"Inspect the catalog.\"},\"events\":[]}"
  }],
  "options": {}
}
```

The response contains `import_id`, `status` (`ready` or `invalid`), `counts`,
`errors` (`file`, `line`, `field`, `code`), `preview` and `expires_at`. Only normalized
draft data is persisted; the draft expires after one hour. JSON-array diagnostics
identify the row index; JSONL diagnostics identify the source line.

Use the returned ID with `POST /api/v1/imports/{import_id}/commit`; no request body
is required. Commit revalidates references and conflicts and writes all resources
in one transaction. An identical version/checksum is idempotent; changed content
under the same version fails without overwriting or partially committing rows.
The draft is pinned to the project selected when preview was created. Changing
the page-header project or navigating back and forth cannot retarget that draft;
create a new preview to import into another project.

For datasets, tool contracts, products, rules and evaluator sets, provide
`options.id` and `options.version` unless the JSON wrapper supplies them.
`options.name` is optional. CSV `options.column_mapping` maps **destination field
to source column**, for example `{"sku":"SKU","price":"Cost","currency":"Unit"}`.
Product/rule commits return `asset_id`, `kind` and `version` references.

CLI imports use the same service and validation rules:

```bash
commerce-eval import trace.json --kind trace --project shop-eval
commerce-eval import products.csv --kind products --project shop-eval --id catalog --version 1
commerce-eval import rules.md --kind rules --project shop-eval --id policy --version 1
```

## Legacy Capability Mapping (0.2.0)

`GET /api/v1/scenario-templates` returns `{items: [...]}`. Read each template's
`capabilities`; map them to the real tool IDs rather than renaming the Agent's
tools. The wizard provides structured mappings, not executable expressions:

| Wizard control | Binding field | Direction / rule |
| --- | --- | --- |
| Your tool ID | `tool_id` | The actual tool ID used by your Agent. |
| Arguments & units: Neutral field -> Tool field / pointer | `argument_mapping` | Neutral argument name -> actual field name or JSON pointer, such as `/params/margin_ratio`. |
| Unit multiplier | `unit_scale` | Neutral numeric value multiplied by this number gives the actual tool value. Keyed by the neutral argument name; blank means 1. |
| Output evidence: Neutral field -> Tool field / pointer | `evidence_mapping` | Neutral evidence name -> actual output field or JSON pointer. No unit multiplier is applied to evidence. |

Expand a capability, then use **Add argument** or **Add evidence field** to add
rows; remove unused rows. Complete both names on each row, avoid duplicate or
overlapping destinations, and use only finite multipliers greater than zero.
Use the capability IDs returned by the selected templates and your real tool
contracts to choose the fields. Cover every capability required by your selection.

For example, this single entry in the instantiate request's `bindings` list maps
one capability; it is not a complete mapping for a whole scenario:

```json
{
  "capability_id": "catalog.generate_listing",
  "tool_id": "merchant.build_listing",
  "argument_mapping": {"margin_percent": "/params/margin_ratio"},
  "unit_scale": {"margin_percent": 0.01},
  "evidence_mapping": {"artifact_id": "/result/file_id"}
}
```

Here a neutral `margin_percent` of 15 becomes an actual `margin_ratio` of 0.15;
reading the actual argument back into the neutral view divides by 0.01. The
actual output's `result.file_id` supplies neutral `artifact_id` evidence.
Submitted bindings and exported traces retain the original tool and field names;
the neutral evaluation view does not rename your Agent's tools or rewrite the
original trace. This capability mapping direction differs from product CSV
`column_mapping`, which maps destination fields to source columns.

For example, `POST /api/v1/scenario-templates/bank/instantiate`:

```json
{
  "project_id": "shop-eval",
  "dataset_id": "selected-scenarios",
  "version": "1",
  "name": "Selected scenarios",
  "template_ids": ["I01"],
  "bindings": null,
  "assets": null
}
```

Here `null` bindings/assets intentionally use the synthetic defaults. For a real
Agent, replace `bindings` with a list covering the selected capabilities and
`assets` with a list such as
`[{"kind":"products","asset_id":"catalog","version":"1"}]`.
References must exist in the selected project. The response includes the Dataset,
resource references and readiness errors; a failure creates no Dataset.

To install the reference bank and its pinned contracts/evaluators/Target, call
`POST /api/v1/onboarding/demo`:

```json
{"project_id":"shop-eval","template_ids":["I01","A01"]}
```

Omit `template_ids` for all 32 scenarios. The endpoint only seeds resources and
returns versioned references plus **two** experiment specifications; it does
**not** start an experiment. Seeding is atomic and idempotent for identical
versions; conflicting existing versions are never overwritten.

| Demo mode | Target at version `0.2.0` | Response specification | Scoring |
| --- | --- | --- | --- |
| Independent policy baseline (UI default) | `standard-reference-policy`, adapter `reference_policy` | `policy_experiment_spec` | Evaluate the rule-based policy's actual decisions against simulated tool feedback; no LLM calls. Not a production Agent assessment. |
| Reference traces (optional) | `standard-reference-fixtures`, adapter `reference_fixture` | `experiment_spec` | Script-driven conformance fixtures, always unscored as candidates. |

Both specifications pin the selected Dataset, tool contracts and evaluator set.
The legacy top-level `target_id`, `target_version` and `candidate_evaluation=false`
still describe the **fixture**, not the policy. Select `policy_experiment_spec`
explicitly for the default policy experience; do not combine it with those
legacy fixture target fields. On final confirmation the UI submits the chosen
specification to `POST /api/v1/experiments` with a fresh `experiment_id`.

The policy chooses actions from public inputs and observations, not the positive
reference script. The separate `reference_fixture` does follow that script:
its traces are **not Agent grades**, remain unscored, and cannot be converted
to candidate scores by `/evaluations`.

## Explicit Evaluation (All Supported Contracts)

Ordinary trace imports also remain **unscored** until you explicitly evaluate
them. First import the `dataset`, `tool-contracts` and `evaluator-set` examples in
the same project, or use your own versioned resources. Using those example IDs,
`POST /api/v1/evaluations` accepts:

```json
{
  "trace_id": "imported-001",
  "project_id": "shop-eval",
  "dataset_id": "example-cases",
  "dataset_version": "1",
  "case_id": "inspect",
  "tool_contract_set_id": "example-tools",
  "tool_contract_version": "1",
  "evaluator_set_id": "example-evaluators",
  "evaluator_set_version": "1"
}
```

Examples demonstrate the wire format, not a meaningful release benchmark: define
case-specific expectations and gates before using results to assess readiness.
CLI/API/web imports and explicit evaluation use built-in offline evaluators only;
an evaluator-set does not install plugins or an external collector bridge. The
explicit evaluation endpoint does not run the Agent or a paid model.
Reevaluate with different pinned resources to create
a **new immutable `evaluation_id`**. `GET /api/v1/evaluations/{evaluation_id}` and
`GET /api/v1/traces/{trace_id}`'s `evaluation_history` retain full earlier results.
The trace's legacy `metrics`, `gates` and `overall_pass` fields show the latest result.

CLI evaluation is opt-in through `--eval` plus all bindings:

```bash
commerce-eval import trace.json --kind trace --project shop-eval --eval --dataset example-cases --dataset-version 1 --case-id inspect --tool-contract-set example-tools --tool-contract-version 1 --evaluator-set example-evaluators --evaluator-set-version 1
```

## HTTP Target contract

The following routes belong to **your Target server**, not the platform API.
They are appended to its configured `base_url`.

| Method and Target path | Operation |
| --- | --- |
| `GET /v1/capabilities` | Non-executing onboarding handshake. |
| `POST /v1/runs` | Explicitly start an Agent run. |
| `POST /v1/runs/{external_run_id}/resume` | Resume the actual pending interaction. |
| `POST /v1/sessions/{session_id}/reset` | Release isolated session state. |

The handshake must return HTTP 200 with a JSON object like this:

```json
{
  "protocol_version": "1.0",
  "operations": ["start", "resume", "reset"],
  "safe_for_eval": true
}
```

Readiness requires protocol `1`, `1.0` or `1.1`, both `start` and `resume`, and a
literal boolean `safe_for_eval=true`. Implement `reset` too: the runner uses it
for cleanup. The check has a three-second total timeout and a 64 KiB JSON limit.
It rejects redirects, HTML 200 responses, compressed bodies, URL userinfo/query
credentials and metadata/non-public addresses. Explicit localhost or literal
loopback development hosts are allowed. Validated IPs are pinned for the check;
this is not a general network sandbox for later Agent execution.

For a non-executing check, `POST /api/v1/onboarding/check`:

```json
{
  "project_id": "shop-eval",
  "definition": {
    "contract_version": "1.1",
    "target_id": "sandbox-agent",
    "version": "1",
    "name": "Sandbox Agent",
    "adapter_type": "http",
    "safe_for_eval": true,
    "config": {"base_url": "http://127.0.0.1:9000", "project_id": "shop-eval"}
  }
}
```

To register it, send **only the inner `definition` object** to
`POST /api/v1/targets?project_id=shop-eval`; `project_id` is a query parameter,
not an additional top-level field in that request body. Registration is separate
from checking and starting. Existing local Targets are checked by sending
`project_id`, `target_id` and `target_version` instead of `definition`; they must
already be registered, safe for evaluation, and dry-run/sandbox only.

If authentication is needed, add `config.credential_env` with the **name** of a
server environment variable, for example `MY_AGENT_TOKEN`. It is normalized to
the runtime's `token_env` reference. Configure the real value server-side, never
in JSON, browser fields, source or logs. Do not upload custom authorization
headers, inline source, Python definitions or executable commands. Explicit local
command-reference registration belongs to the trusted CLI, not public HTTP upload.

The current start request retains a legacy-compatible `case` envelope containing
only candidate-visible input and identifiers. For example, `POST /v1/runs`:

```json
{
  "contract_version": "1.0",
  "request_id": "request-001",
  "session_id": "session-001",
  "case": {
    "contract_version": "1.0",
    "case_id": "inspect",
    "version": "1",
    "name": "Candidate task",
    "input": {"message": "Inspect the catalog.", "assets": []}
  },
  "execution_mode": "sandbox",
  "timeout_ms": 30000
}
```

Start and resume return `TargetRunResponseV1`: `external_run_id`, `status`, a
normalized `trace`, optional `pending_interaction` and optional `error_type`.
Use `awaiting_input` or `awaiting_confirmation` with the real pending interaction
ID/type and required fields. Match the envelope and trace statuses. For a pending
clarification `currency-question`, `POST /v1/runs/remote-001/resume` could receive:

```json
{
  "contract_version": "1.0",
  "request_id": "request-002",
  "external_run_id": "remote-001",
  "session_id": "session-001",
  "interaction_id": "currency-question",
  "response": {"currency": "USD"},
  "timeout_ms": 30000
}
```

Do not invent approval, reuse stale interaction IDs or replay completed side
effects when resuming. Reset receives a body such as `{"protocol_version":"1.0"}`.
Execution uses the `X-Agent-Eval-Protocol` and `X-Agent-Eval-Accept-Protocol`
headers; wire contracts support 1.0 and 1.1. A successful handshake is not an
automatic change to every execution envelope. See [public contracts](CONTRACTS.md)
and the [adapter guide](ADAPTERS.md) for the complete response/evidence model.

### Sandbox tool environment

The library integration example below is not a shipped external bridge or a
registered collector for the `0.3` business bank. Independent business evidence
uses an internal collection path, not a public upload kind; importing `trusted=true`
does not establish trust. The onboarding Skill reports this integration work
separately and does not implement or register a collector.

The Target service owns the actual Agent, model calls and tool dispatch. Bind
those tools to a safe environment explicitly; declaring `safe_for_eval` does not
intercept real tool calls or isolate a child process. Starting a real Target may
use that Target's configured model budget, unlike importing or checking.

**Current support:** `ScenarioEnvironment` is an in-process Python library, not
an HTTP service. Generic HTTP/Python Targets receive only the cropped public
`case`; their start/resume protocols do not carry a tool-execution callback or
the private compiled case. Filling in capability mappings, registering a Target
or passing the handshake does **not** connect its tools to this environment.
Name/field mappings do not replace remote tools with fixtures; an external
HTTP/Python Target still needs an explicitly connected trusted tool backend.
An Agent with its own safe tools can use the generic Target protocol, but that
alone does not exercise the bank's controlled environment.

The existing end-to-end bridge is the built-in `ReferencePolicyTarget` in
[`targets/reference_policy.py`](../src/commerce_eval/targets/reference_policy.py).
The runner privately calls `bind_environment_cases()` only for that adapter
type; this is not automatic injection into arbitrary plugins or HTTP/Python
Targets. Its deterministic policy is an implementation example, not a connector
for your external Agent and not the script-driven `reference_fixture`.

For an external Agent, the supported building block is a **trusted Python
harness that owns tool dispatch**, using the library methods below. Integration
with your Agent SDK/tool callback is adapter work, not a wizard setting:

1. Load the selected Dataset/version on the trusted side with
   `Repository.get_dataset(project_id, dataset_id, version)` and validate the
   selected row as `EvalCaseV1`. Never reconstruct the environment from the
   cropped request or let the candidate choose a different private case.
2. Keep `ScenarioEnvironment(compiled_case)` in that trusted host for the run.
   Send the Agent only `project_candidate_input(compiled_case)` and public tool
   IDs/input schemas from `build_tool_contracts(compiled_case)`. Do not send the
   full contracts' evaluation tags or derive the visible tool list from the
   case's expected/forbidden actions.
3. Configure the Agent's actual tool dispatcher to return each real call to the
   trusted host. Bind its session on the host; dispatch only into that session's
   environment, never production tools. Preserve the original tool ID, arguments
   and call ID. The existing library dispatch/output conversion is:

```python
from commerce_eval.contracts.scenarios import CapabilityBindingV1
from commerce_eval.scenarios.bindings import encode_evidence


def dispatch_actual_call(environment, compiled_case, bound_session_id, actual_call):
    # Host-side code only; none of these private objects go to the candidate.
    receipt = environment.execute(bound_session_id, actual_call)
    binding = next(
        (CapabilityBindingV1.model_validate(row)
         for row in compiled_case.capability_bindings
         if row["tool_id"] == actual_call["tool_id"]),
        None,
    )
    return encode_evidence(binding, receipt) if binding else receipt
```

`actual_call` has `tool_call_id`, `tool_id` and `arguments`. The Agent has already
chosen its actual arguments; do not scale them again before `execute()`. The
environment validates and decodes them. Its returned receipt uses neutral
evidence names, so this fragment applies `evidence_mapping` before returning the
tool result to the Agent. Recorded observation events already use that mapping.
The fragment dispatches one call; it is not a complete Agent loop or a new API.

4. Keep the environment alive across calls and pauses. A pending interaction
   must become a matching `PendingInteractionV1` in the Target response. On the
   corresponding resume, the trusted bridge calls
   `environment.respond(session_id, interaction_id, response)` before resuming
   the Agent. The runner can supply the current scripted reply after validating
   the pending interaction; never send the future script or invent approval.
5. Collect `environment.events(session_id)` as evaluator-side execution evidence,
   combine it with genuinely observed Agent events, and return a valid
   `TargetRunResponseV1`. Keep event order/call IDs and confirmation/artifact
   bindings intact. Call `environment.reset(session_id)` at session cleanup and
   `environment.close()` when the harness finishes.

For an Agent in another process or service, a trusted adapter still needs a
session-scoped IPC/RPC tool bridge. The shipped HTTP routes do not provide one;
PythonAgentTarget's one-request/one-response subprocess protocol does not provide
one either. Do not give the candidate database/API credentials to fetch complete
Datasets as a workaround. A general runner-injected environment bridge or remote
tool endpoint requires coordinated runtime work before it can be advertised as
supported. Until then, use an installed trusted harness or import genuine traces
from your existing safe runtime, with the evidence limitations stated explicitly.

Keep the compiled case, reference scripts, future dialogue, expected answers,
gates and environment internals on the trusted evaluation side. The Agent receives
only its current public task and explicitly permitted assets. Never use the bank's
reference script to choose an examinee's actions or to manufacture its grade.
Input cropping is data minimization, not process isolation: untrusted candidate
code must not share access to the host's environment objects, files or credentials.

## 中文速览

评测设计尚未确定时，可先使用[接入 Skill](ONBOARDING_SKILL.md)：先调查整个产品，
再等待你确认一条主流程和影响正确答案的规则。它只产出交接材料并在临时库离线校验，
不会执行下列真实项目导入、注册或运行操作。可导入不等于已接入，缺证据不能记为 N/A。

1. 打开“接入与导入”，选择项目和模式。已有运行记录优先导入；只有明确需要运行
   Agent 时才连接 Target。预览、提交导入、试接入都不会调用 Agent 或模型。
2. 四类资料是：运行轨迹（JSON/JSONL）、工具合同（JSON/JSONL）、商品资料
   （CSV/JSON）、公司规则（MD/TXT）。考题集、评测器集合和 Target 是独立配置。
3. 先下载模板，再上传、校验、映射、选题和确认。每文件 10 MiB、每次 50 MiB、
   最多 1,000 条轨迹；草稿一小时过期。任一错误整批失败，同版本不同内容禁止覆盖。
   草稿绑定预览时的项目，切换页头项目或前后导航不会改变提交归属；换项目需重新预览。
   映射时展开能力，填写真实工具 ID，并在“参数与单位”“输出证据”中逐行添加
   中立字段与真实工具字段或 JSON 指针。`unit_scale` 为正数，留空按 1：
   中立参数 15 × 0.01 = 实际参数 0.15；`evidence_mapping` 不应用倍率。
   提交的绑定和导出的轨迹保留原始工具名、字段名，不要求重命名 Agent 工具。
4. HTTP 服务必须实现真实 `/v1/capabilities` JSON 握手及 start/resume/reset。
   试接入限时 3 秒、响应上限 64 KiB，HTML 200 不算成功；本地 Target 也须明确安全。
   沙箱工具环境仍需适配器自行接入，平台不会自动隔离真实业务工具。
   通用 HTTP/Python 协议没有环境工具回调；填写名称映射不会自动执行题库工具。
   当前可用 Python 库接口由可信宿主转发真实调用；跨进程桥接需另行适配，不能传完整考题。
5. 轨迹导入后不评分。显式选择 Dataset、Case、工具合同和评测器版本后再评测，
   每次生成新的不可变 `evaluation_id`，历史指标和门禁保留。
6. 内置 32 题默认运行独立规则策略 `reference_policy`：自主选择动作、使用模拟工具、
   不调用 LLM；成绩只属于该策略基线，不代表你的真实 Agent。可选 `reference_fixture`
   仅生成未评分的脚本参考轨迹，禁止转为考生成绩。`/onboarding/demo` 只准备资源，
   返回策略 `policy_experiment_spec` 和旧参考 `experiment_spec`，界面最终确认才启动所选运行。
7. 公开上传不支持 XLSX、压缩包或可执行代码。私有适配器可在本机授权范围内读取
   XLSX，再导出支持的标准数据与证据；不得把私有文件变成平台运行依赖。
8. 凭据只填写服务端环境变量名，不能填写真实 Key/Token。命令和 Python 注册不走
   公开上传；真实工具执行、模型预算、授权和副作用隔离由可信 Target 负责。
