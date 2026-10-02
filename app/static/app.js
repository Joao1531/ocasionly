const $ = (s) => document.querySelector(s);
const api = async (url, opts) => {
  const r = await fetch(url, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch {}
    // 404/405 genéricos numa rota /api/ = o servidor em execução é anterior a esta versão do ecrã
    if ((r.status === 404 || r.status === 405) && String(url).startsWith("/api/") && ["Not Found", "Method Not Allowed"].includes(msg)) {
      msg = "O servidor está desatualizado. Pára-o no terminal (Ctrl+C) e arranca-o outra vez com: uv run uvicorn app.main:app --port 8000 --reload";
    }
    throw new Error(msg);
  }
  return r.json();
};
const json = (method, body) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let items = [], people = [], status = { categories: [], max_items: 8 };
let selectedPerson = null;
const selectedItems = new Set();
let editing = null;
let bulkCategory = null;

// ---------- Tabs ----------
const TABS = ["closet", "advise", "tryon", "wish", "memory", "settings"];
function showTab(name) {
  document.querySelectorAll("nav button").forEach((x) => x.classList.toggle("active", x.dataset.tab === name));
  TABS.forEach((t) => $(`#tab-${t}`).classList.toggle("hidden", t !== name));
  if (name === "tryon") renderTryon();
  if (name === "wish") loadWish();
  if (name === "memory") loadMemory();
  if (name === "settings") loadSettings();
}
document.querySelectorAll("nav button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
$("#settings-btn").addEventListener("click", () => showTab("settings"));

// ---------- Armário por categorias ----------
let closetView = localStorage.getItem("closetView") || "mini";
let closetCat = localStorage.getItem("closetCat") || "";  // "" = todas as categorias
let justAdded = new Set();  // peças acabadas de adicionar: entram com animação

const miniHtml = (it, extra = "") => `
  <div class="mini ${extra}" data-id="${it.id}" title="${esc(it.name)}">
    <img src="${it.thumb_url}" loading="lazy" alt="">
    <span>${esc(it.name)}</span>
  </div>`;

const cardHtml = (it, extra = "") => `
  <div class="card ${extra}" data-id="${it.id}">
    <img src="${it.image_url}" loading="lazy" alt="">
    <div class="meta"><b>${esc(it.name)}</b>${esc([it.brand, it.model, it.size && "tam. " + it.size].filter(Boolean).join(" · "))}</div>
  </div>`;

// Desenha todas as categorias com as suas peças. `withAdd` mostra o botão de adicionar fotos.
function groupsHtml({ withAdd = false, selected = null, mini = false, only = "" } = {}) {
  const known = new Set(status.categories.map((c) => c.id));
  const groups = status.categories.map((c) => ({ ...c, list: items.filter((i) => i.category === c.id) }));
  const loose = items.filter((i) => !known.has(i.category));
  if (loose.length) groups.push({ id: "", label: "Sem categoria", list: loose });
  return groups.filter((g) => !only || g.id === only).map((g) => `
    <div class="group">
      <div class="group-head">
        <h2>${esc(g.label)} <span class="muted">${g.list.length}</span></h2>
        ${withAdd && g.id ? `<button data-add="${g.id}">+ Adicionar fotos</button>` : ""}
      </div>
      ${mini
        ? `<div class="shelf">${g.list.map((i) => miniHtml(i, (selected?.has(i.id) ? "selected " : "") + (justAdded.has(i.id) ? "pop" : ""))).join("")}${withAdd && g.id ? `<button class="mini add" data-add="${g.id}" title="Adicionar fotos"><b>+</b></button>` : ""}</div>${g.list.length || withAdd ? "" : '<p class="muted empty">Ainda sem peças.</p>'}`
        : g.list.length ? `<div class="grid">${g.list.map((i) => cardHtml(i, selected?.has(i.id) ? "selected" : "")).join("")}</div>` : '<p class="muted empty">Ainda sem peças.</p>'}
    </div>`).join("");
}

// Abas por categoria: "Todas" mostra tudo; cada aba mostra só essa categoria.
function renderCatTabs() {
  const tabs = [{ id: "", label: "Todas", n: items.length }, ...status.categories.map((c) => ({ id: c.id, label: c.label, n: items.filter((i) => i.category === c.id).length }))];
  const box = $("#cat-tabs");
  box.innerHTML = tabs.map((t) => `<button data-cat="${esc(t.id)}" class="${t.id === closetCat ? "on" : ""}">${esc(t.label)} <small>${t.n}</small></button>`).join("");
  box.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    closetCat = b.dataset.cat;
    localStorage.setItem("closetCat", closetCat);
    renderCloset();
  }));
}

