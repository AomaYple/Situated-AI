# Situated AI

Victoria 3 AI Mod 与 Python 开发工具链。项目目标是让 AI 国家依据可读取的政治、人口、财政、经济、市场、
贸易、外交、宗属、军事、战争、殖民、地理、身份和世界状态，在原版执行系统中重新评估可行路线。

当前已生成 `Situated AI 1.0.0` 标准 Mod，工程回归结果见[交付记录](docs/design/exec/1.0.0-工程交付-结果.md)：
源数据使用锁定 Victoria 3 `1.14.5` 的原版字段和作用域，
生成器负责规则、语言、manifest、路径和编码门禁，标准 ZIP 不含探针或历史实验。长期 AI 行为、平衡、性能、
玩家体验和创意工坊发布由用户安装后验收；工程通过不能代替这些结论。

## 先读什么

1. [AGENTS.md](AGENTS.md)：代理接手顺序和修改边界。
2. [CONTRIBUTING.md](CONTRIBUTING.md)：生成、检查、分支、提交、PR 和发布。
3. [工程原则](docs/principles/工程原则.md)与[Mod 开发原则](docs/principles/Mod开发原则.md)。
4. [1.0.0 交付计划](docs/design/exec/mod重设计-实施计划.md)与[当前工作清单](docs/design/当前工作清单.md)。

## 目录

```text
mod/                    生产源、策略生成物与本地化
src/pdx/                Python 解析、全量分析、快照、Mod 生成和 ZIP 交付
tests/                  单元、离线合同、生成和跨平台工具测试
tools/ci/               工程质量门；tools/benchmarks/ 为串行 Python 基准
tools/out/              可再生分析、报告和本机证据（忽略）
docs/                   当前规则、设计、计划、结果、审计和知识库
research/               原版资料清单；官方原文镜像不入库
dist/                   可再生发布 ZIP（忽略）
```

## 快速开始

Windows：

```text
.venv\Scripts\python.exe -X utf8 -m pip install -e ".[dev]"
.venv\Scripts\python.exe -X utf8 -m pdx.cli modgen --check
.venv\Scripts\python.exe -X utf8 -m pdx.cli modguard --offline
.venv\Scripts\python.exe -X utf8 -m pdx.cli package --output dist/situated-ai-1.0.0.zip
```

macOS/Linux 将解释器替换为 `.venv/bin/python`。没有游戏时仍可运行离线检查；有游戏时可用
`V3_ROOT`、`V3_USERDIR` 指定路径，工具不会写入仓库外的用户状态，除非命令明确要求部署。

## 标准包

`dist/situated-ai-1.0.0.zip` 是唯一生产交付包。解压至独立 `Victoria 3/mod/Situated AI` 目录，在启动器
单独的 playset 中启用。包内包含：

- `.metadata/metadata.json`：标准启动器名称、稳定 ID、版本和游戏版本；
- `DISTRIBUTION-MANIFEST.json`：模块、语言、源指纹及每个文件的 SHA-256；
- 生成的 `common/`、11 种本体语言的本地化和安装说明。

仓库源和文档统一 UTF-8 无 BOM、LF；只有游戏交付文件在 ZIP 边界添加 BOM。关闭或卸载不会撤回已经发生的
世界变化，用户应保留原存档和原 playset。其它 Mod 若覆盖同一原版文件，可能产生正常的兼容冲突。

## 验证边界

工程检查使用仓库 `.venv`：

```text
.venv\Scripts\python.exe -X utf8 tools/ci/run_check.py baseline
.venv\Scripts\python.exe -X utf8 tools/ci/run_check.py test-offline
```

完整矩阵、性能口径、删除和 Git 流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。静态分析和快照只能证明文件、
字段、生成和引用契约；不能证明引擎运行期语义、AI 行为质量或长期性能。历史实测保留在 `docs/audits/`、
`docs/reports/` 和 `docs/design/exec/` 的日期化文件中。

## 许可证

[Apache-2.0](LICENSE)
