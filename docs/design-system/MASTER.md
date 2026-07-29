# Docling WebUI - Master Design System

> 全局设计源文件。所有页面共享此基础。页面级 Override 在 `pages/<page>.md` 中仅写差异。
> 最后更新：2026-07-22 | 设计师：颜好看

## 全局设计参数

- **设计寄存器**：Product（内部工具）
- **三轴刻度**：Variance=4 / Motion=3 / Density=5
- **对标品牌**：Linear / Vercel / GitHub
- **主题**：Dark-first（默认深色，可切换浅色）
- **图标库**：Lucide React（ISC 许可，16/20/24px，2px stroke）

## Token 引用

所有 Token 定义见 `design-tokens.css` 和 `design-tokens.json`。

### 核心 Token 速查

| Token | Dark | Light |
|-------|------|-------|
| --bg | #0D1117 | #F9FAFB |
| --surface | #161B22 | #FFFFFF |
| --surface-warm | #21262D | #F3F4F6 |
| --fg | #F0F6FC | #111827 |
| --muted | #8B949E | #6B7280 |
| --accent | #2563EB | #2563EB |
| --border | #30363D | #E5E7EB |
| --success | #3FB950 | #16A34A |
| --warn | #D29922 | #D97706 |
| --danger | #F85149 | #DC2626 |

## 组件规范速查

| 组件 | 圆角 | 内边距 | 背景 | 边框 |
|------|------|--------|------|------|
| Primary Button | 8px | 10px 16px | var(--accent) | 无 |
| Secondary Button | 8px | 10px 16px | var(--surface-warm) | 1px var(--border) |
| Input | 8px | 8px 12px | var(--surface) | 1px var(--border) |
| Card | 12px | 20px | var(--surface) | 1px var(--border) |
| Badge | 6px | 2px 8px | 语义色 12% opacity | 无 |
| Modal | 16px | 24px | var(--surface) | 无 |

## 页面导航结构

| 页面 | 路由 | 侧边栏图标 | 说明 |
|------|------|-----------|------|
| 上传/新建任务 | /upload | Upload (Lucide) | 拖拽上传图片/ZIP |
| 任务列表 | /tasks | List (Lucide) | 所有任务列表+筛选 |
| 任务详情 | /tasks/:id | - | 原图+解析结果+LLM表格 |
| 设置 | /settings | Settings (Lucide) | Docling API + LLM 配置 |

## 变更记录

| 日期 | 变更 | 原因 | 影响范围 |
|------|------|------|----------|
| 2026-07-22 | 初始创建 | 项目启动 | 全局 |
