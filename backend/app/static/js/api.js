// ===== API Client =====
const API_BASE = "/api";

const api = {
  token: () => localStorage.getItem("token"),

  headers() {
    const h = { "Content-Type": "application/json" };
    const t = this.token();
    if (t) h["Authorization"] = `Bearer ${t}`;
    return h;
  },

  async request(method, path, body = null) {
    const opts = { method, headers: this.headers() };
    if (body) opts.body = JSON.stringify(body);

    let res;
    try {
      res = await fetch(API_BASE + path, opts);
    } catch (err) {
      throw new Error("Network error: " + err.message);
    }

    const data = await res.json().catch(() => ({}));

    if (res.status === 401) {
      localStorage.removeItem("token");
      localStorage.removeItem("user");
      const currentPath = window.location.pathname || "";
      const onLogin = currentPath === "/" || currentPath === "/login";
      if (!onLogin) {
        window.location.href = "/login";
      }
      throw new Error(data.error || "Sessão inválida ou expirada");
    }

    if (!res.ok) {
      throw new Error(data.error || `Error ${res.status}`);
    }
    return data;
  },

  get: (path) => api.request("GET", path),
  post: (path, body) => api.request("POST", path, body),
  put: (path, body) => api.request("PUT", path, body),
  delete: (path) => api.request("DELETE", path),

  async uploadFile(path, file) {
    const formData = new FormData();
    formData.append("file", file);
    const token = this.token();
    const headers = {};
    if (token) headers.Authorization = `Bearer ${token}`;
    const opts = {
      method: "POST",
      headers,
      body: formData,
    };
    const res = await fetch(API_BASE + path, opts);
    const data = await res.json().catch(() => ({}));
    if (res.status === 401) {
      localStorage.removeItem("token");
      localStorage.removeItem("user");
      const currentPath = window.location.pathname || "";
      const onLogin = currentPath === "/" || currentPath === "/login";
      if (!onLogin) {
        window.location.href = "/login";
      }
      throw new Error(data.error || "Sessão inválida ou expirada");
    }
    if (!res.ok) throw new Error(data.error || `Error ${res.status}`);
    return data;
  },
};

// ===== Toast Notifications =====
function showToast(msg, type = "success", duration = 3500) {
  let container = document.getElementById("toast-container");
  if (!container) {
    container = document.createElement("div");
    container.id = "toast-container";
    document.body.appendChild(container);
  }

  const icons = {
    success: "fa-check-circle",
    error: "fa-times-circle",
    warning: "fa-exclamation-triangle",
    info: "fa-info-circle"
  };

  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.innerHTML = `
    <div class="toast-body">
      <i class="fas ${icons[type] || icons.success} toast-icon"></i>
      <span class="toast-msg">${msg}</span>
    </div>
    <button class="toast-close" aria-label="Fechar"><i class="fas fa-times"></i></button>
    <div class="toast-progress" style="animation-duration: ${duration}ms"></div>
  `;

  const dismiss = () => {
    toast.style.animation = "toastOut 0.25s ease forwards";
    toast.addEventListener("animationend", () => toast.remove(), { once: true });
  };

  toast.querySelector(".toast-close").addEventListener("click", (e) => {
    e.stopPropagation();
    dismiss();
  });
  toast.addEventListener("click", dismiss);

  container.appendChild(toast);
  setTimeout(dismiss, duration);
}

