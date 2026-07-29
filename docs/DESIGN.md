# Docling WebUI 设计规范 (DESIGN.md)

> 生成日期：2026-07-22 | 设计师：颜好看 | 基于：用户需求 + 架构文档
> 三轴刻度：Variance=4 / Motion=3 / Density=5
> 设计寄存器：Product（内部工具，设计服务产品）

## 1. Visual Theme & Atmosphere（视觉主题与氛围）

**视觉主题关键词**：冷静、精准、数据驱动、高效、专业

**氛围描述**：深色为主、数据高亮、极简边框、信息密度适中。整体风格参照 Linear / Vercel 的开发者工具美学——专业感来自克制的色彩和精确的对齐，而非装饰性元素。

**对标品牌**：
- **Linear** — 深色背景 + 单一强调色 + 极简边框 + 紧凑信息密度
- **Vercel** — 纯黑背景 + 高对比文字 + 功能性动效
- **GitHub** — 开发者熟悉的深色配色 + 清晰的层级结构

**设计寄存器判断**：Product 寄存器。这是内部工具，设计服务产品。克制色彩策略（中性色 + 一个强调色 ≤10%），Sans-Serif 为主，功能性动效（150ms 收敛值），无装饰性动画。

## 2. Color Palette & Roles（色彩与角色）

### A1-identity 颜色

| Token | 值 | 用途 |
|-------|-----|------|
| `--bg` | `#0D1117` | 页面背景（GitHub dark） |
| `--surface` | `#161B22` | 卡片/容器背景 |
| `--surface-warm` | `#21262D` | 三级表面（侧边栏、表头） |
| `--fg` | `#F0F6FC` | 主文本色 |
| `--fg-2` | `#D0D6E0` | 次级文本色 |
| `--muted` | `#8B949E` | 副文本/标签 |
| `--meta` | `#484F58` | 元数据/占位符 |
| `--border` | `#30363D` | 默认边框 |
| `--border-soft` | `rgba(255,255,255,0.06)` | 内部行分隔符 |
| `--accent` | `#2563EB` | 品牌强调色（Blue 600） |
| `--accent-on` | `#FFFFFF` | accent 背景上的前景色 |
| `--accent-hover` | `#1D4ED8` | 悬停态 |
| `--accent-active` | `#1E40AF` | 激活态 |

### A2-semantic 颜色

| Token | 值 | 用途 |
|-------|-----|------|
| `--success` | `#3FB950` | 成功状态（任务完成） |
| `--warn` | `#D29922` | 警告状态（处理中/部分失败） |
| `--danger` | `#F85149` | 错误状态（任务失败） |
| `--info` | `#2563EB` | 信息提示 |

### 每屏强调色使用规则

- 每屏最多 2 处可见的 `--accent` 使用
- 强调色仅用于：主 CTA 按钮、选中 Tab/导航项、关键数据高亮
- 标题用 `--fg`（纯白偏蓝），不用强调色
- 语义色仅用于状态指示，不作装饰

### 配色来源

基于 Linear 设计语言变体，主色从 Indigo 调整为 Blue（#2563EB），避免 AI 默认靛蓝色。深色背景采用 GitHub dark 配色（#0D1117），开发者熟悉且专业。

## 3. Typography（排版）

### 字体栈

```css
--font-display: "Inter", "Noto Sans SC", -apple-system, BlinkMacSystemFont, sans-serif;
--font-body: "Inter", "Noto Sans SC", -apple-system, BlinkMacSystemFont, sans-serif;
--font-mono: "JetBrains Mono", "Fira Code", "Cascadia Code", monospace;
```

### Google Fonts @import

```css
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Noto+Sans+SC:wght@400;500;700&family=JetBrains+Mono:wght@400;500&display=swap');
```

### 字号阶梯（8级）

| Token | rem | px | 用途 |
|-------|-----|----|------|
| `--text-xs` | 0.75rem | 12px | 标签、徽章、辅助信息 |
| `--text-sm` | 0.875rem | 14px | 正文（紧凑）、表格内容 |
| `--text-base` | 1rem | 16px | 正文（默认）、输入框 |
| `--text-lg` | 1.125rem | 18px | 三级标题、强调正文 |
| `--text-xl` | 1.25rem | 20px | 二级标题 |
| `--text-2xl` | 1.5rem | 24px | 一级标题 |
| `--text-3xl` | 2rem | 32px | 页面标题 |
| `--text-4xl` | 2.5rem | 40px | Hero 标题（极少使用） |

