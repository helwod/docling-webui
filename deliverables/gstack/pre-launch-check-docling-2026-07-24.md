# 上线前全检报告 — Docling WebUI

**日期**：2026-07-24
**场景**：上线前检查（需求审查 + 代码审查 + 安全审计 + QA 测试与发布就绪）
**参与成员**：产品评审员（需求+代码审查）、安全官（OWASP+STRIDE）、QA 负责人（测试+发布就绪）

---

## 📌 TL;DR（执行摘要）

- **整体结论**：🔴 **不通过（禁止网络暴露部署）**。仅在 `localhost` 单机、单人、完全隔离（air-gapped）的开发/演示场景下可 🟡 条件运行。
- **阻塞项数量**：8（5 项安全/代码严重 🔴 + 3 项发布工程阻塞 🔴）。
- **下一步**：先修"鉴权 + SSRF + 上传安全 + 导出 Zip Slip / 注入"四道安全闸，再补"部署产物 + 端口/配置一致性"，方可进入受限内网试点；对外/生产发布前必须补齐 LLM 全链路验证、埋点、移动端适配。

> 三方独立结论：安全官 🔴 No-Go；产品评审员 🟡 条件通过；QA 负责人 🟡 条件性 Go（功能实测 8/8 全通，但发布工程有阻塞）。**上线决策以最严格的 🔴 为准。**

> **🔁 补充确认（product-reviewer 追加，经 security-officer 逐条复现）**：原报告注入面审查盲区已补——**全接口零鉴权（P0-a）** 与 **未鉴权 SSRF（P0-b）** 确认为最高优先级硬阻断项，已对应本报告 B1/B2。由此 🟡 放行条件须进一步收紧为：**网络严格隔离、无不可信主机可达、且实例不处于云元数据（169.254.169.254）可达环境**；任一不满足即为 🔴 No-Go。Zip Slip / 导出注入等技术上仍为 🔴 严重，但排期上归 P1、与鉴权/SSRF 同批修复。

---

## 🎯 核心结论卡片

| 项目 | 内容 |
|------|------|
| Go / No-Go | 🔴 No-Go（任何绑定 0.0.0.0 / 局域网 / 公网，或云元数据可达环境）；localhost 严格隔离演示 🟡 |
| 严重度分布 | 🔴 8（阻塞） / 🟠 7 / 🟡 13 / 🟢 4 |
| 关键行动项 | 8 条（详见行动清单） |
| 建议负责人 | 安全官 + 产品评审员 + QA 负责人 + 后端 Owner |

---

## 1. 各成员核心结论

### 🔍 产品评审员（需求审查 + 代码审查）
- **核心判断**：🟡 条件通过。核心 OCR 主链路可用（F1 上传/ZIP、F2 Docling 对接、F4 任务列表、F6 单图预览基本可用）；但 F3 LLM 全链路未用真实 Key 验证、F5 导出结构偏离 PRD（无 xlsx、非"每图一文件夹"）、NFR 缺口明显（Docker 部署 P0、数据埋点 P1、移动端兼容、i18n）。
- **关键建议**：① 修导出 **Zip Slip**（🔴，entry 名用 `original_filename` 客户端可控，含 `../` 可写出目标目录）；② 补 Docker 部署产物；③ LLM 输出做 pydantic 校验、导出 HTML 全 `html.escape`、CSV 防公式注入；④ 落地 PRD 埋点；⑤ 清理遗留 React `frontend/`，统一端口/地址文档。
- **代码审查 7 维度小结**：SQL 安全 ✅（全程参数化+动态列白名单）；LLM 信任边界 🔴（无校验+未净化渲染+提示注入）；条件副作用 🟡；错误处理 🟡（无重试+错误信封不一）；并发 🟡（调度竞态风险）；可观测性 🟡（埋点/指标缺失）；性能 🟡（大批次导出内存峰值高）。

