// 上传并解析页逻辑
const ACCEPT = [
  "png", "jpg", "jpeg", "bmp", "tif", "tiff", "webp", "gif",
  "pdf", "docx", "pptx", "html", "txt", "csv", "zip",
];

let selectedFiles = [];

const dz = document.getElementById("dropzone");
const fileInput = document.getElementById("file-input");
const fileListEl = document.getElementById("file-list");
const nameInput = document.getElementById("batch-name");
const enableLlm = document.getElementById("enable-llm");
const submitBtn = document.getElementById("submit-btn");
const msgEl = document.getElementById("msg");

function fmtSize(n) {
  if (!n) return "";
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
  return (n / 1024 / 1024).toFixed(1) + " MB";
}

function renderFiles() {
  if (!selectedFiles.length) {
    fileListEl.innerHTML = "";
    return;
  }
  fileListEl.innerHTML = selectedFiles
    .map(
      (f, i) =>
        `<li><span>${escapeHtml(f.name)}</span>` +
        `<span><span class="fsize">${fmtSize(f.size)}</span>` +
        `<span class="x" data-i="${i}" title="移除">✕</span></span></li>`
    )
    .join("");
  fileListEl.querySelectorAll(".x").forEach((el) => {
    el.onclick = () => {
      selectedFiles.splice(Number(el.dataset.i), 1);
      renderFiles();
    };
  });
}

dz.onclick = () => fileInput.click();
fileInput.onchange = () => {
  for (const f of fileInput.files) selectedFiles.push(f);
  renderFiles();
  fileInput.value = "";
};
["dragenter", "dragover"].forEach((ev) =>
  dz.addEventListener(ev, (e) => {
    e.preventDefault();
    dz.classList.add("dragover");
  })
);
["dragleave", "drop"].forEach((ev) =>
  dz.addEventListener(ev, (e) => {
    e.preventDefault();
    dz.classList.remove("dragover");
  })
);
dz.addEventListener("drop", (e) => {
  const files = e.dataTransfer.files;
  for (const f of files) selectedFiles.push(f);
  renderFiles();
});

function showMsg(text, type = "info") {
  msgEl.innerHTML = `<div class="msg msg-${type}">${escapeHtml(text)}</div>`;
}

submitBtn.onclick = async () => {
  if (!selectedFiles.length) {
    showMsg("请先选择文件。", "error");
    return;
  }
  submitBtn.disabled = true;
  showMsg("正在上传并创建批次…", "info");
  try {
    const fd = new FormData();
    for (const f of selectedFiles) fd.append("files", f, f.name);
    const name = nameInput.value.trim();
    if (name) fd.append("name", name);
    const useLlm = enableLlm.checked;
    fd.append("enable_llm", useLlm ? "true" : "false");

    const batch = await API.createBatch(fd);
    const bid = batch.id;
    let extra = "";
    try {
      await API.processBatch(bid, useLlm);
    } catch (e) {
      // 调度器常在创建后立刻自动拉起，此时显式触发返回 409「already processing」属正常
      if (!(e.status === 409 && /already processing/i.test(e.message))) {
        extra = "（但触发处理失败：" + e.message + "）";
      }
    }
    const rejected = batch.rejected_files || [];
    let rMsg = "";
    if (rejected.length) {
      rMsg =
        "\n有 " + rejected.length + " 个文件被跳过：" +
        rejected.map((r) => r.filename + "（" + r.reason + "）").join("；");
    }
    showMsg(
      `创建完成：${batch.name || "未命名"}（${batch.total_files} 个文件），已加入处理队列。${extra}${rMsg}`,
      "success"
    );
    toast("批次已创建并开始处理", "success");
    selectedFiles = [];
    renderFiles();
    nameInput.value = "";
  } catch (e) {
    showMsg("创建批次失败：" + e.message, "error");
  } finally {
    submitBtn.disabled = false;
  }
};

renderNav("upload");
