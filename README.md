# Situated AI

Victoria 3 的 AI 相关 mod 开发项目。

> **当前状态**：项目处于**前期调研阶段** —— 仓库内目前只有 mod 开发知识库，
> **尚无任何 mod 代码**。本地 mod 目录（`Documents\Paradox Interactive\Victoria 3\mod\`）仍为空。

## 环境

| 项目 | 值 |
|---|---|
| 游戏 | Victoria 3 **1.14.2 (Ice Tea)** |
| Clausewitz | `caligula/release/1.14.x` |
| Steam App ID | `529340` |
| 平台 | Steam / Windows |

## 知识库

[`docs/victoria3-modding/`](docs/victoria3-modding/) —— **21 篇 / 约 1.4 MB**，
基于对本机游戏安装目录与用户数据目录的逐文件读取整理而成，而非网上二手资料。

### 入口

| 想了解 | 看这里 |
|---|---|
| 怎么做一个 mod（结构 / 加载 / 覆盖机制） | [`02-Mod结构与加载.md`](docs/victoria3-modding/02-Mod结构与加载.md) |
| 真实 mod 都改了什么 | [`12-真实mod解剖与改造面地图.md`](docs/victoria3-modding/12-真实mod解剖与改造面地图.md) |
| **AI 系统怎么改** | [`03-AI系统.md`](docs/victoria3-modding/03-AI系统.md) · [`09-AI-mod实战技法.md`](docs/victoria3-modding/09-AI-mod实战技法.md) |
| 某个目录里定义了什么 | [`13-common全量键名索引.md`](docs/victoria3-modding/13-common全量键名索引.md) |
| 游戏自带官方文档有哪些坑 | [`07-官方文档索引.md`](docs/victoria3-modding/07-官方文档索引.md) |

完整索引见 [`docs/victoria3-modding/README.md`](docs/victoria3-modding/README.md)。

### 覆盖范围

| 范围 | 覆盖 |
|---|---|
| `game\common\` 子目录 | 136 / 136 |
| 游戏自带官方 `.md` 文档 | 92 / 92 |
| 已订阅 Workshop mod（解剖） | 23 / 23 |
| `common\history\` 子目录 | 22 / 22 |

### 几个关键结论

- **引擎内置「数据功能前缀」**（`INJECT:` / `REPLACE:` 等 6 个）—— 可精确到**单个键**覆盖，
  官方 92 篇文档**零记载**，原版一处不用，但 23 个 mod 用了 2,700+ 次
- **联机校验和只覆盖 5 个目录**（`common/ events/ map_data/ gui/ localization/`）
- **不需要 `descriptor.mod`** —— 现代格式是 `.metadata\metadata.json`
- **调试模式**：启动参数加 `-debug_mode`，错误看 `logs\error.log`、
  覆盖冲突看 `logs\database_conflicts.log`、AI 看 `logs\ai.log`

## 工具

[`tools/`](tools/) —— 可复现知识库中全部统计数据的 PDX 脚本解析工具链（PowerShell）。

## 目录结构

```
Situated AI/
├─ docs/victoria3-modding/   21 篇 mod 开发知识库（约 1.4 MB）
├─ research/                 调研资料（含 92 篇官方 .md 的逐字镜像）
├─ tools/                    可复现全部统计的 PDX 提取脚本
├─ README.md  LICENSE  .gitignore
```

以下目录在 `.gitignore` 中排除，**仅存在于本机**：

| 目录 | 内容 | 排除原因 |
|---|---|---|
| `tools/out/` | 提取出的大型 JSON（约 3.3 MB） | 可由 `tools/dump_*.ps1` 重新生成 |
| `tools/frag/` | 渲染出的 Markdown 片段（165 KB） | 可由 `tools/make_frags.ps1` 重新生成 |
| `tools/docparts/` | 分块撰写的正文草稿（56 KB） | 内容已 100% 拼入 `docs/` 下成稿 |
| `.dsh/` | 本机 TLS 配置 | 机器相关 |

> `research/` **已纳入版本控制**。其中 `research/official-docs/` 是游戏自带官方 `.md`
> 的逐字镜像，属 Paradox 版权内容，公开分发前请自行评估。

## 开发约定

| 约定 | 说明 |
|---|---|
| **提交信息用中文** | 不加 `feat:` / `fix:` / `chore:` 等英文前缀，直接写中文标题；需要时在正文补充细节 |
| **信息分级标注** | 文档中的每条事实都标来源：**【实测】**（读自本机文件）/ **【官方】**（游戏自带文档原文）/ **【推断】**（由证据推导）/ **未确认** |
| **统计必须写口径** | 同一份数据按「顶层键」或「含嵌套块」会得出不同数字，引用时写明统计规则 |
| **官方文档需交叉验证** | 游戏自带 92 篇 `.md` 已知有多处字段名错误与遗漏，写 mod 前先对照实测 |

## 授权

[Apache-2.0](LICENSE)

---

文档中的语法片段引自游戏本体，仅作技术说明用途。
