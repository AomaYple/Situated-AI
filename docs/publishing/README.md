# 创意工坊发布材料

本目录保存可直接粘贴到 Steam 创意工坊描述栏的 BBCode 正文。各语种统一使用目标、内容、兼容性和支持语言四部分，
面向玩家介绍实际功能、使用方式和兼容提醒。`v3 publish --channel workshop` 从这里读取各语言的正文，
用同一份正式 Mod 包上传内容和封面。完整参数、发布计划和收据见[贡献与维护规范](../../CONTRIBUTING.md#一键发布)。

正文不放工程检查、生成流程、包合同、内部术语、验收分工或要求玩家完成验证的说明；这些内容留在贡献指南、
工程基线和交付收据中。译文保持功能范围一致，不虚构效果或作未经证实的效果保证。

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

## Steamworks 辅助程序

在 Windows x64 上从 Valve 获取 Steamworks SDK 1.53a（`ISteamUGC` 接口版本 `016`）。[Steamworks SDK](https://partner.steamgames.com/doc/sdk)

打开 Visual Studio 的 x64 Developer PowerShell，从仓库根运行构建脚本，分别传入包含 `isteamugc.h` 的 SDK 目录
和 Victoria 3 安装根。脚本使用游戏 `binaries/` 中的 `steam_api64.lib` 和 Valve 签名的 `steam_api64.dll`。

```powershell
./tools/steam_workshop/build.ps1 -SdkIncludeDir '<Steamworks SDK 根目录>/public/steam' -GameRoot '<Victoria 3 安装根>'
```

默认输出为 `tools/out/steam-workshop-helper/situated-ai-steam-workshop.exe`，运行库保存在同一目录。
可用 `-OutputDir` 选择其他目录。运行 `v3 publish` 时用 `--workshop-helper` 指定辅助程序的绝对路径。

启动 Steam 客户端，以拥有该条目的账号登录。首次建条目和接受 Workshop 协议在 Steam 中完成。
发布前核对条目 ID、所有者 SteamID64、Victoria 3 App ID `529340` 和英文标题 `Situated AI`。
发布按表中的 11 种 Steam 语言分别更新描述，并回读文本及绑定 ZIP 和 manifest 的指纹标记。上传后的独立回读包含两项
字节检查。工具重新下载 Steam CDN 主预览，比对正式包封面的 SHA-256。工具优先读取 Steamworks 确认的当前订阅安装，
将其中的目录和文件逐项与正式包载荷比对，包括 manifest 和包内封面。

所有者未订阅条目且 Steamworks 没有返回当前订阅安装时，发布器可以通过 Steamworks 下载临时缓存。该路径需要支持缓存回读及续跑的
Python 发布器，以及支持 `download-cache` 和 `cached` 命令的辅助程序。运行辅助程序的 `version` 命令可确认
`protocol` 为 `2` 且 `download_cache` 为 `true`。只支持订阅读回的旧版协议 2 辅助程序仍可配合当前 Python 发布器
校验已有的当前订阅安装。

缓存下载须收到与 Victoria 3 App ID 和目标条目匹配的成功回调。工具在未订阅状态下逐项比对 Steamworks 返回的当前缓存目录，
并在比对后复核该目录及条目状态。收据的 `download_cache` 记录未订阅缓存回读，`subscription` 记录实际订阅安装回读。
订阅选择由操作者管理。
[Valve 的临时缓存下载接口](https://partner.steamgames.com/doc/api/ISteamUGC#DownloadItem)

继续已有发布时，使用收据绑定的发布源提交、同一组发布参数、原收据目录和已冻结的标准包。辅助程序路径属于发布身份，
需要更新时可把新版辅助程序构建到收据中原有的绝对路径。只实现了订阅读回的历史 Python 发布器仍需当前订阅安装。

Steam 可能清理临时缓存，操作者也可以主动取消订阅。对于已经验证的 Workshop 收据，只读预检复核线上描述、资产指纹和
预览字节。缺少当前订阅安装且符合未订阅缓存回读条件时，预检复用可验证的现有缓存；需要另行下载时显示
`cache_readback: refresh_required`。使用相同参数加上 `--apply` 续跑，发布器复核线上状态后重新下载缓存，
并复用已经验证的上传及描述步骤。执行阶段的字节回读失败时，Workshop 收据保留 `uploaded`，整轮发布记为 `partial`。
