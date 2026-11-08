<!-- 流程与命令见 CONTRIBUTING.md；证据类别见工程交付基线。PR 使用中文，命令、路径和代码标识符保留原文。 -->

## 问题

## 方案

## 实际检查

<!-- 列出实际运行的命令与结果；标明证据类别（static_check / snapshot / simulation / runtime / inference）。 -->

- [ ] `python tools/ci/run_check.py encoding`
- [ ] `python tools/ci/run_check.py lint .` 与 `format --check .`
- [ ] `python tools/ci/run_check.py types`
- [ ] `python tools/ci/run_check.py baseline`
- [ ] 改动域测试，或冻结候选的 `full-acceptance --quiet`
- [ ] 清理可再生缓存后 `python tools/ci/run_check.py hygiene`

## 跳过或失败项

<!-- 未运行的检查、失败项及原因；环境限制如实记录，不放宽门禁。 -->

## 生成物与证据

- [ ] 未手改生成物、指纹、统计或 manifest（如有生成变化，说明重生成命令）
- [ ] 未改锁文件（如有，说明原因与 `v3 lock --write` 复核）
- [ ] 未刷新历史证据身份

## 验收边界

<!-- 本 PR 证明了什么、不证明什么；长期行为、平衡、游戏内性能与玩家体验由用户验收。 -->
