# dsh-pdf-3d-pipeline

> **图纸转三维流水线** · 技能名 `pdf-to-3d-pipeline` · CLI `pdf3d`

一个 dsh 插件包（bundle），里面装的是**一条会拒绝交付错件的建模流水线**：
2D 工程图 PDF → 图注合同 → DWG/DXF → 分段拉伸 → SLDPRT/STEP → 对图注验收 → 交付。

一句话：**图纸进，零件出；中间八道关，一道不过就不许交付。**

打包成插件而不是散装脚本，是因为这条链上真正值钱的不是"能把图画出来"，
而是**每一步那个说"不行，回去改"的闸门**——以及三个真实返工换来的判据。
它们必须和脚本放在一起，agent 才不会只拿一半。

> 市场页 / 列表页的成套文案（一句话、短描述、长描述、英文、标签）见 `MARKET.md`。

## 里面有什么

| 文件 | 作用 |
|---|---|
| `SKILL.md` | 技能入口：适用性、六条铁律、8 个阶段、交付前六问 |
| `AGENTS.md` | 给任意 agent（dsh / Claude Code / Codex / Cursor）的执行契约：停机表、交付定义 |
| `QUICKSTART.md` | 以虚构示例件 DEMO-01 为例，6 步照着敲 |
| `run.ps1` | 唯一入口，8 个阶段，末行 `GATE <stage>: PASS/FAIL` 或 `STOP: ...`，退出码 0/1/2 |
| `reference/` | 操作手册、验收契约（G0~G7）、坑与排障、数据格式、复盘 |
| `scripts/` | python + powershell 各步骤；`diagnostics/` 是验收器的自检 |
| `lib/` `bin/` `cordis.patch.yml` | dsh 插件外壳：加载时把技能挂到 `~/.dsh/skills/`，`pdf3d` CLI |

## 安装

### 1. 作为 dsh 插件（推荐）

```powershell
# 本地路径注册到 dsh profile（会先备份 package.json）
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Register
```

它做三件事：技能目录 junction 到 `~/.dsh/skills/pdf-to-3d-pipeline`、
把包名加进 profile 的 `dsh.profile.bundles` 与 `dependencies`、
在 `node_modules` 下建 junction。**改完要彻底退出 dsh 再启动**（托盘退出，不只是关窗口）。

撤销：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Unregister
```

### 2. 只当技能用（不改 profile）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Targets dsh,workbuddy,claude
```

dsh 扫描的就是 `~/.dsh/skills/<name>/SKILL.md`，junction 即可，不必重启 IDE。

### 3. 只检查环境

```powershell
node .\bin\pdf3d.mjs doctor      # 包完整性 + 各 agent 挂载状态 + run.ps1 preflight
node .\bin\pdf3d.mjs run verify -Spec .\drawing_spec.json -Step .\out\PART.STEP
```

## 前置条件

- Windows + **AutoCAD 已打开**（replay 走 COM）+ SolidWorks（脚本自己拉起、跑完关掉）。
- Python 3 + `pymupdf`。
- **不要用裸 `python`**：Windows 上的 Store 存根执行即 `exit 9009` 且无任何输出，整条链会静默卡住。
  `scripts/env.ps1` 会自己找一个能真正跑起来的解释器，也可 `set PDF3D_PYTHON=<path>`。

## 它不做什么

只吃**单视图 + 板类零件**（等厚拉伸、通孔、沉孔、盲孔、腰形槽、圆角轮廓），图纸要标材质和重量。
多视图回转体、加强筋/拔模/变截面、铸件、装配体一律不做——遇到就直说，不硬跑一个"看着像"的模型。

## 为什么值得装

三个真实故障，每一个都从"所有数字都正常"的模型里漏过去：

1. **4 个反面沉孔一个都没做**——那圈 φ11 只写在图注文字里，DWG 里根本没有这个圆。
   体积、质量、包围盒、孔数全部正常。
2. **2 个 φ5 盲孔被打穿**——图上和通孔画得一模一样，体积只多 0.07%。
3. **只做了一个面的沉孔**——体积和正反面对调的模型分毫不差。

现在能抓住它们的只有一道关：拿 `drawing_spec.json`（图注合同）逐条核数量、孔径、通/盲、
沉孔直径与深度、沉孔在哪一面。这道关自己也要被验（`gate_selftest.py` 做变异测试），
因为**一个永远返回"问题 0 项"的检查器比没有更危险**。
