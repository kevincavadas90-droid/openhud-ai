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
      state.lastAssistantText = payload.text || state.lastAssistantText;
    } else if (event === "tool_start") {
      addToolEvent(payload.name, true, "executando… " + JSON.stringify(payload.arguments));
    } else if (event === "tool_result") {
      addToolEvent(payload.name, payload.ok, payload.output);
    } else if (event === "confirmation") {
      showConfirmation(payload);
    } else if (event === "provider") {
      state.lastProvider = payload.label || payload.provider;
      updateProviderBadge();
    } else if (event === "route") {
      state.lastRoute = payload;
      const el = $("#route-badge");
      if (el) el.textContent = `${payload.icon} ${payload.label}`;
      if (payload.profile) {
        const pb = $("#as-profile-badge");
        if (pb) pb.textContent = `perfil: ${payload.profile}`;
      }
      if (payload.autonomy_level) {
        const lb = $("#as-level-badge");
        if (lb) lb.textContent = `nível: ${payload.autonomy_level}`;
      }
    } else if (event === "task_state") {
      setTaskState(payload.state, payload.label, payload.detail);
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
  screen: "Tela (captura + OCR)", control: "Controle (mouse/teclado)", voice: "Voz (microfone/áudio)",
  ALLOW_MARKET_READ: "MT5 — ler mercado",
  ALLOW_ANALYSIS: "MT5 — analisar",
  ALLOW_ALERTS: "MT5 — criar alertas",
  ALLOW_DEMO_TRADING: "MT5 — operar em conta demo",
  ALLOW_REAL_TRADING: "MT5 — operar em conta REAL (risco de perda)",
  ALLOW_ORDER_MODIFICATION: "MT5 — modificar ordens",
  ALLOW_ORDER_CLOSE: "MT5 — fechar posições",
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

/* ---------------- Trading / MT5 ---------------- */
const trState = { deviceId: null, preview: null, strategyId: null };

async function loadTrading() {
  let cfg;
  try { cfg = await api("/api/trading/config"); } catch (_) { cfg = null; }
  if (cfg && cfg.risk_notice) $("#tr-risk-notice").innerHTML = "⚠️ " + escapeHtml(cfg.risk_notice);
  await refreshTradingStatus();
  trLoadStrategies();
  trLoadAlerts();
  trLoadJournal();
  trLoadPaper();
  trLoadAudit();
  trLoadEducation();
}

async function trLoadEducation() {
  try {
    const e = await api("/api/trading/education");
    let html = e.trilha.map((p) => `<div class="finding"><b>${p.passo}. ${escapeHtml(p.titulo)}</b><small>${escapeHtml(p.texto)}</small></div>`).join("");
    html += "<h4>Glossário</h4>" + Object.entries(e.glossario).map(([k, v]) => `<div class="finding"><b>${escapeHtml(k)}</b><small>${escapeHtml(v)}</small></div>`).join("");
    html += `<p class="hint">${escapeHtml(e.aviso)}</p>`;
    $("#tr-education").innerHTML = html;
  } catch (_) {}
}

async function refreshTradingStatus() {
  let st;
  try { st = await api("/api/trading/status"); }
  catch (err) { showError("#tr-analysis", err.message, "O agente do PC pode estar desconectado."); return; }
  const connected = !!(st && st.ok && st.connected);
  trState.deviceId = st && st.device_id ? st.device_id : null;
  const badge = $("#tr-conn");
  badge.textContent = connected ? "🟢 MT5 conectado" : "🔴 MT5 desconectado";
  badge.className = "badge " + (connected ? "online" : "offline");
  $("#tr-empty").classList.toggle("hidden", connected);
  $("#tr-dash").classList.toggle("hidden", !connected);
  if (!connected) {
    $("#tr-sub").textContent = (st && st.error) ? st.error : "conecte um PC com MetaTrader 5";
    return;
  }
  $("#tr-sub").textContent = `${st.name || "MetaTrader 5"} · build ${st.build || "?"}`;
  trLoadAccount();
  trLoadPositions();
  trLoadMode();
}

async function trLoadMode() {
  try {
    const m = await api("/api/trading/mode");
    if (m && m.ok) {
      $("#tr-mode").value = m.trading_mode;
      $("#tr-mode-badge").textContent = "modo: " + m.trading_mode;
      const lim = m.risk_limits || {};
      if (lim.max_risk_per_trade_pct != null) $("#tr-lim-risk").value = lim.max_risk_per_trade_pct;
      if (lim.max_daily_loss_pct != null) $("#tr-lim-day").value = lim.max_daily_loss_pct;
      if (lim.max_trades_per_day != null) $("#tr-lim-trades").value = lim.max_trades_per_day;
      if (lim.max_open_positions != null) $("#tr-lim-pos").value = lim.max_open_positions;
      if (lim.max_lot != null) $("#tr-lim-lot").value = lim.max_lot;
      if (m.emergency_stop) toast("STOP TRADING está ATIVO", true);
    }
  } catch (_) {}
}

async function trLoadAccount() {
  try {
    const a = await api("/api/trading/account");
    if (!a.ok) { $("#tr-account").innerHTML = `<span class="err">${escapeHtml(a.error)}</span>`; return; }
    const d = a.account;
    $("#tr-account").innerHTML = `
      <div>Login: <b>${escapeHtml(d.login)}</b> @ ${escapeHtml(d.server)} (${escapeHtml(d.broker)})</div>
      <div>Saldo: <b>${d.balance} ${escapeHtml(d.currency)}</b> · Equity: <b>${d.equity}</b></div>
      <div>Margem: ${d.margin} · Livre: ${d.margin_free} · Nível: ${d.margin_level ?? "—"}</div>
      <div>Lucro flutuante: ${d.profit} · Negociação permitida: ${d.trade_allowed}</div>`;
  } catch (err) { showError("#tr-account", err.message); }
}

async function trLoadPositions() {
  try {
    const p = await api("/api/trading/positions");
    if (!p.ok) { $("#tr-positions").innerHTML = `<span class="err">${escapeHtml(p.error)}</span>`; return; }
    if (!p.positions.length) { $("#tr-positions").textContent = "Nenhuma posição aberta."; return; }
    $("#tr-positions").innerHTML = p.positions.map((x) => `
      <div class="list-row">
        <span><b>${escapeHtml(x.symbol)}</b> ${escapeHtml(x.direction)} ${x.volume} @ ${x.price_open}</span>
        <span>SL ${x.sl} · TP ${x.tp} · <b class="${x.profit >= 0 ? "pos" : "neg"}">${x.profit}</b></span>
        <button class="ghost small" data-close-ticket="${x.ticket}">fechar</button>
      </div>`).join("");
  } catch (err) { showError("#tr-positions", err.message); }
}

async function trAnalyse() {
  const symbol = $("#tr-symbol").value.trim();
  const timeframe = $("#tr-timeframe").value;
  $("#tr-analysis").textContent = "analisando…";
  try {
    const a = await api(`/api/trading/analyse?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}&multi=true`);
    if (!a.ok) { showError("#tr-analysis", a.error, "Verifique se o ativo existe no seu MT5 e se há histórico."); return; }
    const mt = a.multi_timeframe;
    let html = `<div class="findings-head">${escapeHtml(a.symbol)} · consenso multi-timeframe: <b>${escapeHtml(mt.consensus)}</b> (${mt.aligned ? "alinhado" : "divergente"})</div>`;
    for (const [tf, v] of Object.entries(mt.per_timeframe)) {
      html += `<div class="finding"><b>${tf}</b>: tendência ${escapeHtml(v.trend)} · estrutura ${escapeHtml(v.structure)} · RSI ${v.rsi ?? "—"}</div>`;
    }
    if (a.detail && a.detail.findings) {
      html += "<hr/>" + a.detail.findings.map((f) => `<div class="finding"><b>${escapeHtml(f.label)}</b><small>${escapeHtml(f.detail)}</small></div>`).join("");
    }
    html += `<p class="hint">Preço: ${a.detail ? a.detail.price : "—"} · barras: ${a.detail ? a.detail.bars : "—"}</p>`;
    $("#tr-analysis").innerHTML = html;
  } catch (err) { showError("#tr-analysis", err.message); }
}

async function trBrief() {
  const symbol = $("#tr-symbol").value.trim();
  const timeframe = $("#tr-timeframe").value;
  $("#tr-analysis").textContent = "gerando resumo…";
  try {
    const b = await api(`/api/trading/brief?symbols=${encodeURIComponent(symbol)}&timeframe=${timeframe}`);
    if (!b.ok) { showError("#tr-analysis", b.error); return; }
    let html = "<h4>Resumo do mercado</h4>";
    for (const e of b.symbols) {
      if (!e.ok) { html += `<div class="finding">${escapeHtml(e.symbol)}: sem dados (${escapeHtml(e.error)})</div>`; continue; }
      html += `<div class="finding"><b>${escapeHtml(e.symbol)}</b> — tendência ${escapeHtml(e.trend)} · volatilidade ${escapeHtml(e.volatility)} · estrutura ${escapeHtml(e.structure)} · preço ${e.price}</div>`;
    }
    if (!b.opportunities.length) html += `<p class="hint">Nenhuma configuração compatível encontrada.</p>`;
    $("#tr-analysis").innerHTML = html;
  } catch (err) { showError("#tr-analysis", err.message); }
}

async function trScan() {
  const symbol = $("#tr-symbol").value.trim();
  const timeframe = $("#tr-timeframe").value;
  $("#tr-analysis").textContent = "varrendo…";
  try {
    const sid = trState.strategyId ? `&strategy_id=${encodeURIComponent(trState.strategyId)}` : "";
    const s = await api(`/api/trading/scan?symbols=${encodeURIComponent(symbol)}&timeframe=${timeframe}${sid}`);
    if (!s.ok) { showError("#tr-analysis", s.error); return; }
    let html = "<h4>Varredura rápida</h4>";
    if (!s.found.length) html += `<p class="hint">Nenhuma configuração compatível encontrada.</p>`;
    for (const f of s.found) html += `<div class="finding"><b>${escapeHtml(f.symbol)}</b> — sinal ${escapeHtml(f.signal)} · preço ${f.price}</div>`;
    $("#tr-analysis").innerHTML = html;
  } catch (err) { showError("#tr-analysis", err.message); }
}

async function trLoadStrategies() {
  try {
    const list = await api("/api/trading/strategies");
    $("#tr-strat-list").innerHTML = list.map((s) => `
      <div class="list-row">
        <span><b>${escapeHtml(s.name)}</b> <small>${escapeHtml(s.timeframe || "")}</small></span>
        <span>
          <button class="ghost small" data-strat-pick="${s.id}">selecionar</button>
          <button class="ghost small" data-strat-del="${s.id}">excluir</button>
        </span>
      </div>`).join("") || "<span class='hint'>Nenhuma estratégia salva.</span>";
  } catch (_) {}
}

async function trSaveStrategy() {
  const text = $("#tr-strat-text").value.trim();
  if (!text) return toast("Descreva a estratégia", true);
  try {
    const r = await api("/api/trading/strategies", { method: "POST", body: JSON.stringify({ text, name: $("#tr-strat-name").value || null, timeframe: $("#tr-timeframe").value }) });
    const s = r.interpreted;
    const rules = [
      ["Entrada compra", s.entry_long.map((c) => c.label).join("; ")],
      ["Entrada venda", s.entry_short.map((c) => c.label).join("; ")],
      ["Saída", s.exit.map((c) => c.label).join("; ")],
      ["Filtros", s.filters.map((c) => c.label).join("; ")],
    ].map(([k, v]) => `<div><b>${k}:</b> ${escapeHtml(v || "—")}</div>`).join("");
    $("#tr-analysis").innerHTML = `<h4>Estratégia interpretada: ${escapeHtml(s.name)}</h4>${rules}
      <div>Stop: ${escapeHtml(JSON.stringify(s.stop))} · Take: ${escapeHtml(JSON.stringify(s.take))}</div>
      ${s.notes.map((n) => `<p class="hint">${escapeHtml(n)}</p>`).join("")}`;
    $("#tr-strat-name").value = "";
    trState.strategyId = r.strategy.id;
    trLoadStrategies();
  } catch (err) { showError("#tr-analysis", err.message); }
}

async function trBacktest() {
  if (!trState.strategyId) return toast("Selecione ou crie uma estratégia", true);
  const symbol = $("#tr-symbol").value.trim();
  const timeframe = $("#tr-timeframe").value;
  $("#tr-backtest-out").textContent = "rodando backtest…";
  try {
    const r = await api("/api/trading/backtest", { method: "POST", body: JSON.stringify({ symbol, strategy_id: trState.strategyId, timeframe, count: 500 }) });
    if (!r.ok) { $("#tr-backtest-out").innerHTML = `<span class="err">${escapeHtml(r.error)}</span>`; return; }
    const m = r.metrics;
    $("#tr-backtest-out").innerHTML = `
      <div>Operações: <b>${m.trades}</b> · Acerto: <b>${m.win_rate}%</b> · Profit factor: <b>${m.profit_factor}</b></div>
      <div>Resultado: ${m.net_result} · Drawdown máx: ${m.max_drawdown_pct}%</div>
      <div>Sequências: ${m.max_consec_wins} ganhos / ${m.max_consec_losses} perdas</div>
      <p class="hint">${escapeHtml(r.disclaimer)}</p>`;
  } catch (err) { $("#tr-backtest-out").innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`; }
}

async function trLoadAlerts() {
  try {
    const list = await api("/api/trading/alerts");
    $("#tr-alert-list").innerHTML = list.map((a) => `
      <div class="list-row">
        <span>${a.enabled ? "🟢" : "⚪"} <b>${escapeHtml(a.symbol)}</b> ${escapeHtml(a.kind)} ${escapeHtml(JSON.stringify(a.params))}</span>
        <span>
          <button class="ghost small" data-alert-toggle="${a.id}" data-enabled="${a.enabled}">${a.enabled ? "pausar" : "ativar"}</button>
          <button class="ghost small" data-alert-del="${a.id}">excluir</button>
        </span>
      </div>`).join("") || "<span class='hint'>Nenhum alerta.</span>";
  } catch (_) {}
}

async function trAddAlert() {
  const kind = $("#tr-alert-kind").value;
  const value = parseFloat($("#tr-alert-value").value);
  const symbol = $("#tr-symbol").value.trim();
  const timeframe = $("#tr-timeframe").value;
  const op = $("#tr-alert-op").value || ">=";
  const params = kind === "price" ? { value, op } : kind === "indicator" ? { indicator: "rsi", period: 14, op, value } : { op, value };
  try {
    await api("/api/trading/alerts", { method: "POST", body: JSON.stringify({ symbol, timeframe, kind, params }) });
    $("#tr-alert-value").value = "";
    trLoadAlerts(); toast("Alerta criado");
  } catch (err) { toast(err.message, true); }
}

async function trEvalAlerts() {
  $("#tr-alert-out").textContent = "avaliando…";
  try {
    const r = await api("/api/trading/alerts/evaluate", { method: "POST" });
    if (!r.ok) { $("#tr-alert-out").innerHTML = `<span class="err">${escapeHtml(r.error)}</span>`; return; }
    $("#tr-alert-out").innerHTML = r.alerts.map((a) => `
      <div>${a.triggered ? "🔔" : "—"} <b>${escapeHtml(a.symbol)}</b> ${escapeHtml(a.reason || a.error || "")}</div>`).join("") || "<span class='hint'>Nenhum alerta ativo.</span>";
  } catch (err) { $("#tr-alert-out").innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`; }
}

async function trLoadPaper() {
  try {
    const r = await api("/api/trading/paper");
    const s = r.summary;
    $("#tr-paper-sum").innerHTML = `
      <div>Saldo: <b>${s.balance}</b> · Equity: <b>${s.equity}</b></div>
      <div>Posições: ${s.open_positions} · Fechadas: ${s.closed_trades} · Acerto: ${s.win_rate ?? "—"}%</div>
      <div>Resultado: ${s.net_result} · Drawdown máx: ${s.max_drawdown_pct}%</div>`;
    $("#tr-paper-pos").innerHTML = (r.positions || []).map((p) => `
      <div class="list-row"><span>${escapeHtml(p.symbol)} ${escapeHtml(p.direction)} ${p.lot} @ ${p.entry}</span>
      <button class="ghost small" data-paper-close="${p.id}">fechar</button></div>`).join("");
  } catch (_) {}
}

async function trPaperOpen() {
  const body = {
    symbol: $("#tr-symbol").value.trim(), direction: $("#tr-paper-dir").value.trim(),
    lot: parseFloat($("#tr-paper-lot").value), entry: parseFloat($("#tr-paper-entry").value),
  };
  try {
    const r = await api("/api/trading/paper/open", { method: "POST", body: JSON.stringify(body) });
    if (!r.ok) return toast(r.error, true);
    trLoadPaper(); toast("Posição simulada aberta");
  } catch (err) { toast(err.message, true); }
}

async function trPrepareOrder() {
  const body = {
    symbol: $("#tr-symbol").value.trim(), direction: $("#tr-ord-dir").value.trim(),
    entry: parseFloat($("#tr-ord-entry").value), stop: parseFloat($("#tr-ord-stop").value),
    take: parseFloat($("#tr-ord-take").value) || null, risk_pct: parseFloat($("#tr-lim-risk").value) || 1,
    request_id: (crypto.randomUUID ? crypto.randomUUID() : String(Date.now())),
  };
  try {
    const r = await api("/api/trading/order/prepare", { method: "POST", body: JSON.stringify(body) });
    if (!r.ok) {
      const v = (r.violations || []).map(escapeHtml).join("<br/>");
      $("#tr-ord-preview").innerHTML = `<span class="err">${escapeHtml(r.error)}</span>${v ? "<br/>" + v : ""}`;
      trState.preview = null; return;
    }
    trState.preview = { ...r.preview, request_id: r.request_id };
    const p = r.preview;
    $("#tr-ord-preview").innerHTML = `
      <div>Modo: <b>${escapeHtml(p.mode)}</b> · ${escapeHtml(p.symbol)} ${escapeHtml(p.direction)}</div>
      <div>Lote: <b>${p.lot}</b> · Risco: ${p.risk_actual} (${p.risk_actual_pct}%) · R:R ${p.reward_risk}</div>
      <div>Margem: ${p.margin} · Livre: ${p.margin_free}</div>
      ${(p.warnings || []).map((w) => `<div class="hint">⚠️ ${escapeHtml(w)}</div>`).join("")}`;
  } catch (err) { $("#tr-ord-preview").innerHTML = `<span class="err">${escapeHtml(err.message)}</span>`; }
}

async function trExecuteOrder() {
  if (!trState.preview) return toast("Calcule a pré-ordem primeiro", true);
  const p = trState.preview;
  if (p.mode === "real" && !window.confirm("ATENÇÃO: enviar ordem REAL com dinheiro real?\n\n" + p.symbol + " " + p.direction + " " + p.lot + " lotes")) return;
  try {
    const r = await api("/api/trading/order/execute", { method: "POST", body: JSON.stringify({
      symbol: p.symbol, direction: p.direction, lot: p.lot, stop: p.stop, take: p.take,
      request_id: p.request_id, strategy_name: p.strategy, confirmed: true,
    }) });
    if (!r.ok) { toast("Ordem não confirmada: " + r.error, true); return; }
    toast(r.duplicate ? "Ordem já registrada (idempotente)" : "Ordem confirmada pelo MT5");
    trState.preview = null; $("#tr-ord-preview").innerHTML = "";
    refreshTradingStatus();
  } catch (err) { toast(err.message, true); }
}

async function trEmergencyStop() {
  if (!window.confirm("Ativar STOP TRADING? Novas ordens serão bloqueadas.")) return;
  try {
    const r = await api("/api/trading/stop", { method: "POST", body: JSON.stringify({ active: true }) });
    toast(r.ok ? "STOP TRADING ativado" : "Falha ao ativar", !r.ok);
  } catch (err) { toast(err.message, true); }
}

async function trLoadJournal() {
  try {
    const list = await api("/api/trading/journal");
    $("#tr-j-list").innerHTML = list.map((j) => `
      <div class="list-row">
        <span><b>${escapeHtml(j.symbol)}</b> ${escapeHtml(j.strategy)} · <span class="${j.result >= 0 ? "pos" : "neg"}">${j.result ?? "—"}</span></span>
        <span><small>${escapeHtml(j.notes)}</small></span>
        <button class="ghost small" data-journal-del="${j.id}">excluir</button>
      </div>`).join("") || "<span class='hint'>Diário vazio.</span>";
  } catch (_) {}
}

async function trAddJournal() {
  const body = {
    symbol: $("#tr-j-symbol").value.trim(), strategy: $("#tr-j-strategy").value.trim(),
    result: parseFloat($("#tr-j-result").value) || 0, notes: $("#tr-j-notes").value.trim(),
  };
  try {
    await api("/api/trading/journal", { method: "POST", body: JSON.stringify(body) });
    $("#tr-j-symbol").value = $("#tr-j-strategy").value = $("#tr-j-result").value = $("#tr-j-notes").value = "";
    trLoadJournal(); toast("Registro salvo");
  } catch (err) { toast(err.message, true); }
}

async function trSaveLimits() {
  const limits = {
    max_risk_per_trade_pct: parseFloat($("#tr-lim-risk").value),
    max_daily_loss_pct: parseFloat($("#tr-lim-day").value),
    max_trades_per_day: parseInt($("#tr-lim-trades").value, 10),
    max_open_positions: parseInt($("#tr-lim-pos").value, 10),
    max_lot: parseFloat($("#tr-lim-lot").value),
  };
  try {
    const r = await api("/api/trading/limits", { method: "POST", body: JSON.stringify({ limits }) });
    toast(r.ok ? "Limites salvos" : "Falha ao salvar", !r.ok);
  } catch (err) { toast(err.message, true); }
}

async function trSetMode() {
  const mode = $("#tr-mode").value;
  try {
    const r = await api("/api/trading/mode", { method: "POST", body: JSON.stringify({ mode }) });
    if (!r.ok) return toast(r.error || "Não foi possível mudar o modo", true);
    $("#tr-mode-badge").textContent = "modo: " + mode;
    toast("Modo alterado para " + mode);
  } catch (err) { toast(err.message, true); refreshTradingStatus(); }
}

async function trLoadAudit() {
  try {
    const list = await api("/api/trading/audit");
    $("#tr-audit").innerHTML = list.map((a) => `
      <div>${new Date(a.ts * 1000).toLocaleString()} · <b>${escapeHtml(a.action)}</b> ${escapeHtml(a.symbol || "")} → ${escapeHtml(a.result || "")} ${a.error ? "(" + escapeHtml(a.error) + ")" : ""}</div>`).join("") || "<span class='hint'>Sem eventos.</span>";
  } catch (_) {}
}

function wireTrading() {
  $("#tr-refresh").onclick = refreshTradingStatus;
  $("#tr-analyse").onclick = trAnalyse;
  $("#tr-brief").onclick = trBrief;
  $("#tr-scan").onclick = trScan;
  $("#tr-strat-save").onclick = trSaveStrategy;
  $("#tr-backtest").onclick = trBacktest;
  $("#tr-alert-add").onclick = trAddAlert;
  $("#tr-alert-eval").onclick = trEvalAlerts;
  $("#tr-paper-open").onclick = trPaperOpen;
  $("#tr-ord-prepare").onclick = trPrepareOrder;
  $("#tr-ord-execute").onclick = trExecuteOrder;
  $("#tr-stop").onclick = trEmergencyStop;
  $("#tr-j-add").onclick = trAddJournal;
  $("#tr-lim-save").onclick = trSaveLimits;
  $("#tr-mode").onchange = trSetMode;
  document.addEventListener("click", async (e) => {
    const pick = e.target.closest("[data-strat-pick]");
    if (pick) { trState.strategyId = pick.dataset.stratPick; toast("Estratégia selecionada"); return; }
    const sdel = e.target.closest("[data-strat-del]");
    if (sdel) { await api(`/api/trading/strategies/${sdel.dataset.stratDel}`, { method: "DELETE" }); trLoadStrategies(); return; }
    const atog = e.target.closest("[data-alert-toggle]");
    if (atog) { await api(`/api/trading/alerts/${atog.dataset.alertToggle}/toggle`, { method: "POST", body: JSON.stringify({ enabled: atog.dataset.enabled !== "true" }) }); trLoadAlerts(); return; }
    const adel = e.target.closest("[data-alert-del]");
    if (adel) { await api(`/api/trading/alerts/${adel.dataset.alertDel}`, { method: "DELETE" }); trLoadAlerts(); return; }
    const jdel = e.target.closest("[data-journal-del]");
    if (jdel) { await api(`/api/trading/journal/${jdel.dataset.journalDel}`, { method: "DELETE" }); trLoadJournal(); return; }
    const ct = e.target.closest("[data-close-ticket]");
    if (ct) { if (window.confirm("Fechar a posição " + ct.dataset.closeTicket + "?")) { const r = await api("/api/trading/close", { method: "POST", body: JSON.stringify({ ticket: parseInt(ct.dataset.closeTicket, 10) }) }); toast(r.ok ? "Posição fechada" : "Falha: " + r.error, !r.ok); refreshTradingStatus(); } return; }
    const pc = e.target.closest("[data-paper-close]");
    if (pc) {
      const price = parseFloat(window.prompt("Preço de fechamento:", $("#tr-symbol").value ? "" : "") || "");
      if (!isNaN(price)) { await api("/api/trading/paper/close", { method: "POST", body: JSON.stringify({ position_id: pc.dataset.paperClose, price }) }); trLoadPaper(); }
      return;
    }
  });
}

/* ---------------- Modes & routing ---------------- */
async function loadModes() {
  try {
    const data = await api("/api/ai/modes");
    const sel = $("#mode-select");
    sel.innerHTML = data.modes.map((m) =>
      `<option value="${m.key}" ${m.key === data.current ? "selected" : ""}>${m.icon} ${m.label}</option>`).join("");
    state.modes = data.modes;
    updateRouteBadge(data.current);
    sel.onchange = async () => {
      try {
        await api("/api/ai/mode", { method: "PUT", body: JSON.stringify({ mode: sel.value }) });
        updateRouteBadge(sel.value);
        toast("Modo alterado");
      } catch (err) { toast(err.message, true); }
    };
  } catch (err) { /* modes are non-critical */ }
}

function updateRouteBadge(modeKey) {
  const m = (state.modes || []).find((x) => x.key === modeKey);
  const el = $("#route-badge");
  if (el) el.textContent = m ? `${m.icon} ${m.label}` : "⚡ AUTO";
}

/* ---------------- Voice ---------------- */
const voice = {
  rec: null, speaking: false, audio: null, text: "", wake: false,
};

function voiceStatus(msg, isError = false) {
  const el = $("#voice-status");
  if (!el) return;
  el.textContent = msg || "";
  el.className = "voice-status" + (isError ? " err" : "");
}

function voiceSupported() {
  return "webkitSpeechRecognition" in window || "SpeechRecognition" in window;
}

async function loadVoiceSettings() {
  try {
    const st = await api("/api/ai/voice/status");
    state.voiceStatus = st;
    const langSel = $("#v-language");
    langSel.innerHTML = `<option value="auto">Detecção automática</option>` +
      st.languages.map((l) => `<option value="${l.code}">${l.label}</option>`).join("");
    const styleSel = $("#v-style");
    styleSel.innerHTML = st.styles.map((s) => `<option value="${s}">${s}</option>`).join("");
    $("#v-providers").textContent = "TTS: " + st.tts_providers.map((p) =>
      `${p.name} ${p.available ? "✓" : "✗"}`).join(" · ") + " | STT: " +
      st.stt_providers.map((p) => `${p.name} ${p.available ? "✓" : "✗"}`).join(" · ");

    // Reflect current config.
    const cfg = st.config || {};
    $("#v-rate").value = cfg.voice_rate || "";
    $("#v-pitch").value = cfg.voice_pitch || "";
    $("#v-provider").value = cfg.voice_provider || "auto";
    $("#v-wake-phrase").value = cfg.voice_wake_phrase || "OpenHUD";
    $("#v-continuous").checked = !!cfg.voice_continuous;
    $("#v-wake").checked = !!cfg.voice_wake_word;
    $("#v-save-transcript").checked = !!cfg.voice_save_transcript;
    $("#v-save-history").checked = !!cfg.voice_save_history;
    if (cfg.voice_language) $("#v-language").value = cfg.voice_language;
    if (cfg.voice_style) $("#v-style").value = cfg.voice_style;
  } catch (err) { /* non-critical */ }
}

async function saveVoiceSettings() {
  const payload = {
    voice_language: $("#v-language").value,
    voice_style: $("#v-style").value,
    voice_rate: $("#v-rate").value,
    voice_pitch: $("#v-pitch").value,
    voice_provider: $("#v-provider").value,
    voice_wake_phrase: $("#v-wake-phrase").value,
    voice_continuous: $("#v-continuous").checked,
    voice_wake_word: $("#v-wake").checked,
    voice_save_transcript: $("#v-save-transcript").checked,
    voice_save_history: $("#v-save-history").checked,
  };
  try {
    await api("/api/ai/voice/config", { method: "PUT", body: JSON.stringify(payload) });
    toast("Configurações de voz salvas");
    loadVoiceSettings();
  } catch (err) { toast(err.message, true); }
}

function currentVoiceLang() {
  const sel = $("#v-language");
  const v = sel ? sel.value : "pt-BR";
  return v === "auto" ? "" : v;
}

function startRecognition(continuous) {
  if (!voiceSupported()) {
    voiceStatus("Reconhecimento de voz não suportado neste navegador.", true);
    return;
  }
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const rec = new SR();
  rec.lang = currentVoiceLang() || "pt-BR";
  rec.continuous = !!continuous;
  rec.interimResults = false;
  voice.rec = rec;
  voiceStatus("🎙️ Ouvindo…");
  rec.onresult = async (e) => {
    const text = Array.from(e.results).map((r) => r[0].transcript).join(" ").trim();
    if (!text) return;
    voice.text = text;
    // Wake word gate (optional).
    if (voice.wake) {
      const phrase = ($("#v-wake-phrase")?.value || "OpenHUD").toLowerCase();
      if (!text.toLowerCase().includes(phrase)) { voiceStatus("Aguardando wake word…"); return; }
      text = text.replace(new RegExp(phrase, "i"), "").trim();
    }
    if (!text) return;
    // Persist transcript only if the user opted in.
    try { await api("/api/ai/voice/transcript", { method: "POST", body: JSON.stringify({ text, language: rec.lang }) }); } catch (_) {}
    voiceStatus("Transcrito. Enviando…");
    await sendMessage(text);
    if (state.lastAssistantText) speakText(state.lastAssistantText);
    if (continuous) { try { rec.start(); } catch (_) {} }
  };
  rec.onerror = (e) => voiceStatus("Erro no microfone: " + e.error, true);
  rec.onend = () => { if (voice.rec && voice.rec._want) { try { rec.start(); } catch (_) {} } };
  try { rec.start(); } catch (err) { voiceStatus("Não foi possível iniciar o microfone: " + err.message, true); }
}

function stopRecognition() {
  if (voice.rec) { voice.rec._want = false; try { voice.rec.stop(); } catch (_) {} voice.rec = null; }
  voiceStatus("Microfone parado.");
}

async function speakText(text) {
  if (!text) { voiceStatus("Nada para falar.", true); return; }
  voice.text = text;
  const cfg = state.voiceStatus && state.voiceStatus.config;
  if (cfg && cfg.voice_provider === "browser") { browserSpeak(text); return; }
  voiceStatus("Sintetizando…");
  try {
    const res = await fetch("/api/ai/voice/speak", {
      method: "POST", headers: { "Content-Type": "application/json" },
      credentials: "same-origin", body: JSON.stringify({ text }),
    });
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try { const j = await res.json(); detail = (j.detail && (j.detail.error || JSON.stringify(j.detail))) || detail; } catch (_) {}
      voiceStatus("TTS falhou (" + detail + "). Tentando o navegador…", true);
      browserSpeak(text);
      return;
    }
    const blob = await res.blob();
    playAudio(blob);
    voiceStatus("🔊 Falando (" + (res.headers.get("x-voice-provider") || "provider") + ")");
  } catch (err) {
    voiceStatus("TTS falhou: " + err.message, true);
    browserSpeak(text);
  }
}

