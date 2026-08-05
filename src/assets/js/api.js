// Docling Serve WebUI - 前端 API 客户端
// 后端统一信封 { code, data }，这里提取 data 返回。
const API_BASE = "api/v1";

async function request(method, path, opts = {}) {
  const { body, isForm = false } = opts;
  const init = { method, headers: {} };
  if (body !== undefined) {
    if (isForm) {
      init.body = body; // FormData，让浏览器自己设置 content-type
    } else {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
  }
  const resp = await fetch(API_BASE + path, init);
  const ct = resp.headers.get("content-type") || "";
  let data = null;
  if (ct.includes("application/json")) {
    try { data = await resp.json(); } catch (e) { data = null; }
  }
  if (!resp.ok) {
    let msg = `HTTP ${resp.status}`;
    if (data) {
      const d = data.detail;
      if (typeof d === "string") msg = d;
      else if (d && d.message) msg = d.message;
      else if (typeof d === "object") msg = JSON.stringify(d);
    }
    const err = new Error(msg);
    err.status = resp.status;
    err.data = data;
    throw err;
  }
  if (data && data.data !== undefined) return data.data;
  return data;
}

function buildQuery(params) {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params || {})) {
    if (v !== undefined && v !== null && v !== "") sp.set(k, v);
  }
  const s = sp.toString();
  return s ? "?" + s : "";
}

// 触发浏览器下载（导出 ZIP/CSV/文件）
function downloadUrl(url, filename) {
  const a = document.createElement("a");
  a.href = url;
  if (filename) a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

// 打开新标签查看（汇总表 HTML）
function openUrl(url) {
  window.open(url, "_blank");
}

const API = {
  health: () => request("GET", "/health"),
  listBatches: (params = {}) => request("GET", "/batches" + buildQuery(params)),
  getBatch: (id) => request("GET", `/batches/${id}`),
  createBatch: (formData) => request("POST", "/batches", { body: formData, isForm: true }),
  deleteBatch: (id) => request("DELETE", `/batches/${id}`),
  batchDelete: (ids) => request("POST", "/batches/batch-delete", { body: ids }),
  pauseBatch: (id) => request("POST", `/batches/${id}/pause`),
  pinBatch: (id) => request("POST", `/batches/${id}/pin`),
  listFiles: (id, params = {}) => request("GET", `/batches/${id}/files` + buildQuery(params)),
  getFileDetail: (bid, fid) => request("GET", `/batches/${bid}/files/${fid}`),
  getOCRSegments: (fid) => request("GET", `/files/${fid}/ocr-segments`),
  getFilePages: (fid) => request("GET", `/files/${fid}/pages`),
  processBatch: (id, enable_llm = true) =>
    request("POST", `/batches/${id}/process`, { body: { enable_llm } }),
  getBatchStatus: (id) => request("GET", `/batches/${id}/status`),
  rerunBatchTable: (id) => request("POST", `/batches/${id}/table/rerun`),
  getConfig: () => request("GET", "/config"),
  updateConfig: (payload) => request("PUT", "/config", { body: payload }),
  listLLMModels: (base_url, api_key) =>
    request("GET", "/config/llm-models" + buildQuery({ base_url, api_key })),
  testLLM: (body) => request("POST", "/config/test-llm", { body }),
  testDocling: (docling_base_url) =>
    request("POST", "/config/test-docling", { body: { docling_base_url: docling_base_url || null } }),
  rerunLLM: (fid, model) =>
    request("POST", `/files/${fid}/llm`, { body: model ? { model } : {} }),
  rerunOCR: (fid) => request("POST", `/files/${fid}/rerun-ocr`),

  // 批次（汇总表）级 LLM 多轮会话 —— 上下文为批次汇总表（每行 = 一个文件）
  getChat: (bid) => request("GET", `/batches/${bid}/chat`),
  postChat: (bid, body) => request("POST", `/batches/${bid}/chat`, { body }),
  deleteChat: (bid) => request("DELETE", `/batches/${bid}/chat`),

  // 下载 / 查看用直链
  exportBatchUrl: (id, fmt = "both") => `${API_BASE}/batches/${id}/export?format=${fmt}`,
  exportFileUrl: (id, fmt = "both") => `${API_BASE}/files/${id}/export?format=${fmt}`,
  tableCsvUrl: (id) => `${API_BASE}/batches/${id}/table?format=csv`,
  tableHtmlUrl: (id) => `${API_BASE}/batches/${id}/table?format=html`,
  fileImageUrl: (id) => `${API_BASE}/files/${id}/image`,
};