### 字重三级体系

| 级别 | 字重 | 用途 |
|------|------|------|
| Regular | 400 | 正文、描述 |
| Medium | 510 | 按钮文字、表头、小标题 |
| Semibold | 590 | 大标题、CTA |

### 字距规则

| 场景 | 字距 |
|------|------|
| 正文 (14-18px) | `0` |
| 小字 (11-13px) | `0.025em` |
| ALL CAPS | `0.06em` |
| 标题 (≥32px) | `-0.02em` |

### 行高

| 场景 | 行高 |
|------|------|
| 正文 | `1.5` |
| 标题 | `1.25` |
| 展示标题 | `1.1` |

## 4. Components（组件规范）

### 图标系统

- **图标库**：Lucide React（`lucide-react` npm 包）
- **许可证**：ISC（免费商用，无需署名）
- **尺寸规范**：16px（行内）/ 20px（按钮内）/ 24px（独立图标）
- **描边**：2px（默认），统一全项目
- **颜色**：通过 `currentColor` 继承文本色
- **禁止**：不混用其他图标库，不使用 emoji 作为功能图标

### 按钮（4 种变体 × 5 种状态）

**Primary Button**（主操作：提交、确认）
- 背景：`var(--accent)` | 文字：`var(--accent-on)`
- 圆角：`var(--radius-md)` (8px) | 内边距：10px 16px
- Hover：`var(--accent-hover)` | Active：`var(--accent-active)`
- Disabled：`opacity: 0.4` + `cursor: not-allowed`
- Loading：Spinner 图标 + 文字置灰
- Focus：`var(--focus-ring)`

**Secondary Button**（次要操作：取消、返回）
- 背景：`var(--surface-warm)` | 文字：`var(--fg)` | 边框：`var(--border)`
- Hover：背景 `rgba(255,255,255,0.08)`

**Ghost Button**（幽灵操作：筛选、排序）
- 背景：透明 | 文字：`var(--muted)`
- Hover：背景 `rgba(255,255,255,0.06)`

**Danger Button**（危险操作：删除）
- 背景：`var(--danger)` | 文字：`#FFFFFF`
- Hover：`#DA3633` | Active：`#B62324`

### 输入框

- 背景：`var(--surface)` | 边框：`var(--border)` | 文字：`var(--fg)`
- 圆角：`var(--radius-md)` (8px) | 内边距：8px 12px
- Focus：边框 `var(--accent)` + `var(--focus-ring)`
- Error：边框 `var(--danger)` + 错误环
- Disabled：背景 `rgba(255,255,255,0.03)` + 文字 `var(--meta)`
- Placeholder：`var(--meta)`

### 卡片

- 背景：`var(--surface)` | 边框：`1px solid var(--border)`
- 圆角：`var(--radius-lg)` (12px) | 内边距：`var(--space-5)` (20px)
- 无默认阴影（`--elev-ring` 仅有 1px 边框环）
- Hover：边框色变为 `var(--meta)`（仅可交互卡片）
- 禁止：`border-left` 彩色强调 + 大模糊阴影同时出现

### 表格

- 表头背景：`var(--surface-warm)` | 表头文字：`var(--muted)` + `font-weight: 510`
- 行高：48px | 行分隔：`1px solid var(--border-soft)`
- 行 Hover：`rgba(255,255,255,0.03)`
- 行选中：`rgba(37,99,235,0.08)`
- 等宽字体用于数字列：`var(--font-mono)`

### 导航

- **侧边栏**（桌面端）：宽 260px | 背景 `var(--bg)` | 右边框 `1px solid var(--border)`
- 导航项：高 36px | 圆角 6px | 文字 `var(--muted)` | 图标 20px
- 激活态：背景 `rgba(37,99,235,0.12)` | 文字 `var(--fg)`
- Hover：背景 `rgba(255,255,255,0.06)`
- **移动端**：底部 TabBar，5 个标签上限，图标 24px + 文字 12px

### Badge / Tag

- 圆角：`var(--radius-sm)` (6px)
- 内边距：2px 8px
- 状态色：success/warn/danger 各有背景色（12% opacity）+ 文字色

### Modal / Dialog

- 背景：`var(--surface)` | 圆角：`var(--radius-xl)` (16px)
- 阴影：`var(--elev-overlay)`
- 遮罩：`rgba(0,0,0,0.5)` + `backdrop-filter: blur(4px)`
- 最大宽度：`max-w-lg` (512px) / `max-w-2xl` (672px)