function playAudio(blob) {
  stopAudio();
  voice.audio = new Audio(URL.createObjectURL(blob));
  voice.speaking = true;
  voice.audio.onended = () => { voice.speaking = false; voiceStatus("Pronto."); };
  voice.audio.play().catch((e) => voiceStatus("Não foi possível reproduzir: " + e.message, true));
}

function stopAudio() {
  if (voice.audio) { try { voice.audio.pause(); } catch (_) {} voice.audio = null; }
  voice.speaking = false;
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
}

function browserSpeak(text) {
  if (!("speechSynthesis" in window)) { voiceStatus("Navegador sem TTS.", true); return; }
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = currentVoiceLang() || "pt-BR";
  window.speechSynthesis.speak(u);
  voiceStatus("🔊 Falando (navegador)");
}

/* ---------------- Codex ---------------- */
async function loadCodexChanges() {
  try {
    const list = await api("/api/ai/codex/changes");
    const el = $("#cx-changes");
    if (!list.length) { el.innerHTML = `<div class="muted small">Nenhuma alteração proposta.</div>`; return; }
    el.innerHTML = list.map((cs) => {
      const diffs = cs.changes.map((c) => `<details><summary class="small">${escapeHtml(c.path)}</summary><pre class="mono small">${escapeHtml(c.diff || "(novo arquivo)")}</pre></details>`).join("");
      return `<div class="list-item"><div class="row"><b>${escapeHtml(cs.title)}</b><span class="badge">${cs.status}</span></div>
        ${diffs}
        <div class="row">
          <button class="ghost small" data-cx-apply="${cs.id}">Aceitar</button>
          <button class="ghost small" data-cx-reject="${cs.id}">Rejeitar</button>
          <button class="ghost small" data-cx-revert="${cs.id}">Reverter</button>
        </div></div>`;
    }).join("");
  } catch (err) { toast(err.message, true); }
}

