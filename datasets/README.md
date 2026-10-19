# 生产来源脱敏数据集

本目录包含两份用户提供的真实业务导出的脱敏副本，用于在其他设备上复现数据处理与压缩。它们保留原始记录结构、成绩、状态、评语主体和记录关系，没有通过复制记录扩大规模，也没有用模型生成文本替代真实评语。

| 文件 | 内容 | 记录数 | 非空评语 | 完整性 |
| --- | --- | ---: | ---: | --- |
| [student_list.json](production_deidentified/student_list.json) | 单个活动下收到的学生记录 | 376 | 374 | 原始来源曾截断，必须传 `source_complete=False` |
| [student_activities.json](production_deidentified/student_activities.json) | 单个学生的活动记录 | 11 | 10 | 未提供业务完整性证明，使用 `None` |

数据中的产品、AI 工具与课程术语属于原评语内容。评语里包含示例、建议和宣传性数字，不能把它们直接当作真实业务统计。

## 脱敏范围

- 学生、教师和活动的原始 ID 替换为一致的测试 ID；学生姓名替换为序号，教师姓名移除。关联关系在两份文件间保持一致。
- 全部有效绝对时间统一平移到合成时间轴，保留相对间隔；空时间保持空。公开时间不能作为真实业务发生日期。
- 评语中两处个人视频账号标签已遮蔽；同时检查已知姓名、原始业务 ID、联系方式、链接和显式日期。
- 不公开身份映射、原始文件、原文件路径、原始模型回答或含业务数据的 API 缓存。

这是针对这两份已检查导出的处理流程，不是自动识别任意个人信息的通用脱敏器。加入新数据前需要重新检查字段和文本。原始导出与脱敏副本不可混称；脱敏与序列化会改变字符数、token 和输入哈希。

## 可复现范围

可以验证记录数、成绩与状态统计、完整结构化行保护、指定对象原文保护、截断恢复及压缩预算。成绩和仍分别为 31594 与 477.4；不同活动的成绩尺度未统一，不能把后者均值解释为百分制表现。

[manifest.json](production_deidentified/manifest.json) 记录公开文件哈希、记录数、精确数值校验值及脱敏方式。历史 2026 年 10 月 12 日模型评测基于原始输入；本目录是 10 月 19 日公开脱敏版本，不声称模型答案和 token 数完全复现历史值。

克隆仓库后，在项目根目录运行，不需要模型密钥：

```text
python -m scripts.check_public_data
```

可选 BPE 审计需要 `pip install -e ".[token-audit]"`，首次使用 tokenizer 可能下载公开编码文件：

```text
python -m scripts.check_public_data --counter o200k
python -m scripts.check_public_data --counter cl100k
```

显式启用模型评测时可以把本目录两个文件传给 `evaluation.lms_business`。仅运行默认本地检查不会调用 LLM。任何模型缓存和含评语的输出继续放在 `evaluation/private_business_*` 中，不提交 Git。
