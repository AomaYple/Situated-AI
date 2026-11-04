# 创意工坊发布材料

本目录保存可直接粘贴到 Steam 创意工坊描述栏的 BBCode 正文。各语种统一使用目标、内容、兼容性和支持语言四部分，
面向玩家介绍实际功能、使用方式和兼容提醒。`v3 publish` 以这些正文为唯一来源，按需部署本地标准包、
更新既有 Steam 工坊条目并同步全部语言；也可继续手工粘贴正文。

正文不放工程检查、生成流程、包合同、内部术语、验收分工或要求玩家完成验证的说明；这些内容留在贡献指南、
工程基线和交付收据中。译文保持功能范围一致，不虚构效果或作未经证实的效果保证。

正文作为长期稳定的产品介绍，维护核心目标、持续设计方向、兼容边界和语言支持，不逐版列举具体规则、数值、
实现细节、阶段进度或新增修复。普通功能扩展与数值调整写入更新说明，不触发正文改写；只有产品目标、功能范围、
兼容边界、支持语言或项目链接发生实质变化，或发现事实与译文错误时，才同步修订受影响语种。

| 本体语言目录 | 描述正文 | Steam 语言 |
|---|---|---|
| simp_chinese | [简体中文](创意工坊描述.md) | schinese |
| english | [English](创意工坊描述-en.md) | english |
| french | [Français](创意工坊描述-fr.md) | french |
| german | [Deutsch](创意工坊描述-de.md) | german |
| japanese | [日本語](创意工坊描述-ja.md) | japanese |
| korean | [한국어](创意工坊描述-ko.md) | koreana |
| polish | [Polski](创意工坊描述-pl.md) | polish |
| braz_por | [Português do Brasil](创意工坊描述-pt-BR.md) | brazilian |
| russian | [Русский](创意工坊描述-ru.md) | russian |
| spanish | [Español](创意工坊描述-es.md) | spanish |
| turkish | [Türkçe](创意工坊描述-tr.md) | turkish |

游戏内本地化由生产生成器维护，工坊正文是独立发布材料。语言分母来自锁定原版 `localization/`，与
`pdx.localization_languages.DEFAULT_LANGUAGES` 一致。正文都附同一 GitHub 仓库链接。

## 一次性自动发布

先用仓库虚拟环境生成固定标准包，再预览。以下示例中的 `python` 在 Windows 替换为
`.venv\Scripts\python.exe -B -X utf8`，macOS/Linux 替换为 `.venv/bin/python -B -X utf8`：

```text
python -m pdx.cli package
python -m pdx.cli publish
python -m pdx.cli publish --execute --changenote "本次更新内容"
```

默认 ZIP 来自 `distribution.DEFAULT_PACKAGE_PATH`，可以用 `--archive <标准ZIP>` 指定；必须与当前生产源和锁定底本一致，
不会自动上传历史包或把工作目录散装文件上传。仅修改发布工具或正文时不需要增加 Mod 版本。
`publish` 默认只预检和预览，不写入游戏目录或工坊；`--execute` 表示执行已选的目标，命令内部不再交互询问。
每次创建独立的 `tools/out/publishing/run-*`，保存固定 ZIP、内容树、远端预检和 `receipt.json`。
可通过 `--run-dir <不存在的目录>` 指定证据位置，不要放进 Mod 源或安装目录。

| 目标 | 命令 | 实际执行范围 |
|---|---|---|
| 全流程 | `python -m pdx.cli publish --execute` | 本地部署 → 工坊内容和封面 → 有差异的全部语言正文 |
| 本地 | `python -m pdx.cli publish --target local --execute` | 只部署标准包，无需 Steam |
| 工坊内容 | `python -m pdx.cli publish --target workshop --execute` | 只更新内容和封面，不改正文、标题或可见性 |
| 正文 | `python -m pdx.cli publish --target descriptions --execute` | 只同步有差异的语言，无需 ZIP 或本机游戏底本检查 |

工坊上传目前明确支持 **Windows x64**，使用 Victoria 3 自带的 `binaries/steam_api64.dll`，
核对 SteamUGC016、SteamUser021 和 SteamUtils010；未知接口版本或平台硬失败，不猜测 ABI。
本地部署、正文校验和测试保持跨平台。需要 Steam 正在运行，登录账号拥有游戏且是工坊条目所有者；
不需要在配置文件中存密码或 API key。条目 ID 和语言映射仅由 [workshop.toml](workshop.toml) 维护，
不会自动创建新条目、改标题、可见性、标签、订阅或启动器播放集。

本地目标是 `V3_USERDIR` 或 `--userdir` 指定的游戏用户目录下 `mod/Situated AI`。
游戏和 Paradox 启动器须关闭；工具不代为结束它们。已有目录必须具有 `id = situated-ai` 的 metadata，
拒绝符号链接及 Windows 重解析点。先在同卷暂存并核对字节，再替换目标；旧树保留在用户目录下
`.situated-ai-backups/<运行身份>/Situated AI`，位于 Mod 扫描范围之外。失败时尽力恢复旧树，
恢复失败会点明原件备份位置。`content_load.json`、存档和其他 Mod 不改动；首次安装仍需在启动器登记并启用。

## 失败与重试

本地部署与 Steam 提交不是同一个事务。所有目标先预检，再串行写入；任一步失败立即停止并返回非零，
收据保留已经完成的步骤，不把部分成功写成全部完成。`succeeded` 表示该步骤通过其核验，`unchanged` 表示无需写入，
`failed` 表示已知失败，`uncertain` 或异常终止留下的 `in_progress` 表示需要重新核对外部状态。

每种语言使用独立更新句柄指定 Steam 语言，收到成功回调后禁用缓存读回全文比较；
仅归一换行与外围空白，不改正文。再次运行 `--target descriptions --execute` 会跳过已相同的语言。
内容上传以 Steam 成功回调为提交证据，**未下载订阅端文件逐字节核验**，收据明确记为
`content_verified = steam_callback`、`remote_bytes_verified = false`。Steam 法律协议待接受、权限错误和网络失败均不算完成。

Steam 提交后不能保证取消；超时或子进程中断可能发生在服务器接受更新之后。
先核对收据和工坊状态，再选择 `local`、`workshop` 或 `descriptions` 重试；内容重试会再次提交同一固定包，
更新说明应避免重复粘贴。工具不在失败后自动重发内容，也不宣称全局回滚。

发布使用游戏用户目录下 `.situated-ai-publish.lock` 排他锁，本地替换另有 `.situated-ai-deploy.lock`。
异常退出若留下锁，应先确认没有发布进程，再移除对应锁文件；不会自动抢锁或恢复常驻任务。
所有 Steam 调用在一次性子进程中执行，正常结束关闭接口；不修改主进程 App 环境，不留下后台轮询。

该工具不会触发 Git 推送、合并、tag、GitHub Release 或定时任务。工具检查、Steam 提交成功也不代表 Mod 长期行为、
平衡或玩家体验通过。协议依据：[Steam 工坊实现指南](https://partner.steamgames.com/doc/features/workshop/implementation)、
[ISteamUGC](https://partner.steamgames.com/doc/api/ISteamUGC)及[Steam 语言代码](https://partner.steamgames.com/doc/store/localization/languages)。
