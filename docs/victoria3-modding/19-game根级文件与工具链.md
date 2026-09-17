# 19 · game 根级文件、工具链与 DLC 结构

> 本文补齐此前未覆盖的区域：`game\` 根目录的 13 个配置文件、`game\tools\` 工具链、
> `game\dlc\` 结构、`platform_specific_game_data\` 日志配置。
> 全部 **【实测】**。

## 1. `game\` 根目录 13 个文件

| 文件 | 字节 | 作用 |
|---|---|---|
| `checksum_manifest.txt` | 279 | **定义联机校验和的范围**（见 §2） |
| `paths.settings` | 2,011 | **路径间接层**：给各类资源目录起别名（见 §3） |
| `paths_checksummed.settings` | 78 | 参与校验的路径（见 §3.2） |
| `compound_settings.txt` | 3,804 | 复合设置 |
| `settings_layout.txt` | 3,290 | 设置界面布局 |
| `save_game_analysis.txt` | 91 | 存档分析器的字段显示规则 |
| `script.py` | 2,043 | **DLC 转换脚本**（见 §6.2） |
| `credits.txt` | 31,479 | 制作人员名单 |
| `game_flow_graphs.anchor` | 15 | 内容为 `../source/logic`（指向源码逻辑图，**对 mod 无影响**） |
| `icon_transfer_all.tga` | 6,149 | 图标导入用的色板 |
| `rotate_glow_mask3.tga` | 235,369 | 旋转辉光遮罩 |
| `node_editor_node_input.tga` | 124 | 节点编辑器素材 |
| `node_editor_title_background.tga` | 84 | 节点编辑器素材 |

## 2. `checksum_manifest.txt` —— 联机校验范围（**重要**）

**【实测】** 全文 22 行，内容极简但意义重大：

```text
directory
name = common
sub_directories = yes

directory
name = events
sub_directories = yes

directory
name = map_data
sub_directories = yes

directory
name = gui
sub_directories = yes

directory
name = localization
sub_directories = yes

