const $ = (s) => document.querySelector(s);
const api = async (url, opts) => {
  const r = await fetch(url, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch {}
    // A generic 404/405 on an /api/ route = the running server predates this version of the page
    if ((r.status === 404 || r.status === 405) && String(url).startsWith("/api/") && ["Not Found", "Method Not Allowed"].includes(msg)) {
      msg = "The server is out of date. Stop it in the terminal (Ctrl+C) and start it again with: uv run uvicorn app.main:app --port 8000 --reload";
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

// ---------- Wardrobe by category ----------
let closetView = localStorage.getItem("closetView") || "mini";
let closetCat = localStorage.getItem("closetCat") || "";  // "" = all categories
let justAdded = new Set();  // garments just added: they animate in

const miniHtml = (it, extra = "") => `
  <div class="mini ${extra}" data-id="${it.id}" title="${esc(it.name)}">
    <img src="${it.thumb_url}" loading="lazy" alt="">
    <span>${esc(it.name)}</span>
  </div>`;

const cardHtml = (it, extra = "") => `
  <div class="card ${extra}" data-id="${it.id}">
    <img src="${it.image_url}" loading="lazy" alt="">
    <div class="meta"><b>${esc(it.name)}</b>${esc([it.brand, it.model, it.size && "size " + it.size].filter(Boolean).join(" · "))}</div>
  </div>`;

// Draws every category with its garments. `withAdd` shows the add-photos button.
function groupsHtml({ withAdd = false, selected = null, mini = false, only = "" } = {}) {
  const known = new Set(status.categories.map((c) => c.id));
  const groups = status.categories.map((c) => ({ ...c, list: items.filter((i) => i.category === c.id) }));
  const loose = items.filter((i) => !known.has(i.category));
  if (loose.length) groups.push({ id: "", label: "Uncategorised", list: loose });
  return groups.filter((g) => !only || g.id === only).map((g) => `
    <div class="group">
      <div class="group-head">
        <h2>${esc(g.label)} <span class="muted">${g.list.length}</span></h2>
        ${withAdd && g.id ? `<button data-add="${g.id}">+ Add photos</button>` : ""}
      </div>
      ${mini
        ? `<div class="shelf">${g.list.map((i) => miniHtml(i, (selected?.has(i.id) ? "selected " : "") + (justAdded.has(i.id) ? "pop" : ""))).join("")}${withAdd && g.id ? `<button class="mini add" data-add="${g.id}" title="Add photos"><b>+</b></button>` : ""}</div>${g.list.length || withAdd ? "" : '<p class="muted empty">No garments yet.</p>'}`
        : g.list.length ? `<div class="grid">${g.list.map((i) => cardHtml(i, selected?.has(i.id) ? "selected" : "")).join("")}</div>` : '<p class="muted empty">No garments yet.</p>'}
    </div>`).join("");
}

// Category tabs: "All" shows everything; each tab shows only that category.
function renderCatTabs() {
  const tabs = [{ id: "", label: "All", n: items.length }, ...status.categories.map((c) => ({ id: c.id, label: c.label, n: items.filter((i) => i.category === c.id).length }))];
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

// Add several photos at once to a category; the vision model suggests name/colour/season.
$("#bulk-file").addEventListener("change", async (e) => {
  const files = [...e.target.files];
  e.target.value = "";
  if (!files.length || !bulkCategory) return;
  const cat = status.categories.find((c) => c.id === bulkCategory);
  const progress = $("#progress");
  let failed = 0;
  for (const [n, f] of files.entries()) {
    progress.textContent = `Saving ${n + 1}/${files.length}…`;
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
  progress.textContent = failed ? `${failed} photo(s) failed.` : "";
  setTimeout(() => { if (!failed) progress.textContent = ""; }, 2000);
});

// ---------- Import from folder ----------
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
  box.innerHTML = '<p class="muted">Reading the folder…</p>';
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
    <div class="import-summary"><b>${fresh.length}</b> new garments${known.length ? ` · ${known.length} already in the app` : ""}${dups.length ? ` · ${dups.length} repeated in the folder` : ""}${scanResult.skipped.length ? ` · ${scanResult.skipped.length} ignored` : ""}</div>
    ${fresh.length ? `<div class="itable-wrap"><table class="itable"><thead><tr><th>File</th><th>Category</th><th>Name</th><th>Size</th><th>Brand</th><th>Model</th><th>Colour</th><th>Fit</th><th>Material</th></tr></thead><tbody>
      ${fresh.map((f) => `<tr><td>${esc(f.rel)}</td><td>${esc(labelOf(f.category))}</td><td>${esc(f.name || "(automatic)")}</td><td>${esc(f.size)}</td><td>${esc(f.brand)}</td><td>${esc(f.model)}</td><td>${esc(f.color)}</td><td>${esc(f.fit)}</td><td>${esc(f.material)}</td></tr>`).join("")}
    </tbody></table></div>` : ""}
    ${known.length ? `<p class="muted">Already in the app (will not be imported): ${known.map((f) => `${esc(f.rel)} (${esc(f.reason)})`).join("; ")}</p>` : ""}
    ${dups.length ? `<p class="muted">Not imported because they have the same name or content as another: ${dups.map((d) => `${esc(d.rel)} = ${esc(d.of)} (${esc(d.reason)})`).join("; ")}</p>` : ""}
    ${scanResult.skipped.length ? `<p class="muted">Ignored: ${scanResult.skipped.map((s) => `${esc(s.rel)} (${esc(s.reason)})`).join("; ")}</p>` : ""}
    ${newPeople.length ? `<div class="import-summary"><b>Loose photos in the folder</b> <span class="muted">(if they are photos of you, import them into the Fitting room)</span>
      ${newPeople.map((p) => `<label class="check"><input type="checkbox" data-person="${esc(p.rel)}"> ${esc(p.rel)}</label>`).join("")}</div>` : ""}
    ${!scanResult.files.length && !scanResult.people.length ? '<p class="muted">No images found. Put the photos in subfolders named after the category.</p>' : ""}`;
  $("#import-run").disabled = !fresh.length && !newPeople.length;
  updateImportEstimate();
});

function updateImportEstimate() {
  const fresh = (scanResult?.files || []).filter((f) => f.status === "new");
  const mode = $("#import-analyze").value;
  const n = mode === "all" ? fresh.length : mode === "missing" ? fresh.filter((f) => !f.color).length : 0;
  $("#import-estimate").textContent = n ? `${n} calls to the vision model (downscaled photos). Actual usage is shown at the end.` : "No calls to the model.";
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
    progress.textContent = `Importing ${done + 1}/${fresh.length}: ${f.rel}`;
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
  const spentTxt = analyze === "none" ? "" : ` Usage for this import: ${after.calls - before.calls} calls, ${spent.toLocaleString("en-GB")} tokens.`;
  progress.innerHTML = failed.length
    ? `<span class="error">${failed.length} failed:</span> ${esc(failed.join(" · "))}`
    : `Imported ${fresh.length} garments${persons.length ? ` and ${persons.length} photos of you` : ""}. Tap a garment to correct its details.${spentTxt}`;
  $("#import-scan").click();
});

// ---------- Edit garment ----------
const form = $("#item-form");

function openItem(it) {
  editing = it;
  form.reset();
  $("#item-error").textContent = "";
  $("#item-preview").src = it.image_url;
  $("#item-source").textContent = it.source_path ? `Source file: ${it.source_path}` : "";
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
  if (!confirm("Delete this garment?")) return;
  await api(`/api/items/${editing.id}`, { method: "DELETE" });
  $("#item-dialog").close();
  selectedItems.delete(editing.id);
  loadItems();
});

// ---------- Stylist: 1) text, 2) the actual garments, 3) image of you ----------
$("#ask-btn").addEventListener("click", async () => {
  const prompt = $("#prompt").value.trim();
  if (!prompt) return;
  const out = $("#advice"), btn = $("#ask-btn");
  btn.disabled = true;
  out.innerHTML = '<p class="muted">Looking through your wardrobe…</p>';
  try {
    const r = await api("/api/advise", json("POST", { prompt }));
    const u = r.usage || {}, cons = r.considered || {};
    const tokens = (u.prompt_tokens || 0) + (u.completion_tokens || 0);
    const usageNote = `<p class="muted usage">${cons.total > cons.sent ? `I analysed ${cons.sent} of your ${cons.total} garments (the most relevant)` : `I analysed your ${cons.total} garments`}${cons.photos ? `, ${cons.photos} with photo` : ""}. ${u.calls || 0} calls, ${tokens.toLocaleString("en-GB")} tokens.${cons.note ? " " + esc(cons.note) : ""}</p>`;
    out.innerHTML = (r.general_tip ? `<p class="tip">${esc(r.general_tip)}</p>` : "") + learnedHtml(r.learned) + (r.outfits || []).map((o, n) => `
      <div class="outfit">
        <h3>${esc(o.title)}</h3>
        <p>${esc(o.why)}</p>
        <p><b>How to wear it:</b> ${esc(o.how_to_wear)}</p>
        ${o.fit_note ? `<p><b>What suits you best:</b> ${esc(o.fit_note)}</p>` : ""}
        ${o.missing ? `<p class="muted">Missing: ${esc(o.missing)}</p>` : ""}
        <h4>Chosen garments</h4>
        <div class="thumbs">${o.items.map((i) => `<div><img src="${i.image_url}" alt=""><span>${esc(i.name)}<br><small class="muted">${esc(i.image)}</small></span></div>`).join("") || '<span class="muted">No garment in the wardrobe fits.</span>'}</div>
        <div class="tryon" id="tryon-${n}"></div>
        <div class="feedback" data-n="${n}">
          <span class="muted">What do you think of this outfit?</span>
          <button data-rate="1">I like it</button><button data-rate="-1">I don't like it</button>
          <span class="fb-form hidden"><input placeholder="Why? (optional)"><button class="primary" data-send>Send</button></span>
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

// "Learned": new facts the stylist stored; the × undoes it.
function learnedHtml(list) {
  if (!list?.length) return "";
  return `<div class="learned"><b>Learned:</b> ${list.map((m) => `<span class="chip yes" data-mem="${m.id}">${esc(m.text)} <a href="#" data-undo="${m.id}" aria-label="Undo">×</a></span>`).join(" ")}</div>`;
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
      msg.textContent = "Learning…";
      try {
        const r = await api("/api/feedback", json("POST", { history_id: historyId, outfit_index: +box.dataset.n, rating, comment: form.querySelector("input").value }));
        form.classList.add("hidden");
        msg.innerHTML = r.learned.length ? `Thanks. Learned: ${r.learned.map((m) => esc(m.text)).join("; ")}` : "Thanks, noted.";
      } catch (ex) {
        msg.textContent = ex.message;
      } finally {
        e.target.disabled = false;
      }
    });
  });
}

// Step 3: the chosen garments go to the image model together with your photo.
async function autoTryOn(outfits) {
  if (!$("#auto-tryon").checked || !outfits.length) return;
  const slot = (n) => $(`#tryon-${n}`);
  const note = (msg) => outfits.forEach((_, n) => (slot(n).innerHTML = `<p class="muted">${msg}</p>`));
  if (!status.tryon) return note("The fitting room is not configured (the image-model key is missing).");
  const list = await api("/api/people");
  if (!list.length) return note("Upload a photo of yourself in the Fitting room tab to see yourself in the outfit.");
  const person = (list.find((p) => p.id === selectedPerson) || list[0]).id;
  outfits.forEach((o, n) => { if (o.item_ids.length) slot(n).innerHTML = '<h4>On you</h4><p class="muted">Dressing you…</p>'; });
  for (const [n, o] of outfits.entries()) {  // one after another, so quotas are not exhausted
    if (!o.item_ids.length) continue;
    try {
      const r = await api("/api/tryon", json("POST", { person_id: person, item_ids: o.item_ids }));
      slot(n).innerHTML = `<h4>On you</h4><img src="${r.image_url}" alt="Outfit on you">`;
    } catch (ex) {
      slot(n).innerHTML = `<h4>On you</h4><p class="error">${esc(ex.message)}</p>`;
    }
  }
}

// ---------- Fitting room (manual) ----------
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
  if (!selectedPerson) return (out.innerHTML = '<p class="error">Upload a photo of yourself first.</p>');
  if (!selectedItems.size) return (out.innerHTML = `<p class="error">Choose at least one garment (max. ${status.max_items}).</p>`);
  btn.disabled = true;
  out.innerHTML = '<p class="muted">Dressing you… this can take up to 30 s.</p>';
  try {
    const r = await api("/api/tryon", json("POST", { person_id: selectedPerson, item_ids: [...selectedItems] }));
    out.innerHTML = `<img src="${r.image_url}" alt="Result">`;
  } catch (ex) {
    out.innerHTML = `<p class="error">${esc(ex.message)}</p>`;
  } finally {
    btn.disabled = false;
  }
});

