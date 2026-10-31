# 文案 — 名字、一句话、市场描述

> 这一页是可直接粘贴的文案仓库。改名字时三处必须同时改，否则技能要么触发不了、要么加载不了。

## 名字：一共四个，各管一件事

| 用在哪 | 值 | 说明 |
|---|---|---|
| 安装名 / npm 包名 | `dsh-pdf-3d-pipeline` | 装在 `node_modules` 下、写进 profile 的 `dependencies` 与 `bundles` |
| 插件 id | `pdf-3d-pipeline` | `cordis.patch.yml` 里那一行的 `id`，改它等于换一个插件位 |
| 技能名 | `pdf-to-3d-pipeline` | `SKILL.md` frontmatter 的 `name`，**必须等于目录名**，dsh 靠它扫到技能 |
| 中文名 | **图纸转三维流水线** | 给人看的。备选：「图纸建模流水线」「PDF 转 SolidWorks」 |
| CLI | `pdf3d` | `pdf3d doctor` / `link` / `run verify` |

## 一句话（中文，40 字内）

> 把工程图 PDF 变成 SolidWorks 零件，并且**拒绝交付孔开错面的模型**。

备选：

- 从 PDF 到 SLDPRT，每一步都有闸门，错件出不了门。
- 图纸进，零件出；中间八道关，一道不过就不许交付。

## 市场短描述（约 100 字，列表页用）

> 2D 工程图 PDF → 图注合同 → DWG/DXF → 分段拉伸 → SLDPRT/STEP → 对图注验收。
> 八道闸门串成一条链，最后一关拿图注逐条核孔径、通/盲、沉孔深度和**在哪一面**——
> 体积、质量、包围盒全对但沉孔做反了的模型，在这里过不去。

## 长描述（详情页用）

### 它解决的不是"画不出来"，是"画错了看不出来"

把图纸变成三维模型，模型软件自己能做一半。真正难的是这三件事，它们全都**不会报错**：

- **4 个反面沉孔一个都没做。** 那圈 φ11 只写在图注文字里，DWG 里根本没有这个圆，
  几何解析永远看不到它。体积、质量、包围盒、孔数全部正常。
- **2 个 φ5 盲孔被打穿。** 图上和通孔画得一模一样，做穿了体积只多 0.07%（117.8 mm³）。
- **沉孔只做了一个面。** 正面 4 个、反面 4 个，正反面对调之后**体积分毫不差**。

这三个故障都在"所有数字都正常"的模型里漏过去过。所以这个包的重点不是建模脚本，
是那套让它们过不去的判据。

### 它怎么保证

1. **先抄图注，再建模。** `φ`、`⌴`、`▽` 在 PDF 里不是文字是矢量线，脚本按形状识别
   （φ 是 49 段闭环、⌴ 是 3 段开口 U、▽ 是横线加倒 V），产出一份 `drawing_spec.json` 当验收基准。
   有读不懂的图注就非零退出——漏一条，后面所有数字都会自洽地错下去。
2. **质量对不上不许开 SolidWorks。** 用图纸重量反算板厚，理论质量差 >1% 就是几何挑错了，
   回去修几何，不许调板厚凑数。
3. **分段拉伸。** 同一草图里出现"同心、异径"一对圆，拉伸会静默失效；板厚按每个孔的 z 区间
   自动切带，每带一次拉伸，任何一带草图中都没有同心异径对。
4. **验收对图注，不对几何。** 最后一道关逐条核：数量、孔径、通/盲、沉孔直径与深度、沉孔在哪一面。
   必须 `问题 0 项` 才允许复制交付。
5. **连验收器本身也要被验。** 变异测试会故意把盲孔加深 2mm、沉孔翻面、数量 +1、通孔改盲孔，
   四类变异必须全部被抓到。**一个永远返回"问题 0 项"的检查器，比没有检查器更危险。**

### 适合 / 不适合

适合：单视图 + 板类零件（等厚拉伸、通孔、沉孔、盲孔、腰形槽、圆角轮廓），图纸标了材质和重量。
不适合：多视图回转体、加强筋/拔模/变截面、铸件、装配体——遇到会直接说"不适用"，
不硬跑一个看着像的错模型。

### 装上之后

说一句"照这张图建个 3D"就够了。技能带 8 个阶段、每个阶段末行是机器可读的
`GATE <stage>: PASS|FAIL` 或 `STOP: <要修什么>`，退出码 0/1/2。
交付 7 件：SLDPRT、STEP、PNG、两张正反视图、图注合同、几何数据、自动生成的验收记录。

## 英文

**Short (npm / market list)**

> A dsh bundle that turns a 2D drawing PDF into a SolidWorks part — callouts → DWG → banded
> extrude → SLDPRT/STEP — and refuses to hand over a model whose counterbores are on the wrong face.

**Long (first paragraph of a detail page)**

> Volume, mass and bounding box can all be right while every counterbore sits on the wrong face:
> flipping the front and back counterbores changes the volume by exactly nothing. This bundle is
> built around that fact. It reads the callouts first (φ/⌴/▽ are vector paths in the PDF, not text),
> treats them as the only acceptance baseline, extrudes the plate in z-bands so no sketch ever holds
> a concentric pair, and gates delivery on a per-callout check of count, diameter, through/blind,
> counterbore depth **and which face it is on**. The checker is itself mutation-tested, because a
> gate that always returns "0 problems" is worse than no gate at all.

## 标签

中文：图纸建模、PDF 转 3D、2D 转 3D、SolidWorks、DWG、DXF、沉头孔、沉孔、盲孔、板类零件、机械设计、质检闸门

英文（`package.json` keywords 已含）：`deepseek-harness` `dsh` `dsh-plugin` `skill` `cad`
`solidworks` `autocad` `pdf` `dwg` `dxf` `windows`

## 首屏可以用的三个数字

- **0.48%** — 少做整整一面（4 个）沉孔，体积只差这么多，还卡在 0.5% 的容差里，靠体积永远查不出来。
- **8 道** — 从预检到交付的闸门数，末行机器可读，不过就停。
- **3 次** — 为了搞清"为什么看起来全对"，实际返工的次数。