file
name = paths_checksummed.settings
```

**即：参与校验和的只有 5 个目录（含全部子目录）+ 1 个文件：**

| 校验对象 |
|---|
| `common/`（含全部子目录） |
| `events/`（含全部子目录） |
| `map_data/`（含全部子目录） |
| `gui/`（含全部子目录） |
| `localization/`（含全部子目录） |
| `paths_checksummed.settings` |

### 2.1 这条信息的实战价值

| 结论 | 说明 |
|---|---|
| **改这 5 个目录 → 影响校验和** | 联机时所有玩家必须有一致的 mod 集合 |
| **改 `gfx/`、`sound/`、`music/`、`fonts/` 不影响校验和** | 纯视觉/音频 mod 不会导致联机失配 |
| `localization/` 也在校验范围内 | 所以**汉化 mod 会影响校验和**（与 mod 的 `mp_synced` 设置相关） |
| 与 DLC 的 `mp_synced` 字段呼应 | `dlc001.dlc` 中有 `mp_synced = no`（见 §6.1） |

> **对应 mod 元数据**：`metadata.json` 里的 `game_custom_data.multiplayer_synchronized` 就是这个机制的用户侧声明。

## 3. `paths.settings` —— 路径间接层（**改 gfx/地图必读**）

**【实测】** 这个文件把「逻辑名」映射到「实际目录」，共 **39 条映射**，分 4 组。

### 3.1 地图与图形

| 逻辑名 | 实际路径 |
|---|---|
| `terrain` | `gfx/map/terrain` |
| `air_graphics` | `gfx/map/air_graphics` |
| `borders` | `gfx/map/borders` |
| `front_graphics` | `gfx/map/borders/front_graphics` |
| `gradient_border_settings` | `gfx/map/gradient_border_settings` |
| `map_modes` | `gfx/map/map_modes` |
| `map_objects` | `gfx/map/map_object_data` |
| `map_masks` | `gfx/map/masks` |
| `post_effects` | `gfx/map/post_effects` |
| `gfx_environment_file` | `gfx/map/environment/environment.txt` |
| `flatmap_textures` / `colormap_textures` | `gfx/map/textures` |
| `mappainting_textures` | `gfx/map/map_painting` |
| `city_data` | `gfx/map/city_data/city_types` |
| `city_vfx` | `gfx/map/city_data/city_vfx` |
| `route_graphics` | `gfx/map/spline_network/route_graphics` |
| `military_route_graphics` | `gfx/map/spline_network/military_route_graphics` |
| `building_config` | `gfx/map/building_config` |
| `game_road_data` | `gfx/map/spline_network/game_road_data.txt` |
| `line_assets_path` | `gfx/lines` |
| `spline_network_file` | `gfx/map/spline_network/spline_network.splnet` |
| `spline_types` / `spline_styles` | `gfx/map/spline_network/spline_types` / `spline_styles` |
| `terrain_effects_settings_file` | `gfx/map/dynamic_masks/terrain_effects.settings` |

### 3.2 内容源与编辑器

| 逻辑名 | 实际路径 |
|---|---|
| `map_object_masks` | `content_source/map_objects/masks` |
| `map_object_generators` | `content_source/map_objects/generators` |
| `map_editor_status_file` | `tools/mapeditor/map_editor_status.txt` |
| `nudger_settings` | `tools/mapeditor/nudger_settings.json` |
| `map_masks_painter_tool` | `tools/mapeditor/mask_painter` |

### 3.3 界面与音频

| 逻辑名 | 实际路径 |
|---|---|
| `achievement_icons` | `gfx/interface/icons/achievements` |
| `loadingscreens` | `gfx/loadingscreens` |
| `startscreen_file` | `gfx/frontend/interface/frontend/startscreen.dds` |
| `media_aliases` | `gfx/media_aliases` |
| `sound_banks` | `sound/banks` |
| `sound_ambience` | `sound/map/ambience` |
| `audio_settings_file` | `sound/audio_settings.txt` |
| `music_player_categories` | `music/music_player_categories` |
| `gfx_skins_path` | `gfx/skins` |
| `gfx_skins_base_path` | `gfx/interface` |

### 3.4 `paths_checksummed.settings`（全文）

**【实测】** 只有 3 行：

```text
map_data = 						"map_data"

highlight_gui =					"gui/tutorial_highlight.gui"
```

> 这两个路径**额外**参与校验和（与 §2 的目录清单配合）。

## 4. `game\tools\` —— 开发工具链

**【实测】** 目录结构：

| 路径 | 大小 | 作用 |
|---|---|---|
| `pdxexporter.settings` | 2,159 | 3D 导出器配置 |
| `pdx_mesh_importer_shader_collection.json` | 19 | 网格导入着色器集合 |
| `texture_converter_settings.json` | 23,193 | **贴图转换配置**（.png → .dds 的规则） |
| `mapeditor\layer_settings.json` | 61 | 地图编辑器图层设置 |
| `mapeditor\map_editor_status.txt` | **1,810,300** | 地图编辑器状态（1.8 MB） |
| `mapeditor\nudger_settings.json` | 247,883 | 地图微调器设置 |
| `mapeditor\mask_painter\` | — | 遮罩绘制工具 |
| `scripted_tests\` | — | **脚本化测试框架**（见 §4.1） |

### 4.1 `scripted_tests\` —— 自动化测试框架（**mod 开发强烈推荐**）

**【官方】** `scripted_tests\scripted_tests.md` 完整说明：

**启用方式（三种）**

| 方式 | 命令 |
|---|---|
| 命令行 | `scripted_tests` |
| 命令行（附加） | `no_save_after_failed_test`（默认会存盘）/ `save_before_failed_test`（很慢，不推荐） |
| 游戏内控制台 | `scripted_tests` / `scripted_tests before` / `scripted_tests none`（再次执行则关闭） |

**结构（官方给出的模板）**

```pdx
last_date = "1879.11.21" # 该文件的测试跑到这个日期为止

