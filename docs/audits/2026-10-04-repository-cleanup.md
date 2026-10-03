# 2026-10-04 仓库残留清理记录

本轮只清理可重建缓存、无引用的一次性产物和未被文档引用的截图；源码、测试、mod 交付物、精简快照、官方文档清单、探针和被报告引用的证据均保留。

- 删除文件：520 个，原始字节合计 82,217,920 B。
- 删除内容：Python/pytest/mypy/Ruff/Hypothesis/coverage 缓存、一次性修复脚本与日志、完整的 1.14.3 本地快照、无文档引用的 auto/t5 截图。
- 归档文档：测试套件重构前审计、2026-10-02 工程收口记录、已完成的仓库结构重组计划。三处原路径保留兼容指针。
- 未删除：`.venv/`、`research/official-docs/`、`tools/out/mem/`、`tools/out/repository-audit/`、`tools/out/evidence/`、`tools/out/perf/` 和被报告点名的实机帧。

删除清单（含 SHA-256）保存在被忽略的 `tools/out/repository-audit/cleanup-20261004.json`，供本机审计和后续恢复策略核对。
