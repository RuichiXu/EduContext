# 技术调研与选择

调研日期：2026-09-14。以下是思路对照，不代表复现了论文结果，也不把外部 benchmark 数字当成本项目效果。

2026 年 10 月业务适配补充：结构化数据继续采用程序精确统计；长评语增加显式启用的 LLM 原文证据选择，只用于有损文本选择。逐字校验后舍弃自由改写标题，失败恢复全部评语。[业务评测](business-evaluation-2026-10-12.md)与[完整流程](pipeline.md)描述当前实现；下表保留原方案取舍。

| 路线 | 一手资料中的做法 | 本项目取舍 |
| --- | --- | --- |
| LLMLingua | 小模型辅助 token 重要性判断、粗到细预算控制 | 借鉴预算分层；不对业务 ID、数值或 JSON 语法做 token 删除，不下载压缩模型 |
| LongLLMLingua | question-aware coarse-to-fine compression，提高与问题相关的信息密度 | 使用可解释的任务模式、名称/ID 精确匹配、跨工具同类实体名称到 ID 关联；不以相关性 top-k 替代统计总体 |
| LLMLingua-2 | 蒸馏训练编码器，将压缩转为 token 分类，强调 task-agnostic 泛化 | 不引入模型推理依赖；将来只适合在业务方授权丢弃的长文本列上作可选实验 |
| TAP4LLM / TableProvider | 面向表格的 sampling、augmentation、packing 三阶段 | 采用表发现、任务证据选择、程序化统计增强、共享表头序列化；不引入 embedding、外部知识补充或服务部署 |
| TOON | 面向 LLM 的紧凑 JSON 数据表示，规则数组可共享表头；嵌套结构不一定更省 token | 自实现 JSON 内的 columns/common/rows，保留通用 JSON 解析能力；增加 missing 位置信息区分缺失与 null，未宣称兼容 TOON |
| Semantic layer | 显式定义维度和度量、区分可加和不可加指标 | 以少量配置声明字段角色、分组、实体及异常上下界；输出 sum/count 与精确有理均值，禁止均值再平均、记录数冒充人数或跨工具自动合并 |

来源：

1. [LLMLingua 论文](https://arxiv.org/abs/2310.05736) 与 [微软实现](https://github.com/microsoft/LLMLingua)。
2. [LongLLMLingua 论文](https://arxiv.org/abs/2310.06839)。
3. [LLMLingua-2 论文](https://arxiv.org/abs/2403.12968)。
4. [TAP4LLM 论文](https://arxiv.org/abs/2312.09039) 与 [TableProvider](https://github.com/microsoft/TableProvider)。
5. [TOON 官方仓库](https://github.com/toon-format/toon)。
6. [Cube 度量定义](https://docs.cube.dev/reference/data-modeling/measures) 与 [非可加指标](https://docs.cube.dev/recipes/pre-aggregations/non-additivity)。

LLMLingua 的实现已经支持结构化压缩和强制保留部分 token，因此不能简单说它“完全不支持结构”。本项目的判断是：即使保留所有数字 token，也不等于保留数值与学生、日期、统计分母之间的关系；结构化业务任务应优先用可校验的数据变换。[官方 API 文档](https://github.com/microsoft/LLMLingua/blob/main/DOCUMENT.md)

## 工程亮点及可验证证据

- **任务感知证据保留**：对象查询保留命中实体的所有明细；名单工具中的名称可以关联同类 ID，再保护成绩工具中的记录。测试验证姓名/学号别名、ASCII ID 边界、缺失对象时保守退化。
- **精确聚合与统计口径**：Decimal 保留 JSON 小数，Fraction 计算精确和及均值；逐字段记录 missing/null/non_numeric，原始工具元数据独立保留。测试覆盖超大整数、布尔值、混合类型和随机小数。
- **结构去重与可追溯证据**：共享表头和公共单元格，原路径及行号定位证据，SHA-256 关联本次完整输入。哈希用于排查输入版本，不是数字签名或防篡改认证。
- **保护优先的预算控制**：只移除可选代表行；目标实体、异常、配置越界、重要标记、极值证据和统计不会因预算再次被删。无法安全满足预算时输出显式告警。
- **三路配对评测与消融**：同题同数据比较原文、相同预算前缀截断、任务压缩；另测无损结构打包，区分结构去重与任务选择的贡献。

这些亮点来自实现与工程验证，不包装成新模型训练、新压缩算法论文贡献或真实业务上线效果。

## 为什么不采用通用 table retrieval / RAG

本模块已经拿到了本轮工具返回的数据，不需要跨知识库检索。向量检索可能漏掉不相似但应计入分母的记录；top-k 的分数并不能证明整体统计完整。这里先在完整记录总体上计算统计，再选择用于解释的原始证据。对于任意 join、排名、时序或因果问题，当前选择保守保留；后续可增加明确的业务计算算子，不必先引入检索基础设施。
