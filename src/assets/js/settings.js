// 设置页逻辑
const msgEl = document.getElementById("msg");
const $ = (id) => document.getElementById(id);

// 「LLM 角色定义」即公共抽取口径（对应后端 DEFAULT_LLM_ROLE，内容较长且会随提示词调整而变），
// 因此不在前端硬编码副本，统一由后端 default_llm_role 下发，避免两处漂移。
const ROLE_FALLBACK_HINT = "（未能从服务端获取内置默认角色，请重建后端镜像后刷新本页）";

// placeholder 在拿到后端默认角色后再填充（见 load()），保证与默认信息一字不差
$("llm_role").placeholder = "加载内置默认角色中…";

function showMsg(text, type = "info") {
  msgEl.innerHTML = `<div class="msg msg-${type}">${escapeHtml(text)}</div>`;
}

function setSelect(id, value, fallback) {
  const el = $(id);
  let v = value || fallback;
  if (![...el.options].some((o) => o.value === v)) v = fallback;
  el.value = v;
}

// 当前已保存的模型名（用于 fetch 后回选）
let savedModel = "";

function ensureModelOption(model, label) {
  const sel = $("model-select");
  if (![...sel.options].some((o) => o.value === model)) {
    const opt = document.createElement("option");
    opt.value = model;
    opt.textContent = label || model;
    sel.appendChild(opt);
  }
  sel.value = model;
}

async function load() {
  try {
    const c = await API.getConfig();
    $("docling_url").value = c.docling_base_url || "";
    $("llm_base_url").value = c.llm_base_url || "";
    savedModel = c.llm_model || "";
    if (savedModel) ensureModelOption(savedModel, savedModel + "（已保存）");
    // 输入框直接显示当前生效的角色定义（即公共抽取口径），placeholder 同步为服务端内置默认角色
    const defRole = c.default_llm_role || "";
    $("llm_role").placeholder = defRole || ROLE_FALLBACK_HINT;
    $("llm_role").value = c.llm_role || defRole;
    setSelect("ocr_engine", c.docling_ocr_engine, "rapidocr");
    setSelect("table_mode", c.docling_table_mode, "accurate");
    setSelect("image_mode", c.docling_image_export_mode, "referenced");
    $("max_conc").value = c.max_concurrent_conversions ?? 5;
    $("poll").value = c.poll_interval_seconds ?? 2;
    showMsg("已加载配置（API Key " + (c.llm_api_key_set ? "已配置" : "未配置") + "）。", "info");
  } catch (e) {
    showMsg("配置加载失败：" + e.message, "error");
  }
}

$("load-btn").onclick = load;

$("save-btn").onclick = async () => {
    const payload = {
      docling_base_url: $("docling_url").value.trim(),
      llm_base_url: $("llm_base_url").value.trim(),
      llm_model: $("model-select").value.trim() || "",
      llm_role: $("llm_role").value,
      docling_ocr_engine: $("ocr_engine").value,
    docling_table_mode: $("table_mode").value,
    docling_image_export_mode: $("image_mode").value,
    max_concurrent_conversions: parseInt($("max_conc").value, 10) || 5,
    poll_interval_seconds: parseInt($("poll").value, 10) || 2,
  };
  const key = $("llm_api_key").value;
  if (key) payload.llm_api_key = key;
  try {
    await API.updateConfig(payload);
    $("llm_api_key").value = "";
    showMsg("设置已保存。", "success");
    toast("设置已保存", "success");
  } catch (e) {
    showMsg("保存失败：" + e.message, "error");
  }
};

$("fetch-models").onclick = async () => {
  const base = $("llm_base_url").value.trim();
  const key = $("llm_api_key").value.trim();
  try {
    const data = await API.listLLMModels(base || null, key || null);
    const models = (data && data.models) || [];
    if (!models.length) {
      showMsg("未返回任何模型（请检查 Base URL / Key，或服务商不支持 /models）。", "error");
      return;
    }
    const sel = $("model-select");
    sel.innerHTML =
      '<option value="">（先点『获取模型列表』）</option>' +
      models.map((m) => `<option value="${escapeHtml(m)}">${escapeHtml(m)}</option>`).join("");
    // 优先回选已保存的模型；不在列表中则默认第一个
    if (savedModel && models.includes(savedModel)) {
      sel.value = savedModel;
    } else {
      sel.value = models[0];
    }
    showMsg(`已获取 ${models.length} 个模型。`, "success");
  } catch (e) {
    showMsg("获取模型列表失败：" + e.message, "error");
  }
};

$("test-docling").onclick = async () => {
  const url = $("docling_url").value.trim();
  try {
    const res = await API.testDocling(url || null);
    if (res && res.ok) {
      showMsg(`Docling 连接成功：HTTP ${res.status_code}，耗时 ${res.latency_ms} ms。`, "success");
    } else {
      showMsg("Docling 连接失败：" + (res && res.error ? res.error : "未知错误"), "error");
    }
  } catch (e) {
    showMsg("测试 Docling 失败：" + e.message, "error");
  }
};

$("test-btn").onclick = async () => {
  const model = $("model-select").value.trim() || null;
  const base = $("llm_base_url").value.trim() || null;
  const key = $("llm_api_key").value.trim() || null;
  try {
    const res = await API.testLLM({ model, base_url: base, api_key: key });
    if (res && res.ok) {
      showMsg(
        `连接成功：模型 ${res.model} 可用，耗时 ${res.latency_ms} ms，回复：${JSON.stringify(res.sample)}`,
        "success"
      );
    } else {
      showMsg("连接测试未通过：" + (res && res.error ? res.error : "未知错误"), "error");
    }
  } catch (e) {
    showMsg("测试连接失败：" + e.message, "error");
  }
};

renderNav("settings");
load();
