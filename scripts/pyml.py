# -*- coding: utf-8 -*-
"""定位 pymupdf，不依赖任何用户名/安装路径。

为什么单独抽一个文件：
    这条流水线要能被别的 agent、别的机器直接跑。原先把
    `sys.path.insert(0, r"C:\\Users\\<某人>\\.dsh\\skills\\pdf-to-black\\libs")`
    写死在脚本里，换个账号就 ImportError。现在按下面的顺序找：

      1. 环境变量 PYMUPDF_PATH / PDF3D_LIBS（env.ps1 会自动填）
      2. <skill>/libs（把 pymupdf 直接放进技能包时）
      3. ~/.dsh/skills/*/libs（dsh 侧车依赖）
      4. ~/.workbuddy/libs
      5. 当前解释器自带的 site-packages（`pip install pymupdf`）

用法：
    from pyml import pymupdf
"""
import glob
import importlib
import os
import sys


def _dirs():
    out = []
    for k in ("PYMUPDF_PATH", "PDF3D_LIBS"):
        v = os.environ.get(k)
        if v:
            out.append(v)
    here = os.path.dirname(os.path.abspath(__file__))
    out.append(os.path.join(here, os.pardir, "libs"))
    home = os.path.expanduser("~")
    out.append(os.path.join(home, ".dsh", "skills", "pdf-to-black", "libs"))
    out.extend(sorted(glob.glob(os.path.join(home, ".dsh", "skills", "*", "libs"))))
    out.append(os.path.join(home, ".workbuddy", "libs"))
    seen, keep = set(), []
    for p in out:
        if not p:
            continue
        p = os.path.abspath(p)
        if os.path.isdir(p) and p not in seen:
            seen.add(p)
            keep.append(p)
    return keep


def load():
    """返回 pymupdf 模块；找不到时抛 SystemExit 并给出可执行的修法。"""
    tried = _dirs()
    for d in tried:
        if d not in sys.path:
            sys.path.insert(0, d)
    importlib.invalidate_caches()
    for name in ("pymupdf", "fitz"):
        try:
            return importlib.import_module(name)
        except ImportError:
            continue
    raise SystemExit(
        "BLOCK: 当前解释器装不了 pymupdf。已尝试的 libs 目录：\n  "
        + "\n  ".join(tried)
        + "\n修法（任选一）：\n"
        + "  <PY> -m pip install pymupdf\n"
        + "  或把 pymupdf 所在目录设成环境变量 PYMUPDF_PATH\n"
        + "  （解释器：" + sys.executable + "）"
    )


pymupdf = load()
