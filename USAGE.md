# 使用说明 — 拿别人的图纸，怎么跑出自己的零件

`QUICKSTART.md` 是照着敲一遍的演示；这份是**填空指南**：你的图纸不是 DEMO-01 时，
哪个数填哪里、哪一行决定了要不要继续、卡住了先去哪找原因。

---

## 1 先判断：它接不接你这单活

| 能做 | 不做 |
|---|---|
| 单视图、等厚拉伸的板类零件 | 多视图回转体、铸件、焊接件 |
| 通孔、沉孔（正/反面）、盲孔、腰形槽 | 加强筋、拔模、变截面、曲面 |
| 外轮廓由直线 + 圆弧 + 圆角组成 | 装配体（只出一个零件） |
| 图纸标了材质和重量 | 扫描件 / 图片版 PDF（没有文字层） |

图纸上要是出现「不共面」「折弯」「两侧不同厚度」，直接停——它不会硬跑一个"看着像"的模型，
因为一个看起来正常的错件比一句"做不了"危险得多。

**硬性条件**（缺一不可）：

- Windows + PowerShell 5.1
- AutoCAD 2020+（用来重画 DWG；**必须开着**，脚本走 COM）
- SolidWorks 2020+（脚本自己拉起、跑完关掉）
- Python 3.9+，且 `pip install pymupdf`
- Node 18+（只有 `pdf3d` 这个 CLI 需要，直接跑 `run.ps1` 不需要）

---

## 2 装

三种角色，选一种就够，不必都装：

```powershell
git clone https://github.com/1123443202/dsh-pdf-3d-pipeline.git
cd dsh-pdf-3d-pipeline
```

| 你的情况 | 命令 | 效果 |
|---|---|---|
| 用 dsh | `.\install.ps1 -Register` | 注册成插件 + 技能可见；**要彻底退出 dsh 再启动** |
| 用 Claude Code / Codex / Cursor / WorkBuddy | `.\install.ps1 -Targets claude,codex,cursor,workbuddy` | 只建 junction，不动任何 profile |
| 不想装，直接跑脚本 | 什么都不用做 | 直接调 `run.ps1` |

`-Targets` 支持 `dsh` `workbuddy` `claude` `codex` `cursor` `agents`。
装错了？`.\install.ps1 -Remove -Targets codex` 只删链接，不删源码。

---

## 3 装完第一件事：自检

```powershell
node .\bin\pdf3d.mjs doctor
```

它做三件事：包完整性、各 agent 挂载状态、跑一遍 `run.ps1 preflight`。后半段长这样：

```
  OK    all 19 scripts present
  OK    interpreter 3.12.14  C:\...\python.exe
  OK    pymupdf loads (step 1 dependency)
  BLOCK AutoCAD not running
  OK    interop at C:\sw2025\SOLIDWORKS\api\redist
RESULT: blocked
GATE preflight: FAIL
```

**凡是 `BLOCK` 必须先修**，别带着往下跑。最常见的两个：

- `AutoCAD not running` → 打开 AutoCAD，等它完全起来（不要停在启动画面）。
- `no python 3` → 裸 `python` 是 Microsoft Store 的存根，执行即退出码 9009 且没有任何提示，
  整条链会静默卡住。用 `set PDF3D_PYTHON=C:\Python312\python.exe` 指一个真的解释器。

---

## 4 准备你的图纸：只抄 4 个数

不需要准备别的，但下面四个数得先在图纸上找出来，后面每条命令都要用：

| 数 | 从图纸哪里来 | 用途 |
|---|---|---|
| **总宽 W**（mm） | 外轮廓最长的那个尺寸 | `dwg` 阶段的 `-PartWidth`，决定全局比例，填错整个零件缩放错 |
| **板厚 t**（mm） | 剖视图或「厚度」标注 | `build`/`part` 的 `-Depth`；没标就走 `thickness` 反算 |
| **重量 m**（kg） | 标题栏的「重量/质量」 | `-Mass`，用来卡住"几何挑错"；没有重量这一关就失灵 |
| **材质** | 标题栏 | `thickness` 的 `-Material`：`aluminium` `steel` `stainless` `brass` `titanium` |

**PDF 本身的三个要求**（不满足就在第 1 阶段被拦下，不会污染后面）：

1. **有文字层**：用鼠标能选中 φ6.6、⌴φ11 这些字符。扫描件不行。
2. **图注是标准写法**：`4×φ6.6 完全贯穿 ⌴φ11▽3.4`、`2×φ5 ▽5`、`反面`。数量、直径、深度、在哪一面，四件事都得写出来。
3. **单视图**：一个主视图就够，不要带装配图或多视图拼版。

