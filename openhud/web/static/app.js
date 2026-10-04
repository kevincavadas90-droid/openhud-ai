/* OpenHUD AI front-end. No build step: plain ES-module-free JS. */
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const state = {
  conversationId: null,
  projectId: "",
  settings: {},
  streaming: false,
  lastProvider: null,
  deviceId: null,
  deviceOnline: false,
  dashTimer: null,
  history: [],
};

/* ---------------- API helpers ---------------- */
async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    ...options,
  });
  if (res.status === 401) { window.location.href = "/login"; return null; }
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail || `HTTP ${res.status}`);
  }
  if (res.status === 204) return null;
  const ct = res.headers.get("content-type") || "";
  return ct.includes("application/json") ? res.json() : res.text();
}

/* FASE 19: never leave the user without an answer. */
function showError(where, message, cause, alternative) {
  const el = typeof where === "string" ? $(where) : where;
  if (!el) return toast(message, true);
  el.innerHTML = `
    <div class="error-box">
      <b>⚠️ Não consegui concluir esta etapa.</b>
      <div><b>Erro:</b> ${escapeHtml(message || "desconhecido")}</div>
      ${cause ? `<div><b>Causa provável:</b> ${escapeHtml(cause)}</div>` : ""}
      ${alternative ? `<div><b>Próxima alternativa:</b> ${escapeHtml(alternative)}</div>` : ""}
    </div>`;
}

function toast(message, isError = false) {
  const el = $("#toast");
  el.textContent = message;
  el.className = "toast" + (isError ? " err" : "");
  setTimeout(() => el.classList.add("hidden"), 3600);
}

