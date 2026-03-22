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

    if (res.status === 401) {
      localStorage.removeItem("token");
      localStorage.removeItem("user");
      const path = window.location.pathname || "";
      const onLogin = path === "/" || path === "/login";
      if (!onLogin) {
        window.location.href = "/login";
      }
      return;
    }

    const data = await res.json().catch(() => ({}));

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
    const opts = {
      method: "POST",
      headers: { Authorization: `Bearer ${this.token()}` },
      body: formData,
    };
    const res = await fetch(API_BASE + path, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `Error ${res.status}`);
    return data;
  },
};

// ===== Toast Notifications =====
function showToast(msg, type = "success") {
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
    <div class="toast-progress"></div>
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
  setTimeout(dismiss, 3500);
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

// Add CSS for toastOut
const style = document.createElement("style");
style.textContent = `@keyframes toastOut { to { opacity: 0; transform: translateX(40px); } }`;
document.head.appendChild(style);
