const state = {
  user: null,
  route: location.pathname,
  bootstrap: null,
  assets: [],
  selectedAsset: null,
  importPreview: null,
  editingAsset: null,
  lookupTab: "locations",
};

const $ = (selector) => document.querySelector(selector);

async function api(path, options = {}) {
  const res = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(error.error || res.statusText);
  }
  const type = res.headers.get("content-type") || "";
  return type.includes("application/json") ? res.json() : res.text();
}

function navigate(path) {
  history.pushState(null, "", path);
  state.route = path;
  render();
}

window.addEventListener("popstate", () => {
  state.route = location.pathname;
  render();
});

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  })[char]);
}

function statusClass(value) {
  return String(value || "").replace(/\s+/g, "");
}

function optionList(items, selected = "") {
  return items.map((item) => `<option value="${esc(item.name)}" ${item.name === selected ? "selected" : ""}>${esc(item.name)}</option>`).join("");
}

async function loadBootstrap() {
  state.bootstrap = await api("/api/bootstrap");
  state.user = state.bootstrap.user;
}

async function loadAssets() {
  const params = new URLSearchParams();
  const search = $("#search")?.value || "";
  const location = $("#filterLocation")?.value || "";
  const category = $("#filterCategory")?.value || "";
  const status = $("#filterStatus")?.value || "";
  if (search) params.set("search", search);
  if (location) params.set("location", location);
  if (category) params.set("category", category);
  if (status) params.set("status", status);
  state.assets = await api(`/api/assets?${params.toString()}`);
  renderAssetsTable();
}

async function init() {
  try {
    const me = await api("/api/me");
    state.user = me.user;
    if (state.user) await loadBootstrap();
  } catch {
    state.user = null;
  }
  render();
}

function render() {
  if (!state.user) {
    renderLogin();
    return;
  }
  document.querySelector("#app").innerHTML = shell(layoutForRoute());
  bindShell();
}

function renderLogin() {
  document.querySelector("#app").innerHTML = `
    <main class="login-page">
      <form class="login-panel" id="loginForm">
        <h1>FLE CMMS Assets</h1>
        <p class="muted">Sign in to manage the asset database.</p>
        <div class="grid">
          <label>Email <input name="email" value="admin@example.com" autocomplete="username"></label>
          <label>Password <input name="password" type="password" value="admin123" autocomplete="current-password"></label>
          <div id="loginError"></div>
          <button class="primary" type="submit">Sign in</button>
        </div>
      </form>
    </main>
  `;
  $("#loginForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const result = await api("/api/login", {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(form)),
      });
      state.user = result.user;
      await loadBootstrap();
      navigate("/dashboard");
    } catch (err) {
      $("#loginError").innerHTML = `<div class="error">${esc(err.message)}</div>`;
    }
  });
}

function shell(content) {
  const nav = [
    ["/dashboard", "Dashboard"],
    ["/assets", "Assets"],
    ["/assets/new", "New Asset"],
    ["/locations", "Locations"],
    ["/settings/categories", "Categories"],
    ["/settings/statuses", "Statuses"],
    ["/imports/assets", "Asset Import"],
  ];
  return `
    <div class="shell">
      <aside class="side">
        <div class="brand">FLE CMMS</div>
        <nav class="nav">
          ${nav.map(([path, label]) => `<button data-nav="${path}" class="${state.route === path ? "active" : ""}">${label}</button>`).join("")}
        </nav>
        <div class="userbox">
          <strong>${esc(state.user.name)}</strong>
          <span>${esc(state.user.role)}</span>
          <button id="logout">Sign out</button>
        </div>
      </aside>
      <main class="main">${content}</main>
    </div>
  `;
}

function bindShell() {
  document.querySelectorAll("[data-nav]").forEach((button) => {
    button.addEventListener("click", () => navigate(button.dataset.nav));
  });
  $("#logout").addEventListener("click", async () => {
    await api("/api/logout", { method: "POST", body: "{}" });
    state.user = null;
    navigate("/login");
  });
}

function layoutForRoute() {
  if (state.route === "/dashboard") return dashboardPage();
  if (state.route === "/assets") return assetsPage();
  if (state.route === "/assets/new") return assetFormPage();
  if (state.route.startsWith("/assets/")) return assetDetailPage(Number(state.route.split("/")[2]));
  if (state.route === "/locations") return lookupPage("locations", "Locations");
  if (state.route === "/settings/categories") return lookupPage("categories", "Categories");
  if (state.route === "/settings/statuses") return lookupPage("statuses", "Statuses");
  if (state.route === "/imports/assets") return importPage();
  return dashboardPage();
}