async function loadItems() {
  items = await api("/api/items");
  renderCloset();
}

function renderCloset() {
  const root = $("#closet");
  if (closetCat && !status.categories.some((c) => c.id === closetCat)) closetCat = "";
  renderCatTabs();
  root.innerHTML = groupsHtml({ withAdd: true, mini: closetView === "mini", only: closetCat });
  justAdded = new Set();
  document.querySelectorAll("#view-toggle button").forEach((b) => b.classList.toggle("on", b.dataset.view === closetView));
  root.querySelectorAll(".card, .mini:not(.add)").forEach((c) => c.addEventListener("click", () => openItem(items.find((i) => i.id == c.dataset.id))));
  root.querySelectorAll("[data-add]").forEach((b) => b.addEventListener("click", () => {
    bulkCategory = b.dataset.add;
    $("#bulk-file").click();
  }));
}

document.querySelectorAll("#view-toggle button").forEach((b) => b.addEventListener("click", () => {
  closetView = b.dataset.view;
  localStorage.setItem("closetView", closetView);
  renderCloset();
}));

// Adicionar várias fotos de uma vez a uma categoria; o modelo com visão sugere nome/cor/estação.
$("#bulk-file").addEventListener("change", async (e) => {
  const files = [...e.target.files];
  e.target.value = "";
  if (!files.length || !bulkCategory) return;
  const cat = status.categories.find((c) => c.id === bulkCategory);
  const progress = $("#progress");
  let failed = 0;
  for (const [n, f] of files.entries()) {
    progress.textContent = `A guardar ${n + 1}/${files.length}…`;
    let s = {};
    if (status.vision) {
      try {
        const fd = new FormData();
        fd.append("image", f);
        s = await api("/api/items/analyze", { method: "POST", body: fd });
      } catch {}
    }
    try {
      const fd = new FormData();
      fd.append("image", f);
      fd.append("name", s.name || `${cat.singular} ${items.filter((i) => i.category === cat.id).length + 1}`);
      fd.append("category", cat.id);
      for (const k of ["color", "season", "formality"]) fd.append(k, s[k] || "");
      const it = await api("/api/items", { method: "POST", body: fd });
      items.unshift(it);
      justAdded.add(it.id);
      renderCloset();
    } catch {
      failed++;
    }
  }
  progress.textContent = failed ? `${failed} foto(s) falharam.` : "";
  setTimeout(() => { if (!failed) progress.textContent = ""; }, 2000);
});

// ---------- Importar da pasta ----------
let scanResult = null;

$("#import-btn").addEventListener("click", async () => {
  $("#import-preview").innerHTML = "";
  $("#import-progress").textContent = "";
  $("#import-run").disabled = true;
  $("#import-analyze-row").classList.toggle("hidden", !status.vision);
  $("#import-dialog").showModal();
  try {
    const c = await api("/api/import/config");
    $("#import-dir").value = c.dir;
    if (c.exists) $("#import-scan").click();
  } catch (ex) {
    $("#import-preview").innerHTML = `<p class="error">${esc(ex.message)}</p>`;
  }
});
$("#import-close").addEventListener("click", () => $("#import-dialog").close());

