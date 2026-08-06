// 任务详情页逻辑
const params = new URLSearchParams(location.search);
const batchId = params.get("batch_id");
let batchTable = null; // 解析后的汇总表对象
let fileItems = []; // 当前批次文件列表
let currentFileId = null;
let currentSegments = []; // 当前文件的识别字段（带 bbox）
let currentPages = []; // 当前文件预览页列表 [{page_no, url}]
let isPdf = false; // 当前文件是否为 PDF
let loadedOcrStatus = null; // 上次加载详情时的 OCR 状态（用于自动刷新判断）
let recognizedMap = []; // 当前文件识别字段 [{key, value}]，用于右侧点击映射
let chatHistory = []; // 当前批次的 LLM 会话历史（基于汇总表，每行=一个文件）
let chatEditIndex = null; // 正在修改的用户消息 seq（null 表示普通发送）

const titleEl = document.getElementById("batch-title");
const metaEl = document.getElementById("batch-meta");
const summaryEl = document.getElementById("summary-table");
const summaryMsg = document.getElementById("summary-msg");
const fileListEl = document.getElementById("file-list");
const imageBox = document.getElementById("image-box");
const imgHint = document.getElementById("img-hint");
const ocrFields = document.getElementById("ocr-fields");
const rowTable = document.getElementById("row-table");
const ocrBox = document.getElementById("ocr-box");
const recognizedEl = document.getElementById("recognized-fields");

function parseBatchTable(raw) {
  if (!raw) return null;
  if (typeof raw === "object") return raw;
  try { return JSON.parse(raw); } catch (e) { return null; }
}

// 在汇总表首列注入真实文件名（与后端 _ensure_filename_column 对齐）
function ensureFilenameColumn(bt, items) {
  if (!bt || !bt.tables) return;
  if (bt.error) return;
  const tables = bt.tables;
  const table = tables[0];
  if (!table) return;
  const fnameMap = {};
  for (const f of items) fnameMap[f.id] = f.original_filename || "";
  const fileOrder = bt.file_order || [];
  let headers = Array.from(table.headers || []);
  if (headers.includes("文件名")) {
    const idx = headers.indexOf("文件名");
    headers.splice(idx, 1);
    for (const r of table.rows || []) {
      if (r && typeof r === "object" && !Array.isArray(r)) delete r["文件名"];
    }
  }
  headers.unshift("文件名");
  const newRows = [];
  for (let i = 0; i < (table.rows || []).length; i++) {
    const r = table.rows[i];
    const fid = fileOrder[i];
    const fname = fid ? fnameMap[fid] || "" : "";
    if (r && typeof r === "object" && !Array.isArray(r)) {
      newRows.push({ 文件名: fname, ...r });
    } else if (Array.isArray(r)) {
      const lst = Array.from(r);
      lst.unshift(fname);
      newRows.push(lst);
    } else {
      newRows.push([fname, r]);
    }
  }
  table.headers = headers;
  table.rows = newRows;
}

function renderTable(headers, rows) {
  if (!headers || !headers.length) return '<p class="muted">（无表头）</p>';
  const head = "<tr>" + headers.map((h) => `<th>${escapeHtml(h)}</th>`).join("") + "</tr>";
  let body = "";
  for (const r of rows || []) {
    let cells;
    if (r && typeof r === "object" && !Array.isArray(r)) {
      cells = headers.map((h) => `<td>${escapeHtml(r[h] ?? "")}</td>`);
    } else if (Array.isArray(r)) {
      cells = r.map((c) => `<td>${escapeHtml(c ?? "")}</td>`);
    } else {
      cells = [`<td>${escapeHtml(r)}</td>`];
    }
    body += "<tr>" + cells.join("") + "</tr>";
  }
  return `<table class="summary-table"><thead>${head}</thead><tbody>${body}</tbody></table>`;
}

function renderSummary() {
  if (batchTable == null) {
    summaryEl.innerHTML = '<p class="muted">尚无汇总表（处理批次后由 LLM 整理成「一张表，每行 = 一个文件」）。</p>';
    return;
  }
  if (batchTable.error) {
    summaryEl.innerHTML = `<p class="muted">汇总表生成失败：${escapeHtml(batchTable.error)}</p>`;
    return;
  }
  const tables = batchTable.tables;
  if (!tables || !tables.length) {
    summaryEl.innerHTML = '<p class="muted">汇总表为空（未能从文件中提取结构化数据）。</p>';
    return;
  }
  const table = tables[0];
  summaryEl.innerHTML =
    `<p class="hint">共 ${table.rows ? table.rows.length : 0} 行 × ${table.headers ? table.headers.length : 0} 列。</p>` +
    renderTable(table.headers, table.rows);
}

