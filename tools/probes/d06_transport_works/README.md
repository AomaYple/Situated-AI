# D06 州级交通工程候选

独立本地候选 `0.1.0-d06.rc2` 面向 Victoria 3 1.15.2、Steam 公开构建 `26763837`。中等权重组与零权重组使用同一法令和资格。每个隔离目录单独加载一组。 [同档实机步骤](PLAYTEST.md) · [实机结果](PLAYTEST-RESULT.md)

## 编译输入

| 源 | 共同编译器接入 |
| --- | --- |
| `payload/common/decrees/zz_sitai_transport_works.txt` | 新增 `sitai_decree_transport_works`，绑定锁定原版的 `decree_road_maintenance`、`centralization`、`state_infrastructure_balance` 和图标路径。 |
| `payload/common/script_values/sitai_d06_transport_works_values.txt` | 新增仅给本法令使用的州级回收阈值，读取原版 `state_infrastructure_mult`。 |
| `payload/localization/` | 11 种原版语言中的两个自有键。说明有效增量取决于当地修饰。 |
| `payload/.metadata/metadata.json` | 独立测试加载身份。共同编译器由组装器提供包级元数据。 |

游戏文本由仓库的字节转换生成 UTF-8 BOM 和 LF。候选 ZIP 含 14 个成员。验证工具、收据、受控样件和存档位于包外。

## 施行与回收

有中央集权科技、有效基础设施为正、容量减用量 ≤ −5 且没有原版道路维护的州可施行。基础权威为 60，原版按国家地位计算实际占用。脚本添加 `state_infrastructure_add = 5`，玩家可在原版界面施行或撤销。中等权重为 75，余量 ≤ −15 时为 100。原版道路在进入常规短缺奖励时为 125。候选实际排序和权威分配待回读。

在位回收阈值为 `3 + 5 × max(1, 1 + M)`，`M` 是州的原版基础设施乘法修饰。达到阈值后，或出现原版道路维护、有效容量失效时，由原版周度州条件回收。门只读取当前州，无额外周任务、计时器、保存标记或强制移除兄弟法令。基于实测和锁定脚本选择的近似模型把法令的直接有效增量记作 `G = 5 × max(0, 1 + M)`。预留 `5 × max(1, 1 + M)` 至少为 5，将乘数非正时的小幅多留用于保守回收。

- 诊断的固定 `+3` 在入场余量恰好 `−5` 且 `G ≥ 8` 时可触发自撤销与再次施行。候选在直接有效增量受预留覆盖时，回收后的外部余量至少为 `+3`，和重新入场的 `−5` 相差 8。只要真实增量比预留多的小于 8，固定外部条件下也不会立即重新合资格。
- 若外部条件改善使在位有效余量过线，候选可回收权威。非正乘数下会比精确扣除稍晚，外部余量约 `+3` 到 `+8` 时可能阶段性保留。若以后独立缺口重新落到 `−5`，原版可重新施行。
- 原版州具名值以有效容量减用量。原版脚本使用州作用域修饰查询，目标修饰由原版定义为百分比型。此前 Bahia 存档中的 `+5 → 有效差 +4.5` 与上述模型一致，当时两臂还相差两个游戏刻。当前证据尚未校准州读点的修饰聚合、容量刷新相位或高乘数下的实际增益。回收阈值、退款、AI 再采纳及州易主须实机签收。 原版值见 `C:/Program Files (x86)/Steam/steamapps/common/Victoria 3/game/common/script_values/objective_values.txt:3`，州修饰读取见 `C:/Program Files (x86)/Steam/steamapps/common/Victoria 3/game/common/script_values/building_values.txt:42`，州修饰类型见 `C:/Program Files (x86)/Steam/steamapps/common/Victoria 3/game/common/modifier_type_definitions/00_modifier_types.txt:2116`。

动态门只在原版法令求值时读取州。曾考虑独立定时冷却，不过需要写入逐州标记和处理州易主、手动撤销与旧存档恢复，也无法直接判断恢复后的容量。本候选优先验证州作用域读取和原版周度失效。若引擎读点漏掉参与该容量计算的乘数来源，需以同档施行和移除对照重估边界，不能据离线模型给更广的资格承诺。

## 离线复核

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
$runner = 'tools/probes/d06_transport_works/candidate.py'
$out = 'tools/out/sa-original-projection-design/d06-0.1.0-d06.rc2'
python -B -X utf8 $runner build $out
python -B -X utf8 $runner verify $out
```

每个归档读回验证成员字节、自己拥有的脚本结构、州门和两档分值、11 种语言键，以及 1274 条合成观测。组间唯一玩法差异为 AI 权重块。固定诊断和首个候选的产物、日志与证据仍可在 `tools/out/sa-original-projection-design/` 下复查。
