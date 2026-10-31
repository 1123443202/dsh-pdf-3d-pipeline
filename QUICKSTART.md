# QUICKSTART — 从一张 PDF 到交付，照着敲

以**虚构示例件 `DEMO-01`**（6061-T6 底板，200×120×8，图纸标 0.47 kg）为例：

| 特征 | 图注 |
|---|---|
| 4 × φ6.6 通孔 | 正面 ⌴φ11▽3.4（四角） |
| 4 × φ6.6 通孔 | 反面 ⌴φ11▽3.4（中间一排） |
| 2 × φ5 盲孔 | ▽5 |
| 1 个窗口 | 60 × 30 |

换成你的零件时，只需替换文件名、`-PartWidth`、`-Mass`、`-Depth`、`-Name`，
下面的**输出数值都会不同**——要盯的是每一行的判据，不是这些数字本身。

> 环境不确定时先跑一次 `node bin\pdf3d.mjs doctor`（包完整性 + 挂载状态 + preflight 一次看完）。
> 想把它暴露给别的 agent：`powershell -File install.ps1 -Targets dsh,workbuddy`；
> 想注册成 dsh 插件：`install.ps1 -Register`（改 profile 前会自动备份）。

```powershell
$R = "C:\path\to\pdf-to-3d-pipeline"              # 技能包根目录，可搬走
$W = "$env:USERPROFILE\cad-agents\work\DEMO-01"   # 工作目录，别污染技能目录
New-Item -ItemType Directory -Force $W | Out-Null
Set-Location $W
Copy-Item "…\DEMO-01.pdf" .\part.pdf
```

---

## 0 预检

```powershell
& "$R\run.ps1" preflight
```

期待：

```
  OK    all 19 scripts present
  OK    interpreter 3.12.14  …\python.exe
  OK    pymupdf loads (step 1 dependency)
  OK    running, PID 12345                    <- AutoCAD 必须开着
  OK    interop at C:\sw2025\SOLIDWORKS\api\redist
RESULT: ready
GATE preflight: PASS
```

任何 `BLOCK` 行都要先修。AutoCAD 没开会直接卡在第 2 阶段。

---

## 1 抄图注（第一条命令，不要跳过）

```powershell
& "$R\run.ps1" spec -Pdf .\part.pdf
```

期待（`call-outs` 条数必须等于图纸上的孔标注条数）：

```
符号识别 9 个（φ/⌴/▽），解析出孔图注 3 条

数量   孔径    通/盲     面    沉孔
2     φ5     盲孔▽5     正面
4     φ6.6   通孔      正面   ⌴φ11▽3.4
4     φ6.6   通孔      反面   ⌴φ11▽3.4
孔位合计 10 个，写入 .\drawing_spec.json
call-outs=3  holes=10  unparsed=0
GATE spec: PASS
```

这一步把 `φ`、`⌴`、`▽` 从**矢量线**里认出来（PDF 里它们不是文字）。
出现 `UNPARSED:` 就停下来放大图纸人工读，补规则后重跑。

---

## 2 PDF → DWG

```powershell
& "$R\run.ps1" dwg -Pdf .\part.pdf -PartWidth 200
```

`-PartWidth` = 图纸上标注的零件总宽（mm），决定全局比例。产出 `part.dwg` + 同目录 `part.dxf`。

```
GATE dwg: PASS
```

---

## 3 挑零件 + 校质量

```powershell
& "$R\run.ps1" part -Dxf .\part.dxf -Depth 8 -Mass 0.47
```

`-Depth` 不知道就随便填（只影响打印的估算值）。盯这几行：

```
outer loop  200.0 x 120.0  area 24000.00 mm2
  window     60.0 x  30.0  area 1800.00
holes 10  total area 312.96 mm2
net area 21887.03 mm2   volume @8.00 = 175096.3 mm3   mass(6061) = 0.4728 kg
  mass 0.4728 kg vs drawing 0.4700 kg  (0.59%)
GATE part: PASS
```

`outer loop` 不等于图纸总尺寸 ⇒ 挑错了（把图框当零件 / 外轮廓没闭合）。
质量偏差 >1% ⇒ 几何错，**回去修，不要调板厚**。

> 这里的 `holes 10` 是**几何里的圆数**，不是孔规格数；而且它一律按"通孔"算——
> 那 2 个 φ5 其实只深 5，那 8 个 φ11 沉口在几何里根本不存在。这些差量在阶段 4、5 才补上。

单视图没标板厚时，紧接着反算：

```powershell
& "$R\run.ps1" thickness -Dxf .\part.dxf -Mass 0.47 -Material aluminium
```

```
thickness      7.953 mm   <-- computed
  t= 7.00  -> 0.4137 kg  (-11.99%)
  t= 8.00  -> 0.4728 kg  ( +0.59%) OK
  t=10.00  -> 0.5909 kg  (+25.73%)
RESULT: use thickness 8.00 mm (mass matches within 2%)
```

---

## 4 建模

