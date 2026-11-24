# D06 同档实机检查

使用当前候选 `0.1.0-d06.rc2` 和 Victoria 3 `1.15.2`、Steam 构建 `26763837`。共同起点是法国作为唯一玩家的 `sa_shared.v3`，SHA-256 `9cded8a012578b4cf35bcb659c820d7b8b2c422809ee9278a9e9121eb48df34e`。共同种子为 `1137923771`。同一日可有多个刻，配对要求保存日期一致且两边均记录相同的 `counters.tick`。

| 冻结包组别 | SHA-256 |
| --- | --- |
| 零权重 `off` | `d425a25a34783c65acbd128ed6456a4a3677fd0334f347ac2dc349c2c77f019e` |
| 中等权重 `moderate` | `a4dc08196e952f515ffc47c830047cece0e8afc05721369c4a87600a4287d9b5` |

## 准备与读回

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
$d06 = 'tools/out/sa-original-projection-design'
$repo = 'tools/probes/d06_transport_works'
$steam = 'C:/Program Files (x86)/Steam/steamapps/common/Victoria 3'
$test = "$d06/d06-rc2-playtest"
python -B -X utf8 "$repo/candidate.py" verify "$d06/d06-0.1.0-d06.rc2"
python -B -X utf8 "$repo/playtest.py" prepare "$d06/d06-0.1.0-d06.rc2" "$d06/d06-runtime/player/save games/sa_shared.v3" $steam $test
```

`prepared.json` 记录游戏可执行文件与包的指纹、参数、挂载文件及各目录的配置。到 D06 的时段时，在 Steam 已登录并有对应 DLC 授权的会话中逐组独占启动。进入主菜单后加载 `sa_shared.v3` 并暂停。关闭后保全各组检查点和日志。重跑可换新的准备目录以保留原始日志。

```powershell
$profile = (Resolve-Path "$test/moderate").Path
$launch = [System.Diagnostics.ProcessStartInfo]::new()
$launch.FileName = Join-Path $steam 'binaries/victoria3.exe'
$launch.WorkingDirectory = Join-Path $steam 'binaries'
$launch.Arguments = "--userdir=`"$profile`" -debug_mode"
$launch.UseShellExecute = $false
$launch.EnvironmentVariables['SteamAppId'] = '529340'
$launch.EnvironmentVariables['SteamGameId'] = '529340'
[System.Diagnostics.Process]::Start($launch)
```

本地首次直接执行时，日志仅列出四个原版基础目录和候选 Mod。后续通过运行中 Steam 的应用身份启动，日志列出四个原版基础目录、18 个 DLC 目录与候选 Mod。每组以其实际挂载日志为准。游戏设置可选每月自动保存，在相同自动保存日期读取两边的 `counters.tick`。将滚动自动档复制到各组自己的 `save games` 并以日期命名，然后配对读取。

保存明文调试存档。下列命令中的文件名为运行时手动保存名称，文件应落在对应组的 `save games`。用 `opening` 单独核验未记录游戏刻的共同起点。人类分支应先推进到第一个可读游戏刻再制作施行前后的检查点。记录界面的权威报价、余额和增减，存档的 `spending_variables` 可能保留旧值。持有原版及本法令时分别记录实例 ID，删档或缺失记录不可代替墓碑或地图和权威的相互印证。

```powershell
python -B -X utf8 "$repo/playtest.py" opening "$test/off/save games/sa_shared.v3" "$test/moderate/save games/sa_shared.v3" --output "$test/opening.json"
python -B -X utf8 "$repo/playtest.py" inspect "$test/moderate/save games/T026.v3" --profile "$test/moderate" --output "$test/moderate-T026.json"
python -B -X utf8 "$repo/playtest.py" compare "$test/off/save games/T026.v3" "$test/moderate/save games/T026.v3" "$test/vanilla/save games/T026.v3" --output "$test/paired-T026.json"
```

读回核对 11 项实际玩法 DLC、原始种子及游戏线，列出里约热内卢、巴伊亚、国家控制、中央集权、容量、用量、权威缓存与法令墓碑。`inspect` 和 `compare` 校验每个存档的组路径、存档头 Mod 集合、启用配置和挂载文件字节。日志须恰好记录原版的四个基础目录、18 个 DLC 目录和该组指定的 Mod 目录。纯原版组的存档与实际挂载都须显示空 Mod 集合。保留原始日志，并在各组各开一次全 DLC 新局确认开局、月度推进、保存读回和原版道路。新局用 `inspect --fresh` 记录独立游戏线、种子和 DLC，附界面与日志收据。

两臂的存档头使用同一个候选显示名。组别依据原始保存目录、该组挂载日志和已安装脚本摘要判定。检查点留在生成它的目录。

## 原生操作与固定检查点