async function codexAction(id, action) {
  try {
    await api(`/api/ai/codex/changes/${id}/${action}`, { method: "POST" });
    toast("Alteração " + action + " concluída");
    loadCodexChanges();
  } catch (err) { toast(err.message, true); }
}

/* ---------------- Media ---------------- */
async function loadMediaProviders() {
  try {
    const p = await api("/api/ai/media/providers");
    $("#im-providers").textContent = "Imagem: " + p.image.map((x) => `${x.name} ${x.available ? "✓" : "✗"}`).join(" · ");
  } catch (_) {}
}

async function loadVideoProviders() {
  try {
    const p = await api("/api/ai/media/providers");
    $("#vd-providers").textContent = "Vídeo: " + p.video.map((x) => `${x.name} ${x.available ? "✓" : "✗"}`).join(" · ");
  } catch (_) {}
}

async function generateImage() {
  const prompt = $("#im-prompt").value.trim();
  if (!prompt) return toast("Informe o prompt", true);
  const el = $("#im-result");
  el.innerHTML = `<div class="muted small">Gerando…</div>`;
  try {
    const res = await api("/api/ai/images/generate", { method: "POST", body: JSON.stringify({
      prompt, width: parseInt($("#im-width").value, 10) || 1024, height: parseInt($("#im-height").value, 10) || 1024,
    }) });
    el.innerHTML = `<div class="card"><img src="${res.url}" alt="${escapeHtml(prompt)}" style="max-width:100%" />
      <div class="small">Provider: ${escapeHtml(res.provider)} · <a href="${res.url}" download>baixar</a></div></div>`;
  } catch (err) {
    showError(el, err.message, "O provider de imagem pode estar indisponível.", "Tente novamente ou configure uma chave OpenAI.");
  }
}