### 🛡️ 安全官（OWASP Top 10 + STRIDE）
- **核心判断**：🔴 **No-Go**。根因是**全接口无任何身份认证与授权**，已逐文件确认（无 `HTTPBearer`/`OAuth2`/`Depends(auth)`/login）。在此根因之上，匿名攻击者可在未登录状态下上传任意文档触发解析链、通过配置接口把后端变成内网/云元数据 SSRF 跳板、篡改全局配置、删除数据、读取/导出他人文件。
- **关键建议**：① 全局鉴权中间件覆盖除 `/health` 外所有 `/api/v1/*`；② SSRF 防护——`base_url` 禁用户可控、协议/地址白名单、硬屏蔽 `169.254.169.254`/`127.0.0.0/8`/`10`/`172.16`/`192.168`/`0.0.0.0`、禁止随重定向跳内网；③ 上传内容/MIME 校验 + 沙箱低权限解析 + 资源上限 + 速率限制；④ 净化 LLM/导出渲染；⑤ CORS 收敛；⑥ 关 `--reload`、默认绑 `127.0.0.1` 或前置带鉴权反向代理；⑦ Gradio 加 `auth=` 并 `show_error=False`；⑧ 密钥不入库明文。

### ✅ QA 负责人（QA 测试 + 发布就绪）
- **核心判断**：🟡 **条件性 Go**。功能链路实测 **8/8 全通**（上传→解析→轮询→预览→导出 ZIP/CSV/HTML、LLM 表格整理连通），后端运行日志无 error，上游 Docling(`5001`)/LLM(`6016`) 可达；但存在 **3 项上线阻塞**（端口配置四处不一致、无部署产物、配置漂移导致全新环境开箱即废）+ 若干中/低危缺陷。
- **关键建议**：① 统一端口（建议 `8001`）到 `.env`/README/STATUS/代码；② 提供 `Dockerfile`+`docker-compose.yml`（或正式将"手动双进程"定为发布方式并写清步骤）；③ 首次启动配置引导/校验消除占位 key；④ 修 CSV 双 BOM；⑤ 锁定 `gradio_app` 依赖版本；⑥ 补 `.gitignore`；⑦ 发布前重置数据库 + 建立备份机制。

---

## 2. 综合审查发现（去重合并，按严重度排序）