> `φ` `⌴` `▽` 在 PDF 里通常**不是文字，是矢量线**。脚本按形状认：φ 是闭合圆，
> ⌴ 是开口的 U 形，▽ 是一条横线加倒 V。认不出来会打印 `UNPARSED:`，那就停下来人工读图。

---

## 5 七个阶段：每步填什么、盯哪一行

下面命令里的 `$R` 是仓库目录，`$W` 是你的工作目录（**别在仓库目录里跑，会污染源码**）：

```powershell
$R = "C:\path\to\pdf-to-3d-pipeline"
$W = "$env:USERPROFILE\cad-agents\work\我的零件"
New-Item -ItemType Directory -Force $W | Out-Null
Set-Location $W
Copy-Item "D:\图纸\我的零件.pdf" .\part.pdf
```

| 阶段 | 命令 | 你要填的 | PASS 长什么样 |
|---|---|---|---|
| 0 预检 | `& "$R\run.ps1" preflight` | — | `RESULT: ready` |
| 1 抄图注 | `& "$R\run.ps1" spec -Pdf .\part.pdf` | — | `call-outs=N holes=M unparsed=0` |
| 2 出图 | `& "$R\run.ps1" dwg -Pdf .\part.pdf -PartWidth 200` | 总宽 W | 生成 `part.dwg` + `part.dxf` |
| 3 挑零件 | `& "$R\run.ps1" part -Dxf .\part.dxf -Depth 8 -Mass 0.47 -Name 我的零件` | 板厚、重量 | `outer loop` 等于图纸外形，质量差 ≤1% |
| 3b 定板厚 | `& "$R\run.ps1" thickness -Dxf .\part.dxf -Mass 0.47 -Material aluminium` | 重量、材质 | `RESULT: use thickness 8.00 mm` |
| 4 建模 | `& "$R\run.ps1" build -Dxf .\part.dxf -Depth 8 -Name 我的零件 -Counterbore 3.4` | 正面沉孔深度 | 每段 `(N个元素)` 等于 `segs=N` |
| 5 验收 | `& "$R\run.ps1" verify -Spec .\drawing_spec.json -Step .\out\我的零件.STEP -Segments .\part_segments.json -Part .\out\我的零件.SLDPRT -OutDir .\out` | — | 四道门全 PASS，`问题 0 项` |
| 6 交付 | `& "$R\run.ps1" deliver -Spec .\drawing_spec.json -Step .\out\我的零件.STEP -Segments .\part_segments.json -To "D:\交付\我的零件" -Mass 0.47` | 交付目录、重量 | 8 个文件 + `验收记录.md` |

每个阶段末行只有两种结局：`GATE <stage>: PASS` 或 `STOP: ...`。**看到 STOP 就停**，
后面几条别执行——否则你会在一个错的几何上继续加深错误。

### 阶段 1：图注条数必须和图纸对上

```
符号识别 9 个（φ/⌴/▽），解析出孔图注 3 条
call-outs=3  holes=10  unparsed=0
```

`call-outs` 是你图纸上**孔标注的条数**（一行算一条，不是孔数）。少一条 = 有一组孔没读到，
后面 4、5 阶段会以"数量对不上"的形式再报一次，但那时已经白跑了两步。

### 阶段 3：这一关专治"挑错了东西"

```
outer loop  200.0 x 120.0  area 24000.00 mm2
net area 21887.03 mm2   volume @8.00 = 175096.3 mm3   mass(6061) = 0.4728 kg
  mass 0.4728 kg vs drawing 0.4700 kg  (0.59%)
```

- `outer loop` 不等于图纸总尺寸 → 挑错了（把图框当零件，或外轮廓没闭合）。
- 质量偏差 >1% → 几何错，**回去修，不要改板厚去凑**。改板厚凑质量是这条链上最容易骗过自己的动作。

> 这里的质量按 6061 铝（2.70 g/mm³）算。**钢件这一行必然偏差大**，别据此改几何：
> 改用阶段 3b 的 `-Material steel` 核对板厚，或直接在图纸上读板厚跳过估算。

### 阶段 4：`(N个元素)` 和 `segs=N` 必须相等

```
band z0~3.4   (18个元素) segs=18 -> ok 凸台-拉伸1
band z5~8     (16个元素) segs=16 -> ok 凸台-拉伸4
```