$("#import-scan").addEventListener("click", async () => {
  const box = $("#import-preview");
  box.innerHTML = '<p class="muted">A ler a pasta…</p>';
  $("#import-run").disabled = true;
  try {
    scanResult = await api("/api/import/scan", json("POST", { dir: $("#import-dir").value.trim() }));
  } catch (ex) {
    box.innerHTML = `<p class="error">${esc(ex.message)}</p>`;
    return;
  }
  const fresh = scanResult.files.filter((f) => f.status === "new");
  const known = scanResult.files.filter((f) => f.status !== "new");
  const dups = scanResult.duplicates || [];
  const newPeople = scanResult.people.filter((p) => p.status === "new");
  const labelOf = (id) => status.categories.find((c) => c.id === id)?.singular || id;
  box.innerHTML = `
    <div class="import-summary"><b>${fresh.length}</b> peças novas${known.length ? ` · ${known.length} já na app` : ""}${dups.length ? ` · ${dups.length} repetidas na pasta` : ""}${scanResult.skipped.length ? ` · ${scanResult.skipped.length} ignorados` : ""}</div>
    ${fresh.length ? `<div class="itable-wrap"><table class="itable"><thead><tr><th>Ficheiro</th><th>Categoria</th><th>Nome</th><th>Tamanho</th><th>Marca</th><th>Modelo</th><th>Cor</th><th>Corte</th><th>Material</th></tr></thead><tbody>
      ${fresh.map((f) => `<tr><td>${esc(f.rel)}</td><td>${esc(labelOf(f.category))}</td><td>${esc(f.name || "(automático)")}</td><td>${esc(f.size)}</td><td>${esc(f.brand)}</td><td>${esc(f.model)}</td><td>${esc(f.color)}</td><td>${esc(f.fit)}</td><td>${esc(f.material)}</td></tr>`).join("")}
    </tbody></table></div>` : ""}
    ${known.length ? `<p class="muted">Já na app (não serão importadas): ${known.map((f) => `${esc(f.rel)} (${esc(f.reason)})`).join("; ")}</p>` : ""}
    ${dups.length ? `<p class="muted">Não importadas por terem o mesmo nome ou conteúdo que outra: ${dups.map((d) => `${esc(d.rel)} = ${esc(d.of)} (${esc(d.reason)})`).join("; ")}</p>` : ""}
    ${scanResult.skipped.length ? `<p class="muted">Ignorados: ${scanResult.skipped.map((s) => `${esc(s.rel)} (${esc(s.reason)})`).join("; ")}</p>` : ""}
    ${newPeople.length ? `<div class="import-summary"><b>Fotos soltas na pasta</b> <span class="muted">(se forem fotos tuas, importa-as para o Provador)</span>
      ${newPeople.map((p) => `<label class="check"><input type="checkbox" data-person="${esc(p.rel)}"> ${esc(p.rel)}</label>`).join("")}</div>` : ""}
    ${!scanResult.files.length && !scanResult.people.length ? '<p class="muted">Não encontrei imagens. Põe as fotos em subpastas com o nome da categoria.</p>' : ""}`;
  $("#import-run").disabled = !fresh.length && !newPeople.length;
  updateImportEstimate();
});

function updateImportEstimate() {
  const fresh = (scanResult?.files || []).filter((f) => f.status === "new");
  const mode = $("#import-analyze").value;
  const n = mode === "all" ? fresh.length : mode === "missing" ? fresh.filter((f) => !f.color).length : 0;
  $("#import-estimate").textContent = n ? `${n} chamadas ao modelo de visão (fotos reduzidas). O consumo real aparece no fim.` : "Nenhuma chamada ao modelo.";
}
$("#import-analyze").addEventListener("change", updateImportEstimate);

$("#import-run").addEventListener("click", async () => {
  const fresh = scanResult.files.filter((f) => f.status === "new");
  const persons = [...document.querySelectorAll("[data-person]:checked")].map((c) => c.dataset.person);
  const analyze = $("#import-analyze").value;
  const before = await api("/api/settings/usage");
  const dir = scanResult.dir, progress = $("#import-progress"), btn = $("#import-run");
  btn.disabled = true;
  const failed = [];
  let done = 0;
  for (const f of fresh) {
    progress.textContent = `A importar ${done + 1}/${fresh.length}: ${f.rel}`;
    try {
      const r = await api("/api/import/item", json("POST", { dir, rel: f.rel, analyze }));
      if (!r.skipped) { items.unshift(r); justAdded.add(r.id); }
    } catch (ex) {
      failed.push(`${f.rel}: ${ex.message}`);
    }
    done++;
  }
  for (const rel of persons) {
    try { await api("/api/import/person", json("POST", { dir, rel })); } catch (ex) { failed.push(`${rel}: ${ex.message}`); }
  }
  renderCloset();
  const after = await api("/api/settings/usage");
  const spent = after.prompt_tokens - before.prompt_tokens + after.completion_tokens - before.completion_tokens;
  const spentTxt = analyze === "none" ? "" : ` Consumo desta importação: ${after.calls - before.calls} chamadas, ${spent.toLocaleString("pt-PT")} tokens.`;
  progress.innerHTML = failed.length
    ? `<span class="error">${failed.length} falharam:</span> ${esc(failed.join(" · "))}`
    : `Importadas ${fresh.length} peças${persons.length ? ` e ${persons.length} fotos tuas` : ""}. Toca numa peça para corrigir os detalhes.${spentTxt}`;
  $("#import-scan").click();
});

// ---------- Editar peça ----------
const form = $("#item-form");