tests = {
	testcase_1 = { # 键名即测试名

		acceptable_fail_rate = 0.0 # 仅作为元数据输出，不影响行为。省略默认为 0.0

		run_count = -1 # 运行次数。只计入 pass/fail 的轮次。小于 0 表示无限运行
		# 每次运行会覆盖上次结果。run_count = 3 且结果 PASS, PASS, FAIL → 计为 FAIL
		# 省略默认为 1

		success = { # 每天检查一次的触发器，通过则测试标记为通过
			...
		}
		fail = { # 每天检查一次的触发器，通过则测试标记为失败
			...
		}
	}
}
```

**判定规则（官方原文要点）**

- `success` 优先：同一天两者都成立时，`fail` 被忽略，测试通过
- 到 `last_date` 仍未触发任何一个 → 计为 **skipped**（可用于跳过不适用的测试）

**输出**

- 结果文本文件 → 文档目录（`Documents\Paradox Interactive\Victoria 3\`）
- XML 文件 → 游戏的 `binaries\` 目录

**【实测】** 现成的测试文件：`germany.txt`(218 B)、`ip3.txt`(1,874 B)、`italy.txt`(164 B)、`springtime.txt`(215 B)、`test.txt`(565 B)。

> **对 mod 开发的价值**：可以写 mod 自己的测试套件，用 `-debug_mode` + `scripted_tests` 跑长期模拟，
> 自动验证「AI 是否按预期发展」「某机制是否触发」—— 比手动开局跑一百年可靠得多。

## 5. `platform_specific_game_data\` —— 日志配置

**【实测】** 两个文件：`log_settings_live.json`(503 行)、`default_log_settings_live.json`。

关键结构：`loggers[].category` → `sinks[].file_name`，即**日志类别决定输出文件名**。

| category | 输出文件 | 默认等级 |
|---|---|---|
| `text_warnings` | `warning` + `error` | warning / error |
| `kernel_release` | `system` | debug |
| `cw` | `debug` + `error` | debug / error |
| `cw_audio` | `debug` + `error` + 控制台 | — |
| `cw_ecs` | `ecs` + `error` | — |
| `cw_fs` | `debug` + `error` | — |
| `cw_graphics` | `graphics` + `error` | — |
| `cw_gui` | `gui` + `error` | — |
| `cw_input` | `error` | — |
| `cw_message` | `message` + `error` | — |
| `cw_network` | `multiplayer` + `error` | — |
| `cw_test` | `error` + 控制台 + MSVC 调试输出 | — |
| **`ai`** | **`ai`** + `error` | debug |
| `automation_stats` | `custom_automated_stats` + `error` | info |
| `code_rev` | `code_revisions` + `error` | info |
| **`db_conflicts`** | **`database_conflicts`** + `error` | error |
| `dedicated_server` | `dedicated_server` + `error` | info |
| `game` | `game` + `error` | info |
| `memory` | `memory` + `error` | debug |
| `mp` | `multiplayer` + `error` | trace |
| `setup` | `setup` + `error` | info |
| `graphics` | `graphics` + `error` | debug |
| `tests` | （无 sink） | — |
| `Checksum` | `checksum`（`clear_file: true`） | debug |
| `Game State Validity` | （无 sink） | — |
| `ui_animation_stats` | `ui_animation_stats`（`clear_file: true`） | debug |

**通用参数**：轮转文件保留 5 份（`max_rotating_files: 5`），单个最大 512 KB（`max_rotating_file_size: 524288`）。

> 这解释了 `logs\` 目录里 `<名>.log` + `<名>.1.log` … `<名>.5.log` 的命名由来。

## 6. `game\dlc\` —— DLC 结构

**【实测】** **17 个** DLC 目录（编号 `dlc001`–`dlc018`，其中**缺 `dlc005`**）。样本 `dlc001_preorder`：

```text
dlc001_preorder\
├─ dlc001.dlc                     241 B   ← DLC 描述符
├─ dlc001_preorder.dlc.json       314 B   ← 同上，JSON 形式
├─ thumbnail.png                  72,551 B
├─ music\
│   ├─ preorder_music.txt         4,289 B
│   └─ music_player_categories\
├─ sound\
│   └─ banks\
└─ Victoria 2 Remastered Soundtrack\    ← 实际音频
    ├─ Flac\
    └─ Mp3\