// 汇总表 LLM 调用记录，渲染进会话内容顶部（不单独显示）
let chatGenRecord = { prompt: null, reply: null };

function renderTableIO(batch) {
  chatGenRecord = {
    prompt: (batch && batch.table_prompt) || null,
    reply: (batch && batch.table_reply) || null,
  };
  // 记录不在此处单独渲染，避免与 loadChat 的 renderChat 重复渲染（导致加载变慢）；
  // load() 会紧接着调用 loadChat() -> renderChat() 统一渲染会话内容（含本记录块）。
}

// 调用记录展示上限（避免原始回复/提示词过大导致 innerHTML 渲染卡顿）
const RECORD_CAP = 8000;

function _capText(s) {
  if (s == null) return "（暂无记录）";
  const str = String(s);
  if (str.length <= RECORD_CAP) return escapeHtml(str);
  return escapeHtml(str.slice(0, RECORD_CAP)) + "\n…（内容较长，已截断显示）";
}

// 构建「本次汇总表 LLM 调用记录」块（显示在会话内容顶部）
function buildChatRecordHtml() {
  const { prompt, reply } = chatGenRecord;
  if (!prompt && !reply) return "";
  const p = _capText(prompt);
  const r = _capText(reply);
  return (
    `<div class="chat-record" id="chat-record">` +
    `<div class="chat-record-head">本次汇总表 LLM 调用记录（发起的提示词 / 原始回复）</div>` +
    `<div class="io-grid">` +
    `<div class="io-col"><h4>发起的（提示词）</h4><pre class="ocr">${p}</pre></div>` +
    `<div class="io-col"><h4>回复（原始响应）</h4><pre class="ocr">${r}</pre></div>` +
    `</div></div>`
  );
}

function renderRowForFile(fid) {
  if (!batchTable || !batchTable.tables || !batchTable.file_order) {
    rowTable.innerHTML = '<p class="muted">汇总表尚未生成。</p>';
    return;
  }
  const tables = batchTable.tables;
  const fileOrder = batchTable.file_order;
  const idx = fileOrder.indexOf(fid);
  if (idx < 0 || !tables[0].rows || idx >= tables[0].rows.length) {
    rowTable.innerHTML = '<p class="muted">该文件无对应行。</p>';
    return;
  }
  const headers = tables[0].headers;
  const row = [tables[0].rows[idx]];
  rowTable.innerHTML = renderTable(headers, row);
}

function renderFileList() {
  if (!fileItems.length) {
    fileListEl.innerHTML = '<span class="muted">（暂无文件）</span>';
    return;
  }
  fileListEl.innerHTML = fileItems
    .map((f) => {
      const st = STATUS_LABEL[f.ocr_status] || f.ocr_status;
      const active = f.id === currentFileId ? " active" : "";
      return (
        `<button type="button" class="filelist-item${active}" data-id="${f.id}">` +
        `<span class="fi-name">${escapeHtml(f.original_filename)}</span>` +
        `<span class="badge badge-${f.ocr_status}">${st}</span>` +
        `</button>`
      );
    })
    .join("");
  fileListEl.querySelectorAll(".filelist-item").forEach((btn) => {
    btn.onclick = () => selectFile(btn.getAttribute("data-id"));
  });
}

function selectFile(fid) {
  if (!fid || fid === currentFileId) return;
  currentFileId = fid;
  renderFileList();
  loadFileDetail(fid, true);
  // 会话跟随整个批次（而非单个文件），只在页面加载时加载一次，切文件不再重载
}

// 渲染预览页：单图或多页 PDF 都统一为「每页一个 .img-stage + overlay」
function renderStages(pages) {
  if (!pages || !pages.length) {
    imageBox.innerHTML = '<span class="muted">该文件无可预览的页面。</span>';
    return;
  }
  imageBox.innerHTML =
    '<div class="pdf-pages">' +
    pages
      .map(
        (p) =>
          `<div class="img-page" id="pg-${p.page_no}">` +
          `<div class="img-page-bar"><span class="page-no">第 ${p.page_no} 页</span></div>` +
          `<div class="img-stage">` +
          `<img class="preview" src="${p.url}" alt="第 ${p.page_no} 页" />` +
          `<div class="img-overlay" id="ov-${p.page_no}"></div>` +
          `<div class="img-markers" id="mk-${p.page_no}"></div>` +
          `</div>` +
          `</div>`
      )
      .join("") +
    "</div>";
}

