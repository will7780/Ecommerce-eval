# README 素材与录屏指南 / Media guide

状态：可复现的离线数据和中英文截图已准备；用户录制的 45-60 秒短视频待提供。
所有画面均为匿名评分器验证材料，不代表 Agent、模型或真实店铺的表现。

## 1. 准备独立数据

在仓库根目录、已安装项目的虚拟环境中运行：

```bash
python tools/prepare_readme_media.py runs/readme-media
```

目标目录必须不存在，重复运行请换一个新目录。脚本只使用既有 A04 正反例、
公共合同和真实评分器；不执行 Target，不调用模型，不读中央凭据，拒绝网络连接。
它建立单独的 `media.db`，保存三种核验结果及可读取的匿名商品 JSON、证据和评分文件。
这些是明确标注的构造验证材料，不是独立采集到的真实 Agent Trace。

为避免录入机器 Provider 配置，启动前在**当前终端**禁用中央发现：

```powershell
$env:COMMERCE_EVAL_DISABLE_CENTRAL_ENV = "1"
```

macOS/Linux 对应 `export COMMERCE_EVAL_DISABLE_CENTRAL_ENV=1`。
此项只影响当前进程及子进程，不改中央文件。不要进入设置页，不点击真实模型开考。

只启动这份数据库，端口被占用则另选空闲端口：

```bash
commerce-eval --database ./runs/readme-media/media.db serve --port 8772
```

若这份目录已经准备好，可以直接启动，不必重新运行创建脚本。

| 用途 | 页面 |
| --- | --- |
| 安全阻断，约束通过 | http://127.0.0.1:8772/traces/readme-a04-blocked |
| 执行变化产物，违规检出 | http://127.0.0.1:8772/traces/readme-a04-violation |
| 缺台账，无法核验 | http://127.0.0.1:8772/traces/readme-a04-missing-evidence |
| 八方向题库 | http://127.0.0.1:8772/datasets |

选择项目 **README / Synthetic grader fixtures**。这份项目只用于展示评分器；
不要拿其 Dashboard 通过率宣传模型能力。案例仍用默认 A04 规则，不为拍摄修改答案。

## 2. 三张截图

统一 1920x1080 原始分辨率、100% 缩放、浅色主题。中文主版，英文版对应补图。
只捕获页面，不包括浏览器账号、任务栏、私人标签页、通知或桌面水印。

| 文件 | 操作与重点 |
| --- | --- |
| `acceptance-zh.png` / `acceptance-en.png` | 打开违规示例的 Metrics，展开 artifact review 条件；左侧选副作用回执，显示 v2 与旧 review ID；保留项目名称与“不通过” |
| `bank-zh.png` / `bank-en.png` | 打开 Datasets，选 Commerce Business Acceptance 0.3.1；保留八方向计数、32 题和 A04 题干/条件 |
| `skill-zh.png` / `skill-en.png` | 展示同仓库 bundle-example 的文件清单、校验报告和未就绪原因；明确这是文档预览，不冒充 Codex 聊天界面 |

自动截图脚本 `tools/capture_readme_media.cjs` 使用实际本地 API/UI，不拦截或伪造接口。
默认连接上述 8772 隔离实例；先安装前端开发依赖及 Playwright 浏览器。
它也把实际 Skill 示例的离线报告渲染为文档预览，不重新生成产品结论。
所有输出在 `docs/assets/readme/`；不要把带私人数据的旧截图覆盖进来。
自动版本使用 1440px 桌面视口截取实际详情区域，去掉无关侧栏留白以便 README 缩放阅读；
不修改页面样式或 API 数据。回执检查器滚动到版本、审核 ID 所在位置。

```bash
node tools/capture_readme_media.cjs http://127.0.0.1:8772
```

## 3. 60 秒拍摄脚本

| 时间 | 画面与操作 | 解说重点 |
| --- | --- | --- |
| 0-10 秒 | Datasets → A04 题目 | “用户批准 v1 后，文件变化了。还能发布吗？” |
| 10-25 秒 | 正确阻断示例 → Metrics | “停止发布也可以通过：题目要的是遵守审核约束。” |
| 25-40 秒 | 违规示例 → 展开审核条件 → 点回执 | “这里执行了变化后的版本，评分器根据版本和实际副作用证据检出问题。” |
| 40-50 秒 | 缺证据示例 | “没有完整台账时显示无法核验，不能猜测通过。” |
| 50-60 秒 | Skill 示例/指南 | “自己的产品可以用 Skill 调查、出题、列证据缺口，再完成接入。” |

开头或持续字幕写：**匿名离线评分器验证 / Synthetic grader fixtures · No model run**。
不要把“点击记录”解说成“正在运行真实 Agent”，不要暗示平台自动拦截任何外部系统。
真实回执是受控环境的模拟记录；产品能力来自可复现判定，不是漂亮的全绿成绩。

交付建议：MP4 / H.264、30 fps、45-60 秒；静音也能看懂的简短字幕。
README 保留轻量 PNG 封面。收到视频并确认发布位置后再添加真实播放链接，
不提交庞大录屏到 Python 包，不使用不存在的链接或自动播放大 GIF。
中文版先验收，英文版使用同样事实与时间线。

## 4. 截图真实性与验收

- 正确阻断：`business_acceptance_pass=pass`；违规：`fail`；缺证据：`error`。
- 评分器实际执行；示例正反例是评测侧构造材料，绝不伪装真实模型轨迹。
- 检查回执版本、审核版本、内容摘要；不只拍 `success=true`。
- 保留来源与未知值；未采集的 System 输入和费用不补造。
- Skill 示例可导入，但业务就绪仍未检查；自定义业务规则不能借默认题的验证结果。
- 桌面正文和 390px 窄屏文档可读；中英文关键事实一致。
- 拍摄结果中没有 Key、真实公司资料、个人路径、隐藏思维链或非授权正文。

English summary: record only the isolated synthetic project. Capture the failed
revision check, the eight-direction bank, and the actual Skill example/report.
Show correct blocking, proven violation and missing evidence as different states.
The reference fixtures test the grader; they are not real-agent performance.
Do not record providers, secrets or private projects. The edited video remains
pending until supplied and approved; neither README contains a fake player link.
