---
name: pdf-to-3d-pipeline
description: "把 2D 工程图 PDF 做成 SolidWorks 三维模型（严格串行：PDF → 图注 → DWG/DXF → 分段拉伸 → SLDPRT/STEP → 验收 → 交付）。当用户要求「按这张图纸建模」「PDF 转 3D」「2D 转 3D」「先出 DWG 再建 3D」「把这个零件三维化」「照着图纸画个模型」时使用。适用于单视图、板类/平板件、图纸标了材质与重量的机械零件。触发词：PDF转3D、图纸建模、2D转3D、按图建模、DWG、DXF、SLDPRT、STEP、SolidWorks 建模、三维化、板类零件、沉头孔、沉孔、盲孔。"
version: 0.2.0
metadata: { "os": ["win32"], "requires": { "bins": ["powershell"], "apps": ["AutoCAD", "SOLIDWORKS"] } }
---

# 2D 图纸 → SolidWorks 三维模型 → 自检 → 交付

一条串行链路，每一步都有可检查的中间产物，每个阶段都能单独重跑。

```
part.pdf
  ├─ spec ─────> drawing_spec.json        图注合同 = 唯一验收基准
  ├─ dwg ──────> part.dwg + part.dxf
  │                └─ part ──────> 零件几何（外轮廓 / 窗口 / 孔）
  │                     └─ thickness ──> 板厚（用图纸重量反算）
  │                          └─ build ──> SLDPRT / STEP / PNG   ← apply_spec 先把图注补进几何
  └────────────── verify（逐条对图注）──> deliver（再验一次才复制）
```

**DWG 是唯一的几何来源，图注是唯一的验收基准。**
DWG 决定形状从哪来，图注决定做对没有——这两句不矛盾，缺一个就会交付一个"看着像"的错件。

## 先读哪一页

| 你要做的事 | 读这个 |
|---|---|
| 判断这条流水线适不适合这个零件 | 本页「适用范围」 |
| 第一次拿自己的图纸跑（填哪 4 个数、卡住怎么查） | `USAGE.md` |
| 照着敲一遍命令 | `QUICKSTART.md` |
| 每个阶段具体怎么做、输出哪几行才算过 | `reference/操作手册.md` |
| 判定标准与数值阈值（G0~G7） | `reference/验收契约.md` |
| 遇到怪现象 / 想改脚本 | `reference/坑与排障.md` |
| 中间产物 JSON 长什么样、脚本接口 | `reference/流水线接口.md` |
| 为什么会有一堆闸门（三个真实返工） | `reference/复盘-三次返工.md` |
| 作为 agent 的执行契约（停机表、交付定义） | `AGENTS.md` |

## 适用范围（不适用就直说，不要硬跑）

| 能做 | 不能做 |
|---|---|
| 等厚拉伸板件、通孔、沉孔（正/反面）、盲孔、腰形槽、圆角轮廓 | 多视图回转体、加强筋/拔模/变截面、铸件、焊接件、装配体 |

单视图没标板厚也能做：用图纸重量反算（阶段 3b）。

## 六条硬规则（违反任何一条，结果一定"看着对、其实错"）

1. **先抄图注，再建模。** `反面`、`▽深度`、`H7` 只存在于文字里，几何里没有。第一步永远是 `spec`，
   `unparsed` 非空不许往下走。
2. **质量对不上，不许开 SolidWorks。** 理论质量与图纸差 >1% = 几何挑错了，回去修几何，
   **不许调板厚凑数**。
3. **DWG 是整张图纸，不是零件。** 图框、标题栏、尺寸线、侧视图全在里面，必须 `part_from_dxf.py`
   挑出零件；直接导入 SW 只会得到 1750×1188 的乱草图和 0 体积。
4. **孔不能和它的沉孔同草图。** 同一草图出现"同心、异径"一对圆，拉伸会**静默失败**。
   板厚按每个孔的 z 区间自动切带，每带一次拉伸。
5. **草图回写必须 `AddToDB = true`。** 否则 `CreateCircleByRadius` 会对已有孔做推理，
   28 个圆只进去 7 个，拉伸照样返回 ok。
6. **验收对图注，不对几何。** 交付前 `spec_verify.py` 必须 `问题 0 项`；
   `hole_audit.py` 只能证明"和 DWG 一致"，证明不了"和图纸要求一致"。

## 八个阶段（入口只有一个，顺序不可交换）

```powershell
& "<技能目录>\run.ps1" preflight|spec|dwg|part|thickness|build|verify|deliver -<参数>
```

末行机器可读：`GATE <stage>: PASS|FAIL` 或 `STOP: <要修什么>`；退出码 `0` 通过 / `1` 闸门未过 / `2` 缺参数或环境。

| # | 阶段 | 关键参数 | 通过判据（不满足就停） |
|---|---|---|---|
| 0 | `preflight` | — | 无 `BLOCK` 行：AutoCAD 在跑、SW interop 在、python+pymupdf 可用 |
| 1 | `spec` | `-Pdf` | `unparsed=0` 且 `holes>0`，条数 = 图纸孔标注条数 |
| 2 | `dwg` | `-Pdf -PartWidth` | `.dwg` 与同名 `.dxf` 都生成且 >4KB |
| 3 | `part` | `-Dxf -Depth -Mass` | `outer loop` = 图纸总尺寸，质量偏差 ≤1% |
| 3b | `thickness` | `-Dxf -Mass -Material` | 出现 `RESULT: use thickness`（无规格能复现重量 = 几何错） |
| 4 | `build` | `-Dxf -Depth -Name -Counterbore` | `ok:true`、`volume>1000`、每带 `segs` = 该带元素数 |
| 5 | `verify` | `-Spec -Step -Segments -Part` | 四道门全 PASS：`verify.spec` → `holes` → `depth` → `views` |
| 6 | `deliver` | `-Step -To -Mass` | 再跑一次 `spec_verify`，不过就拒绝复制 |

