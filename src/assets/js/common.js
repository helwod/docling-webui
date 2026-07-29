// Docling Serve WebUI - 公共函数：导航、状态映射、工具
const STATUS_LABEL = {
  created: "排队中",
  processing: "处理中",
  completed: "已完成",
  failed: "失败",
};
const STATUS_KEY = {
  created: "created",
  processing: "processing",
  completed: "completed",
  failed: "failed",
};

function escapeHtml(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function fmtTime(iso) {
  if (!iso) return "";
  return String(iso).replace("T", " ").slice(0, 16);
}

// 推导批次的 LLM 处理状态（后端无独立 llm_status 字段）
function llmStatusOf(b) {
  if (!b || !b.enable_llm) return ["未启用", "off"];
  let bt = b.batch_table;
  if (typeof bt === "string") {
    try { bt = JSON.parse(bt); } catch (e) { bt = null; }
  }
  if (bt && typeof bt === "object" && !bt.error) {
    const tables = bt.tables;
    if (tables && tables.length) return ["已完成", "completed"];
  }
  const st = b.status;
  if (st === "processing") return ["处理中", "processing"];
  if (st === "failed") return ["失败", "failed"];
  return ["待生成", "pending"];
}

function badge(text, key) {
  return `<span class="badge badge-${key}">${escapeHtml(text)}</span>`;
}

function statusBadge(status) {
  const key = STATUS_KEY[status] || "created";
  const label = STATUS_LABEL[status] || status;
  return badge(label, key);
}

function llmBadge(b) {
  const [label, key] = llmStatusOf(b);
  return badge(label, key);
}

// 顶部导航（active: "upload" | "tasks" | "settings"）
function renderNav(active) {
  const nav = document.getElementById("nav");
  if (!nav) return;
  const items = [
    { key: "upload", label: "上传并解析", href: "." },
    { key: "tasks", label: "任务列表", href: "tasks" },
    { key: "settings", label: "设置", href: "settings" },
  ];
  nav.innerHTML =
    '<div class="nav-inner">' +
    '<a class="brand" href=".">📄 Docling Serve Webui</a>' +
    '<nav class="nav-links">' +
    items
      .map(
        (it) =>
          `<a href="${it.href}" class="${it.key === active ? "active" : ""}">${it.label}</a>`
      )
      .join("") +
    "</nav>" +
    '<span id="conn-state" class="conn-state" title="后端连接状态"></span>' +
    "</div>";
  checkConn();
}

async function checkConn() {
  const el = document.getElementById("conn-state");
  if (!el) return;
  try {
    await API.health();
    el.textContent = "● 已连接";
    el.className = "conn-state ok";
  } catch (e) {
    el.textContent = "● 未连接";
    el.className = "conn-state err";
  }
}

// 轻量提示条
function toast(msg, type = "info") {
  let box = document.getElementById("toast-box");
  if (!box) {
    box = document.createElement("div");
    box.id = "toast-box";
    document.body.appendChild(box);
  }
  const t = document.createElement("div");
  t.className = "toast toast-" + type;
  t.textContent = msg;
  box.appendChild(t);
  setTimeout(() => {
    t.classList.add("show");
  }, 10);
  setTimeout(() => {
    t.classList.remove("show");
    setTimeout(() => t.remove(), 300);
  }, 3600);
}