// 清除所有页高亮，并在目标页画出高亮框，滚动到该页
function highlightSegment(seg) {
  document.querySelectorAll(".img-overlay").forEach((o) => (o.innerHTML = ""));
  document.querySelectorAll(".img-page").forEach((p) => p.classList.remove("active"));
  if (!seg || !seg.bbox) return;
  const ov = document.getElementById("ov-" + seg.page_no);
  if (!ov) return;
  const box = document.createElement("div");
  box.className = "hl";
  box.style.left = (seg.bbox.l * 100).toFixed(2) + "%";
  box.style.top = (seg.bbox.t * 100).toFixed(2) + "%";
  box.style.width = ((seg.bbox.r - seg.bbox.l) * 100).toFixed(2) + "%";
  box.style.height = ((seg.bbox.b - seg.bbox.t) * 100).toFixed(2) + "%";
  ov.appendChild(box);
  const pg = document.getElementById("pg-" + seg.page_no);
  if (pg) {
    pg.classList.add("active");
    pg.scrollIntoView({ behavior: "smooth", block: "center" });
  }
}

function renderFields(segments) {
  currentSegments = segments || [];
  if (!currentSegments.length) {
    ocrFields.innerHTML = '<span class="muted">（该文件无带坐标的识别字段，可展开下方「OCR 原文」查看全文。）</span>';
    return;
  }
  ocrFields.innerHTML = currentSegments
    .map(
      (s) =>
        `<div class="ocr-field" data-idx="${s.idx}" title="点击在左图高亮位置">` +
        escapeHtml(s.text) +
        `</div>`
    )
    .join("");
  ocrFields.querySelectorAll(".ocr-field").forEach((el) => {
    el.onclick = () => {
      const idx = Number(el.getAttribute("data-idx"));
      const seg = currentSegments.find((s) => s.idx === idx);
      ocrFields.querySelectorAll(".ocr-field").forEach((x) => x.classList.remove("active"));
      el.classList.add("active");
      highlightSegment(seg || null);
    };
  });
}

// 在中间 OCR 字段列表里高亮指定 idx 的片段（与右侧识别字段联动）
function markMiddleField(idx) {
  ocrFields.querySelectorAll(".ocr-field").forEach((x) => x.classList.remove("active"));
  const el = ocrFields.querySelector('.ocr-field[data-idx="' + idx + '"]');
  if (el) {
    el.classList.add("active");
    el.scrollIntoView({ behavior: "smooth", block: "center" });
  }
}

// 归一化：去空白、去常见标点、全角转半角、转小写，提升 OCR 噪声下的匹配鲁棒性
function normText(s) {
  if (!s) return "";
  return String(s)
    .replace(/\s+/g, "")
    .replace(/[，。．、：:；;（）()\[\]【】{}“”"''‘’·—_/\\|！!？?~～*]/g, "")
    .replace(/[０-９]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0xfee0))
    .replace(/[Ａ-Ｚａ-ｚ]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0xfee0))
    .toLowerCase();
}

// 最长公共子序列长度（用于近似匹配评分，容忍错别字/缺字）
function lcsLen(a, b) {
  const m = a.length, n = b.length;
  if (!m || !n) return 0;
  const dp = Array.from({ length: m + 1 }, () => new Int32Array(n + 1));
  for (let i = 1; i <= m; i++)
    for (let j = 1; j <= n; j++)
      dp[i][j] = a[i - 1] === b[j - 1] ? dp[i - 1][j - 1] + 1 : Math.max(dp[i - 1][j], dp[i][j - 1]);
  return dp[m][n];
}

