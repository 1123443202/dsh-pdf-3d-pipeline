# AGENTS.md — 2D 图纸 → DWG → SolidWorks 3D → 自检 → 交付

> 给**任何 agent**（dsh / Claude Code / Codex / Cursor / WorkBuddy）看的执行契约。
> 读完这一个文件就能干活；细节文档在 `reference/`，不要跳过本文件的"停"字条款。

本目录即技能包根目录（可整体搬走，脚本不依赖用户名路径）：

```
<pipeline>/            run.ps1  SKILL.md  AGENTS.md  QUICKSTART.md  install.ps1
      scripts/         所有 python / powershell 步骤
      reference/       操作手册、验收契约、坑与排障、数据格式、复盘
      package.json     dsh 插件清单    cordis.patch.yml  dsh 加载自己那一行
      lib/  bin/       dsh 插件运行时 + pdf3d CLI
```

---

## 1. 这条流水线做什么

**输入**：一张机械工程图 PDF（**单视图 + 板类零件**，图纸标了材质和重量）。
**输出**：`SLDPRT` + `STEP` + `PNG` + 正反两张视图 + `验收记录.md`。

严格串行，`DWG 是唯一的几何来源`，`图注是唯一的验收基准`——这两句不矛盾：
DWG 决定形状从哪来，图注决定做对没有。

**先判断适用性，不适用就直说，不要硬跑一个"看着像"的模型：**

| 能做 | 不能做 |
|---|---|
| 等厚拉伸板件、通孔、沉孔（正/反面）、盲孔、腰形槽、圆角轮廓 | 多视图回转体、加强筋/拔模/变截面、铸件、焊接件、装配体 |

同一条链也能处理"没有板厚的单视图"：用图纸重量反算厚度（阶段 3）。

---

## 2. 六条铁律（违反任何一条，结果一定是"看着对、其实错"）

1. **先抄图注，再动手建模。** 图注里的 `反面`、`▽深度`、`H7` 只存在于文字里，几何里没有。
   第一步永远是 `spec` 阶段，`unparsed` 非空就不许往下走。
2. **质量对不上，不许开 SolidWorks。** 第 3 阶段打印的理论质量与图纸差 >1% = 几何挑错了，
   回去修几何，**不要调板厚凑数**。
3. **DWG 是整张图纸，不是零件。** 图框、标题栏、尺寸线、侧视图全在里面，必须用 `part_from_dxf.py`
   挑出零件，直接导入 SolidWorks 只会得到 1750×1188 的乱草图和 0 体积。
4. **孔不能和它的沉孔同草图。** 同一草图里出现"同心、异径"一对圆，拉伸会**静默失败**
   （返回 null 或吞掉圆，不报错）。板厚按每个孔的 z 区间自动切带，每带一次拉伸。
5. **草图回写必须 `AddToDB = true`。** 否则 `CreateCircleByRadius` 会对着已有孔做推理，
   10 个圆只进去 3 个，拉伸照样返回 ok。
6. **验收对图注，不对几何。** 交付前 `spec_verify.py` 必须 `问题 0 项`。
   `hole_audit.py` 只能证明"和 DWG 一致"，证明不了"和图纸要求一致"。

---

## 3. 五个阶段 + 每阶段的停机条件

入口只有一个：`run.ps1 <stage>`。每个阶段最后一行是机器可读结论：

```
GATE <stage>: PASS
GATE <stage>: FAIL
STOP: <要修什么>
```

退出码：`0` 通过 / `1` 闸门未过 / `2` 缺参数或环境。

