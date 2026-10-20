# 输出协议 edu-context/2

2026 年 10 月扩展：LMS 与来源完整性协议见文末。显式恢复或声明不完整时，小输入也可能输出完整性包装，不适用普通透传说明。

v0.2 的显式规划入口另用 `educontext.planned/1`，不改变此处旧格式；其表解码、原文出处、遗漏和失败状态见[新协议与接入](planned-pipeline.md)。计划结构见[JSON Schema](../schemas/compression-plan-v1.schema.json)。

未触发压缩时 `context` 就是原始 JSON。防膨胀退化时同样返回原始 JSON，`Result.stats.output_format=original_json`，不能把它当作压缩封装解析。正常压缩输出为以下结构：

| 字段 | 意义 |
| --- | --- |
| `source` | 原始外层结构，记录数组被表引用替换 |
| `tables[].path` | 表在原文中的 JSON Pointer，数组下标从零开始 |
| `fields` | 全表逐字段统计，覆盖全部输入行 |
| `group_by` / `groups` | 联合分组键与全量分组统计 |
| `target_summary` | 选择器并集的统计，范围在 scope 中声明 |
| `entity_catalog` | 所有实体/维度值的去重关联目录 |
| `evidence` | 被选择的完整原始行的可逆编码 |
| `evidence_reasons` | 原始行被保护的原因，使用闭区间行号列表 |
| `omitted_rows` / `omission_policy` | 省略的普通行数与不可重建的信息 |
| `budget` | 本次计数口径、预算、是否满足及失败原因 |

表引用形如 `{"$edu_table": 0}`，仅在 `tables[].path` 对应的位置解释为引用；原始数据其他位置即使有同名键，也仍是业务数据。

## 表头、公共值、字典与缺失值

下面仅演示解码规则；实际编码器只在节省空间时引入字典。

```json
{
  "columns": ["student_id", "score", "status"],
  "common": {"course_name": "数学"},
  "indices": [4, 8, 9],
  "dictionaries": {
    "student_id": ["001", "002"],
    "status": ["正常", "异常"]
  },
  "rows": [[0, 80, 0], [1, null, 1], [1, null, 0]],
  "missing": {"2": [1]}
}
```

- `columns` 给出各单元格对应的业务字段，`common` 的键值出现在每个还原行。
- 只有 `dictionaries` 列出的列才使用字典索引。上例的学生 ID 是字符串 `001`、`002`，绝不是数字 0、1。数值度量 `score=80` 直接保留。
- 字典列的 null 仍是 null；其他整数单元格按零基索引取字符串。
- `missing["2"]=[1]` 表示编码表第 2 行的第 1 列原本不存在。第 1 行的 score 则是明确的 null，二者不同。
- `evidence.indices` 是原始数组行号；`entity_catalog.indices` 是去重目录自己的序号，不是原文位置。

验证或调试时可调用：

```python
from edu_context.compressor import unpack_rows
original_evidence_rows = unpack_rows(envelope["tables"][0]["evidence"])
```

该函数不计算统计、不补充缺失字段、不推断被省略的行。它还兼容无字典的早期表编码。

## 统计口径

每个度量分别给出 `present/missing/null/numeric_count/non_numeric_count`，`sum/min/max` 仅覆盖数值项。均值以精确分数表达，避免事先舍入。原始字符串数字不转型，布尔值不当成 0/1；异常行仍在总体内。

状态/时间的 `value_counts` 以 `[原值, 个数]` 表示，保留类型区分。分组不自动去重，缺失分组字段不等于 null；未提供的配置分组键在 `missing_group_fields` 中列出。没有出现的状态不自动解释成业务数值 0 或不存在该对象。

没有跨工具自动合并、没有对分组均值再次平均、没有把记录数改称学生人数。对带日期或其他条件的问题，必须使用对应目标明细或上游正确筛选后的结果，不能拿全表统计冒充筛选统计。

## 预算与退化

预算判断使用最终序列化文本，包含说明、码表和预算元数据。先去掉可选代表行；保护内容仍超预算就返回失败标记，不删除更多事实。真实触发且候选更大时，返回完整原文；`candidate_chars/candidate_tokens` 留下候选开销供诊断。

`within_budget=true` 在估算模式下只表示通过估算器，不能等价于生产模型 tokenizer 的硬窗口。外部注入精确 counter 后，该标记严格按注入的计数结果判定。

## LMS 记录协议

`compress_lms` 输出 `format=lms-context/1`。外层 `source` 保留原始元数据，用 `$lms_table` 引用表；`data_quality` 包含输入哈希、`syntax_recovered`、`source_complete` 与恢复事件。`source_complete` 为 true/false/null，语法有效不能推导 true。

`records` 保存全部收到的完整结构化行，字段使用转义 JSON Pointer，采用 `columns/common/rows/dictionaries/missing` 打包。`fields` 为全量精确统计；`row_count` 是记录数，不同学生和活动数量单独给出。

`comments` 按原行号保存稀疏原文，`target_indices` 为目标学生行号。`comment_inventory` 区分缺失、null、空字符串、非字符串、保留与省略，并列出省略原行号。目标保护不是行过滤。

可选 `text_summary` 声明 `lossy=true`，含原文摘录、来源行号、规范化文本字符位置与批次索引。最终 `finding` 取经过校验的第一条原文证据，自由改写标题被丢弃。`validated=true` 仅表示覆盖索引和逐字引用检查通过，不认证语义完整或来源陈述真实。

模型失败时 `text_failure` 只记录异常类型，该表全部原评语恢复，仍按最终大小计算预算。LMS 超预算返回 `within_budget=false`，不要自动套用通用协议的防膨胀原文退化规则。

`unpack_lms_table(table)` 还原保留字段；存在省略评语时 `restore_lms(envelope)` 报错，防止把有损投影当作全量输入。

## 来源完整性包装

小输入未触发压缩但需要传递完整性状态时，LMS 使用 `lms-integrity/1`，通用模块使用 `edu-integrity/1`，字段为 `format/data_quality/source`。`source` 为安全解析后收到的内容，`triggered=false` 不等于未添加完整性信息。

恢复只接受 EOF 前缀，保留完整数组元素，丢弃未完成元素，不补写业务值。即使 caller 传 true，发生语法恢复后也强制来源完整性为 false。