async function renderVideo() {
  const script = $("#vd-script").value.trim();
  if (!script) return toast("Escreva o roteiro", true);
  const images = $("#vd-images").value.split(",").map((s) => s.trim()).filter(Boolean);
  try {
    const res = await api("/api/ai/video/render", { method: "POST", body: JSON.stringify({ script, images }) });
    toast("Vídeo enfileirado");
    pollJobs();
  } catch (err) { toast(err.message, true); }
}

async function pollJobs() {
  try {
    const jobs = await api("/api/ai/jobs?kind=video");
    $("#vd-jobs").innerHTML = jobs.length ? jobs.map((j) => `
      <div class="list-item">
        <div class="row"><b>${j.id.slice(0, 8)}</b><span class="badge">${j.status}</span><span>${j.progress}%</span></div>
        ${j.error ? `<div class="small err">${escapeHtml(j.error)}</div>` : ""}
        ${j.result && j.result.url ? `<div class="small"><a href="${j.result.url}" target="_blank">abrir vídeo</a></div>` : ""}
        <pre class="mono small">${escapeHtml((j.logs || "").slice(-500))}</pre>
      </div>`).join("") : `<div class="muted small">Nenhum job de vídeo.</div>`;
  } catch (_) {}
}

/* ---------------- Plugins ---------------- */
async function loadPlugins() {
  try {
    const s = await api("/api/ai/plugins");
    $("#pl-installed").innerHTML = s.installed.length ? s.installed.map((p) => `
      <div class="list-item"><div class="row"><b>${escapeHtml(p.name)}</b><span class="badge">${p.enabled ? "ativo" : "desativado"}</span>
      <span class="small">risco ${p.risk}</span></div>
      <div class="small">${escapeHtml(p.description)}</div>
      <div class="row">
        <button class="ghost small" data-pl-toggle="${p.name}" data-pl-enable="${!p.enabled}">${p.enabled ? "Desativar" : "Ativar"}</button>
        <button class="ghost small" data-pl-remove="${p.name}">Remover</button>
      </div></div>`).join("") : `<div class="muted small">Nenhum plugin externo instalado.</div>`;

    $("#pl-available").innerHTML = s.available.map((p) => `
      <div class="list-item"><div class="row"><b>${escapeHtml(p.name)}</b>
      <span class="small">v${p.version} · risco ${p.risk} · ${p.builtin ? "nativo" : "externo"}</span></div>
      <div class="small">${escapeHtml(p.description)}</div>
      <div class="small muted">Permissões: ${escapeHtml((p.permissions || []).join(", ") || "nenhuma")}</div>
      ${p.installed ? "" : `<button class="ghost small" data-pl-install="${p.name}">Instalar</button>`}
      </div>`).join("");

    const un = $("#pl-unavailable");
    if (s.unavailable && s.unavailable.length) {
      un.classList.remove("hidden");
      $("#pl-unavailable-list").innerHTML = s.unavailable.map((u) =>
        `<div class="list-item"><b>${escapeHtml(u.name)}</b> — ${escapeHtml(u.reason)}</div>`).join("");
    } else { un.classList.add("hidden"); }
  } catch (err) { toast(err.message, true); }
}