function openItem(it) {
  editing = it;
  form.reset();
  $("#item-error").textContent = "";
  $("#item-preview").src = it.image_url;
  $("#item-source").textContent = it.source_path ? `Ficheiro de origem: ${it.source_path}` : "";
  $("#category-select").innerHTML = status.categories.map((c) => `<option value="${c.id}">${esc(c.singular)}</option>`).join("");
  for (const [k, v] of Object.entries(it)) if (form.elements[k]) form.elements[k].value = v;
  $("#item-dialog").showModal();
}

$("#item-cancel").addEventListener("click", () => $("#item-dialog").close());

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const err = $("#item-error");
  err.textContent = "";
  $("#item-save").disabled = true;
  try {
    await api(`/api/items/${editing.id}`, json("PUT", Object.fromEntries(new FormData(form))));
    $("#item-dialog").close();
    await loadItems();
  } catch (ex) {
    err.textContent = ex.message;
  } finally {
    $("#item-save").disabled = false;
  }
});

$("#item-delete").addEventListener("click", async () => {
  if (!confirm("Apagar esta peça?")) return;
  await api(`/api/items/${editing.id}`, { method: "DELETE" });
  $("#item-dialog").close();
  selectedItems.delete(editing.id);
  loadItems();
});

// ---------- Conselhos: 1) texto, 2) peças concretas, 3) imagem em ti ----------
$("#ask-btn").addEventListener("click", async () => {
  const prompt = $("#prompt").value.trim();
  if (!prompt) return;
  const out = $("#advice"), btn = $("#ask-btn");
  btn.disabled = true;
  out.innerHTML = '<p class="muted">A olhar para o teu armário…</p>';
  try {
    const r = await api("/api/advise", json("POST", { prompt }));
    const u = r.usage || {}, cons = r.considered || {};
    const tokens = (u.prompt_tokens || 0) + (u.completion_tokens || 0);
    const usageNote = `<p class="muted usage">${cons.total > cons.sent ? `Analisei ${cons.sent} das tuas ${cons.total} peças (as mais relevantes)` : `Analisei as tuas ${cons.total} peças`}${cons.photos ? `, ${cons.photos} com foto` : ""}. ${u.calls || 0} chamadas, ${tokens.toLocaleString("pt-PT")} tokens.${cons.note ? " " + esc(cons.note) : ""}</p>`;
    out.innerHTML = (r.general_tip ? `<p class="tip">${esc(r.general_tip)}</p>` : "") + learnedHtml(r.learned) + (r.outfits || []).map((o, n) => `
      <div class="outfit">
        <h3>${esc(o.title)}</h3>
        <p>${esc(o.why)}</p>
        <p><b>Como vestir:</b> ${esc(o.how_to_wear)}</p>
        ${o.fit_note ? `<p><b>O que te fica melhor:</b> ${esc(o.fit_note)}</p>` : ""}
        ${o.missing ? `<p class="muted">Falta: ${esc(o.missing)}</p>` : ""}
        <h4>Peças escolhidas</h4>
        <div class="thumbs">${o.items.map((i) => `<div><img src="${i.image_url}" alt=""><span>${esc(i.name)}<br><small class="muted">${esc(i.image)}</small></span></div>`).join("") || '<span class="muted">Nenhuma peça do armário serve.</span>'}</div>
        <div class="tryon" id="tryon-${n}"></div>
        <div class="feedback" data-n="${n}">
          <span class="muted">Que tal este outfit?</span>
          <button data-rate="1">Gostei</button><button data-rate="-1">Não gostei</button>
          <span class="fb-form hidden"><input placeholder="Porquê? (opcional)"><button class="primary" data-send>Enviar</button></span>
          <span class="fb-msg muted"></span>
        </div>
      </div>`).join("") + usageNote;
    bindLearned(out);
    bindFeedback(out, r.history_id);
    await autoTryOn(r.outfits || []);
  } catch (ex) {
    out.innerHTML = `<p class="error">${esc(ex.message)}</p>`;
  } finally {
    btn.disabled = false;
  }
});

// "Aprendi": factos novos que o estilista guardou; o × desfaz.
function learnedHtml(list) {
  if (!list?.length) return "";
  return `<div class="learned"><b>Aprendi:</b> ${list.map((m) => `<span class="chip yes" data-mem="${m.id}">${esc(m.text)} <a href="#" data-undo="${m.id}" aria-label="Desfazer">×</a></span>`).join(" ")}</div>`;
}
function bindLearned(root) {
  root.querySelectorAll("[data-undo]").forEach((a) => a.addEventListener("click", async (e) => {
    e.preventDefault();
    await api(`/api/memories/${a.dataset.undo}`, { method: "DELETE" });
    a.closest(".chip").remove();
  }));
}