相等 = 这一带该画的圆一个没少。**最后一带少两个不是错误**——那正是盲孔只到 z=5 的证据。
反过来说，`segs` 比图纸上的圆数少，是 SolidWorks 的草图推理把圆吃掉了（脚本已用 `AddToDB` 关闭推理，
但换版本仍可能复现），会打 `WARNING` 并判 FAIL。

### 阶段 5：四道门，顺序不能换

| 门 | 检查什么 | 挂了说明 |
|---|---|---|
| `verify.spec` | 图注逐条：数量、孔径、通/盲、沉孔直径与深度、在哪个面 | 模型和图注不一致，其他都不用看 |
| `verify.holes` | STEP 里每个孔的直径与 z 起止，和 DXF 对账 | 孔位/孔径/沉孔面错了 |
| `verify.depth` | 沉孔大径段是否贴端面 | 沉口悬在板中间 = 深度或方向错了 |
| `verify.views` | 导出正反两张面视图 | 导不出 = 少一份人眼证据 |

第一次跑某个零件，顺手证明这道门是活的（变异测试，5 类必须全报错）：

```powershell
& "$R\run.ps1" verify -Spec .\drawing_spec.json -Step .\out\我的零件.STEP
# 或单独跑
python "$R\scripts\diagnostics\gate_selftest.py" .\drawing_spec.json .\out\我的零件.STEP
# 末行：[PASS] 验收器是活的：正确模型通过，5 类变异全部报错
```

---

## 6 交付物里哪个是给人看的

| 文件 | 给谁 | 说明 |
|---|---|---|
| `验收记录.md` | **审核的人** | 图注要求 vs 实得、包围盒、体积、质量偏差、分段日志、结论 |
| `*-后视看z0面.PNG` / `*-前视看zmax面.PNG` | **你自己** | 两张必须互补；只看一张就是当初漏掉整面沉孔的原因 |
| `*.STEP` | 下游 CAM / 仿真 | 几何以它为准，验收也是拿它做的 |
| `*.SLDPRT` | 后续改图 | 2022 及以上版本可打开 |
| `drawing_spec.json` | 追溯 | 图注合同，改判据时从这里改 |
| `part_segments.json` | 追溯 | 分段与 z 区间，出问题先看它 |

---

## 7 卡住了先看这张表

| 现象 | 多半是 | 怎么办 |
|---|---|---|
| `preflight` 有 BLOCK | AutoCAD 没开 / 没有真 Python | 开 CAD；`set PDF3D_PYTHON=...` |
| `spec` 出现 `UNPARSED:` | 图注写法超出规则 | 人工读那几条，补 `drawing_spec.py` 的规则后重跑，**别手改 JSON 糊过去** |
| `dwg` FAIL | AutoCAD 没运行 / 图框被当成零件 | 看 DWG 旁边的 `.log.txt` |
| `part` 质量差 >1% | 外轮廓没闭合，或挑到了图框 | 看 `outer loop` 尺寸；必要时 `-Visible` 让 CAD 显示重画过程 |
| `thickness` 无解 | 几何错 | 它不会给你一个"差不多"的厚度，这是对的——回去修几何 |
| `build` 报 `band ... segs` 不一致 | 圆被草图推理吞了 | 看 WARNING 行，检查是不是同心异径的两个圆落在同一张草图 |
| `verify.spec` 数量对不上 | 图注漏读，或 `-Counterbore` 填错 | 对比 `drawing_spec.json` 与图纸原文 |
| `verify.spec` 说"沉孔在反面" | 图注写了 `反面` 但几何做在正面 | 检查 `part_segments.json` 的 `back_counterbores` |
| 一切 PASS 但肉眼看不对 | 视图导错面 | 两张 PNG 必须互补，只有一张说明只做了一个面 |

---

## 8 让 agent 替你跑

装好之后不用记命令，直接说：

> 按 pdf-to-3d-pipeline 把这个 PDF 做成 SolidWorks 零件：
> `D:\图纸\XXX.pdf`，总宽 200、板厚 8、材料 6061 铝、图纸重量 0.47 kg。
> 跑完把 `验收记录.md` 和两张面视图给我；哪一关不过就停在那关告诉我原因。

agent 侧的执行契约在 `AGENTS.md`（五阶段停机表、什么算交付），
判定阈值在 `reference/验收契约.md`（G0~G7），踩过的坑在 `reference/坑与排障.md`。

---

## 9 一句话总结

**它的价值不在画出零件，在于不肯交付一个"看起来对"的零件。**
八道关里任何一道 FAIL，正确的反应都是回去改图纸理解的错，而不是调参数让它变绿。