### Toast

- 位置：右下角 | z-index：`var(--z-toast)`
- 背景：`var(--surface-warm)` | 圆角：`var(--radius-md)`
- 动画：从右滑入，150ms

## 5. Layout & Spacing（布局与间距）

### 间距基准

4px 网格：`4 / 8 / 12 / 16 / 20 / 24 / 32 / 40 / 48 / 64 / 80`
禁止非标值（5, 7, 13, 15, 22, 30 等）。

### 布局结构

```
┌─────────────────────────────────────────────────┐
│  Sidebar (260px)  │  Main Content Area          │
│                   │                              │
│  [Logo]           │  ┌──────────────────────┐   │
│  [Nav Items]      │  │  Page Header         │   │
│                   │  │  Title + Actions     │   │
│  [Settings]       │  ├──────────────────────┤   │
│                   │  │  Page Content        │   │
│                   │  │                      │   │
│                   │  └──────────────────────┘   │
└─────────────────────────────────────────────────┘
```

- 侧边栏宽度：260px（可折叠至 64px）
- 主内容区最大宽度：1440px
- 内容区内边距：32px（桌面）/ 24px（平板）/ 16px（手机）
- 网格系统：12 列 / gap 24px

### 响应式断点

| 断点 | 宽度 | 布局策略 |
|------|------|----------|
| xs | <640px | 单列，底部 TabBar |
| sm | ≥640px | 单列或双列 |
| md | ≥768px | 双列，侧边导航可见 |
| lg | ≥1024px | 完整侧边栏 + 多列 |
| xl | ≥1280px | 完整布局 |

## 6. Depth & Elevation（深度与阴影）

### 三级层级

| 层级 | 值 | 用途 |
|------|-----|------|
| Flat | `none` | 默认（按钮、输入框） |
| Ring | `0 0 0 1px var(--border)` | 卡片、容器（1px 边框环） |
| Raised | `0 1px 3px rgba(0,0,0,0.12), 0 1px 2px rgba(0,0,0,0.08)` | 悬浮卡片、下拉菜单 |
| Overlay | `0 8px 24px rgba(0,0,0,0.24), 0 2px 8px rgba(0,0,0,0.16)` | 模态框、Toast |

### Z-Index 层级

| 层级 | 值 | 用途 |
|------|-----|------|
| Base | 0 | 正常文档流 |
| Dropdown | 1000 | 下拉菜单 |
| Sticky | 1100 | 粘性表头 |
| Overlay | 1200 | 遮罩层 |
| Modal | 1300 | 模态框 |
| Toast | 1400 | Toast 通知 |
| Tooltip | 1500 | 工具提示 |

### 深色模式层级表达

通过亮度递进表达层级（非阴影）：
- 背景：`#0D1117` → `#161B22` → `#21262D`
- 文本：`#F0F6FC` → `#D0D6E0` → `#8B949E` → `#484F58`
- 边框：`rgba(255,255,255,0.06)` → `#30363D`

## 7. Do's & Don'ts（设计守则）

### ✅ 应该做的

1. 用 Design Token 引用所有颜色、间距、圆角、阴影
2. 图标统一使用 Lucide React，尺寸 16/20/24px
3. 状态色仅用于状态指示（success/warn/danger）
4. 深色背景通过亮度递进表达层级
5. 表格数字列使用等宽字体 `var(--font-mono)`
6. 所有交互元素支持键盘导航和 focus-visible
7. 加载状态使用骨架屏或进度条
8. 空状态提供引导文案和操作按钮

### ❌ 不应该做的

1. 禁止 emoji 作为功能图标
2. 禁止紫色→粉色渐变（#7C3AED / #A855F7 / #EC4899 任意渐变组合）
3. 禁止默认靛蓝色 #6366F1 作为强调色
4. 禁止 `border-left` 彩色强调 + 大模糊阴影同时出现
5. 禁止 `background-clip: text` 渐变文字
6. 禁止装饰性毛玻璃（仅功能性半透明允许）
7. 禁止圆角 ≥24px（卡片上限 12px，按钮 8px）
8. 禁止 "Welcome to" / "Lorem ipsum" / 空洞占位文案
9. 禁止动画超过 300ms（功能动效收敛值 150ms）
10. 禁止硬编码颜色值（唯一例外：#fff #000）