async function pluginInstall(name, ack) {
  try {
    await api("/api/ai/plugins/install", { method: "POST", body: JSON.stringify({ name, acknowledge_risk: !!ack }) });
    toast("Plugin instalado"); loadPlugins();
  } catch (err) {
    if (String(err.message).includes("risco")) {
      if (confirm("Este plugin pede permissões de alto risco. Instalar mesmo assim?")) return pluginInstall(name, true);
      return;
    }
    toast(err.message, true);
  }
}

async function pluginToggle(name, enable) {
  try { await api(`/api/ai/plugins/${encodeURIComponent(name)}`, { method: "PUT", body: JSON.stringify({ enabled: enable }) }); loadPlugins(); }
  catch (err) { toast(err.message, true); }
}

async function pluginRemove(name) {
  if (!confirm(`Remover o plugin '${name}'?`)) return;
  try { await api(`/api/ai/plugins/${encodeURIComponent(name)}`, { method: "DELETE" }); loadPlugins(); }
  catch (err) { toast(err.message, true); }
}

/* ---------------- Intelligence ---------------- */
async function loadIntelligence() {
  try {
    const d = await api("/api/ai/intelligence");
    const card = (label, value) => `<div class="card"><h3>${label}</h3><div class="big">${value}</div></div>`;
    $("#in-summary").innerHTML =
      card("Taxa de sucesso", d.success_rate == null ? "—" : d.success_rate + "%") +
      card("Experiências", d.counts.total) +
      card("Memórias", d.memories.total) +
      card("Tarefas ativas", d.tasks.enabled);
    const li = (items, fmt) => items.length ? items.map(fmt).join("") : `<div class="muted small">Sem dados.</div>`;
    $("#in-tools").innerHTML = li(d.tools_used, ([n, c]) => `<div class="list-item">${escapeHtml(n)} — ${c}×</div>`);
    $("#in-problems").innerHTML = li(d.recurring_problems, (x) => `<div class="list-item">${escapeHtml(x.action)} — ${x.count}×</div>`);
    $("#in-solutions").innerHTML = li(d.working_solutions, (x) => `<div class="list-item">${escapeHtml(x.action)} — ${x.count}×</div>`);
    $("#in-prefs").innerHTML = li(d.preferences, (m) => `<div class="list-item">${escapeHtml(m.content)}</div>`);
    $("#in-experiences").innerHTML = li(d.experiences, (e) =>
      `<div class="list-item"><span class="badge">${e.success ? "ok" : "falha"}</span> ${escapeHtml(e.action)}</div>`);
  } catch (err) { toast(err.message, true); }
}

