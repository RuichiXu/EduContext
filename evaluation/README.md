# 教学任务端到端评测

新增真实 LMS 数据评测：`lms_business.py` 检查业务适配、两种 BPE 预算与截断恢复，`lms_model_eval.py` 做实际 API 回答对照与证据审阅。[2026 年 10 月报告](../docs/business-evaluation-2026-10-12.md)单独列出结果；下述历史三任务仍是合成实验，不合并口径。

业务评测命令：`python -m evaluation.lms_business --files <学生列表JSON> <活动列表JSON>`。可选 `--model --answer-eval --judge --env-file <授权配置>` 会调用模型；配置由评测器显式读取 `TENCENT_API_KEY` 与 `TENCENT_BASE_URL`。`--only-model` 跳过确定性检查。默认输出 `evaluation/private_business_20261012`，含业务内容，不应分发；该路径已被忽略。

主要评测脚本仅使用 Python 标准库；可选 BPE 审计使用 tiktoken。数据是**合成数据**，不是实际学校查询。三个任务使用同一份 720 条考试记录、120 名学生、2 个班级、6 次考试的数据。原始 JSON 超过 420000 字符；共同的学校说明故意重复，模拟业务 API 冗余。指定学生位于记录尾部，存在一条明确标记的异常。数据规模与分布有限，不能据此推断真实生产正确率。

从项目根目录执行：

```powershell
python -m evaluation.runner prepare --output evaluation/artifacts/preparation.json
python -m evaluation.runner oracle --output evaluation/artifacts/oracle.json
```

`prepare` 生成每题的 raw / truncated / compressed 三种完整 prompt、manifest 和独立 gold。截断基线取原始字符串前缀，使其估算 token 数不超过**该题实际压缩后上下文**；不修复截断 JSON。三个变体的用户问题和答题 schema 相同。`manifest.json` 记录上下文大小、完整 prompt 大小和预算标记。采用模块的估算器，数字不是模型实际 tokenizer 计数。

`oracle` 用原始数据校验记录数、精确成绩总和、原始证据一致性、异常保留和指定学生的所有记录。这是确定性程序校验，**不代表运行过 LLM，更不代表最终任务正确率**。

另包含 60 / 600 / 1800 条记录的重复与高熵文本两种分布，共 6 组规模校验。为比较小规模开销，这 6 组使用 `force=True`。高熵不透明字段变化时必须全量保留，可能比原文更大；报告保留这种失败，不能只汇报有利的高冗余结果。manifest 的 `serialization_ablation` 记录 `compress("保留所有明细", raw, force=True)` 的结构无损基线，完整编码存于 `lossless.context.json`，用于区分公共字段/表格编码和任务摘要各自的效果。

## 模型接口

命令行适配器从 stdin 读取一个 UTF-8 JSON：

```json
{"task_id":"overall","variant":"compressed","prompt":"完整模型输入"}
```

stdout 仅输出 JSON，实际调用模型时三种变体应使用完全相同的模型、版本、系统消息、温度、输出预算等设置，并记录这些设置。适配器可以另将模型版本、用量和延迟保存到日志；日志写 stderr，避免破坏 JSON。超时为 600 秒，不自动重试。不能读取 gold 或使用外部原始数据补充回答。

```json
{"facts":{"record_count":720}}
```

运行全部 9 次真实调用：

```powershell
python -m evaluation.runner run --output evaluation/artifacts/answers.json --command python my_model_adapter.py
```

也可注入 Python callable：

```powershell
python -m evaluation.runner run --output evaluation/artifacts/answers.json --callable my_adapter:answer
```

`answer(request: dict) -> dict` 与命令行接口使用相同结构。适配器负责真正调用生产模型，本模块不引入模型 SDK。适配器失败会记录 `error` 并留空 facts，便于与正常回答区分。

## 通过独立 Agent 读取文件

可以向同一种模型的独立 Agent 提供对应的 `*.prompt.txt` 文件，只允许读取分配的 prompt。每次调用隔离会话，避免看过原始数据后再回答压缩或截断版本造成答案泄漏。评测 Agent 不得读取 `gold.json`、fixtures.py、其他变体、oracle 或其他 Agent 的答案。允许读取完整分配文件；如模型工具输出存在自动截断，应记录，避免将工具截断冒充完整原始上下文评测。