// ===== Modal helpers =====
function openModal(id) {
  const el = document.getElementById(id);
  if (el) {
    el.classList.add("open");
    // Focus first focusable element inside modal
    const focusable = el.querySelector('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
    if (focusable) setTimeout(() => focusable.focus(), 50);
  }
}

function closeModal(id) {
  document.getElementById(id)?.classList.remove("open");
}

// Close on overlay click
document.addEventListener("click", (e) => {
  if (e.target.classList.contains("modal-overlay")) {
    e.target.classList.remove("open");
  }
});

// ===== Confirm Modal =====
function showConfirm({ title = "Confirmar ação", message = "", confirmText = "Confirmar", cancelText = "Cancelar", type = "danger", icon = null, onConfirm }) {
  // Remove existing confirm modal if any
  const existing = document.getElementById("_global-confirm-modal");
  if (existing) existing.remove();

  const iconMap = { danger: "fa-trash-alt", warning: "fa-exclamation-triangle", info: "fa-question-circle" };
  const chosenIcon = icon || iconMap[type] || iconMap.danger;
  const btnClass = type === "danger" ? "btn-danger" : type === "warning" ? "btn-secondary" : "btn-primary";

  const overlay = document.createElement("div");
  overlay.id = "_global-confirm-modal";
  overlay.className = "modal-overlay open";
  overlay.innerHTML = `
    <div class="modal confirm-modal" role="dialog" aria-modal="true" aria-labelledby="_confirm-title">
      <span class="confirm-icon ${type}" aria-hidden="true"><i class="fas ${chosenIcon}"></i></span>
      <h3 class="confirm-title" id="_confirm-title">${title}</h3>
      <p class="confirm-message">${message}</p>
      <div class="modal-footer">
        <button class="btn btn-secondary" id="_confirm-cancel">${cancelText}</button>
        <button class="btn ${btnClass}" id="_confirm-ok">${confirmText}</button>
      </div>
    </div>
  `;

  document.body.appendChild(overlay);

  const close = () => {
    overlay.style.animation = "none";
    overlay.remove();
  };

  overlay.querySelector("#_confirm-cancel").addEventListener("click", close);
  overlay.querySelector("#_confirm-ok").addEventListener("click", () => {
    close();
    if (onConfirm) onConfirm();
  });
  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });

  // Focus confirm button
  setTimeout(() => overlay.querySelector("#_confirm-ok").focus(), 50);
}

// ===== Skeleton helpers =====
function skeletonRows(cols, rows = 5) {
  const widths = ["70%", "50%", "60%", "40%", "80%", "55%", "45%"];
  let html = "";
  for (let r = 0; r < rows; r++) {
    html += "<tr class='skeleton-tr'>";
    for (let c = 0; c < cols; c++) {
      const w = widths[(r * cols + c) % widths.length];
      html += `<td><span class="skeleton skeleton-cell" style="width:${w}"></span></td>`;
    }
    html += "</tr>";
  }
  return html;
}

// ===== Sortable tables =====
function makeTableSortable(tableId) {
  const table = document.getElementById(tableId);
  if (!table) return;

  const headers = table.querySelectorAll("thead th[data-sort]");
  let currentCol = null;
  let currentDir = "asc";

  headers.forEach((th) => {
    th.classList.add("sortable");
    th.setAttribute("tabindex", "0");
    th.setAttribute("role", "columnheader");
    th.setAttribute("aria-sort", "none");

    const doSort = () => {
      const col = th.dataset.sort;
      if (currentCol === col) {
        currentDir = currentDir === "asc" ? "desc" : "asc";
      } else {
        currentCol = col;
        currentDir = "asc";
      }

      // Update classes
      headers.forEach((h) => {
        h.classList.remove("sort-asc", "sort-desc");
        h.setAttribute("aria-sort", "none");
      });
      th.classList.add(currentDir === "asc" ? "sort-asc" : "sort-desc");
      th.setAttribute("aria-sort", currentDir === "asc" ? "ascending" : "descending");

      // Sort rows
      const tbody = table.querySelector("tbody");
      const rows = Array.from(tbody.querySelectorAll("tr:not(.skeleton-tr)"));
      rows.sort((a, b) => {
        const aVal = a.querySelector(`td[data-col="${col}"]`)?.dataset.val ?? a.cells[th.cellIndex]?.textContent.trim() ?? "";
        const bVal = b.querySelector(`td[data-col="${col}"]`)?.dataset.val ?? b.cells[th.cellIndex]?.textContent.trim() ?? "";
        const aNum = parseFloat(aVal.replace(/[^\d.-]/g, ""));
        const bNum = parseFloat(bVal.replace(/[^\d.-]/g, ""));
        let cmp;
        if (!isNaN(aNum) && !isNaN(bNum)) {
          cmp = aNum - bNum;
        } else {
          cmp = aVal.localeCompare(bVal, "pt-BR", { sensitivity: "base" });
        }
        return currentDir === "asc" ? cmp : -cmp;
      });
      rows.forEach((r) => tbody.appendChild(r));
    };

    th.addEventListener("click", doSort);
    th.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); doSort(); } });
  });
}