## 8. Responsive & Accessibility（响应式与无障碍）

### 响应式策略

- **Mobile-first**：从小屏开始设计，逐步增强
- **断点行为**：
  - <768px：底部 TabBar 导航，单列布局，侧边栏隐藏
  - 768-1024px：侧边栏可折叠，双列布局
  - >1024px：完整侧边栏 + 多列布局
- **触摸目标**：最小 44×44px，按钮间距 ≥8px

### 无障碍

- **对比度**：正文 ≥ 4.5:1（--fg #F0F6FC on --bg #0D1117 = 15.4:1 ✓）
- **键盘导航**：Tab 顺序符合视觉顺序，所有交互元素可达
- **Focus 可见**：`:focus-visible` 显示 `var(--focus-ring)`（3px 蓝色半透明环）
- **ARIA**：图标按钮必须有 `aria-label`，动态内容有 `aria-live`
- **prefers-reduced-motion**：禁用所有动画和过渡

### 5 态覆盖

| 状态 | 设计要求 | 示例 |
|------|----------|------|
| Loading | 骨架屏/进度条/Spinner | 任务列表骨架屏、上传进度条 |
| Empty | 引导文案 + CTA | "暂无任务，上传图片开始解析" |
| Error | 错误分类 + 重试 + 降级 | "Docling 服务连接失败，点击重试" |
| Populated | 内容展示 + 交互操作 | 任务列表完整展示 |
| Edge | 边界处理 + 截断 + 安全阀 | 超长文件名省略、100+ 任务分页 |

## 9. Agent Implementation Guide（实现指南）

### Tailwind Config

```json
{
  "theme": {
    "extend": {
      "colors": {
        "bg": "var(--bg)",
        "surface": "var(--surface)",
        "surface-warm": "var(--surface-warm)",
        "fg": "var(--fg)",
        "fg-2": "var(--fg-2)",
        "muted": "var(--muted)",
        "meta": "var(--meta)",
        "border": "var(--border)",
        "border-soft": "var(--border-soft)",
        "accent": "var(--accent)",
        "accent-on": "var(--accent-on)",
        "accent-hover": "var(--accent-hover)",
        "success": "var(--success)",
        "warn": "var(--warn)",
        "danger": "var(--danger)"
      },
      "fontFamily": {
        "display": "var(--font-display)",
        "body": "var(--font-body)",
        "mono": "var(--font-mono)"
      },
      "fontSize": {
        "xs": "0.75rem",
        "sm": "0.875rem",
        "base": "1rem",
        "lg": "1.125rem",
        "xl": "1.25rem",
        "2xl": "1.5rem",
        "3xl": "2rem",
        "4xl": "2.5rem"
      },
      "spacing": {
        "1": "4px",
        "2": "8px",
        "3": "12px",
        "4": "16px",
        "5": "20px",
        "6": "24px",
        "8": "32px",
        "10": "40px",
        "12": "48px",
        "16": "64px",
        "20": "80px"
      },
      "borderRadius": {
        "sm": "6px",
        "md": "8px",
        "lg": "12px",
        "xl": "16px"
      },
      "boxShadow": {
        "ring": "var(--elev-ring)",
        "raised": "var(--elev-raised)",
        "overlay": "var(--elev-overlay)",
        "focus": "var(--focus-ring)"
      },
      "transitionDuration": {
        "fast": "100ms",
        "base": "150ms",
        "slow": "200ms",
        "page": "300ms"
      },
      "zIndex": {
        "dropdown": "1000",
        "sticky": "1100",
        "overlay": "1200",
        "modal": "1300",
        "toast": "1400",
        "tooltip": "1500"
      }
    }
  }
}
```

### CSS 变量引用方式

```css
/* 直接引用 CSS 变量 */
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
}

/* Tailwind class 方式（推荐） */
/* <div className="bg-surface border border-border rounded-lg p-5"> */
```

### 已知坑提醒

1. 深色模式下 `box-shadow` 不如边框明显——优先用边框表达层级
2. `backdrop-filter: blur()` 在 Safari 需要 `-webkit-` 前缀
3. Lucide React 图标默认 `aria-hidden="true"`，图标按钮需手动加 `aria-label`
4. `color-mix()` 函数在某些旧浏览器不支持，用预定义的 hover/active 值
5. 等宽字体用于数字列时，设置 `font-variant-numeric: tabular-nums` 保持对齐
