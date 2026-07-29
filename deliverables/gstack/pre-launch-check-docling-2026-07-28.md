# Docling WebUI 上线前全检报告（代码审查 + 安全审计 + QA 测试）

**日期**：2026-07-28
**场景**：上线前检查（Pre-launch Check）
**参与成员**：产品评审员（gstack-product-reviewer，代码审查 / review skill）、安全官（gstack-security-officer，OWASP+STRIDE）、QA 与发布负责人（gstack-qa-lead，qa skill）

> 对照基准：2026-07-24 全检（`pre-launch-check-docling-2026-07-24.md`）。本次为三成员独立并行作业后的主理人汇总收口。

---

## 📌 TL;DR（执行摘要）

- **整体结论：🔴 No-Go（任何联网 / 局域网 / 公网暴露部署禁止上线）**
- 仅在「严格网络隔离的内网 / 单机 + 绑定 127.0.0.1 + 明确禁止暴露」前提下，可评估为 **🟠 条件 Go**，但须先解除下方阻塞项。
- **根因**：全站**零身份认证与鉴权**，叠加三个未认证即可远程利用的 Critical 漏洞（SSRF 窃取生产 LLM Key、SSRF 探测内网/云元数据、配置被任意篡改）。
- **阻塞项数量**：🔴 6（Critical）+ 🟠 10（High，其中 4 项条件阻塞）= 16 项需上线前处理。
- **正向项**：SQL 全部参数化（无注入）；ZIP 路径穿越有防护；已知 aiofiles 500 已修复；前端重写为原生 JS 并全面 `escapeHtml`（客户端 XSS 已解）；依赖版本已锁定；容器内端口统一 8001；实时核心链路（上传→OCR→LLM 汇总表→导出）冒烟全绿。
- **下一步**：先完成 P0 修复集（鉴权 + 出站白名单 + 导出转义/Zip Slip + 处理卡死 + 最小测试套件），复测并跑 `pip-audit`/`trivy` 无高危后，再评估条件 Go。

---

## 🎯 核心结论卡片

| 项目 | 内容 |
|------|------|
| Go / No-Go | 🔴 No-Go（联网暴露）；🟠 条件 Go（隔离内网/单机） |
| 严重度分布 | 🔴 6 / 🟠 10 / 🟡 16 / 🟢 5 |
| 关键行动项 | 16 条（P0 × 6，P1 × 5，P2 × 5） |
| 建议负责人 | 安全官（鉴权/SSRF/容器）、产品评审员（XSS/并发/契约）、QA（测试/卡死/发布工程） |
| 复测门槛 | 修复阻塞项 + `pip-audit`/`trivy` 无高危 + 最小 E2E 测试套件通过 |

---

## 1. 各成员核心结论

### 🔍 产品评审员（代码审查 / review skill）
- **核心判断**：核心业务流程正确、SQL 无注入、ZIP 穿越有防护、已知 500 已修；但**全站零鉴权 + HTML 导出存储型 XSS + 配置/探测端点 SSRF + LLM Key 经 URL 泄露**四类问题使项目只能「条件放行（本地单用户）」。
- **关键建议**：最小放行补丁集 = B2（html.escape 转义）+ B4（list_llm_models 改 POST）+ M1（异步读）+ M2（复用 OpenAI 客户端）+ M3（batch_id 处理锁）。其余排期。

### 🛡️ 安全官（OWASP Top 10 + STRIDE）
- **核心判断**：「存在多个未经认证即可远程利用的严重漏洞，必须修复阻塞项后方可上线」。最危险的是 `GET /config/llm-models?base_url=攻击者` 会用**已保存的真实 LLM Key** 向攻击者主机发请求并带 `Authorization: Bearer <真实Key>`，直接失窃生产密钥；`test-docling` 可打 `169.254.169.254` 云元数据。
- **关键建议**：先加统一鉴权中间件（覆盖全部写操作）；出站请求加方案+目的地址白名单、禁/限 `follow_redirects`、探测接口不再回退保存 Key；HTML 导出全局转义 + CSP；全局限流 + 解压后真实体积校验；容器非 root + 安全头 + `.env` 移出版本库。