// ===== Section error state =====
function sectionError(message, retryFn) {
  return `
    <tr><td colspan="99">
      <div class="section-error">
        <i class="fas fa-exclamation-circle"></i>
        <p>${message || "Erro ao carregar dados."}</p>
        <button class="btn btn-secondary btn-sm" onclick="(${retryFn.toString()})()">
          <i class="fas fa-redo"></i> Tentar novamente
        </button>
      </div>
    </td></tr>
  `;
}

// ===== Format helpers =====
function fmtCurrency(val) {
  return "R$ " + Number(val || 0).toLocaleString("pt-BR", { minimumFractionDigits: 2 });
}

function fmtDate(str) {
  if (!str) return "—";
  return new Date(str).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

function fmtDateShort(str) {
  if (!str) return "—";
  return new Date(str).toLocaleDateString("pt-BR");
}

// ===== Stock badge =====
function stockBadge(product) {
  if (product.stock <= 0) return `<span class="badge badge-danger">Zerado</span>`;
  if (product.is_low_stock) return `<span class="badge badge-warning">Crítico</span>`;
  return `<span class="badge badge-success">OK</span>`;
}

// ===== Movement type badge =====
function movBadge(type) {
  const map = {
    entry: '<span class="badge badge-success">Entrada</span>',
    exit: '<span class="badge badge-danger">Saída</span>',
    adjustment: '<span class="badge badge-info">Ajuste</span>',
  };
  return map[type] || type;
}

// ===== Global Alert Helpers =====
async function checkSidebarAlerts() {
  try {
    const summary = await api.get("/dashboard/summary");
    const badge = document.getElementById("badge-low-stock");
    if (badge) {
      if (summary.low_stock_count > 0) {
        badge.textContent = summary.low_stock_count;
        badge.style.display = "inline-flex";
        badge.title = `${summary.low_stock_count} produtos com estoque baixo`;
      } else {
        badge.style.display = "none";
      }
    }
  } catch(e) {
    console.warn("Erro ao carregar alertas da sidebar:", e);
  }
}

// ===== Notifications Bell =====
function initNotifications() {
  // Only init on authenticated pages with a topbar
  const topbar = document.querySelector(".topbar-actions");
  if (!topbar || !localStorage.getItem("token")) return;

  // Don't double-init
  if (document.getElementById("notif-bell")) return;

  const bellHtml = `
    <div class="notif-wrapper" id="notif-bell">
      <button class="notif-bell-btn" onclick="toggleNotifications()" title="Notificações" aria-label="Notificações">
        <i class="fas fa-bell"></i>
        <span class="notif-badge" id="notif-badge" style="display:none">0</span>
      </button>
      <div class="notif-dropdown" id="notif-dropdown">
        <div class="notif-header">
          <span class="notif-header-title">Notificações</span>
          <span class="notif-header-count" id="notif-header-count"></span>
        </div>
        <div class="notif-body" id="notif-body">
          <div class="notif-loading">Carregando...</div>
        </div>
      </div>
    </div>
  `;
  topbar.insertAdjacentHTML("afterbegin", bellHtml);

  // Close dropdown when clicking outside
  document.addEventListener("click", (e) => {
    const wrapper = document.getElementById("notif-bell");
    if (wrapper && !wrapper.contains(e.target)) {
      document.getElementById("notif-dropdown")?.classList.remove("open");
    }
  });

  // Load notifications
  loadNotifications();
  // Refresh every 60 seconds
  setInterval(loadNotifications, 60000);
}

function toggleNotifications() {
  const dd = document.getElementById("notif-dropdown");
  if (dd) {
    dd.classList.toggle("open");
    if (dd.classList.contains("open")) loadNotifications();
  }
}

async function loadNotifications() {
  try {
    const data = await api.get("/dashboard/notifications");
    const badge = document.getElementById("notif-badge");
    const body = document.getElementById("notif-body");
    const headerCount = document.getElementById("notif-header-count");

    if (badge) {
      if (data.total > 0) {
        badge.textContent = data.total > 99 ? "99+" : data.total;
        badge.style.display = "flex";
      } else {
        badge.style.display = "none";
      }
    }

    if (headerCount) {
      headerCount.textContent = data.total > 0 ? `${data.total} alerta(s)` : "Tudo certo!";
    }

    if (body) {
      if (data.notifications.length === 0) {
        body.innerHTML = `<div class="notif-empty"><i class="fas fa-check-circle"></i><span>Nenhuma notificação</span></div>`;
      } else {
        const iconMap = { low_stock: "fa-box-open", overdue_tool: "fa-clock", pending_quotation: "fa-file-invoice-dollar" };
        const colorMap = { critical: "var(--danger)", warning: "var(--warn)", info: "var(--accent)" };
        body.innerHTML = data.notifications.map(n => `
          <a href="${n.link}" class="notif-item" data-type="${n.type}">
            <div class="notif-icon" style="color:${colorMap[n.severity] || 'var(--text2)'}">
              <i class="fas ${iconMap[n.type] || 'fa-bell'}"></i>
            </div>
            <div class="notif-content">
              <div class="notif-title">${n.title}</div>
              <div class="notif-message">${n.message}</div>
            </div>
          </a>
        `).join("");
      }
    }
  } catch(e) {
    console.warn("Erro ao carregar notificações:", e);
  }
}

// ===== Global Search (Ctrl+K) =====
function initGlobalSearch() {
  if (!localStorage.getItem("token")) return;
  if (document.getElementById("global-search-overlay")) return;

  // Add search trigger to topbar if present
  const topbar = document.querySelector(".topbar-actions");
  if (topbar) {
    const searchBtn = document.createElement("button");
    searchBtn.className = "notif-bell-btn";
    searchBtn.title = "Busca Global (Ctrl+K)";
    searchBtn.setAttribute("aria-label", "Busca Global");
    searchBtn.innerHTML = '<i class="fas fa-search"></i><kbd style="font-size:9px;margin-left:4px;background:var(--bg3);border:1px solid var(--border);border-radius:3px;padding:1px 5px;color:var(--text2);font-family:var(--font-mono)">K</kbd>';
    searchBtn.onclick = openGlobalSearch;
    topbar.insertAdjacentElement("afterbegin", searchBtn);
  }

  const html = `
    <div class="gsearch-overlay" id="global-search-overlay">
      <div class="gsearch-modal">
        <div class="gsearch-input-wrapper">
          <i class="fas fa-search gsearch-icon"></i>
          <input type="text" id="gsearch-input" class="gsearch-input"
                 placeholder="Buscar produtos, fornecedores, NFs, projetos..."
                 autocomplete="off" spellcheck="false" />
          <kbd class="gsearch-kbd">ESC</kbd>
        </div>
        <div class="gsearch-results" id="gsearch-results"></div>
      </div>
    </div>
  `;
  document.body.insertAdjacentHTML("beforeend", html);

  const overlay = document.getElementById("global-search-overlay");
  const input = document.getElementById("gsearch-input");
  const resultsEl = document.getElementById("gsearch-results");
  let debounceTimer = null;
  let selectedIdx = -1;

  // Keyboard shortcut: Ctrl+K or Cmd+K
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "k") {
      e.preventDefault();
      openGlobalSearch();
    }
    if (e.key === "Escape" && overlay.classList.contains("open")) {
      closeGlobalSearch();
    }
  });

  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeGlobalSearch();
  });

  input.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    selectedIdx = -1;
    const q = input.value.trim();
    if (q.length < 2) {
      resultsEl.innerHTML = '<div class="gsearch-hint">Digite pelo menos 2 caracteres...</div>';
      return;
    }
    resultsEl.innerHTML = '<div class="gsearch-hint">Buscando...</div>';
    debounceTimer = setTimeout(() => doGlobalSearch(q), 250);
  });

  input.addEventListener("keydown", (e) => {
    const items = resultsEl.querySelectorAll(".gsearch-item");
    if (!items.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      selectedIdx = Math.min(selectedIdx + 1, items.length - 1);
      updateSelection(items);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      selectedIdx = Math.max(selectedIdx - 1, 0);
      updateSelection(items);
    } else if (e.key === "Enter" && selectedIdx >= 0) {
      e.preventDefault();
      items[selectedIdx].click();
    }
  });

  function updateSelection(items) {
    items.forEach((it, i) => it.classList.toggle("selected", i === selectedIdx));
    if (items[selectedIdx]) items[selectedIdx].scrollIntoView({ block: "nearest" });
  }
}