// 提取连续数字段并去掉前导零（用于校验日期/编号类字段的数字一致性）
function digitSegs(s) {
  return (s.match(/\d+/g) || []).map((x) => x.replace(/^0+/, "") || "0");
}
// 判断 value 的数字段序列是否按相同顺序出现在 text 的数字段中（容忍 OCR 误识导致的零缺失/补零）
function digitsMatch(nv, nt) {
  const a = digitSegs(nv), b = digitSegs(nt);
  if (a.length === 0) return true; // 无数字则不做数字约束
  let j = 0;
  for (let i = 0; i < a.length; i++) {
    while (j < b.length && b[j] !== a[i]) j++;
    if (j >= b.length) return false; // value 尚有数字段但 text 已耗尽 → 数字不一致
    j++;
  }
  return true;
}

// 在 OCR 片段里为某个「识别字段值」找最匹配的片段，返回片段对象（含 page_no / bbox）。
// 定位依据（优先级从高到低）：
//   1) 归一化后精确相等；
//   2) 归一化后 值是片段的子串（OCR 整行包含字段值，最常见）→ 片段越短越精确；
//      单字字段（男/女/是/否等）仅限较短片段，避免误匹配整页长文本；
//   3) 归一化后 片段是值的子串（字段值较长，OCR 行只是其一部分）→ 片段越长越特异；
//   4) 归一化后最长公共子序列占比 ≥ 0.6 且数字段顺序一致的近似匹配（容忍 OCR 错别字/空格/全角半角/
//      日期数字规范化差异，例如 "2024.1.5" 与 "2024-01-05" 仍能定位到同一行）。
function findBestSegment(value, segments) {
  const v = (value || "").trim();
  if (!v || !segments || !segments.length) return null;
  const nv = normText(v);
  if (!nv) return null;
  let best = null;
  let bestScore = 0;
  for (const s of segments) {
    const t = (s.text || "").trim();
    if (!t) continue;
    const nt = normText(t);
    if (!nt) continue;
    let score = 0;
    if (nv === nt) {
      score = 1e6 + nv.length;                             // 精确相等（最高优先级）
    } else if (nt.includes(nv)) {
      // 值是片段子串：片段越短越精确；单字字段（男/女/是/否）仅限较短片段，避免误匹配超长行
      if (nv.length > 1 || nt.length <= 12) score = 1e5 + nv.length * 100 - nt.length;
    } else if (nv.includes(nt)) {
      score = 1e4 + nt.length;                             // 片段是值子串：片段越长越特异
    } else {
      const lcs = lcsLen(nv, nt);
      const ratio = lcs / Math.min(nv.length, nt.length);
      const maxLen = Math.max(nv.length, nt.length);
      // 近似匹配需数字段顺序一致，避免 "2024-01-05" 误命中 "合同编号 HT-2024-001" 这类仅数字巧合的行
      if (lcs >= 2 && ratio >= 0.6 && maxLen >= 3 && digitsMatch(nv, nt)) {
        score = 1000 + lcs * 10 * ratio;                  // 近似匹配（最低优先级）
      }
    }
    if (score > bestScore) {
      bestScore = score;
      best = s;
    }
  }
  return bestScore > 0 ? best : null;
}

// 用「字段名」在 OCR 片段里找标签行作为定位锚点（当字段值因 LLM 规范化改写而值匹配失败时兜底）。
// 例如字段名"签订日期"可命中 OCR 行"签订日期：2024.1.5"，从而定位到该字段所在行。
// 约束：字段名须在段的前半部分出现（标签通常在行首），且段不过长，避免误匹配正文长段。
function findBestSegmentByKey(key, segments) {
  const k = (key || "").trim();
  if (!k || !segments || !segments.length) return null;
  const nk = normText(k);
  if (nk.length < 2) return null; // 单字字段名（性别/金额等）不可靠，跳过
  let best = null;
  let bestScore = 0;
  for (const s of segments) {
    const t = (s.text || "").trim();
    if (!t) continue;
    const nt = normText(t);
    if (!nt) continue;
    const pos = nt.indexOf(nk);
    if (pos === -1) continue;
    if (pos > Math.floor(nt.length / 2)) continue;   // 字段名须在行首附近（标签位置）
    // 必须是「标签行」：字段名后紧跟标签分隔符（：: 空格 括号）或行尾，排除 "合同编号条款…" 这类正文
    const after = t.slice(t.indexOf(k) + k.length).trimStart();
    if (after && !/^[:：\s（）()【】\[\]]/.test(after)) continue;
    if (nt.length > nk.length + 60) continue;          // 标签行不会太长，过长视为正文
    const score = 1e5 - nt.length;                     // 段越短越像标签行，越精确
    if (score > bestScore) {
      bestScore = score;
      best = s;
    }
  }
  return bestScore > 0 ? best : null;
}

