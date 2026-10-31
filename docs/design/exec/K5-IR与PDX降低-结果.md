# K5 语义 IR 与 PDX 降低结果

> 计划版本：30.0；状态：部分实施，不能关闭 K5。
> 证据边界：以下是静态生成、独立 PDX AST 结构检查和 Python 类型检查，不代表游戏内行为质量。

## 本轮已落地

- `src/pdx/situated/ir.py` 将 1,401 条生产规则登记为可序列化的 source → IR 结构，并保留 operation、条件和原版尾部合同。
- `src/pdx/situated/lowering.py` 在不调用 Python 参考求值器的情况下解析生成 PDX 文本，提取写入见证，并独立检查每个行动块的 `limit`、写入操作和嵌套条件结构。
- 生产 metadata 增加 `ir_lowering_witness` 与 `ast_lowering_witness`，缺失/不匹配/结构错误不会静默通过。
- 关系条件、互补软增量、替代/冲突抑制和使能硬依赖均由统一编译入口生成，生成后再次运行独立 AST 解析。
- `src/pdx/situated/pdx_eval.py` 增加受限独立 PDX 求值器：解释生成行动内核实际使用的 `limit`、`ROOT`、`AND/OR/NOT`、标量比较、分支顺序、嵌套增量和未知回退；不调用 Python 参考选择器，遇到未登记结构硬失败。
- `mod/decisions/action_families.toml` 成为 19 个细分行动族的唯一描述来源；实例合同增加 `family_id`、actor/target 作用域和最终生成文件见证。见证计算已移到所有消费者适配器写入之后，当前 1,408 个实例均有最终文本标记见证。

## 可核查结果

```text
.venv\Scripts\python.exe -B -X utf8 -m pytest -o "addopts=" -p no:cacheprovider -n 0 tests/test_situated_lowering.py tests/test_situated_kernel.py -q
4 passed（本轮定向 metadata/AST 检查）

.venv\Scripts\python.exe -B -X utf8 -m ruff check src/pdx/situated tests/test_situated_*.py
All checks passed

.venv\Scripts\python.exe -B -X utf8 -m mypy src/pdx/situated
Success: no issues found

.venv\Scripts\python.exe -B -X utf8 -m pdx.cli modgen --check
63 个生产文件与源逐字节一致
```

## 尚未满足的 K5 出口

1. 独立求值器仍只覆盖生成器实际输出的受限子集；SC01–SC32 的人工期望、逐实例动态反事实、完整 PDX 语义覆盖和故障注入仍未完成。
2. 旧 information/adapters 规则仍有历史生产旁路，K9 尚未逐项销账和移除双作者。
3. K6–K13 的全域行动化、故障注入、性能/RSS、正式包、Tag、Release、部署和全仓终审均未完成。

因此当前版本保持 `2.0.0`，覆盖报告保持 `incomplete`，不创建 3.0.0 Tag/Release，也不以本结果作为 Workshop 发布依据。