| # | 阶段 | 命令 | 通过判据（不满足就停） |
|---|---|---|---|
| 0 | 预检 | `run.ps1 preflight` | 无 `BLOCK` 行；AutoCAD 在跑、SolidWorks interop 在、python+pymupdf 可用 |
| 1 | 抄图注 | `run.ps1 spec -Pdf part.pdf` | `unparsed=0` 且 `holes>0`；条数与图纸上的孔标注条数一致 |
| 2 | 出 DWG | `run.ps1 dwg -Pdf part.pdf -PartWidth 200` | `.dwg` 与同名 `.dxf` 都生成且 >4KB |
| 3 | 挑几何 | `run.ps1 part -Dxf part.dxf -Depth 8 -Mass 0.47` | 打印 `outer loop` = 图纸总尺寸；质量偏差 ≤1% |
| 3b | 定板厚 | `run.ps1 thickness -Dxf part.dxf -Mass 0.47` | 出现 `RESULT: use thickness`（无规格能复现重量 = 几何错，不是板厚错） |
| 4 | 建模 | `run.ps1 build -Dxf part.dxf -Depth 8 -Name PART -Counterbore 3.4` | `ok:true`、`volume>1000`、每带 `segs` = 该带元素数 |
| 5 | 验收 | `run.ps1 verify -Spec drawing_spec.json -Step out\PART.STEP -Segments part_segments.json -Part out\PART.SLDPRT` | 四道门全 PASS：`verify.spec` → `verify.holes` → `verify.depth` → `verify.views` |
| 6 | 交付 | `run.ps1 deliver -Step out\PART.STEP -To <目标目录> -Mass 0.47` | 再次跑 `spec_verify`，不过就拒绝复制 |

**顺序不可交换。** `verify.spec` 不过，后面所有数字都不算数——它是唯一能发现
"图注要 4 个反面沉孔却做了 0 个""盲孔打穿了"的检查。

一个完整目录里跑完的中间产物（每一步都能单独重跑）：

```
part.pdf → drawing_spec.json → plan.json → part.dwg/part.dxf → PART.part.dxf
        → part_segments.json → out/PART.SLDPRT|STEP|PNG + 两张面视图 + PART.build.json
        → 验收记录.md
```

---

## 4. 你（agent）在每个停机点该做什么

| STOP 出现在 | 说明 | 正确动作 | 绝对不要做 |
|---|---|---|---|
| `spec` | 有图注没读懂 | 打开 PDF 该处截图/放大，人工读出补进解析规则 | 带着 `unparsed` 往下建 |
| `part` | 外轮廓或质量不对 | 看 `outer loop` 是否等于图纸总尺寸；检查 `--part-width`；检查是否把图框当零件 | 调板厚或密度去凑质量 |
| `thickness` | 没有标准板厚能复现重量 | 回第 3 阶段查几何（漏窗口/孔重复计数） | 硬填一个厚度 |
| `build.spec` | 图注数量与几何对不上 | 核对图注孔径 vs DWG 画的孔径（可能差 0.2），确认哪个是图纸要求 | 猜着套上去 |
| `verify.spec` | 模型与图注不符 | 看它打印的 `实际 … / 期望 …`：数量→`apply_spec`；z 起止→盲孔深/沉孔面；直径→`part_segments.json` 的 r | 改判据让它变绿 |
| `verify.holes` | 与 DWG 不一致 | 孔位/直径/沉孔落在哪一面 | 只重跑一次看运气 |
| `verify.depth` | 沉口悬在板中间 | 检查该孔的 z 区间分配 | 改 `depth_check.py` 的容差 |
| `verify.views` | 视图没导出 | SolidWorks 是否被强杀；重跑阶段 4 | 说"图看不看都行" |

---

## 5. 不能跳过的两件事

**(a) 验收器本身要验。** 第一次跑某个零件时，跑一次变异测试：

```powershell
& $PY scripts\diagnostics\gate_selftest.py drawing_spec.json out\PART.STEP
```

盲孔加深 2mm、沉孔翻面、数量 +1、通孔改盲孔，4 类变异必须全部被抓到，末行 `[PASS] 验收器是活的`。
**一个永远返回"问题 0 项"的检查器比没有更危险。**

**(b) 两面都要看。** `verify.views` 出的两张正视图必须**互补**：
A 面四角是台阶孔、横排是直孔，B 面就反过来。两面一样 = 有一面没做。
之前"没画沉头孔"的错误就是只看了一张图。

---

## 6. 交付定义（少一样都不算完成）

| 文件 | 作用 |
|---|---|
| `PART.SLDPRT` | 可编辑模型 |
| `PART.STEP` | 通用交换格式，验收脚本读的就是它 |
| `PART.PNG` | 等轴测图，快速看形状 |
| `PART-后视看z0面.PNG` / `PART-前视看zmax面.PNG` | 两面视图，用户肉眼验收沉孔 |
| `drawing_spec.json` | 图注合同（验收基准，必须一起给） |
| `part_segments.json` | 几何数据（含 `back_counterbores` / `blind_holes`） |
| `验收记录.md` | 自动生成：图注对账结果 + 包围盒 + 体积 + 质量偏差 + 分段证据 |