// 在左图叠加「识别字段」定位标记（蓝色编号），与中间 OCR 定位位置完全一致，点击可反查字段
function renderMarkers() {
  document.querySelectorAll(".img-markers").forEach((m) => (m.innerHTML = ""));
  if (!recognizedMap.length) return;
  recognizedMap.forEach((item, i) => {
    if (!item.seg) return;
    const mk = document.getElementById("mk-" + item.seg.page_no);
    if (!mk) return;
    const dot = document.createElement("div");
    dot.className = "img-marker";
    dot.style.left = (((item.seg.bbox.l + item.seg.bbox.r) / 2) * 100).toFixed(2) + "%";
    dot.style.top = (((item.seg.bbox.t + item.seg.bbox.b) / 2) * 100).toFixed(2) + "%";
    dot.textContent = String(i + 1);
    dot.title = `${item.k}：${String(item.v)}\n第 ${item.seg.page_no} 页 · 与 OCR 定位一致`;
    dot.onclick = () => {
      const f = recognizedEl.querySelector(`.rec-field[data-i="${i}"]`);
      if (f) f.click();
    };
    mk.appendChild(dot);
  });
}

// 右侧「识别的字段」：取自汇总表当前文件对应行，携带与 OCR 定位一致的定位信息
function renderRecognized() {
  recognizedMap = [];
  if (!batchTable || batchTable.error || !batchTable.tables || !batchTable.tables[0]) {
    recognizedEl.innerHTML = '<span class="muted">（汇总表尚未生成或无结构化字段）</span>';
    renderMarkers();
    return;
  }
  const table = batchTable.tables[0];
  const order = batchTable.file_order || [];
  const idx = order.indexOf(currentFileId);
  if (idx < 0 || !table.rows || idx >= table.rows.length) {
    recognizedEl.innerHTML = '<span class="muted">（该文件在汇总表中无对应行）</span>';
    renderMarkers();
    return;
  }
  const row = table.rows[idx];
  const entries = [];
  if (Array.isArray(row)) {
    (table.headers || []).forEach((h, i) => entries.push([h, row[i]]));
  } else if (row && typeof row === "object") {
    (table.headers || []).forEach((h) => entries.push([h, row[h]]));
  }
  if (!entries.length) {
    recognizedEl.innerHTML = '<span class="muted">（无字段）</span>';
    renderMarkers();
    return;
  }
  // 预计算每个字段匹配的 OCR 片段（定位信息由此而来，保证与中间 OCR 定位一致）。
  // 策略：优先用「字段值」匹配 OCR；若值因 LLM 规范化改写而匹配不上，
  // 则回退用「字段名」在 OCR 找标签行作为定位锚点（src 记录来源，便于 UI 区分）。
  recognizedMap = entries.map(([k, v]) => {
    const val = v == null ? "" : v;
    let seg = findBestSegment(val, currentSegments);
    let src = seg ? "value" : null;
    if (!seg) {
      const kseg = findBestSegmentByKey(k, currentSegments);
      if (kseg) {
        seg = kseg;
        src = "key";
      }
    }
    return { k, v: val, seg, src };
  });
  recognizedEl.innerHTML = recognizedMap
    .map((item, i) => {
      const hasPos = !!item.seg;
      let posTxt;
      if (!hasPos) {
        posTxt = "（无对应 OCR 定位）";
      } else if (item.src === "key") {
        posTxt = `第 ${item.seg.page_no} 页 · 按字段名「${item.k}」定位`;
      } else {
        posTxt = `第 ${item.seg.page_no} 页 · 定位框 (${item.seg.bbox.l}, ${item.seg.bbox.t})–(${item.seg.bbox.r}, ${item.seg.bbox.b})`;
      }
      const posCls = item.src === "key" ? "rec-pos key-pos" : "rec-pos";
      const boxCls = `rec-field${hasPos ? "" : " no-pos"}${item.src === "key" ? " key-loc" : ""}`;
      return (
        `<div class="${boxCls}" data-i="${i}" title="点击在左图与中间 OCR 定位一致高亮">` +
        `<span class="rec-k">${escapeHtml(item.k)}</span>` +
        `<span class="rec-v">${escapeHtml(item.v)}</span>` +
        `<span class="${posCls}">📍 ${escapeHtml(posTxt)}</span>` +
        `</div>`
      );
    })
    .join("");
  recognizedEl.querySelectorAll(".rec-field").forEach((btn) => {
    btn.onclick = () => {
      const i = Number(btn.getAttribute("data-i"));
      const item = recognizedMap[i];
      recognizedEl.querySelectorAll(".rec-field").forEach((x) => x.classList.remove("active"));
      btn.classList.add("active");
      if (item.seg) {
        highlightSegment(item.seg);
        markMiddleField(item.seg.idx);
        toast("已定位到 OCR：" + item.seg.text.slice(0, 24), "success");
      } else {
        toast("未在 OCR 字段中找到匹配：" + String(item.v).slice(0, 20), "error");
      }
    };
  });
  // 同步在左图叠加识别字段的定位标记（位置与中间 OCR 定位一致）
  renderMarkers();
}