```powershell
& "$R\run.ps1" build -Dxf .\part.dxf -Depth 8 -Name DEMO-01 -Counterbore 3.4
```

`-Counterbore` 只给**正面**沉孔深度；写「反面」的那组由 `apply_spec.py` 从图注写进
`part_segments.json` 的 `back_counterbores`，不用传参。

```
反面沉孔：4 处 φ6.6，沉口 φ11▽3.4
盲孔：2 处 φ5 深 5
band z0~3.4   (18个元素) segs=18 -> ok 凸台-拉伸1
band z3.4~4.6 (18个元素) segs=18 -> ok 凸台-拉伸2
band z4.6~5   (18个元素) segs=18 -> ok 凸台-拉伸3
band z5~8     (16个元素) segs=16 -> ok 凸台-拉伸4
  volume 173,559.8 mm3
GATE build: PASS
```

**每段 `(N个元素)` 必须等于 `segs=N`**。最后一带只有 16 个元素，少的就是那 2 个 5mm 深盲孔——
它们只到 z=5，这一带里没有它们。**"最后一带少两个"正是盲孔做对的证据**；
反过来 `segs` 比预期少，是圆被草图推理吞了。

体积和阶段 3 的 175096.3 差 −1536.5 mm³，两笔能对上：8 个沉口多切 1654.3，
2 个盲孔少切 117.8（原来按通孔切了 8mm，实际只到 5mm）。**对不上就说明还有别的几何变了。**

---

## 5 验收（四道门，顺序不能换）

```powershell
& "$R\run.ps1" verify -Spec .\drawing_spec.json -Step .\out\DEMO-01.STEP `
                      -Segments .\part_segments.json -Part .\out\DEMO-01.SLDPRT -OutDir .\out
```

```
图注                            要求   实得   判定
2 × φ5 盲孔▽5                    2     2     OK
4 × φ6.6 通孔 正面⌴φ11▽3.4        4     4     OK
4 × φ6.6 通孔 反面⌴φ11▽3.4        4     4     OK
[汇总] 图注 3 条全部对上，问题 0 项
GATE verify.spec: PASS

正面沉孔 4 处 ['下(z=0.0)']   反面沉孔 4 处 ['上(z=8.0)']
[汇总] 问题 0 项
GATE verify.holes: PASS
GATE verify.depth: PASS
GATE verify.views: PASS
GATE verify: PASS
```

三处必须同时成立：

1. 每个沉孔位都有**两个直径**（只出现 `φ11` 一个 = 沉孔丢了）；
2. 大直径段贴端面：`0.0~3.4` 或 `4.6~8.0`，不能 `2.0~5.4`；
3. 正面组和反面组**不在同一个面**（两行都是 `下` = 只做了一个面）。

第一次跑某零件时，顺手证明这道门是活的：

```powershell
& $PY "$R\scripts\diagnostics\gate_selftest.py" .\drawing_spec.json .\out\DEMO-01.STEP
# 末行：[PASS] 验收器是活的：正确模型通过，5 类变异全部报错
```

最后**用眼睛看两张图**（`out\DEMO-01-后视看z0面.PNG`、`out\DEMO-01-前视看zmax面.PNG`），
两面必须互补：z0 面四角是台阶孔、中间一排是直孔，z8 面正好反过来。
只看一张 = 之前漏掉整面沉孔的原因。

---

## 6 交付

```powershell
& "$R\run.ps1" deliver -Spec .\drawing_spec.json -Step .\out\DEMO-01.STEP `
                       -Segments .\part_segments.json -To "<目标目录>\DEMO-01" -Mass 0.47
```

`deliver` 会**再跑一次** `spec_verify`（不过就拒绝复制），然后把
`SLDPRT / STEP / PNG / 两张面视图 / drawing_spec.json / part_segments.json / 验收记录.md`
一起放过去。

`验收记录.md` 是自动生成的证据页：图注逐条要求 vs 实得、包围盒、体积、质量偏差、
分段拉伸日志、结论。

---

## 一次性跑完整条链（参数齐全时）

```powershell
$R="C:\path\to\pdf-to-3d-pipeline"
& "$R\run.ps1" preflight
& "$R\run.ps1" spec  -Pdf .\part.pdf
& "$R\run.ps1" dwg   -Pdf .\part.pdf -PartWidth 200
& "$R\run.ps1" part  -Dxf .\part.dxf -Depth 8 -Mass 0.47 -Name DEMO-01
& "$R\run.ps1" build -Dxf .\part.dxf -Depth 8 -Name DEMO-01 -Counterbore 3.4
& "$R\run.ps1" verify -Spec .\drawing_spec.json -Step .\out\DEMO-01.STEP `
                      -Segments .\part_segments.json -Part .\out\DEMO-01.SLDPRT -OutDir .\out
& "$R\run.ps1" deliver -Spec .\drawing_spec.json -Step .\out\DEMO-01.STEP `
                       -Segments .\part_segments.json -To "…\DEMO-01" -Mass 0.47
```

任一阶段 `STOP`，后面都不要执行——先把这一关修绿。