### ✅ QA 与发布负责人（QA 测试 + 发布就绪 / qa skill）
- **核心判断**：**QA 健康分 55/100**，🔴 No-Go 与整体一致。实时冒烟（:8001）全绿，但**零自动化测试**、**OCR 处理卡死**（重启后 `processing` 文件永不入队）、**镜像只打 latest**、**compose 拓扑 ≠ 已验证拓扑** 均为发布就绪缺口。导出 Zip Slip 与 HTML/CSV 注入经代码确认仍开放。
- **关键建议**：P0 补最小 E2E 冒烟套件（含 Zip Slip 回归）；修复导出安全（F-A/F-B）与处理卡死（F-N1）；镜像打不可变 tag、明确真实拓扑、发布前基线备份 data/uploads 卷、加深 readiness 探针；给出命令级回滚预案。

---

## 2. 阻塞项清单（上线前必须解除）

| # | 严重度 | 类别 | 阻塞条件 | 说明 | 来源 |
|---|--------|------|----------|------|------|
| BL-1 | 🔴 | 鉴权 | 联网/多用户 | 全站无认证鉴权，敏感文档全开放 | 安全 F-001 / 产品 B1 |
| BL-2 | 🔴 | SSRF | 联网/多用户 | 未认证 SSRF + 生产 LLM Key 外泄 | 安全 F-002 |
| BL-3 | 🔴 | SSRF | 联网/多用户 | 未认证 SSRF 探测内网/云元数据 | 安全 F-003 |
| BL-4 | 🔴 | 路径穿越 | 不可信用户可达 | 导出 Zip Slip（arcname 用原始文件名拼） | QA F-A |
| BL-5 | 🔴 | 可靠性 | 生产重启常见 | OCR 处理卡死（processing 文件重启后永不入队） | QA F-N1 |
| BL-6 | 🔴 | 发布工程 | 发布就绪 | 零自动化测试（无 pytest/CI） | QA F-N2 |
| BL-7 | 🟠 | XSS | 任何暴露 | HTML 汇总表导出未转义（存储型 XSS） | 安全 F-004 / 产品 B2 / QA F-B |
| BL-8 | 🟠 | 配置篡改 | 联网（随鉴权解决） | 未认证 PUT /config 篡改 Docling/LLM/并发 | 安全 F-007 |
| BL-9 | 🟠 | 密钥卫生 | 发布前 | LLM Key 经 URL 查询参数（落日志） | 安全 F-006 / 产品 B4 |
| BL-10 | 🟠 | CORS | 跨域暴露 | `allow_origins=["*"]` + `allow_credentials=True` | 安全 F-005 / 产品 B5 |
| BL-11 | 🟠 | 密钥存储 | 联网 | 密钥明文落库且无 ACL | 产品 B6 |
| BL-12 | 🟠 | 配置漂移 | 复用旧卷 | DB settings 覆盖 .env，复用旧 data 卷指向陈旧地址 | QA F-E |
| BL-13 | 🟠 | 发布工程 | 回滚可靠 | 镜像只打 `latest`，无不可变版本 | QA F-N4 |
| BL-14 | 🟠 | DoS | 匿名暴露升阻塞 | ZIP 炸弹（解压校验依赖攻击者可控元数据） | 安全 F-008 |
| BL-15 | 🟠 | DoS/资损 | 匿名暴露升阻塞 | 无限流 + 未认证高成本 OCR/LLM 调用滥用 | 安全 F-009 |
| BL-16 | 🟠 | 部署 | 须文档化 | compose 拓扑 ≠ 已验证拓扑（compose 不设 LLM_*） | QA F-N5 |

> 注：BL-1~BL-3 为安全官主导的「No-Go 根因」，不解除则严禁任何暴露部署。BL-4~BL-6 为 QA/安全交叉确认的硬阻塞。BL-7~BL-16 为条件/高优先阻塞。
>
> **实证更新（QA × 安全官交叉复现）**：BL-2（F-002）、BL-3（F-003）、BL-15（F-009）已在本环境【未认证】即**实弹确认可达**（SSRF 命中 + `Authorization` 头转发验证；40× 请求零 429），不再是代码路径推断，须优先修复。

---

## 3. 综合审查发现（去重合并，按严重度排序）