async function loadFileDetail(fid, force = false) {
  if (!fid) return;
  try {
    const [detail, segResp] = await Promise.all([
      API.getFileDetail(batchId, fid),
      API.getOCRSegments(fid).catch(() => ({ segments: [], total_pages: 1 })),
    ]);
    loadedOcrStatus = detail.ocr_status;
    currentSegments = segResp.segments || [];
    ocrBox.textContent = detail.ocr_md_content || "（OCR 尚未完成）";

    // 判断是否 PDF：文件名后缀或 file_type
    const item = fileItems.find((f) => f.id === fid);
    const fname = (item?.original_filename || detail.original_filename || "").toLowerCase();
    const ftype = (item?.file_type || detail.file_type || "").toLowerCase();
    isPdf = fname.endsWith(".pdf") || ftype === "application/pdf";

    if (isPdf) {
      const pagesResp = await API.getFilePages(fid).catch(() => ({ is_pdf: false, pages: [] }));
      currentPages = pagesResp.pages && pagesResp.pages.length ? pagesResp.pages : [];
      document.getElementById("img-col-title").textContent = `PDF 预览（${currentPages.length} 页）`;
      imgHint.textContent = currentPages.length
        ? "点击右侧字段 → 自动跳到对应页并高亮位置"
        : "（PDF 预览生成失败）";
    } else {
      currentPages = [{ page_no: 1, url: API.fileImageUrl(fid) }];
      document.getElementById("img-col-title").textContent = "原始图片";
      imgHint.textContent = "";
    }
    renderStages(currentPages);
    renderFields(currentSegments);
    renderRecognized();
    renderRowForFile(fid);
  } catch (e) {
    imageBox.innerHTML = `<span class="muted">预览加载失败：${escapeHtml(e.message)}</span>`;
    ocrFields.innerHTML = '<span class="muted">—</span>';
    ocrBox.textContent = "—";
  }
}

async function load() {
  if (!batchId) {
    titleEl.textContent = "缺少 batch_id";
    metaEl.textContent = "请从任务列表点击任务名进入。";
    return;
  }
  try {
    const batch = await API.getBatch(batchId);
    titleEl.textContent = batch.name || "（未命名）";
    metaEl.innerHTML =
      `状态：<b>${STATUS_LABEL[batch.status] || batch.status}</b>　|　来源：${escapeHtml(batch.source_type)}　|　` +
      `文件：${batch.total_files} / 已处理 ${batch.processed_files}　|　创建：${fmtTime(batch.created_at)}　|　` +
      `LLM：${batch.enable_llm ? "开启" : "未开启"}`;
    batchTable = parseBatchTable(batch.batch_table);
    const filesData = await API.listFiles(batchId, { page: 1, limit: 200 });
    fileItems = filesData.items || [];
    ensureFilenameColumn(batchTable, fileItems);
    renderSummary();
    renderTableIO(batch);
    renderFileList();

    if (currentFileId && fileItems.some((f) => f.id === currentFileId)) {
      // 保持当前选择
    } else if (fileItems.length) {
      currentFileId = fileItems[0].id;
    }
    if (currentFileId) await loadFileDetail(currentFileId, true);
    await loadChat();
  } catch (e) {
    titleEl.textContent = "加载失败";
    metaEl.textContent = e.message;
  }
}