/* ---------------- Rendering helpers ---------------- */
function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function renderMarkdown(text) {
  let html = escapeHtml(text);
  const blocks = [];
  html = html.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    blocks.push(`<pre><code>${code.replace(/\n$/, "")}</code></pre>`);
    return `\u0000${blocks.length - 1}\u0000`;
  });
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
  html = html.replace(/^### (.*)$/gm, "<h3>$1</h3>");
  html = html.replace(/^## (.*)$/gm, "<h3>$1</h3>");
  html = html.replace(/^\s*[-*] (.*)$/gm, "• $1");
  html = html.replace(/\n/g, "<br>");
  html = html.replace(/\u0000(\d+)\u0000/g, (_, i) => blocks[+i]);
  return html;
}

function addMessage(role, content) {
  const empty = $(".empty");
  if (empty) empty.remove();
  const el = document.createElement("div");
  el.className = `msg ${role}`;
  el.innerHTML = `<div class="role">${role === "user" ? "Você" : "OpenHUD"}</div><div class="body">${renderMarkdown(content)}</div>`;
  $("#messages").appendChild(el);
  $("#messages").scrollTop = $("#messages").scrollHeight;
  return el;
}

function addToolEvent(name, ok, output) {
  const el = document.createElement("div");
  el.className = "tool-event" + (ok ? "" : " err");
  el.innerHTML = `<div>⚙ <b>${escapeHtml(name)}</b> ${ok ? "concluído" : "falhou"}</div><pre>${escapeHtml(output || "")}</pre>`;
  $("#messages").appendChild(el);
  $("#messages").scrollTop = $("#messages").scrollHeight;
}

/* ---------------- Chat ---------------- */
async function loadConversations() {
  try {
    const list = await api(`/api/conversations${state.projectId ? `?project_id=${state.projectId}` : ""}`);
    const ul = $("#conv-list");
    ul.innerHTML = "";
    list.forEach((c) => {
      const li = document.createElement("li");
      li.className = c.id === state.conversationId ? "active" : "";
      li.innerHTML = `<span>${escapeHtml(c.title)}</span><span class="del" title="Excluir">✕</span>`;
      li.querySelector("span").onclick = () => openConversation(c.id);
      li.querySelector(".del").onclick = async (e) => {
        e.stopPropagation();
        await api(`/api/conversations/${c.id}`, { method: "DELETE" });
        if (state.conversationId === c.id) newConversation();
        loadConversations();
      };
      ul.appendChild(li);
    });
  } catch (err) { toast("Falha ao carregar conversas: " + err.message, true); }
}

async function openConversation(id) {
  state.conversationId = id;
  const conv = await api(`/api/conversations/${id}`);
  $("#conv-title").textContent = conv.title;
  const messages = await api(`/api/conversations/${id}/messages`);
  $("#messages").innerHTML = "";
  messages.forEach((m) => {
    if (m.role === "user" || m.role === "assistant") {
      if (m.content) addMessage(m.role, m.content);
      if (m.tool_calls && Array.isArray(m.tool_calls)) {
        m.tool_calls.forEach((t) => addToolEvent(t.name, true, JSON.stringify(t.arguments)));
      }
    }
  });
  if (!messages.length) {
    $("#messages").innerHTML = `<div class="empty"><h3>Nova conversa</h3><p>Descreva a tarefa.</p></div>`;
  }
  loadConversations();
}

async function newConversation() {
  const conv = await api("/api/conversations", {
    method: "POST",
    body: JSON.stringify({ project_id: state.projectId || null }),
  });
  state.conversationId = conv.id;
  $("#conv-title").textContent = conv.title;
  $("#messages").innerHTML = `<div class="empty"><h3>Nova conversa</h3><p>Descreva a tarefa.</p></div>`;
  loadConversations();
}

async function sendMessage(text) {
  if (!state.conversationId) await newConversation();
  addMessage("user", text);
  $("#input").value = "";
  state.streaming = true;
  $("#send").disabled = true;

  let res;
  try {
    res = await fetch(`/api/conversations/${state.conversationId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ text }),
    });
  } catch (err) {
    state.streaming = false; $("#send").disabled = false;
    showError("#messages", err.message, "Falha de rede ao contatar o servidor.", "Verifique sua conexão e tente novamente.");
    return;
  }
  if (res.status === 401) { window.location.href = "/login"; return; }
  if (!res.ok || !res.body) {
    state.streaming = false; $("#send").disabled = false;
    let detail = "Falha ao enviar mensagem";
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    showError("#messages", detail, `O servidor respondeu HTTP ${res.status}.`, "Tente novamente ou reduza o tamanho da mensagem.");
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let assistantEl = null;
  let errored = false;

  const handle = (chunk) => {
    const lines = chunk.split("\n");
    let event = "message";
    let data = "";
    lines.forEach((line) => {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data += line.slice(5).trim();
    });
    if (!data) return;
    let payload = {};
    try { payload = JSON.parse(data); } catch (_) {}
    if (event === "token") {
      if (!assistantEl) assistantEl = addMessage("assistant", "");
      assistantEl.querySelector(".body").innerHTML = renderMarkdown(payload.text || "");
    } else if (event === "tool_start") {
      addToolEvent(payload.name, true, "executando… " + JSON.stringify(payload.arguments));
    } else if (event === "tool_result") {
      addToolEvent(payload.name, payload.ok, payload.output);
    } else if (event === "confirmation") {
      showConfirmation(payload);
    } else if (event === "provider") {
      state.lastProvider = payload.label || payload.provider;
      updateProviderBadge();
    } else if (event === "activity") {
      refreshActivity();
    } else if (event === "error") {
      errored = true;
      showError("#messages", payload.message, "O provedor de IA falhou nesta tentativa.", "Configure uma chave em Configurações ou rode o Ollama local; o OpenHUD tenta o próximo provedor automaticamente.");
    }
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buffer.indexOf("\n\n")) >= 0) {
        handle(buffer.slice(0, idx));
        buffer = buffer.slice(idx + 2);
      }
    }
  } catch (err) {
    if (!errored) showError("#messages", err.message, "A conexão de streaming foi interrompida.", "Tente novamente.");
  }
  state.streaming = false;
  $("#send").disabled = false;
  loadConversations();
  refreshActivity();
}

/* ---------------- Confirmations ---------------- */
function showConfirmation(payload) {
  $("#confirm-tool").textContent = payload.tool;
  $("#confirm-args").textContent = JSON.stringify(payload.arguments, null, 2);
  $("#confirm-modal").classList.remove("hidden");
  const resolve = async (approved) => {
    await api(`/api/confirmations/${payload.request_id}`, { method: "POST", body: JSON.stringify({ approved }) });
    $("#confirm-modal").classList.add("hidden");
  };
  $("#confirm-approve").onclick = () => resolve(true);
  $("#confirm-deny").onclick = () => resolve(false);
}

/* ---------------- Tools ---------------- */
async function loadTools() {
  const tools = await api("/api/tools");
  const container = $("#tools-list");
  container.innerHTML = "";
  tools.forEach((t) => {
    const card = document.createElement("div");
    card.className = "tool-card";
    card.innerHTML = `
      <header><span class="name">${t.name}</span>
      ${t.requires_confirmation ? '<span class="tag">confirmação</span>' : ""}</header>
      <p>${escapeHtml(t.description)}</p>
      <label class="check" style="margin-top:10px">
        <input type="checkbox" ${t.enabled ? "checked" : ""} data-tool="${t.name}" /> habilitada
      </label>`;
    card.querySelector("input").onchange = async () => {
      // disabled_tools is a blacklist: send the unchecked ones.
      const disabled = [...$$("#tools-list input[data-tool]")].filter((i) => !i.checked).map((i) => i.dataset.tool);
      await api("/api/settings", { method: "PUT", body: JSON.stringify({ disabled_tools: disabled }) });
      state.settings.disabled_tools = disabled;
      toast("Ferramentas atualizadas");
    };
    container.appendChild(card);
  });
}

/* ---------------- Files ---------------- */
async function loadFiles(path = ".") {
  const files = await api(`/api/files?path=${encodeURIComponent(path)}`);
  const list = $("#files-list");
  list.innerHTML = "";
  files.forEach((f) => {
    const el = document.createElement("div");
    el.className = "file";
    el.innerHTML = `<span>${f.is_dir ? "📁" : "📄"} ${escapeHtml(f.name)}</span><span>${f.is_dir ? "" : f.size + "b"}</span>`;
    el.onclick = () => { if (f.is_dir) loadFiles(f.path); else openFile(f.path); };
    list.appendChild(el);
  });
}

async function openFile(path) {
  try {
    const data = await api(`/api/files/content?path=${encodeURIComponent(path)}`);
    $("#file-path").value = data.path;
    $("#file-content").value = data.content;
  } catch (e) { toast(e.message, true); }
}

async function saveFile() {
  const path = $("#file-path").value.trim();
  if (!path) return toast("Informe o caminho", true);
  await api("/api/files", { method: "POST", body: JSON.stringify({ path, content: $("#file-content").value }) });
  toast("Arquivo salvo");
  loadFiles(".");
}

/* ---------------- Memory ---------------- */
async function loadMemories() {
  const memories = await api("/api/memories");
  const list = $("#memory-list");
  list.innerHTML = memories.length ? "" : `<p class="hint">Nenhuma memória ainda.</p>`;
  memories.forEach((m) => {
    const el = document.createElement("div");
    el.className = "list-item";
    el.innerHTML = `<div><div>${escapeHtml(m.content)}</div><div class="meta">${escapeHtml(m.tags || "sem tags")} · ${new Date(m.updated_at * 1000).toLocaleString()}</div></div>`;
    const del = document.createElement("button");
    del.className = "ghost small";
    del.textContent = "Excluir";
    del.onclick = async () => { await api(`/api/memories/${m.id}`, { method: "DELETE" }); loadMemories(); };
    el.appendChild(del);
    list.appendChild(el);
  });
}

/* ---------------- Tasks ---------------- */
async function loadTasks() {
  const tasks = await api("/api/tasks");
  const list = $("#task-list");
  list.innerHTML = tasks.length ? "" : `<p class="hint">Nenhuma tarefa agendada.</p>`;
  tasks.forEach((t) => {
    const el = document.createElement("div");
    el.className = "list-item";
    const status = t.last_status ? ` · último: ${t.last_status}` : "";
    const next = new Date(t.next_run * 1000).toLocaleString();
    el.innerHTML = `<div><div><b>${escapeHtml(t.name)}</b> ${t.enabled ? "" : "(pausada)"}</div>
      <div class="meta">${escapeHtml(t.prompt)}</div>
      <div class="meta">a cada ${t.interval_seconds}s · próxima: ${next}${status}</div></div>`;
    const actions = document.createElement("div");
    actions.className = "row";
    const toggle = document.createElement("button");
    toggle.className = "ghost small";
    toggle.textContent = t.enabled ? "Pausar" : "Ativar";
    toggle.onclick = async () => {
      await api(`/api/tasks/${t.id}`, { method: "PUT", body: JSON.stringify({ enabled: !t.enabled }) });
      loadTasks();
    };
    const del = document.createElement("button");
    del.className = "ghost small";
    del.textContent = "Excluir";
    del.onclick = async () => { await api(`/api/tasks/${t.id}`, { method: "DELETE" }); loadTasks(); };
    actions.append(toggle, del);
    el.appendChild(actions);
    list.appendChild(el);
  });
}

/* ---------------- Activity ---------------- */
async function refreshActivity() {
  const activities = await api("/api/activities?limit=200");
  const list = $("#activity-list");
  list.innerHTML = activities.length ? "" : `<p class="hint">Sem atividades.</p>`;
  activities.forEach((a) => {
    const el = document.createElement("div");
    el.className = "list-item";
    el.innerHTML = `<div><b>${escapeHtml(a.kind)}</b> ${escapeHtml(a.detail)}</div><div class="meta">${new Date(a.created_at * 1000).toLocaleTimeString()}</div>`;
    list.appendChild(el);
  });
}

/* ---------------- Projects ---------------- */
async function loadProjects() {
  const projects = await api("/api/projects");
  const list = $("#projects-list");
  if (list) {
    list.innerHTML = projects.length ? "" : `<p class="hint">Nenhum projeto ainda.</p>`;
    projects.forEach((p) => {
      const el = document.createElement("div");
      el.className = "list-item";
      el.innerHTML = `<div><b>${escapeHtml(p.name)}</b><div class="meta">${escapeHtml(p.description || "")}</div></div>`;
      const del = document.createElement("button");
      del.className = "ghost small";
      del.textContent = "Excluir";
      del.onclick = async () => { await api(`/api/projects/${p.id}`, { method: "DELETE" }); loadProjects(); };
      el.appendChild(del);
      list.appendChild(el);
    });
  }
}

/* ---------------- Settings & secrets ---------------- */
async function loadSettings() {
  const s = await api("/api/settings");
  state.settings = s;
  $("#s-provider").value = s.provider;
  $("#s-model").value = s.model;
  $("#s-base-url").value = s.base_url;
  $("#s-temp").value = s.temperature;
  $("#s-maxtokens").value = s.max_tokens;
  $("#s-maxsteps").value = s.max_steps;
  $("#s-autonomy").value = s.autonomy;
  $("#s-network").checked = !!s.allow_network;
  $("#s-tools").checked = !!s.supports_tools;
  $("#autonomy-badge").textContent = s.autonomy === "autonomous" ? "autônomo" : "supervisionado";
  $("#autonomy-badge").className = "badge" + (s.autonomy === "autonomous" ? " autonomous" : "");
  $("#model-badge").textContent = `${s.provider} · ${s.model}`;
  loadModels();
  loadSecrets();
}

async function loadModels() {
  const data = await api("/api/models");
  const prov = $("#s-provider");
  prov.innerHTML = data.providers.map((p) => `<option value="${p}">${p}</option>`).join("");
  prov.value = state.settings.provider;
  const dl = $("#model-suggestions");
  const update = () => {
    const list = data.suggestions[prov.value] || [];
    dl.innerHTML = list.map((m) => `<option value="${m}">`).join("");
  };
  prov.onchange = () => {
    update();
    $("#s-base-url").value = data.base_urls[prov.value] || "";
  };
  update();
}

async function saveSettings() {
  const patch = {
    provider: $("#s-provider").value,
    model: $("#s-model").value,
    base_url: $("#s-base-url").value,
    temperature: parseFloat($("#s-temp").value),
    max_tokens: parseInt($("#s-maxtokens").value, 10),
    max_steps: parseInt($("#s-maxsteps").value, 10),
    autonomy: $("#s-autonomy").value,
    allow_network: $("#s-network").checked,
    supports_tools: $("#s-tools").checked,
  };
  const s = await api("/api/settings", { method: "PUT", body: JSON.stringify(patch) });
  state.settings = s;
  $("#model-badge").textContent = `${s.provider} · ${s.model}`;
  $("#autonomy-badge").textContent = s.autonomy === "autonomous" ? "autônomo" : "supervisionado";
  toast("Configurações salvas");
}

async function loadSecrets() {
  const secrets = await api("/api/secrets");
  const list = $("#secret-list");
  list.innerHTML = secrets.length ? "" : `<p class="hint">Nenhuma chave configurada.</p>`;
  secrets.forEach((s) => {
    const el = document.createElement("div");
    el.className = "list-item";
    el.innerHTML = `<div><b>${escapeHtml(s.name)}</b> <span class="meta">${escapeHtml(s.preview)}</span></div>`;
    const del = document.createElement("button");
    del.className = "ghost small";
    del.textContent = "Excluir";
    del.onclick = async () => { await api(`/api/secrets/${s.name}`, { method: "DELETE" }); loadSecrets(); };
    el.appendChild(del);
    list.appendChild(el);
  });
}

async function saveSecret() {
  const name = $("#secret-name").value;
  const value = $("#secret-value").value.trim();
  if (!value) return toast("Informe o valor", true);
  await api("/api/secrets", { method: "POST", body: JSON.stringify({ name, value }) });
  $("#secret-value").value = "";
  toast("Chave salva (criptografada)");
  loadSecrets();
}

function updateProviderBadge() {
  if (state.lastProvider) $("#model-badge").textContent = `respondendo via ${state.lastProvider}`;
}

/* ---------------- Health ---------------- */
async function refreshHealth() {
  try {
    const h = await api("/api/health");
    const el = $("#status");
    if (h.configured) { el.textContent = `● ${h.provider} / ${h.model}`; el.className = "status ok"; }
    else { el.textContent = `● configure a chave de API (${h.provider})`; el.className = "status err"; }
  } catch (_) {
    $("#status").textContent = "● API offline";
    $("#status").className = "status err";
  }
}

/* ======================================================================
   PC AGENT — pairing, dashboard, permissions
   ====================================================================== */
const PERM_LABELS = {
  system: "Informações do sistema", cpu: "CPU", gpu: "GPU", ram: "RAM",
  storage: "Armazenamento", processes: "Processos", temperatures: "Temperaturas",
  network: "Rede", games: "Informações de jogos", commands: "Execução de comandos autorizados",
};

async function loadAgents() {
  let data;
  try { data = await api("/api/agents"); }
  catch (err) { showError("#device-list", err.message, "Falha ao consultar dispositivos.", "Recarregue a página."); return; }
  // Ensure the server-host pseudo-device exists so the dashboard is usable.
  try { await api("/api/agents/local", { method: "POST" }); data = await api("/api/agents"); } catch (_) {}

  const devices = data.devices || [];
  const list = $("#device-list");
  if (list) {
    list.innerHTML = devices.length ? "" : `<p class="hint">Nenhum dispositivo.</p>`;
    devices.forEach((d) => {
      const el = document.createElement("div");
      el.className = "list-item";
      el.innerHTML = `<div><b>${escapeHtml(d.name)}</b> ${d.online ? "🟢" : "🔴"}
        <div class="meta">${escapeHtml(d.platform || "")} · ${d.id}</div></div>`;
      const row = document.createElement("div");
      row.className = "row";
      const use = document.createElement("button");
      use.className = "ghost small";
      use.textContent = "Selecionar";
      use.onclick = () => selectDevice(d.id);
      row.appendChild(use);
      if (d.id !== "local") {
        const rev = document.createElement("button");
        rev.className = "ghost small";
        rev.textContent = "Revogar";
        rev.onclick = async () => { await api(`/api/agents/${d.id}/revoke`, { method: "POST" }); loadAgents(); };
        row.appendChild(rev);
      }
      el.appendChild(row);
      list.appendChild(el);
    });
  }
  renderPermissions(devices, data.permission_keys || Object.keys(PERM_LABELS));

  // Auto-select the first online device, else local.
  if (!state.deviceId) {
    const online = devices.find((d) => d.online && d.id !== "local") || devices.find((d) => d.id === "local") || devices[0];
    if (online) selectDevice(online.id);
  } else {
    const cur = devices.find((d) => d.id === state.deviceId);
    state.deviceOnline = cur ? cur.online : false;
    updatePcStatus();
  }
}

function renderPermissions(devices, keys) {
  const container = $("#perm-list");
  if (!container) return;
  const dev = devices.find((d) => d.id === state.deviceId);
  const perms = (dev && dev.permissions) || {};
  container.innerHTML = "";
  keys.forEach((k) => {
    const label = document.createElement("label");
    label.className = "check perm";
    label.innerHTML = `<input type="checkbox" data-perm="${k}" ${perms[k] ? "checked" : ""} /> ${escapeHtml(PERM_LABELS[k] || k)}`;
    label.querySelector("input").onchange = async (e) => {
      if (!state.deviceId) return;
      const patch = {}; patch[k] = e.target.checked;
      try {
        await api(`/api/agents/${state.deviceId}/permissions`, { method: "POST", body: JSON.stringify({ permissions: patch }) });
        toast("Permissões atualizadas");
      } catch (err) { toast(err.message, true); e.target.checked = !e.target.checked; }
    };
    container.appendChild(label);
  });
}

async function selectDevice(id) {
  state.deviceId = id;
  state.lastDiagnosis = null;
  state.lastDiagnosisDevice = null;
  try {
    const dev = await api(`/api/agents/${id}`);
    state.deviceOnline = !!dev.online;
  } catch (_) { state.deviceOnline = false; }
  updatePcStatus();
  await refreshDashboard();
}

function updatePcStatus() {
  const el = $("#pc-status");
  if (!el) return;
  if (state.deviceOnline) { el.textContent = "🟢 PC conectado"; el.className = "badge online"; }
  else { el.textContent = "🔴 PC desconectado"; el.className = "badge offline"; }
  const sub = $("#pc-sub");
  if (sub) sub.textContent = state.deviceId ? `dispositivo: ${state.deviceId}` : "conecte um computador";
}

async function refreshDashboard() {
  if (!state.deviceId) {
    await loadAgents();
    if (!state.deviceId) return;
  }
  const empty = $("#pc-empty"), dash = $("#pc-dash");
  let dev;
  try { dev = await api(`/api/agents/${state.deviceId}`); }
  catch (err) { showError("#pc-findings", err.message, "Dispositivo indisponível.", "Reconecte o agente."); return; }

  state.deviceOnline = !!dev.online;
  updatePcStatus();
  const m = dev.metrics || {};

  if (!state.deviceOnline && state.deviceId !== "local") {
    // keep last known data but make the offline state obvious
  }
  empty.classList.toggle("hidden", state.deviceOnline || state.deviceId === "local" || !!m.ts);
  dash.classList.toggle("hidden", !(state.deviceOnline || state.deviceId === "local" || m.ts));

  setGauge("#g-cpu", m.cpu && m.cpu.percent, m.cpu && m.cpu.temp_c != null ? m.cpu.temp_c + "°C" : (m.cpu && m.cpu.cores_logical ? m.cpu.cores_logical + " threads" : ""));
  const gpu = (m.gpu && m.gpu[0]) || null;
  setGauge("#g-gpu", gpu ? gpu.util_percent : null, gpu ? (gpu.name || "").slice(0, 22) : "não detectada");
  setGauge("#g-ram", m.ram && m.ram.percent, m.ram ? `${m.ram.used_mb} / ${m.ram.total_mb} MB` : "");
  setGauge("#g-vram", gpu ? gpu.mem_percent : null, gpu ? `${gpu.mem_used_mb} / ${gpu.mem_total_mb} MB` : "");
  const temp = (m.cpu && m.cpu.temp_c) || (gpu && gpu.temp_c);
  setGauge("#g-temp", temp, temp != null ? temp + "°C" : "indisponível");
  setGauge("#g-net", null, m.network ? `↓ ${m.network.down_kbps} / ↑ ${m.network.up_kbps} kbps` : "—");

  renderProcesses(m.processes || []);
  renderFindings(dev);

  // history + chart
  try {
    const h = await api(`/api/agents/${state.deviceId}/history`);
    state.history = h.samples || [];
    drawChart();
  } catch (_) {}
}

function setGauge(sel, pct, sub) {
  const el = $(sel);
  if (!el) return;
  const val = el.querySelector(".g-val");
  const bar = el.querySelector(".bar > i");
  const subEl = el.querySelector(".g-sub");
  if (pct == null || isNaN(pct)) {
    val.textContent = "—";
    bar.style.width = "0%";
    bar.style.background = "#475569";
  } else {
    val.textContent = Math.round(pct) + "%";
    bar.style.width = Math.min(100, pct) + "%";
    bar.style.background = pct >= 90 ? "#ef4444" : pct >= 75 ? "#f59e0b" : "#22d3ee";
  }
  if (subEl) subEl.textContent = sub || "";
}

function renderProcesses(procs) {
  const el = $("#pc-procs");
  if (!el) return;
  if (!procs.length) { el.innerHTML = `<p class="hint">Processos não autorizados ou indisponíveis.</p>`; return; }
  el.innerHTML = procs.map((p) =>
    `<div class="list-item"><div><b>${escapeHtml(p.name)}</b> <span class="meta">pid ${p.pid}</span></div>
     <div class="meta">CPU ${p.cpu_percent}% · RAM ${p.memory_percent}%</div></div>`).join("");
}

function renderFindings(dev) {
  const el = $("#pc-findings");
  if (!el) return;
  if (state.lastDiagnosis && state.lastDiagnosisDevice === state.deviceId) {
    renderDiagnosis(el, state.lastDiagnosis);
    return;
  }
  el.innerHTML = `<p class="hint">Clique em "Analisar PC" para gerar o diagnóstico com base nos dados reais.</p>`;
}

async function runDiagnose() {
  if (!state.deviceId) return toast("Nenhum dispositivo selecionado", true);
  const el = $("#pc-findings");
  el.innerHTML = `<p class="hint">analisando…</p>`;
  try {
    const d = await api(`/api/agents/${state.deviceId}/diagnose`, { method: "POST" });
    state.lastDiagnosis = d;
    state.lastDiagnosisDevice = state.deviceId;
    renderDiagnosis(el, d);
  } catch (err) {
    showError(el, err.message, "Não foi possível coletar métricas do PC.", "Verifique se o agente está conectado e tente novamente.");
  }
}

function renderDiagnosis(el, d) {
  if (!d || d.ok === false) {
    showError(el, (d && d.error) || "Sem dados", "Telemetria indisponível.", "Conecte o agente do PC.");
    return;
  }
  let html = "";
  if (d.bottleneck) {
    html += `<div class="bottleneck"><b>Gargalo provável: ${escapeHtml(d.bottleneck.label)}</b><div>${escapeHtml(d.bottleneck.explain)}</div></div>`;
  } else {
    html += `<div class="bottleneck ok"><b>Sem gargalo evidente</b><div>${escapeHtml(d.summary || "")}</div></div>`;
  }
  (d.findings || []).forEach((f) => {
    html += `<div class="finding risk-${f.risk}">
      <div class="f-title">${escapeHtml(f.title)} <span class="tag">risco ${escapeHtml(f.risk_label || f.risk)}</span></div>
      <div class="f-row"><b>Dado observado:</b> ${escapeHtml(f.observed)}</div>
      <div class="f-row"><b>Análise:</b> ${escapeHtml(f.analysis)}</div>
      <div class="f-row"><b>Recomendação:</b> ${escapeHtml(f.recommendation)}</div>
      <div class="f-row"><b>Impacto esperado:</b> ${escapeHtml(f.impact)}</div>
    </div>`;
  });
  el.innerHTML = html || `<p class="hint">Nada a reportar.</p>`;
}

/* ---------------- Pairing ---------------- */
async function generatePairCode() {
  try {
    const r = await api("/api/agents/pairing", { method: "POST" });
    const code = r.code;
    $("#pair-code").textContent = code.split("").join(" ");
    $("#pair-echo").textContent = code;
    $("#pair-server").textContent = window.location.origin;
    toast("Código gerado (válido por 10 min)");
  } catch (err) { showError("#connect-status", err.message, "Falha ao gerar o código.", "Tente novamente."); }
}

/* ---------------- Games ---------------- */
async function analyzeGame() {
  const game = $("#game-name").value.trim();
  if (!game) return toast("Informe o jogo", true);
  if (!state.deviceId) return toast("Nenhum PC conectado", true);
  const fps = parseFloat($("#game-fps").value) || null;
  const list = $("#games-list");
  try {
    const profile = await api(`/api/agents/${state.deviceId}/game-profile`, {
      method: "POST", body: JSON.stringify({ game, fps }),
    });
    const card = document.createElement("div");
    card.className = "card";
    let html = `<h3>${escapeHtml(profile.game)}</h3>`;
    if (profile.measured_fps != null) html += `<p class="hint">FPS médio informado: <b>${profile.measured_fps}</b></p>`;
    if (profile.bottleneck) html += `<div class="bottleneck"><b>Gargalo: ${escapeHtml(profile.bottleneck.label)}</b><div>${escapeHtml(profile.bottleneck.explain)}</div></div>`;
    else if (profile.summary) html += `<div class="bottleneck ok">${escapeHtml(profile.summary)}</div>`;
    (profile.findings || []).forEach((f) => {
      html += `<div class="finding risk-${f.risk}"><div class="f-title">${escapeHtml(f.title)}</div>
        <div class="f-row"><b>Dado:</b> ${escapeHtml(f.observed)}</div>
        <div class="f-row"><b>Recomendação:</b> ${escapeHtml(f.recommendation)}</div>
        <div class="f-row"><b>Impacto:</b> ${escapeHtml(f.impact)}</div></div>`;
    });
    card.innerHTML = html;
    list.prepend(card);
  } catch (err) {
    showError(list, err.message, "Não foi possível analisar o jogo.", "Conecte o agente do PC.");
  }
}

async function scanGames() {
  if (!state.deviceId) return toast("Nenhum PC conectado", true);
  try {
    const r = await api(`/api/agents/${state.deviceId}/games`);
    const box = $("#games-detected"), list = $("#games-detected-list");
    box.classList.remove("hidden");
    if (!r.ok || !(r.data || []).length) {
      list.innerHTML = `<p class="hint">${escapeHtml(r.error || "Nenhum jogo detectado (ou sem permissão de jogos).")}</p>`;
      return;
    }
    list.innerHTML = r.data.map((g) => `<div class="list-item"><div><b>${escapeHtml(g.name)}</b>
      <div class="meta">${g.installed ? "instalado" : ""}${g.running ? " · em execução" : ""}</div></div></div>`).join("");
  } catch (err) {
    showError("#games-detected-list", err.message, "Varredura indisponível.", "Conceda a permissão de jogos e reconecte.");
  }
}

/* ---------------- Performance / optimizations ---------------- */
async function loadOptimizations() {
  if (!state.deviceId) { $("#opt-list").innerHTML = `<p class="hint">Conecte um PC.</p>`; return; }
  try {
    const opts = await api(`/api/agents/${state.deviceId}/optimizations`);
    $("#opt-list").innerHTML = "";
    opts.forEach((o) => {
      const card = document.createElement("div");
      card.className = "tool-card";
      card.innerHTML = `<header><span class="name">${escapeHtml(o.title)}</span>
        <span class="tag">risco ${escapeHtml(o.risk)}</span></header>
        <p>${escapeHtml(o.reason)}</p>
        <div class="meta"><b>Impacto:</b> ${escapeHtml(o.impact)}</div>
        <div class="meta"><b>Como desfazer:</b> ${escapeHtml(o.undo)}</div>
        <button class="ghost small" ${o.safe ? "" : "disabled"} data-opt="${o.id}">${o.safe ? "Executar" : "Somente aviso"}</button>`;
      const btn = card.querySelector("button");
      if (o.safe) btn.onclick = () => runOptimization(o);
      $("#opt-list").appendChild(card);
    });
  } catch (err) {
    showError("#opt-list", err.message, "Catálogo indisponível.", "Conecte um PC.");
  }
}

async function runOptimization(o) {
  const confirmed = window.confirm(
    `ALTERAÇÃO: ${o.title}\nRISCO: ${o.risk}\nMOTIVO: ${o.reason}\nCOMO DESFAZER: ${o.undo}\n\nAutorizar execução?`
  );
  if (!confirmed) return;
  const el = $("#opt-result");
  el.innerHTML = `executando ${escapeHtml(o.id)}…`;
  try {
    const r = await api(`/api/agents/${state.deviceId}/optimize`, { method: "POST", body: JSON.stringify({ id: o.id }) });
    el.innerHTML = `<b>${escapeHtml(o.title)}</b><br>${escapeHtml(JSON.stringify(r, null, 2))}`;
    toast(r.ok ? "Otimização executada" : "Falha: " + (r.error || ""), !r.ok);
  } catch (err) {
    showError(el, err.message, "Otimização não executada.", "Conceda a permissão de comandos e tente novamente.");
  }
}

/* ---------------- Charts ---------------- */
function drawChart() {
  const c = $("#chart");
  if (!c) return;
  const ctx = c.getContext("2d");
  const w = c.width, h = c.height;
  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = "#1e293b";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = (h / 4) * i;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
  }
  const samples = state.history.slice(-300);
  if (samples.length < 2) return;
  const series = [
    { key: "cpu", color: "#22d3ee" },
    { key: "gpu", color: "#a78bfa" },
    { key: "ram", color: "#34d399" },
  ];
  series.forEach((s) => {
    ctx.strokeStyle = s.color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    let started = false;
    samples.forEach((sm, i) => {
      const v = sm[s.key];
      if (v == null) { started = false; return; }
      const x = (i / (samples.length - 1)) * w;
      const y = h - (Math.max(0, Math.min(100, v)) / 100) * h;
      if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
    });
    ctx.stroke();
  });
}

/* ---------------- Navigation ---------------- */
const VIEWS = ["pc", "connect", "chat", "games", "performance", "projects", "memory", "tools", "files", "tasks", "activity", "settings"];

function switchView(view) {
  if (!VIEWS.includes(view)) view = "chat";
  $$(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${view}`));
  if (location.hash !== `#${view}`) history.replaceState(null, "", `#${view}`);
  if (view === "tools") loadTools();
  if (view === "files") loadFiles(".");
  if (view === "memory") loadMemories();
  if (view === "tasks") loadTasks();
  if (view === "activity") refreshActivity();
  if (view === "settings") loadSettings();
  if (view === "projects") loadProjects();
  if (view === "pc") refreshDashboard();
  if (view === "connect") loadAgents();
  if (view === "games") scanGames();
  if (view === "performance") loadOptimizations();
  startDashTimer(view === "pc");
}

function startDashTimer(on) {
  if (state.dashTimer) { clearInterval(state.dashTimer); state.dashTimer = null; }
  if (on) state.dashTimer = setInterval(refreshDashboard, 2000);
}

/* ---------------- Wiring ---------------- */
function init() {
  $$(".nav-btn").forEach((b) => (b.onclick = () => switchView(b.dataset.view)));
  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-goto]");
    if (t) switchView(t.dataset.goto);
    const a = e.target.closest("[data-act]");
    if (a && a.dataset.act === "diagnose") runDiagnose();
  });
  $("#new-conv").onclick = newConversation;
  $("#composer").onsubmit = (e) => {
    e.preventDefault();
    const text = $("#input").value.trim();
    if (text && !state.streaming) sendMessage(text);
  };
  $("#input").onkeydown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#composer").requestSubmit(); }
  };
  $("#toggle-autonomy").onclick = async () => {
    const next = state.settings.autonomy === "autonomous" ? "supervised" : "autonomous";
    const s = await api("/api/settings", { method: "PUT", body: JSON.stringify({ autonomy: next }) });
    state.settings = s;
    $("#autonomy-badge").textContent = next === "autonomous" ? "autônomo" : "supervisionado";
    $("#autonomy-badge").className = "badge" + (next === "autonomous" ? " autonomous" : "");
  };
  $("#file-save").onclick = saveFile;
  $("#file-load").onclick = () => openFile($("#file-path").value.trim());
  $("#memory-form").onsubmit = async (e) => {
    e.preventDefault();
    const content = $("#memory-content").value.trim();
    if (!content) return;
    await api("/api/memories", { method: "POST", body: JSON.stringify({ content, tags: $("#memory-tags").value }) });
    $("#memory-content").value = ""; $("#memory-tags").value = "";
    loadMemories();
  };
  const pf = $("#project-form");
  if (pf) pf.onsubmit = async (e) => {
    e.preventDefault();
    const name = $("#project-name").value.trim();
    if (!name) return;
    await api("/api/projects", { method: "POST", body: JSON.stringify({ name, description: $("#project-desc").value }) });
    $("#project-name").value = ""; $("#project-desc").value = "";
    loadProjects();
  };
  $("#task-form").onsubmit = async (e) => {
    e.preventDefault();
    const name = $("#task-name").value.trim();
    const prompt = $("#task-prompt").value.trim();
    const interval_seconds = parseInt($("#task-interval").value, 10) || 3600;
    if (!name || !prompt) return toast("Informe nome e tarefa", true);
    try {
      await api("/api/tasks", { method: "POST", body: JSON.stringify({ name, prompt, interval_seconds }) });
      $("#task-name").value = ""; $("#task-prompt").value = "";
      loadTasks(); toast("Tarefa agendada");
    } catch (err) { toast(err.message, true); }
  };
  $("#s-save").onclick = saveSettings;
  $("#secret-save").onclick = saveSecret;
  $("#logout").onclick = async () => {
    await api("/api/logout", { method: "POST" });
    window.location.href = "/login";
  };
  $("#pc-refresh").onclick = refreshDashboard;
  $("#pair-generate").onclick = generatePairCode;
  $("#game-analyze").onclick = analyzeGame;
  $("#games-scan").onclick = scanGames;

  refreshHealth();
  setInterval(refreshHealth, 15000);
  loadSettings();
  loadProjects();
  loadConversations().then(() => { if (!state.conversationId) newConversation(); });
  loadAgents();

  const fromPath = (location.pathname.replace(/^\//, "") || "chat").split("/")[0];
  const initial = (location.hash || `#${fromPath}`).slice(1);
  switchView(VIEWS.includes(initial) ? initial : "chat");
}

document.addEventListener("DOMContentLoaded", init);
