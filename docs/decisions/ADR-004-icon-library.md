# ADR-004: 锁定 Lucide React 作为唯一图标库

## Status: Accepted (2026-07-22)

## Background

项目 P0 规则要求：禁止使用 emoji 作为功能图标，必须锁定一套 SVG 图标库，全项目统一不混用。

候选图标库：Lucide React、Heroicons、Tabler Icons。

## Decision

选择 **Lucide React** 作为全项目唯一图标库，锁定版本 `^0.400`。

使用规则：
1. 所有 UI 图标必须使用 `lucide-react` 包中的 SVG 组件
2. 禁止使用 emoji 作为功能图标
3. 禁止混用其他图标库（Heroicons、Tabler Icons、Font Awesome 等）
4. 按需 import，利用 Tree-shaking 控制包体积
5. 图标样式统一通过 props 控制：`size`、`color`、`strokeWidth`

```typescript
// 正确用法
import { Upload, FileText, Download, Trash2 } from 'lucide-react';

<Upload size={20} color="currentColor" strokeWidth={2} />

// 错误用法（禁止）
<span>📎</span>  // 禁止 emoji
<HeroiconUpload />  // 禁止混用
```

## Consequences

### 正面后果
- 1700+ 图标覆盖所有场景需求
- Tree-shaking 完全支持，按需加载零冗余
- shadcn/ui 默认集成 Lucide，组件风格统一
- 可定制性强（size/color/strokeWidth）
- ISC 许可证，免费商用
- 社区活跃，持续更新

### 负面后果
- 图标风格偏极简，不适合需要多彩/拟物图标的场景（本项目不需要）
- 与 Tailwind CSS 集成需要手动设置 CSS 变量映射颜色

## Related ADRs
- ADR-001 (前端框架)
