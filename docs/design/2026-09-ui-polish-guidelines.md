# 2026-09 UI Polish Guidelines — 视觉规范恢复稿

> 本文是恢复轮的**执行规范**：与 `2026-09-ui-polish-recovery-master.md`（为什么改）、
> `2026-09-ui-polish-bug-matrix.md`（改什么）配套，本文回答"改成什么样"。
> 现状基线：HEAD e22b082 + 15 个未提交工作区文件。token 词表以
> `twobyteasr/design/tokens.py` 为准（本文所有新维度都要落到那里，禁止散落字面量）。

## 1. Primary Font / Fallback / Weights

- **展示字体（主视觉）**：思源黑体 Heavy。随包资产 `assets/fonts/SourceHanSansSC-Heavy.otf`
  （当前唯一随包字体）。family 解析顺序（三处必须同源，统一从 `font_system.py`
  `SOURCE_HAN_FAMILY_ALIASES` 导出）：
  `"Source Han Sans SC Heavy" → "Source Han Sans CN Heavy" → "思源黑体 Heavy" → "思源黑体 SC Heavy" → "思源黑体"`。
- **正文字体**：`typography.UI_FONT_FAMILIES` 现状保留（SC → 思源黑体 → Microsoft YaHei UI
  → Segoe 系），常规字重。
- **字重语义（新增到 `tokens.py::WEIGHT_SCALE`，替换全部 QSS 字面量）**：

  | token | 值 | 用途 |
  |---|---|---|
  | regular | 400 | 正文、表格内容 |
  | medium | 500 | 次级按钮、输入框文字 |
  | semibold | 600 | 区块标题、卡标题、表头 |
  | bold | 700 | 主 CTA、强调数值、选中态 |
  | heavy | 800 | 页面主标题/hero/品牌展示位（思源 Heavy 面承载） |

- 850/750 等历史字面量一律收敛到上表（`grep font-weight` 清零为 token 引用或显式豁免注释）。
- **禁止把 Heavy 用于正文/小字**（会糊）；禁止全应用默认字体设为 Heavy。

## 2. Title / Section / Body / Meta Typography Rules

| 层级 | TYPE_SCALE | 字重 | 字体面 | 典型位置 |
|---|---|---|---|---|
| display | 28 | heavy 800 | 思源 Heavy | 首页 hero、导出成功标题 |
| heading1 | 22 | heavy 800 | 思源 Heavy | 页面主标题（sectionTitle/工坊标题/识别模型名） |
| heading2 | 18 | semibold 600 | 默认族 | 区块大标题、弹窗标题 |
| section | 14 | semibold 600 | 默认族 | 卡片组标题、设置分区 |
| body | 13 | regular 400 | 默认族 | 正文、表格 |
| small | 12 | regular 400 | 默认族 | 辅助说明 |
| caption | 11 | regular 400 | 默认族 | meta/时间戳/来源 |

- 同屏字重对比至少两档可见（标题 semibold/heavy vs 正文 regular）；如果一个表面里所有文字
  同字重，视为层级缺失。
- 现存 `main_ui_theme.py:856`（sectionTitle 800）、`ui.py:5120`（进度标题 800）等 800 字面量
  **是对的**，恢复方向是保住并 token 化，而不是被 control_qss 的 500 压平。

## 3. Button Variants and Foreground Rules

- 变体（`build_button_qss` 已有，补充**尺寸×字重**维度）：

  | 变体 | 高度 | 字号/字重 | padding | 用途 |
  |---|---|---|---|---|
  | primary + large（CTA 档） | ≥48 | 15-16px / bold 700 | 11×28 | 每个视图**至多一个** |
  | primary（默认档） | 36 | 14px / bold 700 | 8×20 | 表单确认 |
  | secondary | 36 | 13px / medium 500-600 | 8×16 | 次级动作 |
  | ghost / toolbar / icon | 28 | 13px / medium 500 | 0×4-12 | 工具栏、低频命令 |
  | danger | 36 | 13px / semibold 600 | 8×16 | 破坏性动作 |

- **前景规则（铁律）**：accent 变体的文字与图标颜色**只能**来自 `theme.text_on_accent`
  一个 token。`themed_icons.icon_role_color("on_accent")` 必须解析为 `text_on_accent`
  （2026-09-06 源码复核已满足；BM-04 残余在 `studio_theme.py` 工程卡普通态，runtime 待验证）；任何 QSS/代码里 `#fff`/`white`/`#1F1408` 出现在 accent 按钮上
  即违规。非 accent 变体前景用 `text`/`text_secondary`。
