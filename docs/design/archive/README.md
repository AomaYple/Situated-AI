# 历史计划与设计归档

本目录登记已退出执行路线的计划及冻结参考。归档不关闭任何未完成阶段，不是当前计划或发布依据。
当前状态入口为[架构主计划](../架构主计划.md)、[架构子计划](../架构子计划.md)及[当前工作清单](../当前工作清单.md)。

## 3.4.0 首版开发与发布

3.4.0 完成主计划的首次正式交付，工程、静态语义及单人实测各按固定包收据签署。代表性警务闭环覆盖同一 AI 国家的原版立法、机构成立和后续投资目标。防御条约从接受到后续重评的自然反馈、联机与长期玩法仍待取证。 [固定候选验收](../exec/架构主计划实施-结果.md#固定候选-340-验收) · [3.4.0 交付结果](../exec/3.4.0-交付结果.md)

发布时的首版目标、五步实施顺序和首片差分取证要求，随产品合并提交 `e14d5bd1085e5727274f74c5f82876608df148f0` 的 `docs/design/架构主计划.md` 查阅。该文件为 57,359 字节，SHA-256 为 `412d3d24ec3f3f73f6ac0d097bfcbb2379d6c3145dd73702830a325a3be92973`。 [首次交付的阶段出口](https://github.com/AomaYple/Situated-AI/blob/e14d5bd1085e5727274f74c5f82876608df148f0/docs/design/%E6%9E%B6%E6%9E%84%E4%B8%BB%E8%AE%A1%E5%88%92.md#阶段出口) · [首次交付的实施顺序](https://github.com/AomaYple/Situated-AI/blob/e14d5bd1085e5727274f74c5f82876608df148f0/docs/design/%E6%9E%B6%E6%9E%84%E4%B8%BB%E8%AE%A1%E5%88%92.md#阶段内实施)

后续领域与方面使用 3.4.0 作为初始生产基线，并按各自证据签署。共用架构与验收约束见现行主计划。 [现行验收约束](../架构主计划.md#模型引擎与玩法验收) · [架构子计划](../架构子计划.md#领域与方面的阶段边界)

## X1 广度深度拓展计划

[X1主计划](X1/架构主计划.md)与[X1子计划](X1/架构子计划.md)的 X0–X6 和十一项小计划已完成，随3.2.0交付。
可读正文仅增加归档状态并修正相对导航，战略内容不重写；原始字节来自提交 `5a3c627867c1e5b3097d50e34418a7559615f1da`
的 `docs/design/架构主计划.md` 与 `docs/design/架构子计划.md`，逐文件长度、SHA-256、受控gzip路径和可读正文见
[X1 manifest](X1-manifest.json)。两份原件可在干净克隆中独立解压核验，不依赖短期分支的Git可达性。
实际生产范围与检查见[拓展结果](../exec/广度深度拓展-结果.md)，版本、正式Release与部署身份见[3.2.0交付结果](../exec/3.2.0-交付结果.md)。
当前开发状态见[工作清单](../当前工作清单.md)。

## 冻结版本

所有原始字节固定在提交 `c91569521ab4aad9cd38db0b242836cf8bda64ab`，逐文件身份、字节数和 SHA-256 见 [manifest](manifest.json)。
原始内容以受控 gzip 对象保存在 `objects/<commit>/<sha256>.gz`。解压后必须逐字节匹配 manifest 中的长度及 SHA-256；
提交、原路径及原始哈希仍是冻结身份，不重新签发历史完成证据。对象不是当前计划，当前同路径文件可继续演进。
干净克隆或没有 `.git` 的源码副本可直接读取，不依赖旧对象可达性、归档标签或外部网络。
验证器只读本地受控对象，缺失、篡改、压缩损坏、尾随数据或解压超限均硬失败，不回退到 Git。

旧行动深化主题分支的最后状态 `f77a2b5` 只供迁移追溯，不成为第二条执行主线。
已清理公开归档标签；原引用和已验证 Git bundle 保存在 `tools/out/breadth-20261104/`，不将历史未合并内容重新引入生产。

- [31.4 旧实施计划](../exec/mod重设计-实施计划.md)：D0–D14 未完成，停止作为执行路线。原路径保留供历史收据引用。
- 架构 A1.0 主/子草案：已冻结在上述提交，随后由战略主/子计划替换；不继承其未论证的公式、常量与文件布局。
- [旧处境设计](../03-处境决策设计.md)、[旧行动覆盖](../04-行动覆盖与验收.md)、[旧行动深化](../05-行动层深化设计.md)：迁移参考，不能证明新能力。
- [执行文档索引](../exec/README.md)：保留历史交付、检查与失败的原始事实。

## 原始证据与清理边界

历史结果按原字节和相对目录在其冻结提交查阅。旧 A2 收口工具及其输入随当时提交保存。
`tools/out/` 与 `.superpowers/` 中被结果页引用的原始材料不按缓存整树删除。
D0 原来登记的 `tools/out/situated-depth/d0-baseline/` 本次核对已不存在；不能声称已恢复或用新输出冒充。
`.superpowers/sdd/mod重设计-实施计划/` 中的现有证据继续保留。

2026-10-13 的 G1 重开扫描检查了 `tools/out/decisions` 与 `tools/out/recovery` 共 155 份报告，结论为 `NO_NEW_REOPENING_INPUT`。当时的停止条件和重开条件见[原始扫描报告](https://github.com/AomaYple/Situated-AI/blob/b3c3356e61b7c080038f7d6a61b84d69aedc58d3/tools/out/evidence/v0.1-g1-20261013/g1-reopen-scan-20261013.json)。
当前离线校验使用 `tools/out/snapshots/release-1.15.2.compact.json`。旧版精简快照按原路径从[冻结提交的快照目录](https://github.com/AomaYple/Situated-AI/tree/b3c3356e61b7c080038f7d6a61b84d69aedc58d3/tools/out/snapshots)追溯。

全仓源目录卫生检查结果写入忽略的 `tools/out/architecture-reset/`；零缓存违规只证明运行态整洁，
不代表旧候选的适配语义失败、法律证据接口缺口或完整回归内存终止已解决。

## A2 架构实施计划

A2/S0–S6 已于 2026-11-04 完成其静态功能、工程及交付出口，现停止作为后续扩展执行路线。
原始计划、工作清单及阶段结果固定在提交 `97c606cfb3b4fb4321166e8399578f5cdb7b6796`；逐文件身份见 [A2 manifest](A2-manifest.json)。
同样从 `objects/97c606cfb3b4fb4321166e8399578f5cdb7b6796/<sha256>.gz` 读取精确原始字节；
旧完成结论只属于该快照，不能关闭新的广度深度目标。两份 manifest 保留原字节，12 份原件合计 5,667,643 字节，
受控 gzip 合计 1,325,884 字节；其中包含原 A2 收据，不改写其旧验证结果或签名身份。
保留原有目录关系的 [A2 阶段收据](https://github.com/AomaYple/Situated-AI/blob/b3c3356e61b7c080038f7d6a61b84d69aedc58d3/docs/design/exec/%E6%9E%B6%E6%9E%84%E9%98%B6%E6%AE%B5%E6%94%B6%E6%8D%AE.json)、[阶段结果](https://github.com/AomaYple/Situated-AI/blob/b3c3356e61b7c080038f7d6a61b84d69aedc58d3/docs/design/exec/%E6%9E%B6%E6%9E%84%E9%87%8D%E8%AE%BE%E8%AE%A1-%E7%BB%93%E6%9E%9C.md)和[取证文件](https://github.com/AomaYple/Situated-AI/tree/b3c3356e61b7c080038f7d6a61b84d69aedc58d3/research/situated/a2-evidence)可从冻结提交查阅。