function bindFeedback(root, historyId) {
  root.querySelectorAll(".feedback").forEach((box) => {
    let rating = 0;
    const form = box.querySelector(".fb-form"), msg = box.querySelector(".fb-msg");
    box.querySelectorAll("[data-rate]").forEach((b) => b.addEventListener("click", () => {
      rating = +b.dataset.rate;
      box.querySelectorAll("[data-rate]").forEach((x) => x.classList.toggle("on", x === b));
      form.classList.remove("hidden");
    }));
    box.querySelector("[data-send]").addEventListener("click", async (e) => {
      e.target.disabled = true;
      msg.textContent = "A aprender…";
      try {
        const r = await api("/api/feedback", json("POST", { history_id: historyId, outfit_index: +box.dataset.n, rating, comment: form.querySelector("input").value }));
        form.classList.add("hidden");
        msg.innerHTML = r.learned.length ? `Obrigado. Aprendi: ${r.learned.map((m) => esc(m.text)).join("; ")}` : "Obrigado, registado.";
      } catch (ex) {
        msg.textContent = ex.message;
      } finally {
        e.target.disabled = false;
      }
    });
  });
}

// Passo 3: as peças escolhidas seguem para o Gemini com a tua foto.
async function autoTryOn(outfits) {
  if (!$("#auto-tryon").checked || !outfits.length) return;
  const slot = (n) => $(`#tryon-${n}`);
  const note = (msg) => outfits.forEach((_, n) => (slot(n).innerHTML = `<p class="muted">${msg}</p>`));
  if (!status.tryon) return note("Provador não configurado (falta GEMINI_API_KEY).");
  const list = await api("/api/people");
  if (!list.length) return note("Carrega uma foto tua no separador Provador para te ver com o outfit.");
  const person = (list.find((p) => p.id === selectedPerson) || list[0]).id;
  outfits.forEach((o, n) => { if (o.item_ids.length) slot(n).innerHTML = '<h4>Em ti</h4><p class="muted">A vestir-te…</p>'; });
  for (const [n, o] of outfits.entries()) {  // em sequência, para não esgotar quotas
    if (!o.item_ids.length) continue;
    try {
      const r = await api("/api/tryon", json("POST", { person_id: person, item_ids: o.item_ids }));
      slot(n).innerHTML = `<h4>Em ti</h4><img src="${r.image_url}" alt="Outfit em ti">`;
    } catch (ex) {
      slot(n).innerHTML = `<h4>Em ti</h4><p class="error">${esc(ex.message)}</p>`;
    }
  }
}

// ---------- Provador manual ----------
async function renderTryon() {
  people = await api("/api/people");
  if (!people.some((p) => p.id === selectedPerson)) selectedPerson = people[0]?.id ?? null;
  $("#people").innerHTML = people.map((p) => `
    <div class="card ${p.id === selectedPerson ? "selected" : ""}" data-id="${p.id}"><img src="${p.image_url}" alt=""></div>`).join("");
  $("#people").querySelectorAll(".card").forEach((c) => c.addEventListener("click", () => { selectedPerson = +c.dataset.id; renderTryon(); }));
  $("#max-items").textContent = status.max_items;
  const box = $("#tryon-items");
  box.innerHTML = groupsHtml({ selected: selectedItems, mini: true });
  box.querySelectorAll(".mini").forEach((c) => c.addEventListener("click", () => {
    const id = +c.dataset.id;
    if (selectedItems.has(id)) selectedItems.delete(id);
    else if (selectedItems.size < status.max_items) selectedItems.add(id);
    c.classList.toggle("selected", selectedItems.has(id));
  }));
}

$("#person-file").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append("image", f);
  const p = await api("/api/people", { method: "POST", body: fd });
  selectedPerson = p.id;
  e.target.value = "";
  renderTryon();
});

$("#tryon-btn").addEventListener("click", async () => {
  const out = $("#tryon-result"), btn = $("#tryon-btn");
  if (!selectedPerson) return (out.innerHTML = '<p class="error">Carrega primeiro uma foto tua.</p>');
  if (!selectedItems.size) return (out.innerHTML = `<p class="error">Escolhe pelo menos uma peça (máx. ${status.max_items}).</p>`);
  btn.disabled = true;
  out.innerHTML = '<p class="muted">A vestir-te… pode demorar até 30 s.</p>';
  try {
    const r = await api("/api/tryon", json("POST", { person_id: selectedPerson, item_ids: [...selectedItems] }));
    out.innerHTML = `<img src="${r.image_url}" alt="Resultado">`;
  } catch (ex) {
    out.innerHTML = `<p class="error">${esc(ex.message)}</p>`;
  } finally {
    btn.disabled = false;
  }
});