/* ---------------- Privacy ---------------- */
async function loadPrivacyVoice() {
  try {
    const h = await api("/api/ai/voice/history");
    $("#pv-voice-list").innerHTML = h.length ? h.map((v) =>
      `<div class="list-item">[${escapeHtml(v.kind)}] ${escapeHtml(v.transcript)}</div>`).join("")
      : `<div class="muted small">Histórico vazio (ou desativado).</div>`;
  } catch (_) {}
}

/* ---------------- Admin ---------------- */
async function loadAdmin() {
  try {
    const d = await api("/api/ai/admin/overview");
    const diag = d.diagnostics;
    $("#ad-summary").innerHTML = `<div class="card"><h3>Saúde</h3><div class="big">${diag.summary.ok}/${diag.summary.total}</div>
      <div class="small">${diag.summary.degraded} degradado(s), ${diag.summary.error} erro(s)</div></div>`;
    $("#ad-diagnostics").innerHTML = diag.checks.map((c) =>
      `<div class="list-item"><span class="badge">${c.status}</span> <b>${escapeHtml(c.name)}</b> — ${escapeHtml(c.detail || "")}</div>`).join("");
    $("#ad-providers").innerHTML = Object.entries(d.providers).length ? Object.entries(d.providers).map(([n, s]) =>
      `<div class="list-item">${escapeHtml(n)}: ${s.ok} ok / ${s.fail} falha(s)</div>`).join("") : `<div class="muted small">Sem dados.</div>`;
    $("#ad-jobs").innerHTML = d.jobs.length ? d.jobs.map((j) =>
      `<div class="list-item"><b>${escapeHtml(j.kind)}</b> ${escapeHtml(j.status)} ${j.progress}%</div>`).join("") : `<div class="muted small">Sem jobs.</div>`;
    $("#ad-security").innerHTML = d.security_events.length ? d.security_events.map((e) =>
      `<div class="list-item">${escapeHtml(e.kind)}: ${escapeHtml((e.detail || "").slice(0, 120))}</div>`).join("") : `<div class="muted small">Sem eventos.</div>`;
  } catch (err) { toast(err.message, true); }
}

/* ---------------- Personality ---------------- */
async function loadPersonality() {
  try {
    const p = await api("/api/ai/personality");
    state.personality = p;
    $("#p-style").innerHTML = p.styles.map((s) => `<option value="${s}" ${s === p.style ? "selected" : ""}>${s}</option>`).join("");
    $("#p-adaptive").checked = !!p.adaptive;
    $("#p-traits").innerHTML = p.available_traits.map((t) => `
      <div class="trait"><label>${t}</label>
      <input type="range" min="0" max="100" value="${p.traits[t] || 50}" data-trait="${t}" />
      <span data-trait-val="${t}">${p.traits[t] || 50}</span></div>`).join("");
    $("#p-traits").querySelectorAll("input[type=range]").forEach((inp) => {
      inp.oninput = () => { $(`[data-trait-val="${inp.dataset.trait}"]`).textContent = inp.value; };
    });
    $("#p-guidance").textContent = p.guidance;
  } catch (err) { /* non-critical */ }
}

async function savePersonality() {
  const traits = {};
  $("#p-traits").querySelectorAll("input[type=range]").forEach((inp) => { traits[inp.dataset.trait] = parseInt(inp.value, 10); });
  try {
    await api("/api/ai/personality", { method: "PUT", body: JSON.stringify({
      traits, style: $("#p-style").value, adaptive: $("#p-adaptive").checked,
    }) });
    toast("Personalidade salva");
    loadPersonality();
  } catch (err) { toast(err.message, true); }
}

/* ---------------- Navigation ---------------- */
const VIEWS = ["pc", "assistant", "control-center", "connect", "trading", "chat", "codex", "images", "video", "plugins", "games", "performance", "projects", "memory", "intelligence", "tools", "files", "tasks", "activity", "privacy", "admin", "settings"];

const TASK_STATE_CLASSES = {
  observing: "st-observing", understanding: "st-understanding", waiting_user: "st-waiting_user",
  executing: "st-executing", waiting_confirmation: "st-waiting_confirmation",
  done: "st-done", error: "st-error", cancelled: "st-cancelled",
};

function setTaskState(st, label, detail) {
  const badge = $("#task-state-badge");
  const det = $("#task-detail");
  if (!badge) return;
  badge.textContent = label || (st || "").toUpperCase();
  badge.className = "badge " + (TASK_STATE_CLASSES[st] || "");
  if (det) det.textContent = detail || "";
  state.lastTaskState = st;
  state.lastTaskLabel = label;
}

async function taskAction(action) {
  if (!state.conversationId) return;
  try {
    await api(`/api/assistant/tasks/${state.conversationId}/action`, { method: "POST", body: JSON.stringify({ action }) });
    toast(action === "cancel" ? "Parado" : action === "pause" ? "Pausado" : "Retomado");
    if (action === "cancel") setTaskState("cancelled", "CANCELADO");
    if (action === "pause") setTaskState("waiting_user", "AGUARDANDO USUÁRIO", "Pausado");
  } catch (err) { toast(err.message, true); }
}

/* ---------------- Accessibility ---------------- */
function applyAccessibility(prefs) {
  const b = document.body;
  b.classList.toggle("a11y-large-text", !!prefs.large_text);
  b.classList.toggle("a11y-big-buttons", !!prefs.big_buttons);
  b.classList.toggle("a11y-high-contrast", !!prefs.high_contrast);
  state.a11y = prefs;
}

async function loadAccessibility() {
  try {
    const d = await api("/api/assistant/accessibility");
    const p = d.preferences || {};
    applyAccessibility(p);
    const map = { "a-large-text": "large_text", "a-big-buttons": "big_buttons", "a-high-contrast": "high_contrast", "a-read-aloud": "read_aloud", "a-calm-voice": "calm_voice", "a-simple-language": "simple_language" };
    Object.entries(map).forEach(([id, key]) => { const el = $("#" + id); if (el) el.checked = !!p[key]; });
  } catch (_) {}
}

async function saveAccessibility() {
  const map = { large_text: "a-large-text", big_buttons: "a-big-buttons", high_contrast: "a-high-contrast", read_aloud: "a-read-aloud", calm_voice: "a-calm-voice", simple_language: "a-simple-language" };
  const body = {};
  Object.entries(map).forEach(([key, id]) => { const el = $("#" + id); if (el) body[key] = el.checked; });
  try {
    const d = await api("/api/assistant/accessibility", { method: "PUT", body: JSON.stringify(body) });
    applyAccessibility(d.preferences || {});
    toast("Acessibilidade salva");
  } catch (err) { toast(err.message, true); }
}

/* ---------------- Assistant ---------------- */
async function loadAssistant() {
  try {
    const [levels, profiles] = await Promise.all([
      api("/api/assistant/autonomy"), api("/api/assistant/profiles"),
    ]);
    const lv = $("#as-levels");
    if (lv) {
      lv.innerHTML = levels.levels.map((l) => `<div class="list-item as-level ${l.key === levels.current ? "active" : ""}" data-as-level="${l.key}"><b>Nível ${l.level} · ${escapeHtml(l.label)}</b><div class="small muted">${escapeHtml(l.description)}</div></div>`).join("");
    }
    const pf = $("#as-profiles");
    if (pf) {
      pf.innerHTML = profiles.profiles.map((p) => `<div class="list-item as-level ${p.key === profiles.current ? "active" : ""}" data-as-profile="${p.key}"><b>${escapeHtml(p.label)}</b><div class="small muted">${escapeHtml(p.description)}</div></div>`).join("");
    }
    const lb = $("#as-level-badge"); if (lb) lb.textContent = `nível: ${levels.current}`;
    const pb = $("#as-profile-badge"); if (pb) pb.textContent = `perfil: ${profiles.current}`;
    const desc = $("#as-level-desc");
    const cur = levels.levels.find((l) => l.key === levels.current);
    if (desc && cur) desc.textContent = cur.description;
    const sug = $("#as-suggest");
    if (sug) sug.innerHTML = ["Quero entrar no meu e-mail", "Não sei onde clicar", "Pode abrir o navegador?", "O que apareceu nessa tela?", "Não estou conseguindo", "Pode fazer para mim?"].map((s) => `<button class="ghost small" data-as-example="${escapeHtml(s)}">${escapeHtml(s)}</button>`).join(" ");
  } catch (err) { /* the assistant page still works without the metadata */ }
}

async function setAutonomyLevel(level) {
  try {
    await api("/api/assistant/autonomy", { method: "PUT", body: JSON.stringify({ level }) });
    toast("Nível atualizado");
    loadAssistant();
  } catch (err) { toast(err.message, true); }
}