| # | 严重度 | 类别 | 位置 | 问题描述 | 建议 | 来源成员 |
|---|--------|------|------|----------|------|---------|
| 1 | 🔴 | 鉴权 | main.py:74-76；routers/* | 全站无身份认证/鉴权，所有 API 与页面匿名可调用 | 统一鉴权依赖覆盖全部 /api/v1/* 与敏感页 | 安全/产品 |
| 2 | 🔴 | SSRF | config.py:64-76→llm_service | 未认证 SSRF + 生产 LLM Key 外泄（回退到保存 Key）【实弹确认：未认证 GET 即把生效 Key 转发至攻击者 URL】 | 鉴权 + 出站白名单 + 探测接口不再回退保存 Key | 安全 |
| 3 | 🔴 | SSRF | config.py:79-105→docling_service | 未认证 SSRF 探测内网/云元数据（follow_redirects=True）【实弹确认：未认证 POST 即向任意外部 URL 出站，同等可打 169.254.169.254】 | 出站白名单 + 禁/限重定向 + 频控 | 安全 |
| 4 | 🔴 | 路径穿越 | export_service.py:29,34；batches.py:355-439 | 导出 Zip Slip（arcname 用原始 original_filename 拼 `../`） | arcname 前 `os.path.basename` + 拒绝 `..`/`/` | QA/产品 |
| 5 | 🔴 | 可靠性 | task_poller.py:63-95；main.py:31-38 | OCR 处理卡死：重启后 processing 文件永不入队，批次永久 processing | 启动恢复把 processing→pending；或重试超时文件 | QA |
| 6 | 🔴 | 发布工程 | 全仓库 | 零自动化测试（无 pytest/CI） | 补单元/集成/E2E + CI 门槛 | QA |
| 7 | 🟠 | XSS | batches.py:361-445；export_service | HTML 导出 filename/表值未 `escape`（存储型 XSS） | 全 `html.escape` + CSP；CSV 防公式注入 | 安全/产品/QA |
| 8 | 🟠 | 配置篡改 | config.py:39-61 | 未认证 PUT /config 篡改 Docling/LLM/并发（转向与 DoS） | 鉴权 + 配置白名单 + 数值范围校验 | 安全 |
| 9 | 🟠 | 密钥卫生 | config.py:64-73；api.js:81-82 | LLM Key 经 URL 查询参数传输（落访问日志） | 改 POST + body；避免日志打印 query | 安全/产品 |
| 10 | 🟠 | CORS | main.py:65-71 | `allow_origins=["*"]` + `allow_credentials=True` | 显式可信源；无跨域则去掉 credentials/通配 | 安全/产品 |
| 11 | 🟠 | 密钥存储 | setting_repo.py:18-26 | 密钥明文落库无加密/ACL | 加密存储或 Secret Manager；写操作鉴权 | 产品 |
| 12 | 🟠 | 配置漂移 | database.py:114-129；config.py | DB settings 覆盖 .env，复用旧卷指向陈旧地址 | 首启引导/校验；发布前重置卷或 PUT 校正 | QA |
| 13 | 🟠 | 发布工程 | Dockerfile；compose | 镜像只打 `latest`，无不可变版本 | 构建打 `<语义版本或 git SHA>` 并保留旧 tag | QA |
| 14 | 🟠 | DoS | upload_service.py:80-125 | ZIP 炸弹：解压体积校验依赖攻击者可控元数据 | zf.read 后按真实 len 校验 + 总量硬上限 | 安全 |
| 15 | 🟠 | DoS/资损 | main.py（无限流） | 无限流 + 未认证高成本 OCR/LLM 滥用【实弹确认：40×/20× 快速循环全 200、零 429，后端仅 CORS 中间件无限制器】 | 全局+按端点限流；LLM 预算/配额 | 安全 |
| 16 | 🟠 | 部署 | docker-compose.yml:39-45 | compose 拓扑 ≠ 已验证拓扑（不设 LLM_*） | 参数化 LLM_* 或文档声明仅 OCR | QA |
| 17 | 🟡 | 性能 | docling_service.py:35-36 | 同步阻塞读大文件阻塞事件循环 | aiofiles / run_in_executor | 产品/安全 |
| 18 | 🟡 | 资源泄漏 | llm_service.py:83-84 | AsyncOpenAI 客户端从不 aclose（连接池泄漏） | 模块级单例或 `async with` | 产品 |
| 19 | 🟡 | 并发 | batches.py:251-303；queue_scheduler | 重复处理并发未防（server.log 实证批次两次启动） | batch_id 处理锁；API 入口即置 processing | 产品 |
| 20 | 🟡 | 校验 | config.py:39-61 | max_concurrent_conversions=0 致静默死锁 | 数值范围/正整数校验 | 产品 |
| 21 | 🟡 | 性能/UX | files.py:276-312 | rerun-ocr 同步阻塞最长 ~10min 且无超时 | 改入队异步 + 流式校验大小 | 产品/QA |
| 22 | 🟡 | 一致性 | batches.py:60-90 | create_batch 下游失败落盘文件变孤儿 | try/except 清理或先建 DB 再写盘 | 产品 |
| 23 | 🟡 | 契约 | schemas.py:143-144；batches.py:275 | ocr_engine/table_mode 被接受但忽略（误导） | 实现按批次覆盖或文档说明仅全局 | 产品 |
| 24 | 🟡 | 正确性 | batches.py:516,532 | CSV 双 BOM（write("\ufeff") + utf-8-sig） | 去掉手动 BOM 或改用 utf-8 | QA/产品 |
| 25 | 🟡 | 加固 | Dockerfile（无 USER） | 容器以 root 运行 | 非 root + cap_drop + no-new-privileges + 资源限制 | 安全 |
| 26 | 🟡 | 安全头 | main.py | 缺失 CSP/HSTS/X-Frame-Options 等 | 中间件统一下发 | 安全 |
| 27 | 🟡 | 上传校验 | file_utils.py:20-23 | 仅按扩展名校验，内容类型未验证 | python-magic 校验真实 MIME | 安全 |
| 28 | 🟡 | 信息泄露 | .env（入库）；config.py:27 | .env 入库 + GET /config 回显内网拓扑 | .env 移出版本库；地址脱敏 | 安全 |
| 29 | 🟡 | 部署 | docker-compose.yml:46 | depends_on 无 condition: service_healthy | 加 service_healthy | QA |
| 30 | 🟡 | 可观测性 | main.py:79-81；Dockerfile:35 | 健康检查仅存活探针（不校验 DB/Docling） | 加深 readiness | QA |
| 31 | 🟡 | 兼容性 | docling_service.py:72,76 | `asyncio.get_event_loop()` 已弃用 | 改用 `get_running_loop()` | 产品 |
| 32 | 🟢 | 卫生 | task_poller.py / docling_service.py 等 | 死代码（未调用函数/导入） | 清理 | 产品 |
| 33 | 🟢 | 卫生 | backend/data/docling_serve.db | 孤儿 DB（代码仅引用 docling_webui.db） | 删除孤儿文件 | QA |
| 34 | 🟢 | 文档漂移 | overview.md / STATUS.md | overview 仍写 React18 + "LLM 必须"（与现状不符） | 统一三份文档 | QA/产品 |
| 35 | 🟢 | 正确性 | batches.py:170 | batch_delete 计数含不存在 id | 修正计数逻辑 | 产品 |
| 36 | 🟢 | 卫生 | export_service.py:23-98 | 导出临时文件依赖 BackgroundTasks，断连可能残留 | 显式清理 + 大小上限 | 产品 |

---

## 4. 回滚预案（Rollback Plan，命令级，来自 QA 评估）

**触发条件**：健康检查连续失败 >2min；5xx/Traceback 突增；Docling/LLM 不可达致核心链路中断；DB 损坏或批次状态错乱（含处理卡死无法自愈）。

**前置要求（发布前必做）**：备份 `webui-data`、`webui-uploads` 两个卷（含 `-wal`/`-shm`）：
```bash
# 卷名来自 docker-compose.yml
docker run --rm -v webui-data:/data -v $(pwd):/backup alpine \
  sh -c "cd /data && tar czf /backup/webui-data-$(date +%Y%m%d%H%M).tar.gz ."
docker run --rm -v webui-uploads:/data -v $(pwd):/backup alpine \
  sh -c "cd /data && tar czf /backup/webui-uploads-$(date +%Y%m%d%H%M).tar.gz ."
```

**回滚步骤**：
```bash
cd <repo>
docker compose down
# 1) 镜像回滚到上一不可变 tag（当前只打 latest，须曾保留旧 tag 或 git 回退重 build）
docker build -t docling-webui:<上一稳定版本> .   # 或 docker tag docling-webui:<old> docling-webui:latest
# 2) 数据恢复（覆盖卷，含 -wal/-shm）
docker run --rm -v webui-data:/data -v $(pwd):/backup alpine \
  sh -c "cd /data && tar xzf /backup/webui-data-<基线>.tar.gz"
# 3) 重启
docker compose up -d
# 4) 冒烟验证
curl -fsS http://localhost:8001/api/v1/health
curl -fsS http://localhost:8001/api/v1/batches
```

**RTO / RPO**：RTO ≈ 5–10 分钟（切旧镜像）/ 15 分钟（重 build）；RPO = 上次手动备份（当前无自动备份，建议发布前基线 + 重要操作前备份）。迁移为向前追加式，旧镜像忽略新增列，**回滚一般安全**；`uploads/` 与 `data/` 均为卷持久化，回滚不破坏用户文件。

**金丝雀监控要点（摘要）**：`/health` 连续 2min 非 200 告警；5min 内 >5 次 5xx/Traceback 告警；OCR 全失败且非用户文件问题告警；Docling/LLM 不可达 >1min 告警；单批次 processing >15min 告警（命中卡死）；队列积压持续 >并发数且 10min 不降告警；容器 mem >1.5GB 或 OOM 告警。指标全绿且无新增异常 → 放量；否则触发回滚。

---

## ✅ 行动清单（具体可执行项）

| # | 行动 | 负责方 | 紧急度 | 期望完成 |
|---|------|--------|--------|----------|
| 1 | 引入统一鉴权中间件（API Key/会话）覆盖全部 /api/v1/* 与配置写操作 | 安全官 | P0 | 发布窗口内 |
| 2 | 出站请求加方案+目的地址白名单、禁/限 `follow_redirects`、探测接口不再回退保存 Key | 安全官 | P0 | 发布窗口内 |
| 3 | HTML 导出全局 `html.escape` + CSP；LLM Key 改 POST body 不再经 URL | 产品评审员+安全官 | P0 | 发布窗口内 |
| 4 | 修复导出 Zip Slip（arcname basename + 拒绝 `..`/`/`），并补 Zip Slip 回归测试 | QA | P0 | 发布窗口内 |
| 5 | 修复 OCR 处理卡死（启动恢复 processing→pending 或重试超时文件） | QA | P0 | 发布窗口内 |
| 6 | 补齐最小自动化测试套件（单元+集成+E2E 导出安全）作为发布门槛 + CI | QA | P0 | 发布窗口内 |
| 7 | 全局限流 + 解压后真实体积校验（ZIP 炸弹） | 安全官 | P1 | 复测前 |
| 8 | 容器非 root + 安全响应头 + `.env` 移出版本库 | 安全官 | P1 | 复测前 |
| 9 | 配置数值范围校验；镜像打不可变 tag；depends_on service_healthy；健康检查加深 ready | QA/产品 | P1 | 复测前 |
| 10 | 明确真实部署拓扑（参数化 LLM_* 或文档声明仅 OCR）；发布前基线备份 data/uploads 卷 | QA | P1 | 发布前 |
| 11 | 同步阻塞读→异步；AsyncOpenAI 复用/关闭；batch_id 处理锁防重复 | 产品评审员 | P1 | 复测前 |
| 12 | 死代码清理、API 契约一致、文档统一（overview/STATUS/README） | 产品评审员 | P2 | 后续迭代 |
| 13 | CSV 双 BOM 修复；batch_delete 计数修正；孤儿 DB 清理 | 产品评审员/QA | P2 | 后续迭代 |
| 14 | 上传内容类型校验（python-magic）；CORS 收敛 | 安全官 | P1 | 复测前 |
| 15 | 密钥加密存储或走 Secret Manager；GET /config 内部地址脱敏 | 安全官/产品 | P1 | 复测前 |
| 16 | CI 增加 `pip-audit` + `trivy` 扫描门禁（HIGH/CRITICAL 阻断）；本环境工具缺失，须在 CI runner 安装后执行 | 安全官 | P0 | 发布硬性前置 |
| 17 | 阻塞验证清单 B-S1~B-S5 全绿（SSRF 白名单 / 限流 / 真实解压体积上限 / 扫描门禁） | 安全官+QA | P0 | 发布门槛 |

---

## ⚠️ 待完善 / 已知局限

- 本次为**只读静态审查 + 实时冒烟 + 部分动态复现**：SSRF/Key 外泄（F-002）、SSRF 内网（F-003）、无限流（F-009）已由 QA 在**未认证**条件下实弹复现确认（详见下文「实测复现证据」）；动态复现均在隔离内联监听完成，未外泄真实 Key。
- 依赖/镜像漏洞扫描（`pip-audit`/`trivy`）**本 QA 环境未安装工具，未能执行**；列为发布硬性 CI 门禁（行动 16/17），未通过不得发布。已知 python-multipart==0.0.9 已含 CVE-2024-24762 修复。
- 产品评审员与 QA 均确认 SQL 参数化、ZIP 穿越有防护、前端客户端 XSS 已解决（原生 JS `escapeHtml`），这些不在阻塞项内。
- 镜像仅 `latest` 标签，回滚依赖曾保留旧 tag 或 git 回退重 build（行动 13/9）。
- 当前服务运行于 :8001，已验证可用拓扑为「外部 Docling 10.0.0.22:5001 + 外部 DeepSeek 兼容 LLM 10.0.0.22:6016」，与 compose 默认拓扑不一致，发布前须明确。

---

## 🔬 实测复现证据（QA × 安全官交叉验证，未认证条件）

| 项 | 复现方式 | 结果 | 阻塞 |
|----|----------|------|------|
| F-002 SSRF + 生产 Key 外泄 | 未认证 `GET /api/v1/config/llm-models?base_url=攻击者URL`，内联监听捕获请求头 | ✅ 确认：服务端把生效 Key 经 `Authorization: Bearer` 转发至攻击者 URL（本环境 `llm_api_key_set=true`） | 🔴 |
| F-003 SSRF 内网/元数据 | 未认证 `POST /config/test-docling` docling_base_url=攻击者URL，监听捕获 `GET /health`（UA=python-httpx/0.27.2） | ✅ 确认：未认证即向任意外部 URL 出站（同等可打 `169.254.169.254/latest/meta-data`） | 🔴 |
| F-009 无限流/资损 | 40× /health + 20× /config 快速循环 | ✅ 确认：全部 200、零 429；后端仅 CORSMiddleware 无限制器 | 🔴 |
| F-008 ZIP 炸弹 | 构造 file_size=1、真实解压 5MB 的 ZIP 上传 | ⚠️ 本运行时被拒（CPython 3.13 按声明 size 截断 + CRC 校验 → 400）；但校验仅信声明头字段 + 无硬上限（max_zip_size=200MB）+ 无限流，仍构成磁盘耗尽 DoS 路径 | 🟠 |
| 依赖/镜像扫描 | 尝试运行 `pip-audit`/`trivy` | ⚠️ 本环境未安装工具，未能执行 | 🔴（须 CI 门禁） |

> 说明：F-002 复现使用 dummy key 覆盖，刻意未外泄真实生产 Key；bomb.zip 为测试产物未写入磁盘。

## ✅ 阻塞验证清单（发布前必须全绿，来自交叉验证）

- [ ] **B-S1（F-002）**：`/config/llm-models`、`/config/test-llm`、`/config/test-docling` 加认证；`base_url` 仅允许服务端已配置地址，禁 `169.254.169.254`/内网/公网任意地址；`llm-models` 不接受外部 base_url，绝不外发配置 Key。
- [ ] **B-S2（F-003）**：`test-docling` 的 `docling_base_url` 白名单校验，禁 SSRF。
- [ ] **B-S3（F-009）**：全局限流（slowapi Limiter）+ 每 IP/用户上传配额与并发上限；`rerun-llm`/`rerun-ocr`/`process` 等计费接口限流 + 计费保护。
- [ ] **B-S4（F-008）**：上传校验改为基于真实解压字节流计数硬上限（边解压边计数，超阈值即中断），不依赖声明 file_size；配合每 IP 配额。
- [ ] **B-S5（扫描门禁）**：CI 增加 `pip-audit -r backend/requirements.txt`、`trivy image`（基础镜像 + docling-serve 镜像，HIGH/CRITICAL 阻断）；本环境缺工具，须 CI runner 安装后执行。

---

## 📚 成员产出索引

- gstack-product-reviewer（产品评审员）原始产出：代码审查报告 — 执行摘要 + 按严重度发现表（B1–B6 / M1–M9 / L1–L5）+ Go/No-Go 建议。结论：条件 Go（本地单用户），联网 No-Go。
- gstack-security-officer（安全官）原始产出：安全审计报告 — STRIDE 威胁建模 + OWASP Top 10 检查表 + 发现表（F-001~F-017）+ 阻塞项清单 + Go/No-Go。结论：No-Go。
- gstack-qa-lead（QA 负责人）原始产出：QA 与发布就绪报告 — 测试覆盖评估 + 发布清单 + 金丝雀计划 + 回滚预案 + 发现表（F-A/F-B/F-N1~F-N12）+ Go/No-Go（并补充与安全官交叉**实弹复现** F-002/F-003/F-008/F-009 及 B-S1~B-S5 阻塞验证清单）。结论：🔴 No-Go（联网），🟠 条件 Go（隔离内网）。

---

> 本报告由软件工坊 AI 协作生成（主理人：沽思航 / GStack CEO）。关键决策请由工程负责人复核。
