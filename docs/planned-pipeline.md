# 通用规划管线接入说明

`compress_planned` 是 v0.2 新增的显式入口。调用方提供业务字段定义、文本压缩权限和保护条件，模型提出受约束的计划，程序验证后执行。所有结构化行保持原始对应关系，数值统计由程序完成。原有 `compress` 和 `compress_lms` 的默认行为不变。

## 输入与最小示例

```python
from edu_context import Policy, compress_planned
from edu_context.model_client import JSONModelClient

policy = Policy(
    definitions={"/records": {
        "/person": {"role": "entity"},
        "/points": {"role": "metric", "unit": "points", "scale": "0-100"},
        "/level": {"role": "status"},
        "/detail/comment": {"role": "text"},
    }},
    protected_entities={"/records": [{"field": "/person", "value": "S1"}]},
    required_fields={"/records": ["/level"]},
    text_permissions={"/records": {"/detail/comment": ["retain", "extract"]}},
    max_tokens=12000,
    max_model_calls=10,
    max_model_input_tokens=50000,
    retries=1,
)
client = JSONModelClient(
    api_key=caller_key, base_url=caller_url, model=caller_model,
    timeout=120, max_calls=10,
)
result = compress_planned(
    user_task, raw_json, policy=policy, model_call=client, allow_model=True,
    source_complete=None, token_counter=actual_model_counter,
)
```

`definitions` 和其他映射先以表的 JSON Pointer 定位，再以记录内的 JSON Pointer 定位字段。`/` 和 `~` 分别编码为 `~1`、`~0`。数字 ID 与等级编码必须声明成相应角色，不能因为是数字就当成绩。`metric` 需要调用方明确 `unit` 和 `scale`；同名字段跨表仍分别统计，不跨评分尺度合并。

只提供 `model_call` 不会调用模型；必须同时传 `allow_model=True`。不传计划也不启用模型时执行保守无损计划。可以传 `plan=...` 完全离线执行已审核计划，见 [可运行示例](../examples/planned_integration.py)。核心不读取环境文件，不搜索凭据。

## 数据概况与计划验证

程序严格解析 JSON，保留小数精度，拒绝重复键和非有限数字。显式启用 `recover_truncated=True` 才恢复 EOF 截断，丢弃未闭合记录，并将来源完整性标为 `False`。正常 JSON 的业务完整性仍由调用方提供。

概况扫描全部收到的记录，提供字段路径、类型频次、missing/null、类别基数和文本长度分布。格式样例只说明 JSON 类型，不发送实际身份值或长文本。若结构或字段数量超过请求字符/输入预算，规划失败并保留数据。

[计划 JSON Schema](../schemas/compression-plan-v1.schema.json) 定义结构，运行时校验器另外验证字段存在、调用方语义、单位、量表、字段类型及保护权限。模型不能增加筛选器、代码、预算覆盖或其他未定义操作。允许的聚合是 `stats`：记录数、数值数、精确和与均值、极值，以及按已定义类别字段分组。

排名、趋势、相对时间、连接和权重未实现，明确要求这些算子时返回 `unsupported`，即使还缺少时间字段等数据。其他任务缺少必要业务含义时返回 `needs_clarification`；例如尚未提供“优秀”的定义时先澄清，补充定义后也不代表等级判定算子已实现。这是给调用方的状态，组件不会自动给用户发消息。模型可能误解自然语言，所以结构合法不等于意图完全正确；调用方可以检查返回的 `plan`，或直接使用审核后的手写计划。

## 结构化数据与保护

全部记录按原始顺序保留，嵌套对象展开为叶字段，嵌套数组保持为完整单元格。未知字段默认保留。共享表头、公共值和字符串字典减少重复；missing、null、空对象、空字符串和数字字符串保持区别。

`protected_entities` 是 OR 并集保护，完整保留命中记录及其所有文本，**不筛选统计总体**。`required_fields` 保留对应字段原文，包含父子路径保护。`required_quotes` 接受 `{"table": ..., "field": ..., "quote": ...}`，保护包含所需原句的完整记录。未找到必保实体或原句时返回 `needs_clarification`，不继续有损处理。

`sum_exact` 与 `mean_exact` 使用有理数分子/分母。均值只以实际数值单元格计数，字符串数字、missing 和 null 不被填零。分组键用 `{"missing":true}` 区分缺失与 `{"value":null}`。人数需要明确身份去重语义，不能把记录数改称人数。

