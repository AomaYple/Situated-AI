"""历史 Win32/PowerShell 四法实验已冻结；当前三平台量尺使用 psutil。

冻结原件：tools/probe/frozen/mem_method_crosscheck-windows.py.frozen。
历史不同 API 的读数不能与新的采样 RSS 混为同一条基线。
"""

from __future__ import annotations

from pdx.performance import main

if __name__ == "__main__":
    raise SystemExit(main())