// 轻量自动刷新：更新元信息 / 文件列表 / 对应行，仅在 OCR 状态变化时才重渲详情
async function autoRefresh() {
  if (!batchId) return;
  try {
    const batch = await API.getBatch(batchId);
    metaEl.innerHTML =
      `状态：<b>${STATUS_LABEL[batch.status] || batch.status}</b>　|　来源：${escapeHtml(batch.source_type)}　|　` +
      `文件：${batch.total_files} / 已处理 ${batch.processed_files}　|　创建：${fmtTime(batch.created_at)}　|　` +
      `LLM：${batch.enable_llm ? "开启" : "未开启"}`;
    const filesData = await API.listFiles(batchId, { page: 1, limit: 200 });
    fileItems = filesData.items || [];
    ensureFilenameColumn(batchTable, fileItems);
    renderFileList();
    if (currentFileId) {
      const cur = fileItems.find((f) => f.id === currentFileId);
      if (cur && cur.ocr_status !== loadedOcrStatus) {
        await loadFileDetail(currentFileId, true);
      } else {
        renderRowForFile(currentFileId);
      }
    }
  } catch (e) {
    /* 静默，下一轮再试 */
  }
}

document.getElementById("export-csv").onclick = () => {
  if (!batchId) return;
  downloadUrl(API.tableCsvUrl(batchId));
};
document.getElementById("export-html").onclick = () => {
  if (!batchId) return;
  openUrl(API.tableHtmlUrl(batchId));
};
document.getElementById("rerun-table").onclick = async () => {
  if (!batchId) return;
  const btn = document.getElementById("rerun-table");
  btn.disabled = true;
  summaryMsg.textContent = "正在重新生成汇总表…";
  try {
    await API.rerunBatchTable(batchId);
    // 后端为同步生成（返回时即已写入 DB），直接重新拉取整页数据
    await load();
    summaryMsg.textContent = "已重新生成汇总表，调用记录已刷新。";
  } catch (e) {
    // 即便失败也刷新，便于在「调用记录」中查看错误原文
    await load();
    summaryMsg.textContent = "重新生成失败：" + e.message + "（详见下方调用记录）";
  } finally {
    btn.disabled = false;
  }
  // 高亮会话内容顶部的「调用记录」块，确保用户看到刷新结果
  const rec = document.getElementById("chat-record");
  if (rec) {
    rec.scrollIntoView({ block: "nearest" });
    const panel = rec.querySelector(".io-grid");
    if (panel) {
      panel.classList.remove("io-flash");
      void panel.offsetWidth; // 触发重排以重启动画
      panel.classList.add("io-flash");
    }
  }
};
document.getElementById("export-file").onclick = () => {
  if (!currentFileId) return toast("请先选择文件", "error");
  downloadUrl(API.exportFileUrl(currentFileId, "both"));
};
document.getElementById("rerun-ocr").onclick = async () => {
  if (!currentFileId) return toast("请先选择文件", "error");
  try {
    await API.rerunOCR(currentFileId);
    toast("已触发重新 OCR", "success");
    setTimeout(load, 1500);
  } catch (e) {
    toast("重新识别失败：" + e.message, "error");
  }
};

// ---------------------------------------------------------------------------
// LLM 会话：基于【批次汇总表】（每行 = 一个文件）的多轮对话，支持编辑调整与继续上下文
// ---------------------------------------------------------------------------
const chatBox = document.getElementById("chat-box");
const chatInput = document.getElementById("chat-input");
const chatHint = document.getElementById("chat-hint");
const chatSendBtn = document.getElementById("chat-send");

async function loadChat() {
  if (!batchId) return;
  chatEditIndex = null;
  resetChatSendBtn();
  try {
    const resp = await API.getChat(batchId);
    chatHistory = resp.history || [];
    renderChat();
  } catch (e) {
    chatHistory = [];
    renderChat();
  }
}