| # | 严重度 | 类别 | 位置 | 问题描述 | 建议 | 来源 |
|---|--------|------|------|---------|------|------|
| 1 | 🔴 | 鉴权 | `main.py:62-73`；`routers/*` | 全接口无身份认证/授权，匿名可调用所有业务接口 | 全局鉴权中间件 + 按路由授权（除 `/health`） | 安全官 |
| 2 | 🔴 | SSRF | `config.py:64-91`；`llm_service.py:83-84`；`docling_service.py:24-25,49` | 未鉴权 SSRF：用户可控 `base_url` 直接喂后端客户端，可读云元数据/内网探活 | `base_url` 白名单 + 屏蔽 link-local/内网 + 禁重定向跳内网；config 写需管理员鉴权 | 安全官 |
| 3 | 🔴 | 上传安全 | `batches.py:53-90`→`upload_service.py`→`docling_service.py` | 任意文件上传（仅扩展名白名单，无内容校验）→ 触发 Docling 解析恶意文档（解析器 RCE/DoS 链） | 鉴权前置 + 内容/MIME 校验 + 沙箱解析 + 资源上限 | 安全官 |
| 4 | 🔴 | 路径穿越 | `export_service.py:29/34/50/55`；`batches.py:355-439` | 导出 ZIP entry 名由客户端可控 `original_filename` 直接拼接，含 `../` 可写出目标目录（Zip Slip） | 生成 arcname 前统一 `basename` + 拒绝 `..`/`/`；或改序号重命名 | 产品评审员 |
| 5 | 🔴 | 注入 | `batches.py:355-439`；`export_service.py:50/55` | 导出 HTML/CSV 注入：filename 与 LLM 表格值未 `html.escape` 直接拼接；CSV 未防 `=+-@` 公式注入 | 导出 HTML 全转义；CSV 前导危险字符加前缀 | 产品评审员 |
| 6 | 🔴 | 部署 | 仓库根 / `overview.md` | 无 `Dockerfile`/ `docker-compose.yml`，但文档宣称"Docker Compose 一键启动"为生产方式（实际 TODO） | 提供 Docker 部署产物，或正式声明手动双进程为发布方式并写清步骤 | 产品+QA |
| 7 | 🔴 | 配置 | `.env`/README/STATUS/`api_client.py` | 端口四处不一致（8000/8001 混用），照文档启动极易连不上 | 统一固定端口（建议 8001）到 `.env`/README/STATUS/代码 | QA |
| 8 | 🔴 | 配置 | `backend/.env` + `config.py` 配置漂移 | DB `settings` 表覆盖 `.env`；`.env` 仍为占位 key，全新部署首次启动不可用 | 首次启动配置引导/校验或种子脚本写入正确配置 | QA |
| 9 | 🟠 | XSS | `frontend/.../ResultPanel.tsx:161` | 存储型 XSS：LLM 返回含 `<script>` 经 `dangerouslySetInnerHTML` 渲染，管理员查看即执行 | DOMPurify 净化或结构化渲染，禁止直接渲染 LLM 输出 | 安全官 |
| 10 | 🟠 | XSS/LLM边界 | `llm_service.py` + `formatters.py` + `gr.Markdown` | LLM 返回 JSON 无模式校验，经允许内联 HTML 的 `gr.Markdown` 渲染 → 提示注入→存储型 XSS | pydantic 校验 LLM 输出；渲染前 HTML 净化 | 产品评审员 |
| 11 | 🟠 | 安全配置 | `main.py:62-68` | CORS `allow_origins=["*"]` + `allow_credentials=True` 反模式（加鉴权后即成漏洞） | 收敛到前端真实源；按需关 credentials | 安全官/产品 |
| 12 | 🟠 | 暴露面 | `config.py:15`(0.0.0.0)；`STATUS.md`(`--reload`) | 全接口绑 0.0.0.0 + 开发态 `--reload`，无鉴权即暴露 | 生产绑 127.0.0.1 或前置带鉴权反向代理；关 `--reload` | 安全官 |
| 13 | 🟠 | DoS | `batches.py:53`；`upload_service.py` | 无速率限制；`await file.read()` 先全量读内存再校验大小 | 加速率限制；流式/分块校验大小；全局上传上限 | 安全官 |
| 14 | 🟠 | DoS | `upload_service.py:90-120` | ZIP 炸弹防护不全：仅按头部声明 `file_size` 求和，单条解压无上限 | 限制单条解压后体积；真实解压预算；限制嵌套/总条目 | 安全官 |
| 15 | 🟠 | 依赖 | `gradio_app/requirements.txt` | 依赖未锁定（`gradio>=4.40` 等浮动范围），安装不可复现 | 锁定具体版本，与后端 `requirements.txt` 对齐 | QA |
| 16 | 🟠 | 错误处理 | `docling_service.py:_poll_task/convert` | 网络错误无重试（PRD 要求自动重试≤3 次），单次 `RequestError` 即失败 | 指数退避重试≤3 次，区分瞬时/终态 | 产品评审员 |
| 17 | 🟡 | 导出缺陷 | `batches.py:get_batch_table` | 导出 CSV 双 BOM（`write("\ufeff")` + `utf-8-sig`），严格解析器首列表头乱码 | 去掉 `write("\ufeff")` 或改 `utf-8` 编码 | QA |
| 18 | 🟡 | 安全配置 | `gradio_app/main.py:20-25` | Gradio `show_error=True` 泄露堆栈/内部路径 | 加 `auth=`；`show_error=False` | 安全官/产品 |
| 19 | 🟡 | 密钥 | `repositories/setting_repo.py` | LLM API Key 明文存 SQLite，DB 被读即泄露 | 加密/密钥管理（KMS/环境变量注入，不入库） | 安全官 |
| 20 | 🟡 | 内容校验 | `upload_service.py:33`；`file_utils.py:20-23` | 仅扩展名白名单，内容可为任意字节；`.html` 在白名单内 | 校验 magic/signature；可脚本类型单独处置 | 安全官 |
| 21 | 🟡 | 并发 | `queue_scheduler.py` + `docling_service.py` | 调度单实例 + 批次并发(5) + 信号量(5) 双重限流；`rerun_ocr` 与调度器在 processing 批次上可能竞态；SQLite 单连接复用 | `rerun` 仅允许 completed；评估 DB/写队列 | 产品评审员 |
| 22 | 🟡 | 可观测性 | 后端整体 / `gradio_app` | PRD P1 埋点缺失（无 trackEvent/analytics）+ 无指标；仅 logging | 落地 `trackEvent()`；后端加时延/失败指标 | 产品评审员 |
| 23 | 🟡 | 性能 | `batches.py:355-439` / `export_service` | 导出 ZIP 全量读内存再逐条 `zf.read`；大批次(100+图)内存峰值高 | 流式读取；大批次改后台任务+分块写盘 | 产品评审员 |
| 24 | 🟡 | 错误处理 | `schemas.py` + routers | API 错误信封不一致（成功 `{code:0,data}`，错误 `{detail:{code,message}}`） | 统一异常处理器包成同构信封 | 产品评审员 |
| 25 | 🟡 | 需求偏差 | PRD F5 / `export_service` | 导出结构偏离验收（无 .xlsx、非每图文件夹） | 引入 openpyxl 生成 xlsx，或更新 PRD 对齐 | 产品评审员 |
| 26 | 🟡 | NFR | PRD | 移动端兼容、i18n、降级（Docling 离线红绿点）未实现/未验证 | 补移动端响应式、i18n、连接状态指示 | 产品评审员 |
| 27 | 🟢 | 条件副作用 | `batches.py:147-167` | 批量删除逐条 `os.remove` 无事务，单文件失败被吞，可能残留磁盘文件 | 删除+软删放事务/补偿 | 产品评审员 |
| 28 | 🟢 | 代码异味 | `file_repo.py:60-91` | 动态列名 f-string 拼接 SET，但列名取白名单、值均参数化 → 实际安全 | 改显式字段映射消除误报 | 产品评审员 |
| 29 | ⚪ | 发布卫生 | 仓库根 / `backend/` / `data/` | 遗留 `nul` 文件、`tc_test.py` 混入交付目录；DB 预置 10 个测试批次（发布前须重置） | 清理；发布前重置/迁移 DB 为空 | QA |
| 30 | ⚪ | 文档漂移 | `overview.md`/`STATUS.md`/`README.md` | 端口与前端技术栈（React vs Gradio）描述与现状不符 | 统一三份文档 | QA/产品 |