async function setProfile(profile) {
  try {
    await api("/api/assistant/profile", { method: "PUT", body: JSON.stringify({ profile }) });
    toast("Perfil atualizado");
    loadAssistant();
    loadAccessibility();
  } catch (err) { toast(err.message, true); }
}

async function analyzeScreen() {
  const out = $("#as-screen-out");
  if (out) out.textContent = "Analisando a tela…";
  try {
    const d = await api("/api/assistant/screen/analyze", { method: "POST", body: JSON.stringify({}) });
    const lines = [`Tela ${d.width}x${d.height}`, d.summary || ""];
    (d.elements || []).slice(0, 40).forEach((e) => lines.push(`${e.kind} '${e.text}' em (${e.box.cx}, ${e.box.cy})`));
    if (out) out.textContent = lines.join("\n");
  } catch (err) { if (out) out.textContent = err.message; }
}

async function findElement() {
  const q = ($("#as-find-q")?.value || "").trim();
  if (!q) return toast("Descreva o elemento", true);
  const out = $("#as-screen-out");
  try {
    const d = await api("/api/assistant/screen/find", { method: "POST", body: JSON.stringify({ command: "screen_find", args: { query: q } }) });
    const lines = (d.matches || []).map((m) => `${m.kind} '${m.text}' em (${m.box.cx}, ${m.box.cy})`);
    if (out) out.textContent = lines.length ? lines.join("\n") : "Nenhum elemento correspondente encontrado.";
  } catch (err) { if (out) out.textContent = err.message; }
}

async function highlightElement() {
  const q = ($("#as-find-q")?.value || "").trim();
  if (!q) return toast("Descreva o elemento", true);
  const out = $("#as-highlight-out");
  try {
    const d = await api("/api/assistant/screen/highlight", { method: "POST", body: JSON.stringify({ command: "screen_highlight", args: { query: q } }) });
    if (!d.highlight) { if (out) { out.classList.remove("hidden"); out.textContent = d.note || "Não encontrei esse elemento."; } return; }
    if (out) {
      out.classList.remove("hidden");
      const b = d.highlight.box;
      out.textContent = `➡️ Procure na tela: "${d.highlight.text}" — posição aproximada (${b.cx}, ${b.cy}).`;
    }
  } catch (err) { if (out) { out.classList.remove("hidden"); out.textContent = err.message; } }
}

async function scamCheck() {
  const text = $("#as-scam-text")?.value || "";
  const url = $("#as-scam-url")?.value || "";
  const out = $("#as-scam-out");
  try {
    const d = await api("/api/assistant/scam-check", { method: "POST", body: JSON.stringify({ text, url }) });
    const cls = d.risk === "high" ? "risk-high" : d.risk === "medium" ? "risk-medium" : "risk-low";
    let html = `<div class="${cls}">${escapeHtml(d.message)}</div>`;
    (d.findings || []).forEach((f) => { html += `<div class="list-item">• ${escapeHtml(f.label)}: ${escapeHtml(f.explanation || "")} <span class="muted">("${escapeHtml(f.evidence || "")}")</span></div>`; });
    if (out) out.innerHTML = html;
    if (d.risk === "high" && state.a11y && state.a11y.read_aloud) speakText(d.message);
  } catch (err) { toast(err.message, true); }
}

async function loadControlCenter() {
  try {
    const d = await api("/api/assistant/control-center");
    const health = $("#cc-health");
    if (health) {
      const h = d.health;
      health.innerHTML = `<div class="card"><h3>Saúde</h3><div class="big">${h.summary.ok} ok · ${h.summary.degraded} degradado · ${h.summary.error} erro</div></div>`;
    }
    const dev = $("#cc-devices");
    if (dev) {
      dev.innerHTML = (d.devices || []).map((x) => `<div class="list-item"><b>${escapeHtml(x.name)}</b> ${x.online ? "🟢 online" : "🔴 offline"}<div class="small muted">${escapeHtml(x.platform || "")} · última conexão ${x.last_seen ? new Date(x.last_seen * 1000).toLocaleString() : "—"}</div></div>`).join("") || "<div class='muted'>Nenhum dispositivo.</div>";
    }
    const tasks = $("#cc-tasks");
    if (tasks) {
      const live = (d.tasks.live || []).map((t) => `<div class="list-item">${escapeHtml(t.label)} — ${escapeHtml(t.detail || "")}</div>`).join("");
      const jobs = (d.tasks.jobs || []).map((j) => `<div class="list-item">${escapeHtml(j.kind)} · ${j.status} ${j.progress}%${j.error ? " · " + escapeHtml(j.error) : ""}</div>`).join("");
      tasks.innerHTML = (live || jobs) ? live + jobs : "<div class='muted'>Sem tarefas ativas.</div>";
    }
    const sec = $("#cc-security");
    if (sec) {
      sec.innerHTML = (d.security.events || []).slice().reverse().map((e) => `<div>[${new Date(e.created_at * 1000).toLocaleTimeString()}] ${escapeHtml(e.kind)}: ${escapeHtml(e.detail)}</div>`).join("") || "<div class='muted'>Sem eventos.</div>";
    }
  } catch (err) { toast(err.message, true); }
}



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
  if (view === "settings") { loadSettings(); loadPersonality(); loadVoiceSettings(); }
  if (view === "projects") loadProjects();
  if (view === "pc") refreshDashboard();
  if (view === "connect") loadAgents();
  if (view === "trading") loadTrading();
  if (view === "games") scanGames();
  if (view === "performance") loadOptimizations();
  if (view === "codex") loadCodexChanges();
  if (view === "images") loadMediaProviders();
  if (view === "video") loadVideoProviders();
  if (view === "plugins") loadPlugins();
  if (view === "intelligence") loadIntelligence();
  if (view === "privacy") loadPrivacyVoice();
  if (view === "admin") loadAdmin();
  if (view === "assistant") loadAssistant();
  if (view === "control-center") loadControlCenter();
  startDashTimer(view === "pc");
}

function startDashTimer(on) {
  if (state.dashTimer) { clearInterval(state.dashTimer); state.dashTimer = null; }
  if (on) state.dashTimer = setInterval(refreshDashboard, 2000);
}

