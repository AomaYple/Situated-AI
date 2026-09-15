# V3 提取工具链

用于从 Victoria 3 安装目录机械提取结构化数据，供 `docs/victoria3-modding/` 引用。

> 这些脚本是**可复现性保障**：文档里的数字与清单都可以用它们重新生成，不必信任一次性的人工统计。

## 脚本

| 脚本 | 作用 |
|---|---|
| `v3-extract.ps1` | 通用 PDX 脚本**顶层键提取器**（大括号深度感知 + 引号内 `#` 保护） |
| `extract_defines.ps1` | 提取 defines 文件的**命名空间块**与成员参数名 |
| `dump_defines.ps1` | 把 defines 提取结果**导出为 JSON** |
| `dump_precise.ps1` | 精确版 defines 提取器：把一级条目分类为 **标量 / 内联列表 / 嵌套块** |
| `dump_misc.ps1` | 通用顶层键提取器（供 modifier_types、static_modifiers 等复用） |
| `make_frags.ps1` | 把提取结果渲染成 **ASCII-only 的 Markdown 片段** |

## 输出（`tools\out\`，已 gitignore）

| 文件 | 大小 | 内容 |
|---|---|---|
| `defines_all.json` | ~228 KB | 全部 defines 参数 |
| `defines_precise.json` | — | 分类后的精确 defines |
| `modifier_types.json` | ~850 KB | 全部修饰符类型 |
| `static_modifiers.json` | ~2.0 MB | 全部静态修正符 |

> 输出目录被 `.gitignore` 排除：体积达 MB 级且**可随时重新生成**。
> 需要时直接跑脚本即可，不需要把它们提交进仓库。

## 设计要点

脚本里的注释剥离函数做了**引号感知**，这是必要的：

```powershell
function Remove-PdxComment {
    param([string]$Line)
    $inQ = $false
    for ($i = 0; $i -lt $Line.Length; $i++) {
        $c = $Line[$i]
        if ($c -eq '"') { $inQ = -not $inQ }
        elseif ($c -eq '#' -and -not $inQ) { return $Line.Substring(0, $i) }
    }
    return $Line
}
```

因为 PDX 脚本里字符串常量可能包含 `#`（如本地化键、图标路径），
朴素的 `-replace '#.*$'` 会错误截断这些行。

同理，键提取必须**跟踪大括号深度**，否则会把嵌套块里的键误判为顶层键。

## 复用方式

脚本采用 dot-source 风格，没有 `param` 块，可直接在会话中载入：

```powershell
Invoke-Expression (Get-Content -LiteralPath .\tools\v3-extract.ps1 -Raw)
Get-TopLevelKeys -Path "C:\Program Files (x86)\Steam\steamapps\common\Victoria 3\game\common\on_actions\00_on_actions.txt"
```

## 已知限制

- 只做**词法**解析，不理解 PDX 语义；对畸形输入不做校验
- 大括号计数会被**字符串常量里的花括号**干扰（当前未对 `{}` 做引号保护）
- 仅用于只读提取，不会修改游戏文件
