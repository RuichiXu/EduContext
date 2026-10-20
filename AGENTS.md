# Project instructions

- Windows 命令默认使用 PowerShell 7（`pwsh`）。
- 项目是独立上下文压缩组件，不依赖报告 Skill，不生成 HTML 报告；下游自行组合 Skill。
- 当前已实现功能见 README；规划层协议见 `docs/planned-pipeline.md`，阶段状态见 `docs/roadmap.md`。不要把待验证目标写成已实现，不沿用旧实验数字证明新链路。
- 公共业务样本仅限 `datasets/production_deidentified/`。保留其生产来源、脱敏方式和来源完整性说明；禁止提交身份映射、原始业务文件、个人身份信息、密钥、`.env` 或私有模型缓存。
- 新增数据必须先审查字段与自然语言内容，再脱敏；现有脚本只针对已审查的两种导出结构。
- 修改压缩逻辑后运行 `python -m unittest discover -s tests -v`、`python -m unittest evaluation.test_runner -v` 和 `python -m scripts.check_public_data`。
- 修改规划层后还需运行 `python -m evaluation.planned_acceptance --output .test-tmp/planned`。公开真实模型评测时只导出聚合检查与调用元数据；不能上传模型缓存或凭据。
- 模型 API 调用必须显式启用并有明确授权；普通测试与公开数据验证保持离线。调用方显式传凭据，不自动查找其他项目环境文件。
- 精确统计与原文证据分开；missing/null、对象关系、来源范围和保护条件不能为压缩率牺牲。未知语义保守保留或返回澄清/不支持状态。