// ---------- Desejos: links, lojas e ideias da IA ----------
let stores = [], wishes = [];
const catLabel = (id) => status.categories.find((c) => c.id === id)?.singular || "";

async function loadWish() {
  [stores, wishes] = await Promise.all([api("/api/stores"), api("/api/wishlist")]);
  $("#wish-category").innerHTML = '<option value="">Categoria (opcional)</option>' + status.categories.map((c) => `<option value="${c.id}">${esc(c.singular)}</option>`).join("");
  renderStores();
  renderWishes();
}

function renderStores() {
  $("#stores").innerHTML = stores.length ? stores.map((s) => `
    <span class="chip ${s.interested ? "yes" : "no"}" data-id="${s.id}" title="Tocar para alternar">${esc(s.name)}${s.count ? `<small>${s.count}</small>` : ""} <a href="#" data-del="${s.id}" aria-label="Remover">×</a></span>`).join("")
    : '<span class="muted">Ainda sem lojas. Adiciona abaixo ou guarda um link.</span>';
  $("#stores").querySelectorAll(".chip").forEach((c) => c.addEventListener("click", async (e) => {
    e.preventDefault();
    const id = +c.dataset.id;
    if (e.target.dataset.del) {
      await api(`/api/stores/${id}`, { method: "DELETE" });
    } else {
      const s = stores.find((x) => x.id === id);
      await api(`/api/stores/${id}`, json("PUT", { interested: !s.interested }));
    }
    stores = await api("/api/stores");
    renderStores();
  }));
  const cur = $("#wish-filter").value;
  $("#wish-filter").innerHTML = '<option value="">Todas as lojas</option>' + stores.map((s) => `<option ${s.name === cur ? "selected" : ""}>${esc(s.name)}</option>`).join("");
}

function renderWishes() {
  const f = $("#wish-filter").value.toLowerCase();
  const list = wishes.filter((w) => !f || w.store.toLowerCase() === f);
  $("#wishlist").innerHTML = list.length ? list.map((w) => `
    <div class="wish ${w.bought ? "bought" : ""}" data-id="${w.id}">
      ${w.image_url ? `<img src="${w.image_url}" alt="" loading="lazy">` : ""}
      <div class="body">
        <b>${esc(w.title)}</b>
        <div class="tags">${esc([w.store, catLabel(w.category), w.price].filter(Boolean).join(" · "))}</div>
        ${w.notes ? `<div>${esc(w.notes)}</div>` : ""}
        <div class="acts">
          ${w.url ? `<a href="${esc(w.url)}" target="_blank" rel="noopener noreferrer">${w.source === "ai" ? "Pesquisar" : "Abrir"}</a>` : ""}
          <button data-bought>${w.bought ? "Por comprar" : "Comprado"}</button>
          <button data-del>Apagar</button>
        </div>
      </div>
    </div>`).join("") : '<p class="muted">Nada guardado ainda.</p>';
  $("#wishlist").querySelectorAll(".wish").forEach((el) => {
    const id = +el.dataset.id;
    el.querySelector("[data-bought]").addEventListener("click", async () => {
      await api(`/api/wishlist/${id}`, json("PUT", { bought: !wishes.find((w) => w.id === id).bought }));
      wishes = await api("/api/wishlist");
      renderWishes();
    });
    el.querySelector("[data-del]").addEventListener("click", async () => {
      if (!confirm("Apagar este item?")) return;
      await api(`/api/wishlist/${id}`, { method: "DELETE" });
      await loadWish();
    });
  });
}
$("#wish-filter").addEventListener("change", renderWishes);

$("#wish-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = $("#wish-msg"), btn = $("#wish-save"), f = e.target;
  const data = Object.fromEntries(new FormData(f));
  btn.disabled = true;
  msg.className = "muted";
  msg.textContent = data.url ? "A ler o link…" : "A guardar…";
  try {
    const w = await api("/api/wishlist", json("POST", { ...data, source: data.url ? "link" : "manual" }));
    f.reset();
    msg.textContent = w.scraped ? "Guardado." : "Guardado, mas o site não deixou ler os detalhes. Podes escrever o título e o preço à mão.";
    await loadWish();
  } catch (ex) {
    msg.className = "error";
    msg.textContent = ex.message;
  } finally {
    btn.disabled = false;
  }
});