function dashboardPage() {
  setTimeout(loadDashboard, 0);
  return `
    <section class="page">
      <div class="topbar">
        <div>
          <h1>Dashboard</h1>
          <p class="muted">Asset database overview.</p>
        </div>
        <button class="primary" data-nav="/assets/new">New asset</button>
      </div>
      <div class="grid cols-4" id="stats">
        <div class="card stat"><span class="muted">Assets</span><strong>...</strong></div>
        <div class="card stat"><span class="muted">Locations</span><strong>...</strong></div>
        <div class="card stat"><span class="muted">Under repair</span><strong>...</strong></div>
        <div class="card stat"><span class="muted">Disposed</span><strong>...</strong></div>
      </div>
    </section>
  `;
}

async function loadDashboard() {
  const stats = await api("/api/dashboard");
  $("#stats").innerHTML = `
    <div class="card stat"><span class="muted">Assets</span><strong>${stats.assets}</strong></div>
    <div class="card stat"><span class="muted">Locations</span><strong>${stats.locations}</strong></div>
    <div class="card stat"><span class="muted">Under repair</span><strong>${stats.under_repair}</strong></div>
    <div class="card stat"><span class="muted">Disposed</span><strong>${stats.disposed}</strong></div>
  `;
}

function assetsPage() {
  setTimeout(loadAssets, 0);
  return `
    <section class="page">
      <div class="topbar">
        <div>
          <h1>Assets</h1>
          <p class="muted">Search, filter, export, and open asset records.</p>
        </div>
        <div class="toolbar">
          <button onclick="window.location.href='/api/assets/export'">Export CSV</button>
          <button class="primary" data-nav="/assets/new">New asset</button>
        </div>
      </div>
      <div class="card grid cols-4">
        <input id="search" placeholder="Search ID, name, serial">
        <select id="filterLocation"><option value="">All locations</option>${optionList(state.bootstrap.locations)}</select>
        <select id="filterCategory"><option value="">All categories</option>${optionList(state.bootstrap.categories)}</select>
        <select id="filterStatus"><option value="">All statuses</option>${optionList(state.bootstrap.statuses)}</select>
      </div>
      <div id="assetsTable" class="table-wrap"></div>
    </section>
  `;
}

function renderAssetsTable() {
  ["search", "filterLocation", "filterCategory", "filterStatus"].forEach((id) => {
    const el = $(`#${id}`);
    if (el && !el.dataset.bound) {
      el.dataset.bound = "1";
      el.addEventListener("input", loadAssets);
    }
  });
  $("#assetsTable").innerHTML = `
    <table>
      <thead><tr><th>Picture</th><th>Asset ID</th><th>Name</th><th>Location</th><th>Category</th><th>Status</th><th>Serial</th><th></th></tr></thead>
      <tbody>
        ${state.assets.map((asset) => `
          <tr>
            <td>${assetPhoto(asset)}</td>
            <td><strong>${esc(asset.asset_id)}</strong></td>
            <td>${esc(asset.name)}</td>
            <td>${esc(asset.location)}</td>
            <td>${esc(asset.category)}</td>
            <td><span class="badge ${statusClass(asset.status)}">${esc(asset.status)}</span></td>
            <td>${esc(asset.serial_number)}</td>
            <td><button data-open-asset="${asset.id}">Open</button></td>
          </tr>
        `).join("") || `<tr><td colspan="8">No assets found.</td></tr>`}
      </tbody>
    </table>
  `;
  document.querySelectorAll("[data-open-asset]").forEach((button) => {
    button.addEventListener("click", () => navigate(`/assets/${button.dataset.openAsset}`));
  });
}

function assetPhoto(asset, size = "thumb") {
  if (asset.photo_url) {
    return `<img class="asset-photo ${size}" src="${esc(asset.photo_url)}" alt="${esc(asset.asset_id)} picture">`;
  }
  return `<div class="asset-photo placeholder ${size}" aria-label="No asset picture">No photo</div>`;
}