汇报时给：**包围盒、体积、质量与图纸偏差、正面几处沉孔 / 反面几处沉孔 / 盲孔几处**，
以及中间产物路径（用户要回 CAD 改图时用得上）。

---

## 7. 环境

- Windows + AutoCAD（**必须先打开**，replay 走 COM）+ SolidWorks（脚本自己拉起，跑完关掉）。
- Python 3 + `pymupdf`。**不要用裸 `python`**：Windows 上的 Store 存根会 `exit 9009` 且无任何输出。
  `scripts/env.ps1` 会自动找一个**能真正执行**的 3.x 解释器，也认 `PDF3D_PYTHON` 环境变量。
- 首次使用先跑 `run.ps1 preflight`，按 `BLOCK` 行修。

**装到别的 agent**（软链接，改一处即可，不必复制）：

```powershell
& .\install.ps1 -List                               # 看哪些 agent 目录存在
& .\install.ps1 -Targets workbuddy,codex            # 建 junction
& .\install.ps1 -Targets claude -Copy               # 不跟随 junction 的用实拷贝
& .\install.ps1 -Remove -Targets codex              # 只删链接，不删源目录
& .\install.ps1 -Register                           # 注册成 dsh 插件（备份后改 profile）
& .\install.ps1 -Unregister                         # 撤销
```

支持的 key：`dsh` `workbuddy` `claude` `codex` `cursor` `agents`（对应 `~\.<key>\skills`）。
装成 dsh 插件后要**彻底退出 dsh 再启动**才会加载。

---

## 8. 文件地图

| 文件 | 作用 |
|---|---|
| `run.ps1` | 唯一入口，8 个阶段，带闸门 |
| `scripts/env.ps1` | 环境探测（python / pymupdf / AutoCAD / SW / 模板） |
| `scripts/selftest.ps1` | 预检（只读，不开任何程序） |
| `scripts/drawing_spec.py` | 1 `spec` PDF 文字层 + **矢量符号**（φ/⌴/▽）→ `drawing_spec.json` |
| `scripts/pdf2cad2.py` + `replay2.ps1` | 2 `dwg` PDF → AutoCAD 重画 → `.dwg` + `.dxf` |
| `scripts/part_from_dxf.py` | 3 `part` 从整张图里挑出零件（外轮廓 + 窗口 + 孔） |
| `scripts/estimate_thickness.py` | 3b `thickness` 用图纸重量反算板厚 |
| `scripts/part_segments.py` | 4 `build` DXF → 逐段几何 + 圆孔 `part_segments.json` |
| `scripts/apply_spec.py` | 4 `apply_spec` 把图注里几何表达不出来的孔写进几何（反面沉孔、盲孔深） |
| `scripts/DwgBuild.cs` + `build_from_dwg.ps1` | 4 `build` 分段拉伸 → SLDPRT/STEP/PNG |
| `scripts/spec_verify.py` | 5 `verify` **G1 图注对账**（唯一验收基准） |
| `scripts/hole_audit.py` | 5 `verify` G2/G3 与 DWG 逐孔对账、正面/反面沉孔计数 |
| `scripts/depth_check.py` | 5 `verify` G4 沉口是否贴端面 |
| `scripts/views.ps1` | 5 `verify` 出正反两张视图 |
| `scripts/make_report.py` | ⑥ 生成 `验收记录.md` |
| `scripts/diagnostics/gate_selftest.py` | 变异测试：证明验收器是活的 |
| `scripts/diagnostics/bisect.ps1` | 拉伸失败时二分定位坏环 |
| `package.json` + `cordis.patch.yml` | dsh 插件清单与加载行 |
| `lib/index.js` | dsh 加载时把本目录挂到 `~/.dsh/skills/pdf-to-3d-pipeline`；**永不抛异常** |
| `bin/pdf3d.mjs` | CLI：`doctor` / `link` / `unlink` / `run <stage>` |

细节：`QUICKSTART.md`（照着敲一遍）、`reference/操作手册.md`（逐阶段做法与判读）、
`reference/验收契约.md`（判定标准与阈值）、`reference/坑与排障.md`（8 个坑 + 排障表）、
`reference/复盘-三次返工.md`（为什么会有这些闸门）、`reference/流水线接口.md`（数据格式）。
