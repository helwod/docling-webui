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
let chatHistory = []; // 当前文件的 LLM 会话历史
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
  loadChat();
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

// 在 OCR 片段里为某个「识别字段值」找最匹配的片段（子串双向匹配，取最长）
function mapValueToSegment(value) {
  const v = (value || "").trim();
  if (!v || !currentSegments.length) {
    toast("无 OCR 定位可映射", "error");
    return;
  }
  let best = null;
  let bestScore = 0;
  for (const s of currentSegments) {
    const t = (s.text || "").trim();
    if (!t) continue;
    let score = 0;
    if (v.includes(t) && t.length > 1) score = t.length; // 片段是值的子串
    else if (t.includes(v) && v.length > 1) score = v.length; // 值是片段的子串
    if (score > bestScore) {
      bestScore = score;
      best = s;
    }
  }
  if (!best) {
    toast("未在 OCR 字段中找到匹配：" + v.slice(0, 20), "error");
    return;
  }
  highlightSegment(best);
  markMiddleField(best.idx);
  toast("已映射到 OCR 定位：" + best.text.slice(0, 20), "success");
}

// 右侧「识别的字段」：取自汇总表当前文件对应行，点击 → 映射到 OCR 定位
function renderRecognized() {
  recognizedMap = [];
  if (!batchTable || batchTable.error || !batchTable.tables || !batchTable.tables[0]) {
    recognizedEl.innerHTML = '<span class="muted">（汇总表尚未生成或无结构化字段）</span>';
    return;
  }
  const table = batchTable.tables[0];
  const order = batchTable.file_order || [];
  const idx = order.indexOf(currentFileId);
  if (idx < 0 || !table.rows || idx >= table.rows.length) {
    recognizedEl.innerHTML = '<span class="muted">（该文件在汇总表中无对应行）</span>';
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
    return;
  }
  recognizedMap = entries;
  recognizedEl.innerHTML = entries
    .map(
      ([k, v], i) =>
        `<div class="rec-field" data-i="${i}" title="点击在左图与 OCR 定位一致高亮">` +
        `<span class="rec-k">${escapeHtml(k)}</span>` +
        `<span class="rec-v">${escapeHtml(v == null ? "" : v)}</span>` +
        `</div>`
    )
    .join("");
  recognizedEl.querySelectorAll(".rec-field").forEach((btn) => {
    btn.onclick = () => {
      const i = Number(btn.getAttribute("data-i"));
      const [k, v] = recognizedMap[i];
      recognizedEl.querySelectorAll(".rec-field").forEach((x) => x.classList.remove("active"));
      btn.classList.add("active");
      mapValueToSegment(v);
    };
  });
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
  summaryMsg.textContent = "正在重新生成汇总表…";
  try {
    await API.rerunBatchTable(batchId);
    summaryMsg.textContent = "已触发重新生成，稍后自动刷新。";
    setTimeout(load, 1500);
  } catch (e) {
    summaryMsg.textContent = "重新生成失败：" + e.message;
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
// LLM 会话：基于当前文件 OCR 原文的多轮对话，支持编辑调整与继续上下文
// ---------------------------------------------------------------------------
const chatBox = document.getElementById("chat-box");
const chatEmpty = document.getElementById("chat-empty");
const chatInput = document.getElementById("chat-input");
const chatHint = document.getElementById("chat-hint");
const chatSendBtn = document.getElementById("chat-send");

async function loadChat() {
  if (!currentFileId) return;
  chatEditIndex = null;
  resetChatSendBtn();
  try {
    const resp = await API.getChat(currentFileId);
    chatHistory = resp.history || [];
    renderChat();
  } catch (e) {
    chatHistory = [];
    renderChat();
  }
}

function renderChat() {
  if (!chatHistory.length) {
    chatBox.innerHTML = "";
    chatEmpty.style.display = "";
    return;
  }
  chatEmpty.style.display = "none";
  chatBox.innerHTML = chatHistory
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
  chatBox.querySelectorAll(".chat-edit").forEach((b) => {
    b.onclick = () => startEdit(Number(b.getAttribute("data-seq")));
  });
  chatBox.querySelectorAll(".chat-regen").forEach((b) => {
    b.onclick = () => regenerateChat();
  });
  chatBox.scrollTop = chatBox.scrollHeight;
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
  if (!currentFileId) return toast("请先选择文件", "error");
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
    const resp = await API.postChat(currentFileId, body);
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
  if (!currentFileId) return;
  const last = [...chatHistory].reverse().find((m) => m.role === "assistant");
  if (!last) return toast("没有可重新生成的回复", "error");
  chatHint.textContent = "重新生成中…";
  try {
    const resp = await API.postChat(currentFileId, { regenerate: true });
    chatHistory = resp.history || [];
    renderChat();
  } catch (e) {
    toast("重新生成失败：" + e.message, "error");
  } finally {
    chatHint.textContent = "";
  }
}

async function clearChat() {
  if (!currentFileId) return;
  try {
    await API.deleteChat(currentFileId);
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
