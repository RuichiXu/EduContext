# EduContext

教学 Agent 工具结果进入最终 LLM 前的轻量 Python 上下文压缩模块。**核心零运行时第三方依赖，不部署服务；长评语可显式启用额外 LLM 选取原文证据。** 默认压缩不调用模型。

把结构化记录转换成可核对的统计、实体目录和原始证据行。关键内容过多时保留内容并报告预算不足，不承诺所有 JSON 都能压缩十倍。

组件独立于下游报告 Skill：输入用户任务、JSON 和配置，输出精简上下文；报告 Agent 再结合自己的 Skill 生成 HTML。当前任务判断是规则与显式参数，尚未实现 LLM 计划生成器。下一步的完整设计与验收要求见[改进路线图](docs/roadmap.md)。

## 克隆与复现

```text
git clone https://github.com/RuichiXu/EduContext.git
cd EduContext
python -m pip install -e .
python -m unittest discover -s tests -v
python -m unittest evaluation.test_runner -v
python -m scripts.check_public_data
```

上述测试与数据验证不调用模型 API。建议在虚拟环境中运行。仓库包含两份[生产来源脱敏数据](datasets/README.md)，可跨设备复现结构与数值检查；原始数据、身份映射和私有模型缓存不公开。脱敏改变 ID、时间及少量文本，历史模型评测数字与公开样本验证分开记录。

2026 年 10 月新增 `compress_lms`，适配实际 `data.studentList` / `data.activityList`，保留全部收到的完整结构化记录；支持截断 JSON 恢复与可选评语摘录。[完整流程](docs/pipeline.md) · [两份业务数据评测](docs/business-evaluation-2026-10-12.md) · [接入示例](examples/lms_integration.py)。

大文件 376 条记录：纯统计 17.02 倍、指定学生 16.39 倍、评语摘录 14.69 倍（o200k 编码）。指定学生配对测试为原文 6/14、压缩 14/14、等预算截断 1/14；仅一次小样本测试，不代表生产准确率。完整保留全部评语只有 1.16 倍。小文件 11 条活动未达到字符阈值，原样透传。

## 快速使用

Python 3.10+，在本目录可直接运行；也可用 `python -m pip install -e .` 安装。构建需 setuptools，运行模块只需标准库。

```python
from edu_context import compress, Config

result = compress(
    "分析学号 S119 的成绩异常",
    {"grades_api": grades_json, "roster_api": roster_json},
    config=Config(
        entities={"student_id": "S119"},
        field_roles={"points": "metric", "studentId": "entity"},
        bounds={"points": (0, 100)},  # 业务已确定量表时才配置
    ),
    # token_counter=lambda s: len(your_tokenizer.encode(s)),
)

if result.triggered and not result.within_budget:
    handle_budget_failure(result.stats)  # 缩小 API 查询、拆分任务或换更大窗口
else:
    final_llm(user_request, tool_context=result.context)
```

`data` 接受 JSON 值或已序列化的 JSON 字符串。多工具建议传 `{工具名: 工具结果}`。JSON 字符串的小数以 Decimal 解析；如果调用方已经把高精度小数转成 float，本模块无法恢复先前损失。

`compress(task, data, *, config=None, token_counter=None, force=False, recover_truncated=False, source_complete=None) -> Result`：

| 输出 | 含义 |
| --- | --- |
| `context` | 直接提供给最终 LLM 的字符串 |
| `original_chars` / `compressed_chars` | Python 字符数，不是 UTF-8 字节数 |
| `original_tokens` / `compressed_tokens` | 注入 counter 的计数，或内置估算 |
| `triggered` | 是否进入压缩流程 |
| `target_tokens` / `within_budget` | 目标预算与是否满足，不是回答质量认证 |
| `stats` | 任务模式、行数、实体命中量、压缩率、失败原因、输入哈希 |