| 场景 | 操作 | 通过证据 |
| --- | --- | --- |
| 自然采用与权威机会 | `vanilla`、`off`、`moderate` 均保持法国玩家。从共同起点推进，在第 26、59、84、112、140 刻暂停保存。提前先读开局。如果各臂在目标日停于不同子时段，匹配具体游戏刻再纳入对照。 | 记录至少一个巴西权威机会的中央集权、原版道路、州缺口和权威。自然采用要求中等组在仍合资格时出现活动实例，零组同刻对应州无该实例。记录原版与两组的道路及其他法令变化。中等组无采用时如实登记为该窗口无观察，不用受控操作补作自然采用。 |
| 人类界面与手动撤销 | `player` 的共同起点由原版切换国家界面接管巴西。在里约记录起始容量、使用量及权威，从州右键施行。暂停存档后继续到容量刷新，再验证界面只剩一次撤销。撤下后保存，从新存档重载。 | 一个活动实例、一次权威占用、一次退款。刷新后有容量增量，撤下后恢复。一名玩家和原版道路等其他界面选项均能确认。 |
| 正常自然恢复 | 从已施行的 `player` 分支，用原版港口、铁路科技或基础设施生产方式改善实际容量。保留施行前后的原版动作和用量。跨过实测阈值后观察下一次周度检查，并至少追踪两周。仍有余量时保持关闭。以原版增加需求或减少外部容量重新制造缺口，再尝试施行。 | 自然改善是可观察的外部改变。旧实例死亡且实际退款。低于入场线后产生新实例而非复活旧实例。若窗口内自然改善未过线，记录未跨过，不推断结果。 |
| 原版道路重叠 | 由同一个 `player` 已施行档分支。一次在周检查前一天施行道路，另一次在周检查后一天施行道路。每次先保存并确认两个实例，逐日保存直到原版检查，再从纯原版道路在位的状态尝试施行原创。 | 原版道路可施行且保留，原创实例在实际周检时死亡且只返还原创花费。原版道路在位时无法再施行原创，保留各组实际重叠天数。 |

## 受控分支

`controlled-player` 使用零权重。`controlled-ai-off` 与 `controlled-ai-moderate` 使用 `compare --controlled` 做同一干预下的 AI 比较。两组载入同一未改存档并以法国控制，用同一暂停相位与顺序执行指令，然后正常推进。受控目录的附加 Mod 只定义五个静态修饰。原版权威与法令状态由原版结算。

在调试控制台执行相应单行，先保存基线，然后保存变化后的同刻和下一实际刷新。每个步骤仍检查宏观外部状态。移除与易主分支应从已冻结的施行后存档重载开始。

```text
effect s:STATE_RIO_DE_JANEIRO.region_state:BRZ = { add_modifier = { name = sitai_d06_playtest_high_multiplier } }
effect s:STATE_RIO_DE_JANEIRO.region_state:BRZ = { add_modifier = { name = sitai_d06_playtest_trim_capacity } }
effect s:STATE_RIO_DE_JANEIRO.region_state:BRZ = { add_modifier = { name = sitai_d06_playtest_recovery } }
effect s:STATE_RIO_DE_JANEIRO.region_state:BRZ = { remove_modifier = sitai_d06_playtest_recovery }
effect s:STATE_RIO_DE_JANEIRO.region_state:BRZ = { set_state_owner = c:URU }
effect c:BRZ = { add_modifier = { name = sitai_d06_playtest_authority_limit } }
effect c:BRZ = { add_modifier = { name = sitai_d06_playtest_authority_competition } }
effect c:BRZ = { remove_modifier = sitai_d06_playtest_authority_limit }
effect c:BRZ = { remove_modifier = sitai_d06_playtest_authority_competition }
```

| 场景 | 操作与验收 |
| --- | --- |
| 高乘数防抖 | 在独立玩家分支加高乘数。先刷新，只有首次施行前确实 ≤ −5 才测试。若高乘数组仍宽松，施加小幅容量微调，再按实际容量和用量重验。施行后的有效增量须 ≥ 8 且余量达到旧诊断线 +3，才算命中过往反例。保持同一控制量，观察至少三个周检，实例与权威占用保持唯一。必要时以人工撤下的配对分支测实际有效增量。 |
| 脚本阈值读回 | 仅在受控分支用控制台 `effect s:STATE_RIO_DE_JANEIRO.region_state:BRZ = { set_variable = { name = sitai_d06_playtest_threshold value = sitai_d06_transport_works_release_threshold } }`。在明文档搜索该变量并记录实际阈值。分别在普通与高乘数状态取样，并用同刻或最近刷新后的开关对照验证预留。只有观察到原版州读点在该乘数测试确实变化，以及跨过门的在位实例被周检回收，才签候选效果。 |
| 跨线回收与再次施行 | 在前一个高乘数分支施加恢复修饰。真实在位余量过线后记录失效和退款，保持恢复修饰继续两周，检查旧 ID 墓碑与无重申。随后撤销恢复修饰。待真实余量重新 ≤ −5 且仍合资格后从玩家界面重申。对 AI 两组可重复相同干预，记录自然首采和重新采纳，零组作为同期对照。 |
| 州易主 | 从巴西已施行存档把里约交给乌拉圭，保存转让前、转让后及周检后。比较旧拥有者实例是否终结、两国实际权威变化和界面。新 owner 已没有旧 owner 的权威占用，若新 owner 满足科技和权威，独立测试它能否重新施行。州实例编号若改变，用地区、所有者及旧实例墓碑追踪。 |
| 权威不足与竞争 | 独立分支施加 `authority_limit` 并读取实际玩家余额，要求低于原创法令当日报价再做负例。第二个分支用 `authority_competition`，校验至少有两项争用同一余额，分别记录原创、原版道路、其他法令的原生价格，以及选择一个后余量能否购买另一个。两项修饰分别测试，实际余额以 UI 核对。AI 两组用相同有限权威起点观察原生选项消耗和代替关系。 |
| 科技门和保存 | 优先以共同档内缺中央集权但其他入场条件成立的州及控制权切换验证。两档候选下均测试原版界面选择与保存重载。记录目标州、技术位、报价和候选实例。暂无同档合法样本时，科技阴性保持未覆盖。 |

这些控制指令使用锁定原版已有的作用域、修饰和州转让形式。固定修饰的实际净效果、控制台解析与周度相位须在当前候选实机核对。