function assetFormPage(asset = null, autoBind = true) {
  const a = asset || {};
  if (autoBind) setTimeout(bindAssetForm, 0);
  return `
    <section class="page">
      <div class="topbar">
        <div>
          <h1>${asset ? "Edit Asset" : "New Asset"}</h1>
          <p class="muted">Manual asset ID is required and must be unique.</p>
        </div>
      </div>
      <form class="card form" id="assetForm">
        <div class="grid cols-3">
          <label>Asset ID * <input name="asset_id" value="${esc(a.asset_id)}" required></label>
          <label>Name * <input name="name" value="${esc(a.name)}" required></label>
          <label>Location * <select name="location" required>${optionList(state.bootstrap.locations, a.location)}</select></label>
          <label>Category * <select name="category" required>${optionList(state.bootstrap.categories, a.category)}</select></label>
          <label>Status * <select name="status" required>${optionList(state.bootstrap.statuses, a.status || "Active")}</select></label>
          <label>Criticality <select name="criticality"><option value=""></option>${optionList(state.bootstrap.criticalities, a.criticality)}</select></label>
          <label>Make <input name="make" value="${esc(a.make)}"></label>
          <label>Model <input name="model" value="${esc(a.model)}"></label>
          <label>Serial number <input name="serial_number" value="${esc(a.serial_number)}"></label>
          <label>Supplier <input name="supplier" value="${esc(a.supplier)}"></label>
          <label>Purchase date <input type="date" name="purchase_date" value="${esc(a.purchase_date)}"></label>
          <label>Install date <input type="date" name="install_date" value="${esc(a.install_date)}"></label>
          <label>Warranty expiry <input type="date" name="warranty_expiry" value="${esc(a.warranty_expiry)}"></label>
        </div>
        <label>Description <textarea name="description">${esc(a.description)}</textarea></label>
        <label>Notes <textarea name="notes">${esc(a.notes)}</textarea></label>
        <div id="assetError"></div>
        <div class="form-actions">
          <button type="button" data-nav="/assets">Cancel</button>
          <button class="primary" type="submit">Save asset</button>
        </div>
      </form>
    </section>
  `;
}

function bindAssetForm(assetId = null) {
  $("#assetForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(event.currentTarget));
    try {
      const result = await api(assetId ? `/api/assets/${assetId}` : "/api/assets", {
        method: assetId ? "PUT" : "POST",
        body: JSON.stringify(payload),
      });
      await loadBootstrap();
      navigate(`/assets/${result.id}`);
    } catch (err) {
      $("#assetError").innerHTML = `<div class="error">${esc(err.message)}</div>`;
    }
  });
}

function assetDetailPage(id) {
  setTimeout(() => loadAssetDetail(id), 0);
  return `<section class="page" id="assetDetail"><div class="card">Loading asset...</div></section>`;
}

async function loadAssetDetail(id) {
  const asset = await api(`/api/assets/${id}`);
  $("#assetDetail").innerHTML = `
    <div class="topbar">
      <div>
        <h1>${esc(asset.asset_id)} - ${esc(asset.name)}</h1>
        <p class="muted">${esc(asset.location)} - ${esc(asset.category)} - <span class="badge ${statusClass(asset.status)}">${esc(asset.status)}</span></p>
      </div>
      <div class="toolbar">
        <button id="editAsset">Edit</button>
        <button class="danger" id="archiveAsset">Archive</button>
      </div>
    </div>
    <div class="grid cols-2">
      <div class="card">
        <h2>Asset Picture</h2>
        <div class="asset-picture-panel">
          ${assetPhoto(asset, "large")}
          <div class="grid">
            <p class="muted">This picture is shown in the asset list.</p>
            <label>Upload asset picture <input id="assetPhoto" type="file" accept="image/*"></label>
            <button class="primary" id="uploadAssetPhoto">Save picture</button>
          </div>
        </div>
      </div>
      <div class="card">
        <h2>Details</h2>
        <p><strong>Criticality:</strong> ${esc(asset.criticality || "Not set")}</p>
        <p><strong>Make / Model:</strong> ${esc(asset.make)} ${esc(asset.model)}</p>
        <p><strong>Serial:</strong> ${esc(asset.serial_number)}</p>
        <p><strong>Supplier:</strong> ${esc(asset.supplier)}</p>
        <p><strong>Purchase:</strong> ${esc(asset.purchase_date)} <strong>Install:</strong> ${esc(asset.install_date)}</p>
        <p><strong>Warranty:</strong> ${esc(asset.warranty_expiry)}</p>
        <p>${esc(asset.description)}</p>
      </div>
      <div class="card">
        <h2>Documents</h2>
        <div class="attachments">
          ${asset.attachments.map((file) => `
            <div class="attachment-row">
              <a href="/uploads/${encodeURIComponent(file.stored_name)}" target="_blank">${esc(file.original_name)}</a>
              <button class="danger" data-delete-file="${file.id}">Delete</button>
            </div>
          `).join("") || `<p class="muted">No attachments yet.</p>`}
        </div>
        <label>Upload manual or document <input id="attachment" type="file"></label>
        <button class="primary" id="uploadAttachment">Upload document</button>
      </div>
    </div>
    <div class="card">
      <h2>Notes</h2>
      <p>${esc(asset.notes || "No notes recorded.")}</p>
    </div>
  `;
  $("#editAsset").addEventListener("click", () => {
    document.querySelector(".main").innerHTML = assetFormPage(asset, false);
    bindAssetForm(id);
  });
  $("#archiveAsset").addEventListener("click", async () => {
    if (!confirm("Archive this asset?")) return;
    await api(`/api/assets/${id}`, { method: "DELETE" });
    navigate("/assets");
  });
  $("#uploadAttachment").addEventListener("click", async () => uploadAttachment(id));
  $("#uploadAssetPhoto").addEventListener("click", async () => uploadAssetPhoto(id));
  document.querySelectorAll("[data-delete-file]").forEach((button) => {
    button.addEventListener("click", async () => {
      await api(`/api/assets/${id}/attachments/${button.dataset.deleteFile}`, { method: "DELETE" });
      loadAssetDetail(id);
    });
  });
}