$("#store-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = e.target.elements.name.value.trim();
  if (!name) return;
  await api("/api/stores", json("POST", { name, interested: e.submitter?.dataset.interest !== "0" }));
  e.target.reset();
  stores = await api("/api/stores");
  renderStores();
});

$("#suggest-btn").addEventListener("click", async () => {
  const out = $("#suggestions"), btn = $("#suggest-btn");
  btn.disabled = true;
  out.innerHTML = '<p class="muted">A analisar o teu armário…</p>';
  try {
    const r = await api("/api/wishlist/suggest", json("POST", { prompt: $("#suggest-prompt").value.trim() }));
    const list = r.suggestions || [];
    out.innerHTML = list.map((s, n) => `
      <div class="outfit sugg">
        <h3>${esc(s.title)}</h3>
        <div class="muted">${esc([catLabel(s.category), s.store].filter(Boolean).join(" · "))}</div>
        <p>${esc(s.why)}</p>
        ${s.combines_with.length ? `<div class="thumbs">${s.combines_with.map((i) => `<div><img src="${i.image_url}" alt=""><span>${esc(i.name)}</span></div>`).join("")}</div>` : ""}
        <div class="bar">
          <a class="button" href="${esc(s.search_url)}" target="_blank" rel="noopener noreferrer">Pesquisar</a>
          <button data-save="${n}">Guardar</button>
        </div>
      </div>`).join("") || '<p class="muted">Sem sugestões desta vez.</p>';
    out.querySelectorAll("[data-save]").forEach((b) => b.addEventListener("click", async () => {
      const s = list[b.dataset.save];
      b.disabled = true;
      try {
        await api("/api/wishlist", json("POST", { url: s.search_url, title: s.title, store: s.store, category: s.category, notes: s.why, source: "ai" }));
        b.textContent = "Guardado";
        wishes = await api("/api/wishlist");
        stores = await api("/api/stores");
        renderWishes();
        renderStores();
      } catch (ex) {
        b.disabled = false;
        alert(ex.message);
      }
    }));
  } catch (ex) {
    out.innerHTML = `<p class="error">${esc(ex.message)}</p>`;
  } finally {
    btn.disabled = false;
  }
});

// ---------- Memória ----------
async function loadMemory() {
  const [profile, mems, hist, body] = await Promise.all([api("/api/profile"), api("/api/memories"), api("/api/history"), api("/api/body")]);
  $("#profile-text").value = profile.text;
  for (const [k, v] of Object.entries(body)) $("#body-form").elements[k].value = v;
  $("#memory-count").textContent = mems.length ? `(${mems.length})` : "";
  $("#memories").innerHTML = mems.length ? mems.map((m) => `
    <div class="mem" data-id="${m.id}" data-kind="${esc(m.kind)}">
      <span class="badge">${esc(m.kind)}</span>
      <span class="mem-text">${esc(m.text)}</span>
      <small class="muted">${m.source === "user" ? "tu" : m.source === "feedback" ? "feedback" : "aprendido"}</small>
      <button data-edit>Editar</button><button data-del>×</button>
    </div>`).join("") : '<p class="muted">Ainda sem memória. Diz ao estilista o que gostas ou evitas, ou dá feedback aos outfits.</p>';
  $("#memories").querySelectorAll(".mem").forEach((el) => {
    const id = +el.dataset.id;
    el.querySelector("[data-del]").addEventListener("click", async () => {
      await api(`/api/memories/${id}`, { method: "DELETE" });
      loadMemory();
    });
    el.querySelector("[data-edit]").addEventListener("click", async () => {
      const text = prompt("Editar:", el.querySelector(".mem-text").textContent);
      if (text === null) return;
      try {
        await api(`/api/memories/${id}`, json("PUT", { text, kind: el.dataset.kind }));
        loadMemory();
      } catch (ex) { alert(ex.message); }
    });
  });
  $("#history").innerHTML = hist.length ? hist.map((h) => `
    <div class="hist">
      <small class="muted">${esc(h.created_at.slice(0, 10))}</small> <b>${esc(h.prompt)}</b>
      ${h.outfits.map((o) => `<div class="muted">${o.rating > 0 ? "👍" : o.rating < 0 ? "👎" : "•"} ${esc(o.title)}: ${esc(o.item_names.join(", "))}</div>`).join("")}
    </div>`).join("") : '<p class="muted">Ainda sem pedidos.</p>';
}

$("#body-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = $("#body-msg");
  try {
    await api("/api/body", json("PUT", Object.fromEntries(new FormData(e.target))));
    msg.className = "muted";
    msg.textContent = "Guardado.";
    setTimeout(() => (msg.textContent = ""), 2000);
  } catch (ex) {
    msg.className = "error";
    msg.textContent = ex.message;
  }
});