```

### 6.1 `.dlc` 描述符格式（**全文 8 行**）

```pdx
name = "Victoria 2 Remastered Soundtrack"
path = "dlc/dlc001_preorder"
steam_id = "2071470"
pops_id = "dlc001_preorder"
mp_synced = no
affects_save_compatibility = no
localizable_name = "dlc001"
checksum = "3a59f318633b40ff609df0719da2b2fc"
```

| 字段 | 说明 |
|---|---|
| `name` | DLC 显示名 |
| `path` | DLC 内容目录（相对 `game\`） |
| `steam_id` | Steam 上的 App ID |
| `pops_id` | Paradox 账号系统的 ID |
| **`mp_synced`** | **是否参与联机同步**（与 §2 的校验和机制相关） |
| `affects_save_compatibility` | 是否影响存档兼容性 |
| `localizable_name` | 本地化键（与 `dlc_metadata\` 对应，见 `01-环境与版本.md` §4） |
| `checksum` | DLC 内容校验和 |

### 6.2 `script.py` —— DLC 转换脚本

**【实测】** 游戏根目录里有一个 Python 3 脚本，作用是把 `.dlc` 文件转成 `.dlc.json`：

- 只在**当前目录路径中含有 `game` 目录名**时运行，否则报错退出
- 递归查找所有 `*.dlc`（排除当前目录本身）
- 把 PDX 键值格式转成 JSON，并把 `"yes"`/`"no"`/纯数字转成布尔/数字
- 生成 `文件名.dlc.json` 后**删除原 `.dlc` 文件**

> **这是 Paradox 内部开发工具**，用于把旧格式迁移到新格式。举例：`dlc001_preorder` 里同时存在
> `dlc001.dlc` 与 `dlc001_preorder.dlc.json`，说明迁移未完全统一。
> **mod 开发中一般用不到**，但说明了 `.dlc` 与 `.dlc.json` 两种格式并存。

## 7. `save_game_analysis.txt`

**【实测】** 全文 4 行：

```pdx
"database" = {
	note="Hiding these, as every database has a database block."
	hidden=yes
}
```

作用：控制存档分析器里 `database` 块的显示（隐藏，因为每个数据库都自带该块）。

## 8. 对 mod 开发的要点总结

```text
① 联机兼容
   改 common/ events/ map_data/ gui/ localization/ → 影响校验和
   改 gfx/ sound/ music/ fonts/ → 不影响
   → 纯视觉 mod 天然联机友好

② 改地图/图形前先看 paths.settings
   39 条路径映射决定了资源实际读哪里

③ 用 scripted_tests 做自动化验证
   命令：-debug_mode + scripted_tests
   可写 mod 自己的测试套件，自动跑长期模拟

④ 日志按 category 分流
   调 AI 看 ai.log；查覆盖冲突看 database_conflicts.log

⑤ DLC 用 .dlc / .dlc.json 描述符
   mp_synced 与 affects_save_compatibility 决定联机与存档行为
```

## 9. 未确认项

| 项 | 状态 |
|---|---|
| `compound_settings.txt`（3.8 KB）的具体字段 | **未读** |
| `settings_layout.txt`（3.3 KB）的结构 | **未读** |
| `texture_converter_settings.json` 的转换规则 | **未读** |
| `map_editor_status.txt`（1.8 MB）的用途 | **未读** |
| mod 能否提供 `content_source\`、`tools\` 目录 | **未确认**（23 个 mod 均未使用） |
| `.dlc` 与 `.dlc.json` 同时存在时哪个生效 | **未确认** |