async function uploadAssetPhoto(assetId) {
  const file = $("#assetPhoto").files[0];
  if (!file) return;
  const data = await fileToBase64(file);
  await api(`/api/assets/${assetId}/photo`, {
    method: "POST",
    body: JSON.stringify({ name: file.name, content_type: file.type, data }),
  });
  loadAssetDetail(assetId);
}

async function uploadAttachment(assetId) {
  const file = $("#attachment").files[0];
  if (!file) return;
  const data = await fileToBase64(file);
  await api(`/api/assets/${assetId}/attachments`, {
    method: "POST",
    body: JSON.stringify({ name: file.name, content_type: file.type, data }),
  });
  loadAssetDetail(assetId);
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1]);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function lookupPage(type, title) {
  const items = state.bootstrap[type] || [];
  setTimeout(() => bindLookup(type), 0);
  return `
    <section class="page">
      <div>
        <h1>${title}</h1>
        <p class="muted">Admin-managed lookup list.</p>
      </div>
      <div class="card">
        <form class="toolbar" id="lookupForm">
          <input name="name" placeholder="Add ${title.toLowerCase().slice(0, -1)}" required>
          <button class="primary">Add</button>
        </form>
        <div>
          ${items.map((item) => `
            <div class="lookup-row">
              <strong>${esc(item.name)}</strong>
              <button class="danger" data-delete-lookup="${item.id}">Archive</button>
            </div>
          `).join("")}
        </div>
      </div>
    </section>
  `;
}

function bindLookup(type) {
  $("#lookupForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(event.currentTarget));
    await api(`/api/${type}`, { method: "POST", body: JSON.stringify(payload) });
    await loadBootstrap();
    render();
  });
  document.querySelectorAll("[data-delete-lookup]").forEach((button) => {
    button.addEventListener("click", async () => {
      await api(`/api/${type}/${button.dataset.deleteLookup}`, { method: "DELETE" });
      await loadBootstrap();
      render();
    });
  });
}

function importPage() {
  setTimeout(bindImport, 0);
  return `
    <section class="page">
      <div>
        <h1>Asset Import</h1>
        <p class="muted">Upload CSV or XLSX, preview errors, then commit valid rows.</p>
      </div>
      <div class="card grid">
        <label>Import file <input id="importFile" type="file" accept=".csv,.xlsx"></label>
        <div class="toolbar">
          <button class="primary" id="previewImport">Preview import</button>
          <button id="commitImport" disabled>Commit valid rows</button>
        </div>
        <div id="importResult"></div>
      </div>
    </section>
  `;
}

function bindImport() {
  $("#previewImport").addEventListener("click", async () => {
    const file = $("#importFile").files[0];
    if (!file) return;
    const data = await fileToBase64(file);
    state.importPreview = await api("/api/imports/assets/preview", {
      method: "POST",
      body: JSON.stringify({ name: file.name, data }),
    });
    renderImportResult();
  });
  $("#commitImport").addEventListener("click", async () => {
    const result = await api("/api/imports/assets/commit", {
      method: "POST",
      body: JSON.stringify({ rows: state.importPreview.valid }),
    });
    state.importPreview = null;
    $("#importResult").innerHTML = `<div class="card">Created ${result.created} assets.</div>`;
    $("#commitImport").disabled = true;
  });
}

function renderImportResult() {
  const preview = state.importPreview;
  $("#commitImport").disabled = !preview.valid.length || preview.invalid.length;
  $("#importResult").innerHTML = `
    <div class="grid cols-2">
      <div>
        <h2>Valid rows: ${preview.valid.length}</h2>
        <div class="table-wrap">
          <table><thead><tr><th>Row</th><th>Asset ID</th><th>Name</th><th>Location</th></tr></thead>
          <tbody>${preview.valid.map((row) => `<tr><td>${row.row}</td><td>${esc(row.asset_id)}</td><td>${esc(row.name)}</td><td>${esc(row.location)}</td></tr>`).join("")}</tbody></table>
        </div>
      </div>
      <div>
        <h2>Invalid rows: ${preview.invalid.length}</h2>
        <div class="table-wrap">
          <table><thead><tr><th>Row</th><th>Asset ID</th><th>Errors</th></tr></thead>
          <tbody>${preview.invalid.map((row) => `<tr><td>${row.row}</td><td>${esc(row.asset_id)}</td><td>${esc(row.errors.join(", "))}</td></tr>`).join("")}</tbody></table>
        </div>
      </div>
    </div>
  `;
}

init();