`verify.spec` 不过，后面所有数字都不算数——它是唯一能发现"图注要 4 个反面沉孔却做了 0 个""盲孔打穿了"的检查。

## 八条静默失败（都踩过，改脚本前必读 `reference/坑与排障.md`）

1. **SW 的 DXF 导入不能用**——`InsertDwgOrDxfFile` 返回 True、轮廓全闭合，`FeatureExtrusion3` 永远 null。
2. **同心异径圆让拉伸失效**——必须拆到不同 z 带。
3. **草图推理吞圆**——`AddToDB = true`；`segs` 从 100 掉到 79 就是这个。
4. **体积一样几何可以不一样**——少 4 个沉孔只差 0.48%，正反面对调体积分毫不差。
5. **图注里的沉孔，DWG 里没有那个圆**——φ11 只在文字里，必须 `apply_spec.py` 注入 `back_counterbores`。
6. **bulge 圆弧中点取右法向**——取左会整圈镜像，SW 不报错、只是拉伸失败。
7. **拿几何当验收基准，永远查不出漏读**——基准错了，验收越认真越自信地错。
8. **盲孔和通孔画得一模一样**——`▽5` 是深度，不是又一处标注。

## 验收器本身也要被验

第一次跑某个零件时，跑一次变异测试（盲孔 +2mm、沉孔翻面、数量 +1、通孔改盲孔）：

```powershell
& $PY "<技能目录>\scripts\diagnostics\gate_selftest.py" .\drawing_spec.json .\out\PART.STEP
# 末行：[PASS] 验收器是活的
```

**一个永远返回"问题 0 项"的检查器，比没有检查器更危险。**

## 交付前六问（答不出就不许交付）

1. **图注抄全了吗？** `drawing_spec.json` 条数 = 图纸孔标注条数，`unparsed` 为空。
2. **每条图注都对上了吗？** `spec_verify.py` → `问题 0 项`。这一条否决其余所有指标。
3. **几个面有沉孔？** 正面 N 处、反面 M 处，与图纸两条标注逐字对应（含"反面"二字）。
4. **有没有盲孔？** `▽数字` 就是深度，`depth_check.py` 要看到 `φ5 0.0~5.0`。
5. **质量对不对、且体积变化能解释吗？** 例如 2 个 φ5 只做 5 深，比通孔少切 117.8 mm³。
6. **两面图都看过了吗？** 两张正视图必须互补；只有一面有台阶 = 有一面没做。

前两条防漏，后四条防错。**质量、体积、包围盒全对也只是辅助证据**——它们证明不了孔在哪个面、沉孔多深、盲孔有没有打穿。

## 交付

```powershell
& "<技能目录>\run.ps1" deliver -Spec .\drawing_spec.json -Step .\out\<Name>.STEP `
       -Segments .\part_segments.json -To "<目标目录>" -Mass 0.47
```

交付 7 件：`SLDPRT` `STEP` `PNG` + 两张面视图（`-后视看z0面` / `-前视看zmax面`）+ `drawing_spec.json`
+ `part_segments.json` + `验收记录.md`。

汇报时给：包围盒、体积、质量与图纸偏差、**正面几处沉孔 / 反面几处沉孔 / 盲孔几处**，以及中间产物路径
（用户要回 CAD 改图时用得上）。

## 包结构

```
pdf-to-3d-pipeline/     ← 既是技能，也是一个 dsh 插件包
├── SKILL.md            本页：入口与铁律
├── AGENTS.md           agent 执行契约（停机表 / 交付定义 / 文件地图）
├── QUICKSTART.md       6 步照着敲
├── USAGE.md            给别人用：4 个数怎么填、每关盯哪行
├── MARKET.md           市场文案：名字 / 一句话 / 短描述 / 长描述 / 英文 / 标签
├── run.ps1             唯一入口，8 个阶段，带闸门
├── reference/          操作手册 / 验收契约 / 坑与排障 / 流水线接口 / 复盘
├── scripts/            python + powershell 各步骤，含 diagnostics/
├── package.json        dsh 插件清单（dsh.bundle.patch → cordis.patch.yml）
├── cordis.patch.yml    dsh 加载自己那一行
├── lib/                dsh 插件运行时：自挂载技能目录、写 boot log
├── bin/pdf3d.mjs       CLI：doctor / link / unlink / run / path
└── install.ps1         装到 dsh / workbuddy / claude / codex / cursor
```

装到别的 agent：

```powershell
& .\install.ps1 -List                        # 看哪些 agent 目录存在
& .\install.ps1 -Targets dsh,workbuddy       # 建 junction，一处改动处处生效
& .\install.ps1 -Register                     # 注册成 dsh 插件（改 profile，先备份）
& .\install.ps1 -Unregister                   # 撤销注册
```