为了避免重复读取三遍大输入，raw 组可以只读取一次 `raw.json`，再读取不含 gold 的 `questions.json`，一次回答三个任务。此运行方式需在报告中记录：它是同一输入的批量答题，与每题单独调用有条件差异。三组均不使用计算工具，不运行脚本求和、不读取其他数据源；文件读取工具仅用于提供分配的上下文。当前 raw 为 429210 字符，模块估算 98698 tokens；实际模型 tokenizer 可能显著不同。

本次最终实验冻结在 `experiments/validated`，`artifacts` 中的同名输入与模型报告是其副本。三组使用相同的 Codex 父任务默认模型设置；接口未给出可核实的具体模型版本、温度或 API token 用量。每个变体独立会话，一次回答三题。`prepare_bundles.py` 生成纯输入包；`deliver.py` 每次输出最多 9000 字符，必须按偏移顺序读取到 EOF，工具输出不得抑制或截断。三组输入分别完整输出 48 / 11 / 6 段。`.delivery.jsonl` 记录哈希与区间，`collect --delivery-log` 检查连续覆盖后计分。这证明传输完整性，不能证明模型内部注意力或记忆完整性。

```powershell
python -m evaluation.collect --directory evaluation/experiments/validated --delivery-log
```

其他实验目录属于探索过程，未完整验证输入传输的模型结果标记 `use_for_final_metrics=false`，不可混入最终质量指标。后续正式复现建议用上述生产模型适配器，执行每题每变体共 9 次隔离调用，并保存模型参数与服务端用量。

可向 `prepare` 注入实际 tokenizer，使压缩与截断使用同一计数器：

```powershell
python -m evaluation.runner prepare --directory evaluation/experiments/my_run --counter my_counter:count
```

可选审计：安装 `.[token-audit]` 后运行 `python -m evaluation.token_audit`。`evaluation.counters:cl100k` 与 `evaluation.counters:o200k` 也可用于上述参数。它们是公开编码基准，不代表本次模型的真实 tokenizer。

答案文件格式如下，可包含一条或多条；三种变体缺少的结果标记 `not_run`，不会当作已经评测：

```json
[
  {"task_id":"overall","variant":"raw","facts":{}},
  {"task_id":"student","variant":"compressed","facts":{}}
]
```

计分：

```powershell
python -m evaluation.runner score --answers evaluation/artifacts/answers.json --output evaluation/artifacts/model_report.json
python -m unittest evaluation.test_runner -v
```

计分按各任务客观金标逐字段进行。数字容差是绝对误差 0.00001；数组顺序和长度均必须正确。

- `key_fact_accuracy`：正确字段数 / 要求字段数。
- `numeric_scope_accuracy`：数字字段及统计单位字段正确比例。
- `completion`：非空字段比例，**不等于正确率**。
- `missing_fields`：缺失或 null 字段；回答错误不能自动认定为源信息缺失。
- `facts_correct_raw_but_wrong_here`：同题原始回答正确、当前变体错误的字段，作为损失信号，不声称因果关系。
- `context_chars`、`context_tokens`、`prompt_tokens`：输入规模；压缩率见 manifest。

本评测是 3 题小规模 smoke evaluation。应进一步加入多工具重叠、缺失值、不同评分尺度、长尾实体、开放问题等业务集，多次重复运行并人工审查；原始版本本身也可能算错。不得把确定性校验通过率、未运行项或模拟数据结果写成真实业务 LLM 正确率。

## v0.2 通用规划验收

`python -m evaluation.planned_acceptance --output .test-tmp/planned` 离线检查两份公开数据、固定原句与保护条件。真实模型测试需显式增加 `--live --env-file <调用方指定文件>`，并把输出放在被忽略的 `evaluation/private_business_*` 目录。

`python -m evaluation.export_planned --input <私有结果目录> --output <公开汇总路径>` 只导出检查结果、哈希与用量，拒绝把未通过门槛的结果导出为通过版本。具体范围和成本见 [v0.2 验收报告](../docs/planned-evaluation-2026-10-20.md)。