---

## 🚧 阻塞项清单（上线前必须解除，共 8 项）

| 编号 | 阻塞项 | 严重度 | 负责方 |
|------|--------|--------|--------|
| B1 | 全接口无鉴权/授权 | 🔴 | 安全官 + 后端 |
| B2 | 未鉴权 SSRF（读内网/云元数据） | 🔴 | 安全官 + 后端 |
| B3 | 任意文件上传→Docling 解析链（RCE/DoS） | 🔴 | 安全官 + 后端 |
| B4 | 导出 Zip Slip（路径穿越写文件） | 🔴 | 产品评审员 + 后端 |
| B5 | 导出 HTML/CSV 注入 | 🔴 | 产品评审员 + 后端 |
| B6 | 缺部署产物（Docker/compose） | 🔴 | QA + 后端 |
| B7 | 端口配置四处不一致 | 🔴 | QA + 后端 |
| B8 | 配置漂移 / 首次启动不可用（占位 key） | 🔴 | QA + 后端 |

---

## ✅ 行动清单（8 条具体可执行项）

| # | 行动 | 负责方 | 紧急度 | 期望完成 |
|---|------|--------|--------|---------|
| 1 | 全局鉴权中间件（API Key/Session），覆盖除 `/health` 外所有 `/api/v1/*`；写操作需鉴权+授权 | 安全官 + 后端 | P0 | 上线前 |
| 2 | 封堵 SSRF：`base_url` 协议/地址白名单 + 硬屏蔽 link-local/内网 + 禁重定向跳内网；config 写需管理员鉴权 | 安全官 + 后端 | P0 | 上线前 |
| 3 | 导出安全修复：Zip Slip（`basename`+拒绝 `..`）+ HTML 全 `html.escape` + CSV 防公式注入 | 产品评审员 + 后端 | P0 | 上线前 |
| 4 | 上传内容/MIME 校验 + 沙箱低权限解析 + 资源上限 + 速率限制 | 安全官 + 后端 | P0/P1 | 上线前 |
| 5 | 补部署产物（`Dockerfile`+`docker-compose.yml`）或固化手动双进程部署 + 统一端口(8001) + 首次启动配置引导 | QA + 后端 | P0/P1 | 上线前 |
| 6 | 净化 LLM 输出（DOMPurify/pydantic 校验）+ CORS 收敛到前端源 | 产品评审员 + 前端 | P1 | 试点前 |
| 7 | 补 `.gitignore` + 锁定 `gradio_app` 依赖 + 修 CSV 双 BOM + 发布前重置 DB + 建立备份机制 | QA | P1 | 试点前 |
| 8 | 落地 PRD 埋点 + 移动端适配 + 更新 PRD 验收标准（导出结构/xlsx） | 产品评审员 | P2 | 生产前 |