/* ---------------- Wiring ---------------- */
async function loadAccountChip() {
  try {
    const d = await api("/api/account/me");
    if (!d || !d.authenticated) return;
    const u = d.user;
    const chip = $("#user-chip");
    if (!chip) return;
    chip.classList.remove("hidden");
    $("#uc-name").textContent = u.name || u.email.split("@")[0];
    $("#uc-mail").textContent = u.email;
    $("#uc-avatar").textContent = (u.name || u.email).trim().charAt(0).toUpperCase() || "?";
  } catch (_) { /* operator-only mode: no account chip */ }
}

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
    try { await api("/api/account/logout", { method: "POST" }); } catch (_) {}
    try { await api("/api/logout", { method: "POST" }); } catch (_) {}
    window.location.href = "/login";
  };
  loadAccountChip();
  $("#pc-refresh").onclick = refreshDashboard;
  $("#pair-generate").onclick = generatePairCode;
  $("#game-analyze").onclick = analyzeGame;
  $("#games-scan").onclick = scanGames;
  wireTrading();

  // Phase 4 wiring.
  $("#voice-toggle").onclick = () => {
    if (voice.rec) stopRecognition();
    else startRecognition($("#voice-continuous").checked || ($("#v-continuous")?.checked));
  };
  $("#voice-listen").onclick = () => speakText(state.lastAssistantText);
  $("#voice-stop").onclick = () => { stopRecognition(); stopAudio(); voiceStatus("Parado."); };
  $("#voice-pause").onclick = () => {
    if (voice.audio) { if (voice.audio.paused) { voice.audio.play(); voiceStatus("🔊 Retomado"); } else { voice.audio.pause(); voiceStatus("⏸ Pausado"); } }
    else if ("speechSynthesis" in window && window.speechSynthesis.speaking) { window.speechSynthesis.pause(); voiceStatus("⏸ Pausado"); }
  };
  $("#voice-repeat").onclick = () => speakText(state.lastAssistantText);
  $("#voice-continuous").onchange = (e) => {
    if (voice.rec) { stopRecognition(); startRecognition(e.target.checked); }
    api("/api/ai/voice/config", { method: "PUT", body: JSON.stringify({ voice_continuous: e.target.checked }) }).catch(() => {});
  };
  $("#voice-wake").onchange = (e) => {
    voice.wake = e.target.checked;
    api("/api/ai/voice/config", { method: "PUT", body: JSON.stringify({ voice_wake_word: e.target.checked }) }).catch(() => {});
    voiceStatus(e.target.checked ? "Wake word ativo — o microfone ficará ativo quando você falar." : "Wake word desativado.");
  };

  $("#cx-plan").onclick = async () => {
    const objective = $("#cx-objective").value.trim();
    if (!objective) return toast("Informe o objetivo", true);
    try {
      const plan = await api("/api/ai/codex/plan", { method: "POST", body: JSON.stringify({ objective }) });
      $("#cx-plan-out").classList.remove("hidden");
      $("#cx-plan-list").innerHTML = plan.steps.map((s, i) => `<div class="list-item">${i + 1}. ${escapeHtml(s)}</div>`).join("");
    } catch (err) { toast(err.message, true); }
  };
  $("#cx-analyze").onclick = async () => {
    try {
      const a = await api("/api/ai/codex/analyze", { method: "POST", body: JSON.stringify({ path: "." }) });
      $("#cx-analyze-out").classList.remove("hidden");
      $("#cx-analyze-body").innerHTML = `<div>Arquivos: ${a.file_count} · linhas: ${a.total_lines}</div>
        <div>Linguagens: ${escapeHtml(JSON.stringify(a.languages))}</div>
        <div>Testes: ${a.test_files.length}</div>
        <div>Observações: ${escapeHtml((a.findings || []).join("; "))}</div>`;
    } catch (err) { toast(err.message, true); }
  };
  $("#cx-test").onclick = async () => {
    toast("Rodando testes…");
    try {
      const t = await api("/api/ai/codex/test", { method: "POST", body: JSON.stringify({ path: "." }) });
      $("#cx-test-out").classList.remove("hidden");
      const s = t.tests ? `${t.tests.passed} passou, ${t.tests.failed} falhou, ${t.tests.errors} erro(s)` : "sem resumo";
      $("#cx-test-body").innerHTML = `<div>${s}</div><pre>${escapeHtml((t.stdout || "").slice(-2000))}</pre>`;
    } catch (err) { toast(err.message, true); }
  };
  $("#cx-sandbox-run").onclick = async () => {
    const code = $("#cx-sandbox-code").value;
    if (!code.trim()) return toast("Escreva o código", true);
    try {
      const r = await api("/api/ai/codex/sandbox", { method: "POST", body: JSON.stringify({ code }) });
      $("#cx-sandbox-out").textContent = `exit=${r.exit_code} timed_out=${r.timed_out}\n${r.stdout}\n${r.stderr}`;
    } catch (err) { $("#cx-sandbox-out").textContent = err.message; }
  };
  $("#cx-run").onclick = () => {
    const objective = $("#cx-objective").value.trim();
    if (!objective) return toast("Informe o objetivo", true);
    switchView("chat");
    sendMessage(objective);
  };
  $("#cx-changes").addEventListener("click", (e) => {
    const a = e.target.closest("[data-cx-apply]"); if (a) return codexAction(a.dataset.cxApply, "apply");
    const r = e.target.closest("[data-cx-reject]"); if (r) return codexAction(r.dataset.cxReject, "reject");
    const v = e.target.closest("[data-cx-revert]"); if (v) return codexAction(v.dataset.cxRevert, "revert");
  });

  $("#im-generate").onclick = generateImage;
  $("#vd-render").onclick = renderVideo;
  setInterval(() => { if ($("#view-video")?.classList.contains("active")) pollJobs(); }, 3000);

  $("#pl-installed").addEventListener("click", (e) => {
    const t = e.target.closest("[data-pl-toggle]");
    if (t) return pluginToggle(t.dataset.plToggle, t.dataset.plEnable === "true");
    const r = e.target.closest("[data-pl-remove]");
    if (r) return pluginRemove(r.dataset.plRemove);
  });
  $("#pl-available").addEventListener("click", (e) => {
    const i = e.target.closest("[data-pl-install]");
    if (i) return pluginInstall(i.dataset.plInstall);
  });

  $("#p-save").onclick = savePersonality;
  $("#v-save").onclick = saveVoiceSettings;
  $("#a-save").onclick = saveAccessibility;
  $("#task-cancel").onclick = () => taskAction("cancel");
  $("#task-pause").onclick = () => taskAction(state.lastTaskState === "waiting_user" ? "resume" : "pause");
  $("#as-go").onclick = () => {
    const t = ($("#as-request").value || "").trim();
    if (!t) return toast("Escreva o que você precisa", true);
    switchView("chat");
    sendMessage(t);
  };
  $("#as-request").onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); $("#as-go").click(); } };
  $("#as-speak").onclick = () => startRecognition(false);
  $("#as-screen-analyze").onclick = analyzeScreen;
  $("#as-find").onclick = findElement;
  $("#as-highlight").onclick = highlightElement;
  $("#as-scam-check").onclick = scamCheck;
  $("#cc-refresh").onclick = loadControlCenter;
  document.addEventListener("click", (e) => {
    const lv = e.target.closest("[data-as-level]");
    if (lv) return setAutonomyLevel(lv.dataset.asLevel);
    const pf = e.target.closest("[data-as-profile]");
    if (pf) return setProfile(pf.dataset.asProfile);
    const ex = e.target.closest("[data-as-example]");
    if (ex) { $("#as-request").value = ex.dataset.asExample; $("#as-go").click(); }
  });
  $("#pv-voice-load").onclick = loadPrivacyVoice;
  $("#pv-voice-clear").onclick = async () => { await api("/api/ai/voice/history", { method: "DELETE" }); loadPrivacyVoice(); toast("Histórico apagado"); };
  $("#pv-mem-clear").onclick = async () => { if (confirm("Apagar toda a memória de longo prazo?")) { await api("/api/ai/privacy/memory", { method: "DELETE" }); toast("Memória apagada"); } };
  $("#pv-exp-clear").onclick = async () => { if (confirm("Apagar todas as experiências?")) { await api("/api/ai/privacy/experiences", { method: "DELETE" }); toast("Experiências apagadas"); } };
  $("#pv-backup").onclick = async () => {
    const out = $("#pv-backup-out");
    try {
      const d = await api("/api/assistant/maintenance/backup", { method: "POST", body: JSON.stringify({}) });
      if (out) out.textContent = `Backup criado: ${d.path} (${d.bytes} bytes, integridade: ${d.integrity})`;
      toast("Backup criado");
    } catch (err) { if (out) out.textContent = err.message; toast(err.message, true); }
  };
  $("#pv-backup-list").onclick = async () => {
    const out = $("#pv-backup-out");
    try {
      const list = await api("/api/assistant/maintenance/backups");
      if (out) out.textContent = list.length ? list.map((b) => `${b.name} — ${b.bytes} bytes — ${new Date(b.created_at * 1000).toLocaleString()}`).join("\n") : "Nenhum backup ainda.";
    } catch (err) { if (out) out.textContent = err.message; }
  };
  $("#pv-update-check").onclick = async () => {
    const out = $("#pv-update-out");
    try {
      const d = await api("/api/assistant/update/check", { method: "POST", body: JSON.stringify({ manifest_url: $("#pv-update-url").value || null }) });
      if (out) {
        if (d.error) out.textContent = d.error;
        else if (d.available) out.innerHTML = `<div class="list-item"><b>Nova versão: ${escapeHtml(d.latest)}</b> (atual ${escapeHtml(d.current)})<div class="small muted">${escapeHtml(d.notes || "")}</div></div>`;
        else out.textContent = `Você está atualizado (${d.current}). ${d.notes || ""}`;
      }
    } catch (err) { if (out) out.textContent = err.message; }
  };
  $("#pv-export").onclick = async () => {
    try { const d = await api("/api/ai/privacy/export"); $("#pv-export-out").textContent = JSON.stringify(d, null, 2).slice(0, 8000); }
    catch (err) { toast(err.message, true); }
  };

  loadModes();
  refreshHealth();
  setInterval(refreshHealth, 15000);
  loadSettings();
  loadAccessibility();
  loadProjects();
  loadConversations().then(() => { if (!state.conversationId) newConversation(); });
  loadAgents();

  const fromPath = (location.pathname.replace(/^\//, "") || "chat").split("/")[0];
  const initial = (location.hash || `#${fromPath}`).slice(1);
  switchView(VIEWS.includes(initial) ? initial : "chat");
}

document.addEventListener("DOMContentLoaded", init);