function openGlobalSearch() {
  const overlay = document.getElementById("global-search-overlay");
  const input = document.getElementById("gsearch-input");
  if (!overlay) return;
  overlay.classList.add("open");
  input.value = "";
  document.getElementById("gsearch-results").innerHTML = '<div class="gsearch-hint">Digite para buscar...</div>';
  setTimeout(() => input.focus(), 50);
}

function closeGlobalSearch() {
  document.getElementById("global-search-overlay")?.classList.remove("open");
}

async function doGlobalSearch(q) {
  const resultsEl = document.getElementById("gsearch-results");
  try {
    const data = await api.get(`/dashboard/search?q=${encodeURIComponent(q)}`);
    if (!data.results.length) {
      resultsEl.innerHTML = '<div class="gsearch-empty"><i class="fas fa-search"></i> Nenhum resultado encontrado</div>';
      return;
    }
    const typeLabels = { product: "Produto", supplier: "Fornecedor", invoice: "Nota Fiscal", project: "Projeto" };
    resultsEl.innerHTML = data.results.map((r, i) => `
      <a href="${r.link}" class="gsearch-item" data-idx="${i}">
        <div class="gsearch-item-icon" style="color:${r.color}"><i class="fas ${r.icon}"></i></div>
        <div class="gsearch-item-content">
          <div class="gsearch-item-title">${r.title}</div>
          <div class="gsearch-item-sub">${r.subtitle}</div>
        </div>
        <span class="gsearch-item-type">${typeLabels[r.type] || r.type}</span>
      </a>
    `).join("");
  } catch(e) {
    resultsEl.innerHTML = `<div class="gsearch-empty">Erro na busca: ${e.message}</div>`;
  }
}