function renderChat() {
  if (!chatBox) return; // 防御：元素未就绪时不抛 null 错误
  const recordHtml = buildChatRecordHtml();
  let body;
  if (!chatHistory.length) {
    body = `<div class="chat-empty" id="chat-empty">尚未开始对话。在下方输入问题，例如「汇总表里金额合计是多少？」「第 3 个文件的甲方是谁？」。</div>`;
  } else {
    body = chatHistory
      .filter((m) => m.role !== "system")
      .map((m) => {
        const cls = m.role === "user" ? "me" : "ai";
        const label = m.role === "user" ? "我" : "AI";
        const ops =
          m.role === "user"
            ? `<div class="chat-ops"><button class="chat-edit" data-seq="${m.seq}">修改</button></div>`
            : `<div class="chat-ops"><button class="chat-regen" data-seq="${m.seq}">重新生成</button></div>`;
        return (
          `<div class="chat-msg ${cls}" data-seq="${m.seq}">` +
          `<div class="chat-role">${label}</div>` +
          `<div class="chat-bubble">${escapeHtml(m.content)}</div>` +
          ops +
          `</div>`
        );
      })
      .join("");
  }
  chatBox.innerHTML = recordHtml + body;
  if (chatHistory.length) {
    chatBox.querySelectorAll(".chat-edit").forEach((b) => {
      b.onclick = () => startEdit(Number(b.getAttribute("data-seq")));
    });
    chatBox.querySelectorAll(".chat-regen").forEach((b) => {
      b.onclick = () => regenerateChat();
    });
    chatBox.scrollTop = chatBox.scrollHeight;
  }
}

function resetChatSendBtn() {
  chatSendBtn.textContent = "发送";
}

function startEdit(seq) {
  const msg = chatHistory.find((m) => m.seq === seq && m.role === "user");
  if (!msg) return;
  chatEditIndex = seq;
  chatInput.value = msg.content;
  chatInput.focus();
  chatSendBtn.textContent = "保存修改";
  chatHint.textContent = "正在修改一条历史消息，保存后将截断其后所有对话并重新生成。";
}

async function sendChat() {
  if (!batchId) return toast("请先打开批次", "error");
  const text = chatInput.value.trim();
  if (!text && chatEditIndex == null) return toast("请输入问题", "error");

  const body = {};
  if (chatEditIndex != null) {
    body.message = text;
    body.edit_index = chatEditIndex;
  } else {
    body.message = text;
  }
  chatSendBtn.disabled = true;
  chatHint.textContent = "LLM 思考中…";
  try {
    const resp = await API.postChat(batchId, body);
    chatHistory = resp.history || [];
    chatEditIndex = null;
    chatInput.value = "";
    resetChatSendBtn();
    renderChat();
  } catch (e) {
    toast("对话失败：" + e.message, "error");
  } finally {
    chatSendBtn.disabled = false;
    chatHint.textContent = "";
  }
}

async function regenerateChat() {
  if (!batchId) return;
  const last = [...chatHistory].reverse().find((m) => m.role === "assistant");
  if (!last) return toast("没有可重新生成的回复", "error");
  chatHint.textContent = "重新生成中…";
  try {
    const resp = await API.postChat(batchId, { regenerate: true });
    chatHistory = resp.history || [];
    renderChat();
  } catch (e) {
    toast("重新生成失败：" + e.message, "error");
  } finally {
    chatHint.textContent = "";
  }
}

async function clearChat() {
  if (!batchId) return;
  try {
    await API.deleteChat(batchId);
    chatHistory = [];
    chatEditIndex = null;
    resetChatSendBtn();
    renderChat();
    toast("对话已清空", "success");
  } catch (e) {
    toast("清空失败：" + e.message, "error");
  }
}

document.getElementById("chat-send").onclick = sendChat;
document.getElementById("chat-clear").onclick = clearChat;
document.getElementById("chat-regen-table").onclick = regenTableFromChat;

async function regenTableFromChat() {
  if (!batchId) return toast("请先打开批次", "error");
  // 用户指令：优先用输入框内容；为空则用默认「补全缺失 + 修正不一致」
  const text =
    chatInput.value.trim() ||
    "请检查并补全所有缺失字段、修正各字段之间不一致的数据，重新生成汇总表。";
  chatSendBtn.disabled = true;
  chatHint.textContent = "正在根据指令重新生成汇总表…";
  try {
    const resp = await API.postChat(batchId, {
      message: text,
      regenerate_table: true,
    });
    chatHistory = resp.history || [];
    chatInput.value = "";
    chatEditIndex = null;
    resetChatSendBtn();
    renderChat();
    if (resp.table_updated) {
      toast("汇总表已根据指令重新生成", "success");
      await load(); // 刷新左侧汇总表
    }
  } catch (e) {
    toast("重新生成失败：" + e.message, "error");
  } finally {
    chatSendBtn.disabled = false;
    chatHint.textContent = "";
  }
}
chatInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendChat();
  }
});

// 每 5 秒轻量刷新
setInterval(autoRefresh, 5000);
renderNav("tasks");
load();
