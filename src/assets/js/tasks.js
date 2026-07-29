// 任务列表页逻辑
const checkedIds = new Set();
let currentItems = [];

const tbody = document.getElementById("task-rows");
const selectAll = document.getElementById("select-all");
const statusLine = document.getElementById("status-line");
const msgEl = document.getElementById("msg");

function showMsg(text, type = "info") {
  msgEl.innerHTML = `<div class="msg msg-${type}">${escapeHtml(text)}</div>`;
}

function renderRows(items) {
  currentItems = items;
  if (!items.length) {
    tbody.innerHTML = "";
    document.getElementById("empty-hint").innerHTML =
      '<div class="empty">暂无任务。请先到 <a href=".">上传并解析</a> 创建批次。</div>';
    return;
  }
  document.getElementById("empty-hint").innerHTML = "";
  tbody.innerHTML = items
    .map((b) => {
      const bid = b.id;
      const total = b.total_files || 0;
      const done = b.processed_files || 0;
      const pct = total ? Math.round((done / total) * 100) : 0;
      const paused = b.paused;
      const prio = b.priority;
      const progress =
        total > 0
          ? `<div class="progress"><span style="width:${pct}%"></span></div> ${pct}%`
          : '<span class="muted">—</span>';
      const isChecked = checkedIds.has(bid) ? "checked" : "";
      return (
        "<tr>" +
        `<td><input type="checkbox" class="row-cb" value="${bid}" ${isChecked} /></td>` +
        `<td>${statusBadge(b.status)}</td>` +
        `<td><a class="tname-link" href="task?batch_id=${encodeURIComponent(bid)}">${escapeHtml(b.name || "(未命名)")}</a></td>` +
        `<td>${done}/${total}</td>` +
        `<td class="muted">${fmtTime(b.created_at) || "—"}</td>` +
        `<td class="${paused ? "warn-text" : "muted"}">${paused ? "已暂停" : "—"}</td>` +
        `<td>${prio ? "P" + prio : "—"}</td>` +
        `<td>${llmBadge(b)}</td>` +
        `<td>${progress}</td>` +
        "</tr>"
      );
    })
    .join("");

  tbody.querySelectorAll(".row-cb").forEach((cb) => {
    cb.onchange = () => {
      if (cb.checked) checkedIds.add(cb.value);
      else checkedIds.delete(cb.value);
      syncSelectAll();
    };
  });
  syncSelectAll();
}

function syncSelectAll() {
  const all = currentItems.map((b) => b.id);
  const allChecked = all.length > 0 && all.every((id) => checkedIds.has(id));
  selectAll.checked = allChecked;
  selectAll.indeterminate = !allChecked && all.some((id) => checkedIds.has(id));
}

selectAll.onchange = () => {
  for (const b of currentItems) {
    if (selectAll.checked) checkedIds.add(b.id);
    else checkedIds.delete(b.id);
  }
  renderRows(currentItems);
};

async function load() {
  try {
    const data = await API.listBatches({ page: 1, limit: 200 });
    const items = data.items || [];
    renderRows(items);
    let nProc = 0, nQueue = 0, nPause = 0;
    for (const b of items) {
      if (b.status === "processing") nProc++;
      else if (b.status === "created" && !b.paused) nQueue++;
      else if (b.status === "created" && b.paused) nPause++;
    }
    const parts = [];
    if (nProc) parts.push(`处理中 ${nProc}`);
    if (nQueue) parts.push(`排队 ${nQueue}`);
    if (nPause) parts.push(`已暂停 ${nPause}`);
    statusLine.textContent =
      `共 ${items.length} 个批次` + (parts.length ? "　｜　" + parts.join("　｜　") : "　｜　当前无进行中的任务");
  } catch (e) {
    statusLine.textContent = "加载失败：" + e.message;
  }
}

function selectedList() {
  return currentItems.map((b) => b.id).filter((id) => checkedIds.has(id));
}

document.getElementById("process-btn").onclick = async () => {
  const ids = selectedList();
  if (!ids.length) return showMsg("请先勾选批次。", "error");
  let ok = 0, errs = [];
  for (const bid of ids) {
    try {
      let useLlm = true;
      try { useLlm = !!API.getBatch ? (await API.getBatch(bid)).enable_llm : true; }
      catch (e) { useLlm = true; }
      await API.processBatch(bid, useLlm);
      ok++;
    } catch (e) {
      if (e.status === 409 && /already processing/i.test(e.message)) ok++;
      else errs.push(bid.slice(0, 8) + ": " + e.message);
    }
  }
  showMsg(
    `已加入队列 ${ok} 个批次（仅重跑失败/未处理的 OCR，LLM 汇总表在开启时按需重建）` +
      (errs.length ? "　失败：" + errs.join("；") : ""),
    errs.length ? "error" : "success"
  );
  await load();
};

document.getElementById("pause-btn").onclick = async () => {
  const ids = selectedList();
  if (!ids.length) return showMsg("请先勾选批次（仅未开始的排队批次可暂停）。", "error");
  const msgs = [];
  for (const bid of ids) {
    try {
      const r = await API.pauseBatch(bid);
      msgs.push(`${bid.slice(0, 8)} ${r.paused ? "已暂停" : "已恢复"}`);
    } catch (e) { msgs.push(`${bid.slice(0, 8)} 失败：${e.message}`); }
  }
  showMsg(msgs.join("；"), "info");
  await load();
};

document.getElementById("pin-btn").onclick = async () => {
  const ids = selectedList();
  if (!ids.length) return showMsg("请先勾选要置顶的批次。", "error");
  const bid = ids[0];
  try {
    const r = await API.pinBatch(bid);
    showMsg(`${bid.slice(0, 8)} 已置顶（优先级 ${r.priority}），将是下一个处理的批次。`, "success");
  } catch (e) { showMsg("置顶失败：" + e.message, "error"); }
  await load();
};

document.getElementById("delete-btn").onclick = async () => {
  const ids = selectedList();
  if (!ids.length) return showMsg("请先勾选要删除的批次。", "error");
  if (!confirm(`确认删除 ${ids.length} 个批次？此操作不可撤销。`)) return;
  try {
    await API.batchDelete(ids);
    ids.forEach((id) => checkedIds.delete(id));
    showMsg(`已删除 ${ids.length} 个批次。`, "success");
  } catch (e) { showMsg("删除失败：" + e.message, "error"); }
  await load();
};

document.getElementById("export-btn").onclick = () => {
  const ids = selectedList();
  if (!ids.length) return showMsg("请先勾选批次（导出取第一个勾选项）。", "error");
  downloadUrl(API.exportBatchUrl(ids[0], "both"));
  showMsg(`正在导出 ${ids[0].slice(0, 8)} …`, "info");
};

document.getElementById("refresh-btn").onclick = () => load();

// 每 8 秒自动刷新（保留勾选）
setInterval(load, 8000);
renderNav("tasks");
load();