// Auto-init notifications and search when DOM is ready
document.addEventListener("DOMContentLoaded", () => {
  setTimeout(initNotifications, 100);
  setTimeout(initGlobalSearch, 150);
});

// Add CSS for toastOut and notifications
const style = document.createElement("style");
style.textContent = `
@keyframes toastOut { to { opacity: 0; transform: translateX(40px); } }

/* Notifications */
.notif-wrapper { position: relative; margin-right: 12px; }
.notif-bell-btn {
  background: none; border: none; color: var(--text2); font-size: 18px;
  cursor: pointer; padding: 8px; border-radius: 8px; position: relative;
  transition: color 0.2s, background 0.2s;
}
.notif-bell-btn:hover { color: var(--accent); background: var(--bg3); }
.notif-badge {
  position: absolute; top: 2px; right: 2px;
  background: var(--danger); color: white;
  font-size: 10px; font-family: var(--font-mono);
  min-width: 16px; height: 16px; border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  padding: 0 4px; line-height: 1;
}
.notif-dropdown {
  display: none; position: absolute; top: 100%; right: 0;
  width: 360px; max-height: 480px;
  background: var(--card); border: 1px solid var(--border);
  border-radius: var(--radius); box-shadow: var(--shadow);
  z-index: 1000; margin-top: 8px;
  overflow: hidden;
}
.notif-dropdown.open { display: block; }
.notif-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; border-bottom: 1px solid var(--border);
}
.notif-header-title { font-weight: 600; font-size: 14px; color: var(--text); }
.notif-header-count { font-size: 11px; color: var(--text2); font-family: var(--font-mono); }
.notif-body { max-height: 400px; overflow-y: auto; }
.notif-item {
  display: flex; align-items: flex-start; gap: 12px;
  padding: 12px 16px; border-bottom: 1px solid var(--border);
  text-decoration: none; color: var(--text);
  transition: background 0.15s;
}
.notif-item:hover { background: var(--bg3); }
.notif-icon { font-size: 16px; margin-top: 2px; flex-shrink: 0; }
.notif-content { flex: 1; min-width: 0; }
.notif-title { font-size: 12px; font-weight: 600; margin-bottom: 2px; }
.notif-message { font-size: 11px; color: var(--text2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.notif-empty {
  display: flex; flex-direction: column; align-items: center; gap: 8px;
  padding: 32px; color: var(--text2); font-size: 13px;
}
.notif-empty i { font-size: 24px; color: var(--accent3); }
.notif-loading { padding: 24px; text-align: center; color: var(--text2); font-size: 12px; }

@media (max-width: 480px) {
  .notif-dropdown { width: calc(100vw - 32px); right: -8px; }
}

/* Global Search Modal */
.gsearch-overlay {
  display: none; position: fixed; inset: 0;
  background: rgba(0,0,0,0.6); backdrop-filter: blur(4px);
  z-index: 9999; align-items: flex-start; justify-content: center;
  padding-top: 15vh;
}
.gsearch-overlay.open { display: flex; }
.gsearch-modal {
  width: 580px; max-width: calc(100vw - 32px);
  background: var(--card); border: 1px solid var(--border);
  border-radius: 12px; box-shadow: 0 20px 60px rgba(0,0,0,0.5);
  overflow: hidden;
}
.gsearch-input-wrapper {
  display: flex; align-items: center; gap: 12px;
  padding: 16px 20px; border-bottom: 1px solid var(--border);
}
.gsearch-icon { color: var(--text2); font-size: 16px; }
.gsearch-input {
  flex: 1; background: none; border: none; color: var(--text);
  font-size: 16px; font-family: var(--font-head); outline: none;
}
.gsearch-input::placeholder { color: var(--text2); }
.gsearch-kbd {
  background: var(--bg3); color: var(--text2); border: 1px solid var(--border);
  border-radius: 4px; padding: 2px 8px; font-size: 11px; font-family: var(--font-mono);
}
.gsearch-results { max-height: 400px; overflow-y: auto; }
.gsearch-item {
  display: flex; align-items: center; gap: 12px;
  padding: 12px 20px; text-decoration: none; color: var(--text);
  border-bottom: 1px solid var(--border); transition: background 0.1s;
}
.gsearch-item:hover, .gsearch-item.selected { background: var(--bg3); }
.gsearch-item-icon { font-size: 18px; width: 28px; text-align: center; flex-shrink: 0; }
.gsearch-item-content { flex: 1; min-width: 0; }
.gsearch-item-title { font-size: 13px; font-weight: 600; }
.gsearch-item-sub { font-size: 11px; color: var(--text2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.gsearch-item-type {
  font-size: 10px; color: var(--text2); font-family: var(--font-mono);
  background: var(--bg3); border-radius: 4px; padding: 2px 8px; flex-shrink: 0;
}
.gsearch-hint, .gsearch-empty {
  padding: 24px; text-align: center; color: var(--text2); font-size: 13px;
}
.gsearch-empty i { margin-right: 6px; }
`;
document.head.appendChild(style);
