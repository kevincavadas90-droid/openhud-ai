/* OpenHUD front-end. No build step: plain ES module-free JS. */
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const state = {
  conversationId: null,
  projectId: "",
  settings: {},
  streaming: false,
  lastProvider: null,
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
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  const ct = res.headers.get("content-type") || "";
  return ct.includes("application/json") ? res.json() : res.text();
}

function toast(message, isError = false) {
  const el = $("#toast");
  el.textContent = message;
  el.className = "toast" + (isError ? " err" : "");
  setTimeout(() => el.classList.add("hidden"), 3200);
}

/* ---------------- Rendering helpers ---------------- */
function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
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

  const res = await fetch(`/api/conversations/${state.conversationId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (res.status === 401) { window.location.href = "/login"; return; }
  if (!res.ok || !res.body) {
    state.streaming = false;
    $("#send").disabled = false;
    const detail = await res.json().catch(() => ({}));
    toast(detail.detail || "Falha ao enviar mensagem", true);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let assistantEl = null;

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
      addMessage("assistant", "⚠️ Erro: " + (payload.message || "desconhecido"));
    }
  };

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
    await api(`/api/confirmations/${payload.request_id}`, {
      method: "POST",
      body: JSON.stringify({ approved }),
    });
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
    card.querySelector("input").onchange = async (e) => {
      const checked = [...$$("#tools-list input[data-tool]")].filter((i) => i.checked).map((i) => i.dataset.tool);
      await api("/api/settings", { method: "PUT", body: JSON.stringify({ enabled_tools: checked }) });
      state.settings.enabled_tools = checked;
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
    el.onclick = () => {
      if (f.is_dir) loadFiles(f.path);
      else openFile(f.path);
    };
    list.appendChild(el);
  });
}

async function openFile(path) {
  try {
    const data = await api(`/api/files/content?path=${encodeURIComponent(path)}`);
    $("#file-path").value = data.path;
    $("#file-content").value = data.content;
  } catch (e) {
    toast(e.message, true);
  }
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

/* ---------------- Provider badge ---------------- */
function updateProviderBadge() {
  const el = $("#model-badge");
  if (state.lastProvider) {
    el.textContent = `respondendo via ${state.lastProvider}`;
  }
}

/* ---------------- Health ---------------- */
async function refreshHealth() {
  try {
    const h = await api("/api/health");
    const el = $("#status");
    if (h.configured) {
      el.textContent = `● ${h.provider} / ${h.model}`;
      el.className = "status ok";
    } else {
      el.textContent = `● configure a chave de API (${h.provider})`;
      el.className = "status err";
    }
  } catch (_) {
    $("#status").textContent = "● API offline";
    $("#status").className = "status err";
  }
}

/* ---------------- Projects ---------------- */
async function loadProjects() {
  const projects = await api("/api/projects");
  const sel = $("#project-select");
  sel.innerHTML = `<option value="">Sem projeto</option>` +
    projects.map((p) => `<option value="${p.id}">${escapeHtml(p.name)}</option>`).join("");
  sel.value = state.projectId;
}

/* ---------------- Navigation ---------------- */
function switchView(view) {
  $$(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${view}`));
  if (view === "tools") loadTools();
  if (view === "files") loadFiles(".");
  if (view === "memory") loadMemories();
  if (view === "tasks") loadTasks();
  if (view === "activity") refreshActivity();
  if (view === "settings") loadSettings();
}

/* ---------------- Wiring ---------------- */
function init() {
  $$(".nav-btn").forEach((b) => (b.onclick = () => switchView(b.dataset.view)));
  $("#new-conv").onclick = newConversation;
  $("#composer").onsubmit = (e) => {
    e.preventDefault();
    const text = $("#input").value.trim();
    if (text && !state.streaming) sendMessage(text);
  };
  $("#input").onkeydown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      $("#composer").requestSubmit();
    }
  };
  $("#toggle-autonomy").onclick = async () => {
    const next = state.settings.autonomy === "autonomous" ? "supervised" : "autonomous";
    const s = await api("/api/settings", { method: "PUT", body: JSON.stringify({ autonomy: next }) });
    state.settings = s;
    $("#autonomy-badge").textContent = next === "autonomous" ? "autônomo" : "supervisionado";
    $("#autonomy-badge").className = "badge" + (next === "autonomous" ? " autonomous" : "");
  };
  $("#add-project").onclick = async () => {
    const name = $("#project-name").value.trim();
    if (!name) return;
    await api("/api/projects", { method: "POST", body: JSON.stringify({ name }) });
    $("#project-name").value = "";
    loadProjects();
  };
  $("#project-select").onchange = (e) => {
    state.projectId = e.target.value;
    state.conversationId = null;
    loadConversations();
  };
  $("#file-save").onclick = saveFile;
  $("#file-load").onclick = () => openFile($("#file-path").value.trim());
  $("#memory-form").onsubmit = async (e) => {
    e.preventDefault();
    const content = $("#memory-content").value.trim();
    if (!content) return;
    await api("/api/memories", { method: "POST", body: JSON.stringify({ content, tags: $("#memory-tags").value }) });
    $("#memory-content").value = "";
    $("#memory-tags").value = "";
    loadMemories();
  };
  $("#task-form").onsubmit = async (e) => {
    e.preventDefault();
    const name = $("#task-name").value.trim();
    const prompt = $("#task-prompt").value.trim();
    const interval_seconds = parseInt($("#task-interval").value, 10) || 3600;
    if (!name || !prompt) return toast("Informe nome e tarefa", true);
    try {
      await api("/api/tasks", { method: "POST", body: JSON.stringify({ name, prompt, interval_seconds }) });
      $("#task-name").value = "";
      $("#task-prompt").value = "";
      loadTasks();
      toast("Tarefa agendada");
    } catch (err) { toast(err.message, true); }
  };
  $("#s-save").onclick = saveSettings;
  $("#secret-save").onclick = saveSecret;
  $("#logout").onclick = async () => {
    await api("/api/logout", { method: "POST" });
    window.location.href = "/login";
  };

  refreshHealth();
  setInterval(refreshHealth, 15000);
  loadSettings();
  loadProjects();
  loadConversations().then(() => {
    if (!state.conversationId) newConversation();
  });
}

document.addEventListener("DOMContentLoaded", init);