- 禁止在控件里自行 `setIcon(_icon(x, "white"))` 这类字面色（工作区已开始迁移，收尾）。
- 状态（hover/pressed/checked/disabled/focus）一律走 `build_button_qss` 状态机，不允许
  页面局部重写状态色。

## 4. Form Field Width Rules

- `FIELD_WIDTHS` 语义（已定义，落实到位）：`numeric`(80-144) 数值/时长；
  `compact`(120-240) 枚举/短下拉；`preferred`(180-360) **默认档**；`large`(240-520) 模型名/
  URL；`expanding` **仅限**真自由文本与文件路径。
- **禁止无脑 Expanding**：一个表单里 expanding 字段超过 2 个要自查；禁止对
  `findChildren(QLineEdit)` 批量设宽度（工作区 `studio_export_ui.py` 的一刀切要撤）。
- `QFormLayout::WrapLongRows` 只允许给标签可能很长的行单独开，不做全表默认。
- 字段高度跟按钮档位（28/36/44），输入框与同行按钮等高。

## 5. CTA Emphasis Rules

- 每个视图一个主 CTA；它是该视图**视觉权重第一**的元素：最大字号（≥15px）、最重字重
  （≥700）、accent 底+`text_on_accent` 前景、图标与文字同色、高度 ≥48。
- 主 CTA 旁边最多一个次级动作；其余进 overflow/ghost。识别页 actionBar：
  「开始生成字幕」primary-large，「字幕工作台」secondary，二者不再同规格。
- 判定法（ headed 截图 5 秒测试）：眯眼/缩小看，用户第一眼应落在主 CTA 上；
  否则视为失败。

## 6. Section Spacing / Density Rules

- 栅格：`SPACE_SCALE`(4,8,12,16,24,32)；区块间距 24、卡内边距 12-16、控件行距 8-12。
- 密度基调：**容器收紧、强调元素放大**。压缩内边距（如卡边距 13→8）必须同时放大卡内
  主文字号，否则不许合入。
- 卡片网格（hub 320 vs 356）之类整体缩放属 BM-07，需 A/B 裁定后定档，不许单文件悄悄改。

## 7. Dialog Shell Rules

- 目标壳：`SpringDialog + DialogSurface`（标题栏/关闭钮/body_layout/footer_layout），
  快捷键弹窗（工作区 `studio_shortcuts.py`）为样板。
- SpringDialog 的窗口级 `APP_QSS` 副本使其内部 `#primary` 为 15px/750——迁移弹窗时注意
  这是**偶然正确**，BM-06 落地后统一走按钮状态机。
- 弹窗必须有标题+关闭钮；footer 主右次左；危险动作 danger 变体且不设默认焦点。
- 存量裸 QDialog（API key 弹窗等）按 BM-09 清单逐个迁移，不做一次性大迁移。

## 8. Icon Consistency Rules

- 图标一律走 `install_themed_icon(widget, name, role)`（随主题重着色）；role 词表：
  `text/text_secondary/on_accent/danger/…`，与文字 token 同名同源。
- 同一行内图标视觉尺寸一致（工具栏 16-18、CTA 20-24）；禁止混用实心/线框风格于同组。
- `icon_background` 等死字段不消费就不写。

## 9. Color Semantic Rules

- 语义色只从 `p9a_tokens()` / ThemeDefinition 取；accent=主行动、success/warning/danger
  语义位不可挪用装饰。
- 大面积底色遵守 70/25/5（底/面板/强调）比例铁律（字幕主题契约 H 同源）。
- 两个主题世界并存是现状：首页暖色系与 Studio 暗色系**不合并**，但控制语言（按钮/字段/
  弹窗/图标）必须同一套——"同语言、不同方言"。

## 10. 禁忌项（不要再犯）

1. ❌ 在 `build_control_qss`/`build_surface_qss` 新增选择器前不查同名 ID 在
   APP_QSS/_global_qss/页面 QSS 的既有声明——这两块 sheet 在 app 级**最后拼接**，
   同特异度必胜（BM-01 事故机理）。
2. ❌ 给全部按钮统一一个字号/字重/高度（"统一"≠"相同"；是**分级**）。
3. ❌ accent 按钮上写字面色/图标色字面量（只能 `text_on_accent`）。
4. ❌ 字段无脑 Expanding / 批量 findChildren 设样式。
5. ❌ 把"现代化"理解成压平字重、缩小卡片、去掉装饰——用户要的是**层级对比**，
   不是均匀低权重。
6. ❌ 只改代码不 headed 取证就宣称"已修复/已统一"。
7. ❌ 顺手大包围式 UI 改动（一次只做一个 chunk，见 master §10）。
8. ❌ 不更新 worklog/bug-matrix 就结束 session。