默认仅当**字符数严格大于 420000** 时压缩。未触发时，字符串原样返回，不解析或验证 JSON；对象仅做 JSON 序列化。未触发时 `within_budget` 与 `max_tokens` 比较，不应用十倍压缩目标。`force=True` 用于开发和测试。

显式设置 `recover_truncated=True` 或 `source_complete=False` 时，也会在阈值以下解析并携带完整性信息；发生恢复或声明不完整时输出完整性包装。恢复只接受文件末尾截断，不修复中间语法错误、不猜测未收到的数字或记录。

触发后的目标为 `min(200000, original_tokens // 10)`。内置估算分别处理英文词、数字串、中文与 JSON 标点，经过两种公开 BPE 编码复核，仍然**不是窗口硬保证**。生产应注入实际模型 counter。预算含压缩格式说明和告警，不含用户问题、系统提示、其他对话与预留输出；Agent 须自行预留。可选 `token-audit` extra 使用 tiktoken，核心完全不依赖它。

## 处理流程与保护范围

1. 递归发现记录数组，保留外层工具元数据。每表独立统计，不自动跨工具 join 或去重。
2. 识别报告、比较、异常任务；排名、趋势、因果、加权、去重人数、及格率、相对时间和比较筛选等未实现计算算子的任务，回退到无损结构打包。原文中精确出现的日期和状态值也可参与证据保护；不猜测未知时间范围。
3. 按字段角色区分实体、维度、度量、状态、时间。显式配置优先；未知且变化的字段、变化的嵌套单元格触发该表全量保留。
4. 全量计算每表及分组的总和、数值个数、极值、精确有理均值，记录 missing/null/非数值；状态与时间保留值频次。配置上下界时给出区间内外计数，不默认量表或异常阈值。
5. 实体目录保护所有出现的 ID/名称关联。命中实体的全部原始行、异常状态、越界、重要标记、缺失/非数值度量、首行及极值证据强制保留。极值并列保留一条见证及并列数量。
6. 同类实体名称与 ID 可跨工具关联，例如名单中的“张三”关联成绩工具的“学号”。选择器是**并集保护**，不是过滤器；点名班级会保护该班全部明细。
7. `columns/common/rows` 避免重复 key 和公共值；对划算的重复字符串使用列字典，业务数值不编码；`missing` 区分缺失与 null。保留原因用连续行号区间表示，路径、行号和 SHA-256 支持溯源。详见[输出协议](docs/protocol.md)。
8. 超预算仅删可选代表行。仍超预算则 `within_budget=False`，原因 `protected_content_exceeds_budget`，不再裁切。若真实触发时候选输出比原文更耗 token，则直接返回完整原 JSON，并在结果统计中标记防膨胀退化。

**可靠保护指保留的证据行及实体目录不改写单元格，统计在声明的总体内精确。** 报告压缩是有损变换，不保留所有普通记录的逐行数值/时间/状态关联；输出列出省略行数及不可重建信息。若任务需要每条关联，应使用明细任务或显式实体选择，接受较低压缩率。

均值用 `mean_exact: {"numerator": ..., "denominator": ...}` 表示。分母只含该列数值记录；布尔值、数值字符串、null、缺失不算数值，不自动转型或填零。异常行不被排除。原工具的单位、过滤范围、分页或权重信息仍在 `source` 中；记录均值不能当作加权均值，记录数不能当作人数。`target_summary` 给出被保护目标集合的精确统计，明确采用选择器 OR 并集，不能冒充自然语言问题的 AND/范围筛选结果。

## 配置

