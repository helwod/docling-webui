# ADR-001: 使用 React + Vite 作为前端框架

## Status: Accepted (2026-07-22)

## Background

Docling Serve WebUI 是一个个人/内部工具，用于批量图片 OCR 和 LLM 表格数据提取。前端需要实现文件上传、批次管理、结果查看和导出功能。无需 SEO，无需 SSR，纯内部使用。

需要在前端框架之间做出选择：React + Vite、Next.js 15、Vue 3 + Vite。

## Decision

选择 **React 18 + Vite 5** 作为前端框架。

技术栈：
- React 18 (UI 框架)
- Vite 5 (构建工具)
- TypeScript (类型系统)
- Tailwind CSS (样式)
- shadcn/ui (组件库)
- Lucide React (图标库)
- TanStack Query (服务端状态)
- Zustand (客户端状态)
- React Router (路由)
- Axios (HTTP 客户端)

## Consequences

### 正面后果
- React 生态最大，组件库和工具链选择最多
- Vite 构建极快（esbuild），开发体验优秀
- 纯 SPA 部署简单，只需静态文件服务器
- shadcn/ui 提供可复制粘贴的组件，代码完全可控
- TypeScript 提供类型安全
- TanStack Query 处理轮询场景（OCR 状态轮询）非常方便

### 负面后果
- 无 SSR，首屏加载需要等待 JS 执行（内部工具可接受）
- 需要自行处理路由（React Router），不像 Next.js 文件路由开箱即用
- 需要自行配置 API 代理（Vite proxy）

## Related ADRs
- ADR-002 (后端框架)
- ADR-004 (图标库)
