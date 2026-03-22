// ===== Auth Utilities =====

function getUser() {
  try {
    return JSON.parse(localStorage.getItem("user") || "null");
  } catch {
    return null;
  }
}

function requireAuth() {
  const token = localStorage.getItem("token");
  if (!token) {
    window.location.href = "/login";
    return false;
  }
  return true;
}

function logout() {
  fetch("/api/auth/logout", { method: "POST" }).finally(() => {
    localStorage.removeItem("token");
    localStorage.removeItem("user");
    window.location.href = "/login";
  });
}

function initUserInfo() {
  const user = getUser();
  if (!user) return;

  const nameEl = document.getElementById("user-name");
  const roleEl = document.getElementById("user-role");
  const avatarEl = document.getElementById("user-avatar");

  if (nameEl) nameEl.textContent = user.name;
  if (roleEl) roleEl.textContent = roleLabels[user.role] || user.role;
  if (avatarEl) avatarEl.textContent = getInitials(user.name);
}

function getInitials(name) {
  if (!name) return "U";
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const first = parts[0]?.charAt(0) || "";
  const last = parts.length > 1 ? parts[parts.length - 1].charAt(0) : "";
  return (first + last).toUpperCase() || "U";
}

const roleLabels = {
  admin: "Administrador",
  manager: "Gerente",
  operator: "Operador",
  buyer: "Compras",
};

function setActiveNav(page) {
  document.querySelectorAll(".nav-item").forEach((el) => {
    el.classList.remove("active");
    el.removeAttribute("aria-current");
    if (el.dataset.page === page) {
      el.classList.add("active");
      el.setAttribute("aria-current", "page");
    }
  });
}

// ===== Mobile hamburger sidebar =====
function toggleSidebar() {
  const sidebar = document.querySelector(".sidebar");
  const overlay = document.querySelector(".sidebar-overlay");
  if (!sidebar) return;
  sidebar.classList.toggle("open");
  if (overlay) overlay.classList.toggle("open");
}

function initHamburger() {
  // Inject hamburger button and overlay if not present
  if (!document.querySelector(".sidebar-toggle")) {
    const btn = document.createElement("button");
    btn.className = "sidebar-toggle";
    btn.setAttribute("aria-label", "Abrir menu");
    btn.setAttribute("aria-expanded", "false");
    btn.innerHTML = '<i class="fas fa-bars"></i>';
    btn.addEventListener("click", () => {
      toggleSidebar();
      const isOpen = document.querySelector(".sidebar")?.classList.contains("open");
      btn.setAttribute("aria-expanded", isOpen ? "true" : "false");
    });
    document.body.appendChild(btn);
  }

  if (!document.querySelector(".sidebar-overlay")) {
    const overlay = document.createElement("div");
    overlay.className = "sidebar-overlay";
    overlay.addEventListener("click", () => {
      document.querySelector(".sidebar")?.classList.remove("open");
      overlay.classList.remove("open");
      document.querySelector(".sidebar-toggle")?.setAttribute("aria-expanded", "false");
    });
    document.body.appendChild(overlay);
  }
}

// ===== Global Escape key handler =====
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    // Close any open modal overlay
    const openModal = document.querySelector(".modal-overlay.open");
    if (openModal) {
      openModal.classList.remove("open");
      return;
    }
    // Close global confirm modal
    const confirmModal = document.getElementById("_global-confirm-modal");
    if (confirmModal) {
      confirmModal.remove();
      return;
    }
    // Close mobile sidebar
    const sidebar = document.querySelector(".sidebar.open");
    if (sidebar) {
      toggleSidebar();
    }
  }
});

// Auto-redirect on login page if already authenticated
if (window.location.pathname === "/" || window.location.pathname === "/login") {
  const token = localStorage.getItem("token");
  if (token) {
    api.get("/auth/me")
      .then((user) => {
        if (user) localStorage.setItem("user", JSON.stringify(user));
        window.location.href = "/dashboard";
      })
      .catch(() => {
        localStorage.removeItem("token");
        localStorage.removeItem("user");
      });
  }
}

// Init hamburger on DOMContentLoaded (for all authenticated pages)
document.addEventListener("DOMContentLoaded", () => {
  initHamburger();
});