$("#profile-save").addEventListener("click", async () => {
  await api("/api/profile", json("PUT", { text: $("#profile-text").value }));
  $("#profile-msg").textContent = "Guardado.";
  setTimeout(() => ($("#profile-msg").textContent = ""), 2000);
});

$("#memory-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = $("#memory-msg");
  msg.textContent = "";
  try {
    await api("/api/memories", json("POST", Object.fromEntries(new FormData(e.target))));
    e.target.elements.text.value = "";
    loadMemory();
  } catch (ex) {
    msg.textContent = ex.message;
  }
});

// ---------- Definições dos modelos ----------
const SETTING_FIELDS = ["LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "LLM_VISION_MODEL", "GEMINI_API_KEY", "TRYON_MODEL", "TRYON_BASE_URL"];

async function refreshStatus() {
  status = { ...status, ...(await api("/api/status")) };
  const dot = $("#model-dot");
  dot.className = "dot " + (status.advice ? "ok" : "bad");
  dot.title = `Texto: ${status.advice ? "ok" : "falta configurar"} · Visão: ${status.vision ? "ok" : "desligada"} · Provador: ${status.tryon ? "ok" : "desligado"}`;
}

async function loadSettings() {
  api("/api/settings/usage").then((u) => {
    $("#usage-line").textContent = `Desde que o servidor arrancou: ${u.calls} chamadas · ${u.prompt_tokens.toLocaleString("pt-PT")} tokens enviados · ${u.completion_tokens.toLocaleString("pt-PT")} recebidos.`;
  }).catch(() => {});
  const s = await api("/api/settings");
  const f = $("#settings-form");
  for (const name of SETTING_FIELDS) {
    const el = f.elements[name];
    if (name.endsWith("_KEY")) {
      el.value = "";
      el.placeholder = s[`${name}_set`] ? `guardada (${s[name + "_hint"]}) — deixa vazio para manter` : el.placeholder;
    } else {
      el.value = s[name];
    }
  }
}

const settingsBody = () => Object.fromEntries(SETTING_FIELDS.map((n) => [n, $("#settings-form").elements[n].value]));

async function saveSettings() {
  await api("/api/settings", json("PUT", settingsBody()));
  await loadSettings();
  await refreshStatus();
}

$("#settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = $("#settings-msg");
  try {
    await saveSettings();
    msg.className = "muted";
    msg.textContent = "Guardado.";
  } catch (ex) {
    msg.className = "error";
    msg.textContent = ex.message;
  }
});

$("#load-models").addEventListener("click", async () => {
  const msg = $("#models-msg");
  msg.textContent = "A carregar…";
  try {
    await saveSettings();
    const r = await api("/api/settings/models");
    $("#model-list").innerHTML = r.models.map((m) => `<option value="${esc(m)}">`).join("");
    msg.textContent = r.ok ? `${r.models.length} modelos. Clica num campo de modelo e escolhe.` : r.error;
  } catch (ex) {
    msg.textContent = ex.message;
  }
});

document.querySelectorAll("[data-test]").forEach((btn) => btn.addEventListener("click", async () => {
  const kind = btn.dataset.test, box = $(`#result-${kind}`);
  btn.disabled = true;
  box.className = "result";
  box.textContent = "A testar…";
  try {
    await saveSettings();
    const r = await api(`/api/settings/test/${kind}`, { method: "POST" });
    const warn = r.ok && (r.json_ok === false || r.sees_image === false);
    box.className = "result " + (r.ok && !warn ? "ok" : "bad");
    box.innerHTML = r.ok
      ? `<b>${warn ? "⚠ Respondeu, mas…" : "✓ Funciona"}</b> · ${esc(r.model)} · ${r.ms} ms`
        + (r.note ? `<div>${esc(r.note)}</div>` : "")
        + (r.reply ? `<code>${esc(r.reply)}</code>` : "")
        + (r.image_url ? `<img src="${r.image_url}" alt="Resultado do teste">` : "")
      : `<b>✗ Falhou</b> · ${r.ms} ms<div>${esc(r.error)}</div>`;
  } catch (ex) {
    box.className = "result bad";
    box.textContent = ex.message;
  } finally {
    btn.disabled = false;
  }
}));

// ---------- Arranque ----------
(async () => {
  status = await api("/api/status");
  await refreshStatus();
  if (!status.advice) showTab("settings");  // primeira vez: começa pela configuração dos modelos
  await loadItems();
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js");
})();
