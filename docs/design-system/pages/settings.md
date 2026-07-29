## 页面：设置

- 路由：`/settings`
- 布局：单列居中，最大宽度 `max-w-2xl` (672px)，左侧子导航（锚点跳转）

### 核心组件

1. **页面标题区**
   - 标题："设置"（--text-2xl, --font-weight: 590）

2. **子导航**（左侧粘性，锚点跳转）
   - Docling 服务（Server 图标）
   - LLM 配置（Brain 图标）
   - 解析默认值（Sliders 图标）
   - 外观（Palette 图标）
   - 关于（Info 图标）

3. **Docling 服务配置区**
   - 标题："Docling 服务"（--text-lg, --font-weight: 590）+ 描述
   - 服务地址：输入框（placeholder "http://localhost:5001"）
   - API Key（可选）：密码输入框 + 显示/隐藏切换
   - 连接测试按钮（Secondary）+ 状态指示器
     - 测试中：Spinner
     - 成功：Check-circle 图标 + "连接正常"（--success）
     - 失败：Alert 图标 + "无法连接"（--danger）
   - 高级选项（折叠面板）：
     - 默认 OCR 引擎：下拉（auto / tesseract / easyocr / rapidocr）
     - PDF 后端：下拉（dlparse_v4 / dlparse_v3）
     - 表格模式：单选（快速 / 精准）
     - 强制 OCR：开关
     - 图片导出模式：单选（embedded / referenced）

4. **LLM 配置区**
   - 标题："LLM 大模型"（--text-lg, --font-weight: 590）+ 描述
   - 启用 LLM 增强：开关（关闭时以下字段禁用）
   - API Base URL：输入框（placeholder "https://api.openai.com/v1"）
   - API Key：密码输入框
   - 模型名称：输入框（placeholder "gpt-4o"）+ 下拉推荐
   - 默认提示词：文本域（"提取所有表格数据并结构化整理为 Markdown 格式"）
   - 测试按钮（Secondary）+ 状态指示器
   - Token 消耗统计：今日已用 N tokens（--text-sm, --muted）

5. **解析默认值区**
   - 标题："解析默认值"（--text-lg, --font-weight: 590）
   - 默认输出格式：复选框组（Markdown / JSON / HTML）
   - 默认表格提取模式：单选
   - 最大并发任务数：数字输入框（默认 3，范围 1-10）
   - 文件大小上限：数字输入框（默认 50MB）
   - 自动删除已完成任务：开关 + 天数输入（默认 30 天）

6. **外观区**
   - 标题："外观"（--text-lg, --font-weight: 590）
   - 主题：三选一卡片（深色 / 浅色 / 跟随系统）
     - 选中态：边框 var(--accent) + 背景 rgba(37,99,235,0.04)
   - 界面语言：下拉（简体中文 / English）

7. **关于区**
   - 标题："关于"（--text-lg, --font-weight: 590）
   - 版本号：v1.0.0
   - Docling 版本：（从 API 获取）
   - GitHub 链接（ExternalLink 图标）
   - 开源许可

8. **底部操作栏**（粘性底部）
   - 保存按钮（Primary）+ 重置按钮（Ghost）
   - 未保存更改时：保存按钮高亮 + 离开页面确认提示

### 交互

- 修改任何配置 → 保存按钮变为可点击态（--accent 高亮）
- 连接测试 → 点击后 Spinner → 2s 内显示结果
- 主题切换 → 即时预览，不需保存
- 离开未保存 → Modal "有未保存的更改，确定离开？"
- 保存成功 → Toast "设置已保存"（--success 色，右下角，3s 自动消失）

### 响应式

- 桌面（≥1024px）：左侧子导航 + 右侧表单
- 平板/手机（<1024px）：子导航变为顶部 Tab，表单全宽

### 状态覆盖

- **Loading**：连接测试中 Spinner
- **Empty**：首次使用时所有字段为空 + placeholder 引导
- **Error**：连接失败显示错误详情 + 重试
- **Populated**：已保存的配置完整展示
- **Edge**：API Key 输入框超长时水平滚动，不撑破布局