- `trigger_chars`、`max_tokens`、`ratio`：默认 420000、200000、10。
- `representative_rows`：最多取前几行作可选示例，不是用于统计推断的随机样本。
- `dictionary_encoding`：默认开启；只在预计节省字符和 token 时对重复字符串列编码，可关闭作消融。
- `field_roles`：精确字段名 → `entity/dimension/metric/status/time/important/ignore/unknown`。`ignore` 表示调用者授权该列不参与统计与保守性判断；保留的证据行仍含该列。
- `entities`：字段名 → 目标值；未指定才从任务推断。找不到显式对象则全量保留并告警。
- `group_by`：联合分组键；不指定则用识别出的班级、课程维度。缺失与 null 不混同。
- `bounds`：度量字段 → `(下界, 上界)`，边界包含，`None` 表示该侧不限。
- `abnormal_values`：有类型的状态精确匹配值；英文不区分大小写，数值 `2` 与字符串 `"2"` 不混同，应配置业务枚举。

## 文件结构

```text
edu_context/
  __init__.py            对外 API
  compressor.py          选择、精确统计、编码、预算与溯源
tests/                  边界与随机化完整性测试
examples/integration.py  工具链示例
evaluation/
  fixtures.py            合成数据及独立金标
  runner.py              三路输入、模型适配、评分和完整性验证
  test_runner.py         评分器测试
  robustness.py          360 项随机完整性检查与低冗余数据验证
  token_audit.py         可选公开 BPE 计数复核
  artifacts/             输入、答案、评分与统计
  experiments/           冻结的实验输入和回答
docs/
  research.md            论文和开源方案取舍
  evaluation.md          本次评测及局限
  protocol.md            输出结构与统计口径
  resume.md              基于已验证结果的简历条目
pyproject.toml
```

## 验证

```powershell
python -m unittest discover -s tests -v
python -m unittest evaluation.test_runner -v
python -m evaluation.runner oracle --output evaluation/artifacts/oracle.json
python -m examples.integration
python -m examples.demo
```

[本次评测报告](docs/evaluation.md) 区分程序化验证与真实子 Agent 回答；[评测说明](evaluation/README.md) 提供 callable 和命令行适配器，可接入生产模型。模型评测禁止代码代算，金标仅在回答后计分。

9 月历史交付：44 项测试通过，其中含 360 组随机完整性检查；3 道合成数据模型对照题中，完整输入与压缩输入均答对 21/21 个关键事实，直接截断答对 3/21。报告与指定学生任务经两种公开 BPE 编码复核约 28–30 倍压缩；两班比较因保留全部目标记录仅约 6 倍，明确标记预算失败。参见[历史简历条目](docs/resume.md)，这些结果不代表生产准确率。

10 月 12 日版本：67 项模块测试加 6 项评测器测试，共 73 项通过。两份真实 LMS 数据结果见[业务评测](docs/business-evaluation-2026-10-12.md)，与历史合成实验分开记录。公开发布版本额外验证脱敏处理与公开数据复现，以当前 CI 为准。

调研并参考 [TAP4LLM](https://arxiv.org/abs/2312.09039)、[LongLLMLingua](https://arxiv.org/abs/2310.06839)、[LLMLingua-2](https://arxiv.org/abs/2403.12968)、[TOON](https://github.com/toon-format/toon) 与语义层思路，未引入其模型或依赖。详见[调研文档](docs/research.md)。

## 已知边界

- 关键词和实体别名规则不是通用自然语言理解；生产推荐显式 schema 与实体参数。
- 仅做记录级描述统计，不统一业务指标定义，不计算任意关联、因果、加权率、时序突变或跨表连接。
- 未标记异常只有极值见证；不能声称发现全部异常。状态、重要标记、阈值须由业务配置。
- 高基数实体/时间/分组、大量必要文本可能无法缩小；通用模块候选膨胀时返回完整原文，LMS 适配器保留保护内容并标记超预算，由 Agent 处理。
- 全量解析、多遍扫描，内存随数据增长；不是流式处理器，深嵌套受 Python 递归限制。
- 字段配置按键名生效；不同工具同名异义应先规范字段或分别调用。
- 不处理分页补全、权限或脱敏，不替代数据质量控制。输入哈希不是签名认证。
- 合成数据和少量模型实验不代表生产准确率，不能据此写成数百条真实查询的上线提升。