---

## 🔄 回滚预案（来自 QA 负责人）

**回滚触发条件**
- 健康检查连续失败（`:8001/health` 或 `:7860` 非 200）超过 2 分钟；
- 错误率突增（后端日志大量 5xx / Traceback）；
- 上游 Docling(`5001`) 或 LLM(`6016`) 不可达导致核心链路中断；
- 数据损坏（SQLite 报错 / 批次状态错乱）。

**回滚步骤（当前为手动双进程，无编排）**
1. 停止服务：`taskkill` 后端 uvicorn 进程与 Gradio 进程（或对应 PID）。
2. 代码回退：若有 git，`git checkout <上一稳定 tag>` 或 `git revert`；重新安装依赖。
3. 数据恢复：以发布前备份覆盖 `backend/data/docling_webui.db`（连同 `-wal`/`-shm`），避免 WAL 残留导致版本错配。
4. 重启：先后端（`:8001`）后 Gradio（`:7860`）。
5. 验证：跑 QA 冒烟集（health / config / 创建一个测试批次 process→completed / 导出 zip）→ 全绿即恢复。

**预计耗时**：约 5–10 分钟（无容器编排，纯手动）。
**前置要求**：发布前必须**先对 `backend/data/*.db*` 做一次基线备份**（当前无自动备份机制，属缺口）。

---

## ⚠️ 待完善 / 已知局限

- 仓库非 git 工作区、无 PR/差异可比对，`review` skill 未适用；代码审查为静态手工，非增量 diff 审查。
- 安全结论基于**静态审计 + 威胁建模 + 代码逻辑复现**，未做动态 PoC 验证（SSRF/上传 RCE 未实弹打，属高概率真实风险面）。
- 浏览器级 UI 自动化未做（环境无浏览器驱动），UI 仅验证到服务可用（7860/200 + Gradio 标记）；交互契约（后端 API）已全量实测通过。
- LLM 表格整理全链路（含 xlsx）从未跑真实 Key；业务级验收（真实含表图片）未做（仅 1×1 测试 PNG）。
- 产品形态从 PRD 的"每图独立表格"变为"批次汇总表（每行=一个文件）"——核心交互模型变更，PRD 未同步更新，存在验收争议风险。
- QA 创建的测试批次已清理（批次总数回退为 10），未污染生产数据。

---

## 📚 成员产出索引

- **产品评审员（需求+代码）原始产出**：需求覆盖度矩阵（F1~F6 + NFR 缺口）、代码审查 7 维度表（含 Zip Slip 🔴、导出注入 🔴、LLM 信任边界 🔴、CORS/重试/并发/可观测性/性能/信封不一）、Top 5 行动项、Go/No-Go 倾向 🟡。
- **安全官（OWASP+STRIDE）原始产出**：总体态势 🔴 No-Go；3 项 🔴（F-01 无鉴权 / F-02 SSRF / F-03 上传解析链）；STRIDE 摘要；OWASP Top 10 逐项清单；13 项发现表（F-01~F-13）；Top 5 修复项；已确认的良性控制（UUID 重命名、ZIP basename、SQL 参数化、无硬编码密钥、无命令注入）。
- **QA 负责人（测试+发布）原始产出**：总体 🟡 条件性 Go；功能用例 8/8 通过；后端冒烟全绿且日志无 error；前端 Gradio 可启动（React 遗留可 build 但非交付物）；缺陷表（CSV 双 BOM / 依赖未锁 / 缺 .gitignore 等）；3 项阻塞；发布检查清单；回滚预案；Top 5 行动项。

---

> 本报告由软件工坊 AI 协作生成（主理人沽思航汇编），关键决策请由工程负责人复核。
