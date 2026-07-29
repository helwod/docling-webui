## 页面：任务列表

- 路由：`/tasks`
- 布局：全宽内容区，表格 + 筛选栏

### 核心组件

1. **页面标题区**
   - 标题："解析任务"（--text-2xl, --font-weight: 590）
   - 右侧操作：筛选按钮（Ghost, Filter 图标）+ 新建任务按钮（Primary, Plus 图标 + "新建任务"）

2. **统计卡片栏**（3 个并排卡片）
   - 卡片 1：总任务数（大数字 --text-3xl + "个任务" 小字）
   - 卡片 2：处理中（数字 + Spinner 图标，--warn 色）
   - 卡片 3：已完成（数字 + Check-circle 图标，--success 色）
   - 卡片样式：var(--surface) 背景 + 1px var(--border) + 12px 圆角 + 20px 内边距

3. **筛选/搜索栏**
   - 左侧：搜索框（Search 图标 + placeholder "搜索文件名或任务 ID"）
   - 右侧：状态筛选 Tab（全部 / 处理中 / 已完成 / 失败）+ 时间范围下拉
   - Tab 样式：选中态背景 rgba(37,99,235,0.12) + 文字 var(--fg)，未选中文字 var(--muted)

4. **任务表格**
   - 表头：var(--surface-warm) 背景 + var(--muted) 文字 + font-weight: 510
   - 列：文件名 / 文件类型 / 状态 / 页数 / 创建时间 / 操作
   - 行高 52px，行分隔 1px var(--border-soft)
   - 行 Hover：背景 rgba(255,255,255,0.03)
   - 状态列：Badge 组件（圆点 + 文字）
     - 处理中：--warn 色 + Spinner
     - 已完成：--success 色 + Check 图标
     - 失败：--danger 色 + Alert 图标
     - 排队中：--muted 色 + Clock 图标
   - 文件类型列：文件图标 + 扩展名（如 "JPG", "ZIP"）
   - 时间列：相对时间（"3 分钟前"）+ hover 显示绝对时间 tooltip
   - 操作列：查看（Eye 图标）、导出（Download 图标）、删除（Trash2 图标，Danger 色）
   - 点击行 → 跳转任务详情页

5. **分页栏**
   - 底部固定：左 "共 N 条" + 右分页器
   - 分页器：上一页/下一页 + 页码（选中态 var(--accent)）

### 交互

- 点击 Tab 筛选 → 表格 150ms 淡入新数据
- 搜索输入 → 300ms 防抖后触发搜索
- 点击行 → 跳转 `/tasks/:id`
- 点击导出 → 下拉菜单（Markdown / JSON / HTML / ZIP 打包）
- 点击删除 → 确认 Modal "确定删除此任务？删除后无法恢复"
- 任务处理中 → 每 5s 自动刷新状态（或 WebSocket 推送）

### 响应式

- 桌面（≥1024px）：完整表格，所有列可见
- 平板（768-1024px）：隐藏"页数"列，文件名截断
- 手机（<768px）：卡片列表替代表格，每条任务一个卡片

### 状态覆盖

- **Loading**：表格骨架屏（5 行占位条），统计卡片显示 "--"
- **Empty**：中央插图区域 "暂无解析任务" + "上传第一张图片开始" 按钮
- **Error**：错误状态条 "加载失败，点击重试" + 重试按钮
- **Populated**：任务列表完整展示
- **Edge**：>100 条任务分页，超长文件名 `text-overflow: ellipsis`