// ---------- Wishlist: links, stores and AI ideas ----------
let stores = [], wishes = [];
const catLabel = (id) => status.categories.find((c) => c.id === id)?.singular || "";

async function loadWish() {
  [stores, wishes] = await Promise.all([api("/api/stores"), api("/api/wishlist")]);
  $("#wish-category").innerHTML = '<option value="">Category (optional)</option>' + status.categories.map((c) => `<option value="${c.id}">${esc(c.singular)}</option>`).join("");
  renderStores();
  renderWishes();
}

function renderStores() {
  $("#stores").innerHTML = stores.length ? stores.map((s) => `
    <span class="chip ${s.interested ? "yes" : "no"}" data-id="${s.id}" title="Tap to switch">${esc(s.name)}${s.count ? `<small>${s.count}</small>` : ""} <a href="#" data-del="${s.id}" aria-label="Remove">×</a></span>`).join("")
    : '<span class="muted">No stores yet. Add one below or save a link.</span>';
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
  $("#wish-filter").innerHTML = '<option value="">All stores</option>' + stores.map((s) => `<option ${s.name === cur ? "selected" : ""}>${esc(s.name)}</option>`).join("");
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
          ${w.url ? `<a href="${esc(w.url)}" target="_blank" rel="noopener noreferrer">${w.source === "ai" ? "Search" : "Open"}</a>` : ""}
          <button data-bought>${w.bought ? "Not bought" : "Bought"}</button>
          <button data-del>Delete</button>
        </div>
      </div>
    </div>`).join("") : '<p class="muted">Nothing saved yet.</p>';
  $("#wishlist").querySelectorAll(".wish").forEach((el) => {
    const id = +el.dataset.id;
    el.querySelector("[data-bought]").addEventListener("click", async () => {
      await api(`/api/wishlist/${id}`, json("PUT", { bought: !wishes.find((w) => w.id === id).bought }));
      wishes = await api("/api/wishlist");
      renderWishes();
    });
    el.querySelector("[data-del]").addEventListener("click", async () => {
      if (!confirm("Delete this item?")) return;
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
  msg.textContent = data.url ? "Reading the link…" : "Saving…";
  try {
    const w = await api("/api/wishlist", json("POST", { ...data, source: data.url ? "link" : "manual" }));
    f.reset();
    msg.textContent = w.scraped ? "Saved." : "Saved, but the site would not let me read the details. You can type the title and price by hand.";
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
  out.innerHTML = '<p class="muted">Analysing your wardrobe…</p>';
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
          <a class="button" href="${esc(s.search_url)}" target="_blank" rel="noopener noreferrer">Search</a>
          <button data-save="${n}">Save</button>
        </div>
      </div>`).join("") || '<p class="muted">No suggestions this time.</p>';
    out.querySelectorAll("[data-save]").forEach((b) => b.addEventListener("click", async () => {
      const s = list[b.dataset.save];
      b.disabled = true;
      try {
        await api("/api/wishlist", json("POST", { url: s.search_url, title: s.title, store: s.store, category: s.category, notes: s.why, source: "ai" }));
        b.textContent = "Saved";
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

// ---------- Memory ----------
async function loadMemory() {
  const [profile, mems, hist, body] = await Promise.all([api("/api/profile"), api("/api/memories"), api("/api/history"), api("/api/body")]);
  $("#profile-text").value = profile.text;
  for (const [k, v] of Object.entries(body)) $("#body-form").elements[k].value = v;
  $("#memory-count").textContent = mems.length ? `(${mems.length})` : "";
  $("#memories").innerHTML = mems.length ? mems.map((m) => `
    <div class="mem" data-id="${m.id}" data-kind="${esc(m.kind)}">
      <span class="badge">${esc(m.kind)}</span>
      <span class="mem-text">${esc(m.text)}</span>
      <small class="muted">${m.source === "user" ? "you" : m.source === "feedback" ? "feedback" : "learned"}</small>
      <button data-edit>Edit</button><button data-del>×</button>
    </div>`).join("") : '<p class="muted">No memory yet. Tell the stylist what you like or avoid, or give feedback on outfits.</p>';
  $("#memories").querySelectorAll(".mem").forEach((el) => {
    const id = +el.dataset.id;
    el.querySelector("[data-del]").addEventListener("click", async () => {
      await api(`/api/memories/${id}`, { method: "DELETE" });
      loadMemory();
    });
    el.querySelector("[data-edit]").addEventListener("click", async () => {
      const text = prompt("Edit:", el.querySelector(".mem-text").textContent);
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
    </div>`).join("") : '<p class="muted">No requests yet.</p>';
}

$("#body-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = $("#body-msg");
  try {
    await api("/api/body", json("PUT", Object.fromEntries(new FormData(e.target))));
    msg.className = "muted";
    msg.textContent = "Saved.";
    setTimeout(() => (msg.textContent = ""), 2000);
  } catch (ex) {
    msg.className = "error";
    msg.textContent = ex.message;
  }
});

$("#profile-save").addEventListener("click", async () => {
  await api("/api/profile", json("PUT", { text: $("#profile-text").value }));
  $("#profile-msg").textContent = "Saved.";
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

// ---------- Model settings ----------
const SETTING_FIELDS = ["LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "LLM_VISION_MODEL", "GEMINI_API_KEY", "TRYON_MODEL", "TRYON_BASE_URL"];

async function refreshStatus() {
  status = { ...status, ...(await api("/api/status")) };
  const dot = $("#model-dot");
  dot.className = "dot " + (status.advice ? "ok" : "bad");
  dot.title = `Text: ${status.advice ? "ok" : "not configured"} · Vision: ${status.vision ? "ok" : "off"} · Fitting room: ${status.tryon ? "ok" : "off"}`;
}

async function loadSettings() {
  api("/api/settings/usage").then((u) => {
    $("#usage-line").textContent = `Since the server started: ${u.calls} calls · ${u.prompt_tokens.toLocaleString("en-GB")} tokens sent · ${u.completion_tokens.toLocaleString("en-GB")} received.`;
  }).catch(() => {});
  const s = await api("/api/settings");
  const f = $("#settings-form");
  for (const name of SETTING_FIELDS) {
    const el = f.elements[name];
    if (name.endsWith("_KEY")) {
      el.value = "";
      el.placeholder = s[`${name}_set`] ? `saved (${s[name + "_hint"]}) — leave empty to keep it` : el.placeholder;
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
    msg.textContent = "Saved.";
  } catch (ex) {
    msg.className = "error";
    msg.textContent = ex.message;
  }
});

$("#load-models").addEventListener("click", async () => {
  const msg = $("#models-msg");
  msg.textContent = "Loading…";
  try {
    await saveSettings();
    const r = await api("/api/settings/models");
    $("#model-list").innerHTML = r.models.map((m) => `<option value="${esc(m)}">`).join("");
    msg.textContent = r.ok ? `${r.models.length} models. Click a model field and choose one.` : r.error;
  } catch (ex) {
    msg.textContent = ex.message;
  }
});

document.querySelectorAll("[data-test]").forEach((btn) => btn.addEventListener("click", async () => {
  const kind = btn.dataset.test, box = $(`#result-${kind}`);
  btn.disabled = true;
  box.className = "result";
  box.textContent = "Testing…";
  try {
    await saveSettings();
    const r = await api(`/api/settings/test/${kind}`, { method: "POST" });
    const warn = r.ok && (r.json_ok === false || r.sees_image === false);
    box.className = "result " + (r.ok && !warn ? "ok" : "bad");
    box.innerHTML = r.ok
      ? `<b>${warn ? "⚠ It answered, but…" : "✓ Works"}</b> · ${esc(r.model)} · ${r.ms} ms`
        + (r.note ? `<div>${esc(r.note)}</div>` : "")
        + (r.reply ? `<code>${esc(r.reply)}</code>` : "")
        + (r.image_url ? `<img src="${r.image_url}" alt="Test result">` : "")
      : `<b>✗ Failed</b> · ${r.ms} ms<div>${esc(r.error)}</div>`;
  } catch (ex) {
    box.className = "result bad";
    box.textContent = ex.message;
  } finally {
    btn.disabled = false;
  }
}));

// ---------- Start-up ----------
(async () => {
  status = await api("/api/status");
  await refreshStatus();
  if (!status.advice) showTab("settings");  // first run: start with the model settings
  await loadItems();
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js");
})();