## 逐记录文本证据

只有定义为 `text` 且在 `text_permissions` 中明确允许的字段，才可使用 `extract` 或 `omit`。`omit` 是调用方授权的整字段省略，必须适合当前任务；需要保留的事实应通过保护约束传入。没有权限时默认 `retain`。

`extract` 将一条记录的多个文本字段一起送入模型，以完整物理段落作为不可切分单位。程序只接受段落下标，不接受模型改写的事实或标题。每个证据保留表路径、原行号、字段和原始字符串的字符起止位置；相同原句只合并来源列表，不把近义文本合并成未经验证的主题。

含条件、否定、异常或冲突提示词的字段保守保留整段原文。这是额外规则保护，不能覆盖全部语言表达。非空文本不允许空摘录：不确定相关性时选全部段落，非法选择或失败则保留对应字段。必保对象不经过摘录。

`reviewed_fields` 校验的是模型回传的覆盖声明，不能证明实际阅读。逐字原句证明出处，不能证明语义完整；选择后的文本不能用于推断多数、人数或主题频率。生产使用前应按业务建立人工事实金标。原始 HTML 不执行，也不做语义清洗；需要 HTML 规范化的既有 LMS 路径仍可单独使用。

## 输出与失败处理

返回字典包含 `context`、`payload`、`status`、`within_budget`、输入与输出 token 数。`context` 是最终序列化的 `educontext.planned/1` 包装，直接提供给下游模型。模型计划文字只是意图描述，不是事实来源。

| 字段 | 内容 |
| --- | --- |
| `scope` | 原始输入哈希、来源完整性、截断恢复信息 |
| `source` | 保留的外层元数据，表位置由引用替代 |
| `tables` | 全部结构化记录、精确统计、保护行号和人口范围 |
| `evidence` | 原文段落及完整出处列表 |
| `omissions` | 每个被省略或摘录的文本单元格及损失说明 |
| `plan` / `definitions` | 计划及调用方字段含义；失败时不据计划声明已执行操作 |
| `text_coverage` | 可提取、验证成功、回退的字段数 |
| `cost` | 规划/文本每次调用、计数器用量、延迟及可用的 provider usage |
| `budget` | 最终输出预算检查及失败原因 |

`unpack_planned_table` 解码所有保留单元格；只有 `omissions` 为空时，`restore_planned` 才能还原完整 JSON 值。还原不保证原输入的空格、键顺序或数字词法形式逐字一致。

| 状态 | 调用方处理 |
| --- | --- |
| `ready` | 计划已验证并执行；仍需检查业务语义与 `within_budget` |
| `needs_clarification` | 使用 `plan.questions` 或 `unmatched_protection` 补充定义、对象或来源 |
| `unsupported` | 调整任务或在上游完成该算子 |
| `fallback` | 规划失败时全量保留；文本失败时保留受影响字段，检查 `warnings` |
| `over_budget` | 保留内容但超预算，拆任务、缩小来源或增大窗口 |

预算不足不会裁剪保护内容。预算使用最终序列化输出计数；内置估算不是模型窗口保证。即使预算内，小输入也可能比原文更大，调用方可继续使用既有小输入透传路径。

调用按顺序执行，并发为 1。重试计入 `max_model_calls` 和输入预算；单条超长记录不切开。`max_model_input_tokens` 限制调用方计数器计得的系统文字和请求正文，不是账单额度：供应商 tokenizer、聊天包装和缓存计费可能不同，应以 `provider.usage` 单独核对。使用内置客户端可设置超时和网络调用上限；替换成自定义 callable 时，超时由该实现负责。缓存含业务响应，只应放在私有或忽略目录。

## 验证

```text
python -m unittest discover -s tests -v
python -m unittest evaluation.test_runner -v
python -m scripts.check_public_data
python -m evaluation.planned_acceptance --output .test-tmp/planned
python -m examples.planned_integration
```

以上命令全部离线。真实模型评测必须另行显式启用 `--live --env-file <调用方指定的文件>`；输出应放在被忽略的 `evaluation/private_business_*` 下。正式结论见 [v0.2 验收报告](planned-evaluation-2026-10-20.md)。
