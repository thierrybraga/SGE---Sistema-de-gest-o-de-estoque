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

  // Global Alerts Check (e.g. Low Stock Badge in Sidebar)
  if (user.role === 'admin' || user.role === 'manager') {
    checkSidebarAlerts();
  }

  // Prompt user to change initial credentials
  if (user.must_change_password) {
    setTimeout(() => openChangeCredentialsModal(), 800);
  }
}

// ── Change Credentials Modal (first-login) ───────────────────────────────────
function openChangeCredentialsModal() {
  // Inject modal if not yet in DOM
  if (!document.getElementById("modal-change-credentials")) {
    const ROLE_COLORS = { admin: "#C00000", manager: "#375623", operator: "#1F3864", buyer: "#7030A0" };
    const user = getUser();
    const roleLabel = { admin: "Administrador", manager: "Gerente", operator: "Operador", buyer: "Compras" }[user?.role] || user?.role;
    const roleColor = ROLE_COLORS[user?.role] || "#333";

    const html = `
    <div id="modal-change-credentials" style="
      position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,0.7);
      display:flex;align-items:center;justify-content:center;padding:16px">
      <div style="background:#fff;border-radius:12px;width:100%;max-width:480px;box-shadow:0 20px 60px rgba(0,0,0,.4);overflow:hidden">
        <!-- Header -->
        <div style="background:#1F3864;padding:20px 24px 16px">
          <div style="display:flex;align-items:center;gap:12px">
            <div style="width:44px;height:44px;border-radius:50%;background:#2E74B5;display:flex;align-items:center;justify-content:center;font-size:20px">🔐</div>
            <div>
              <div style="color:#fff;font-weight:700;font-size:16px">Bem-vindo ao StockOS — Vitória Luz</div>
              <div style="color:#9DC3E6;font-size:12px;margin-top:2px">Esta é sua primeira entrada no sistema</div>
            </div>
          </div>
        </div>
        <!-- User badge -->
        <div style="padding:16px 24px 0">
          <div style="background:#F5F7FA;border-radius:8px;padding:12px 14px;display:flex;align-items:center;gap:10px">
            <div style="width:36px;height:36px;border-radius:50%;background:#1F3864;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:13px" id="cred-avatar"></div>
            <div>
              <div style="font-weight:600;font-size:14px" id="cred-name"></div>
              <div style="font-size:11px;font-weight:700;letter-spacing:.5px" style="color:${roleColor}" id="cred-role-badge"></div>
            </div>
          </div>
          <div style="margin-top:12px;background:#FFF3CD;border:1px solid #FFEAA0;border-radius:8px;padding:10px 14px;font-size:13px;color:#7B5E00">
            <strong>⚠️ Por segurança, altere seu e-mail e senha de acesso.</strong><br>
            <span style="font-size:12px">As credenciais iniciais são compartilhadas. Personalize agora para proteger sua conta.</span>
          </div>
        </div>
        <!-- Form -->
        <div style="padding:16px 24px">
          <div style="margin-bottom:12px">
            <label style="font-size:12px;font-weight:600;color:#444;display:block;margin-bottom:4px">Senha atual (fornecida pelo administrador)</label>
            <input id="cred-current-pwd" type="password" placeholder="Senha atual"
              style="width:100%;padding:9px 12px;border:1px solid #D0D5DD;border-radius:6px;font-size:14px;box-sizing:border-box"/>
          </div>
          <div style="margin-bottom:12px">
            <label style="font-size:12px;font-weight:600;color:#444;display:block;margin-bottom:4px">Novo e-mail</label>
            <input id="cred-new-email" type="email" placeholder="seu@email.com"
              style="width:100%;padding:9px 12px;border:1px solid #D0D5DD;border-radius:6px;font-size:14px;box-sizing:border-box"/>
          </div>
          <div style="margin-bottom:12px">
            <label style="font-size:12px;font-weight:600;color:#444;display:block;margin-bottom:4px">Nova senha</label>
            <input id="cred-new-pwd" type="password" placeholder="Mín. 8 caracteres, 1 maiúscula, 1 número"
              style="width:100%;padding:9px 12px;border:1px solid #D0D5DD;border-radius:6px;font-size:14px;box-sizing:border-box"/>
          </div>
          <div style="margin-bottom:4px">
            <label style="font-size:12px;font-weight:600;color:#444;display:block;margin-bottom:4px">Confirmar nova senha</label>
            <input id="cred-confirm-pwd" type="password" placeholder="Repita a nova senha"
              style="width:100%;padding:9px 12px;border:1px solid #D0D5DD;border-radius:6px;font-size:14px;box-sizing:border-box"/>
          </div>
          <div id="cred-error" style="display:none;margin-top:10px;padding:8px 12px;background:#FDECEA;border:1px solid #F5C6CB;border-radius:6px;color:#721C24;font-size:13px"></div>
        </div>
        <!-- Footer -->
        <div style="padding:0 24px 20px;display:flex;gap:10px;justify-content:flex-end">
          <button onclick="dismissChangeCredentials()" style="padding:9px 18px;border:1px solid #D0D5DD;background:#fff;border-radius:6px;font-size:14px;cursor:pointer;color:#555">
            Lembrar depois
          </button>
          <button onclick="saveNewCredentials()" style="padding:9px 20px;background:#1F3864;color:#fff;border:none;border-radius:6px;font-size:14px;font-weight:600;cursor:pointer">
            <span id="cred-save-text">Salvar e continuar</span>
          </button>
        </div>
      </div>
    </div>`;
    document.body.insertAdjacentHTML("beforeend", html);

    const user2 = getUser();
    const el = document.getElementById("cred-avatar");
    if (el) el.textContent = getInitials(user2?.name || "");
    const nameEl = document.getElementById("cred-name");
    if (nameEl) nameEl.textContent = user2?.name || "";
    const roleEl = document.getElementById("cred-role-badge");
    if (roleEl) {
      roleEl.textContent = roleLabel;
      roleEl.style.color = roleColor;
    }
    // Pre-fill email with current
    const emailEl = document.getElementById("cred-new-email");
    if (emailEl) emailEl.value = user2?.email || "";
  }
  document.getElementById("modal-change-credentials").style.display = "flex";
}

function dismissChangeCredentials() {
  const el = document.getElementById("modal-change-credentials");
  if (el) el.style.display = "none";
}

async function saveNewCredentials() {
  const currentPwd = document.getElementById("cred-current-pwd")?.value || "";
  const newEmail   = document.getElementById("cred-new-email")?.value?.trim() || "";
  const newPwd     = document.getElementById("cred-new-pwd")?.value || "";
  const confirmPwd = document.getElementById("cred-confirm-pwd")?.value || "";
  const errDiv     = document.getElementById("cred-error");
  const saveBtn    = document.getElementById("cred-save-text");

  const showErr = (msg) => { errDiv.textContent = msg; errDiv.style.display = "block"; };
  errDiv.style.display = "none";

  if (!currentPwd) { showErr("Informe a senha atual."); return; }
  if (!newEmail)   { showErr("Informe o novo e-mail."); return; }
  if (!newPwd)     { showErr("Informe a nova senha."); return; }
  if (newPwd !== confirmPwd) { showErr("As senhas não conferem."); return; }
  if (newPwd.length < 8) { showErr("A senha deve ter ao menos 8 caracteres."); return; }
  if (!/[A-Z]/.test(newPwd)) { showErr("A senha deve conter ao menos uma letra maiúscula."); return; }
  if (!/[a-z]/.test(newPwd)) { showErr("A senha deve conter ao menos uma letra minúscula."); return; }
  if (!/[0-9]/.test(newPwd)) { showErr("A senha deve conter ao menos um número."); return; }

  saveBtn.textContent = "Salvando...";
  try {
    const token = localStorage.getItem("token");
    const resp = await fetch("/api/auth/me", {
      method: "PUT",
      headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` },
      body: JSON.stringify({ email: newEmail, current_password: currentPwd, new_password: newPwd })
    });
    const data = await resp.json();
    if (!resp.ok) { showErr(data.error || "Erro ao salvar."); saveBtn.textContent = "Salvar e continuar"; return; }
    // Update localStorage
    const user = getUser() || {};
    user.email = data.email;
    user.must_change_password = false;
    localStorage.setItem("user", JSON.stringify(user));
    dismissChangeCredentials();
    if (typeof showToast === "function") showToast("Credenciais atualizadas com sucesso!", "success");
  } catch(e) {
    showErr("Erro de conexão. Tente novamente.");
    saveBtn.textContent = "Salvar e continuar";
  }
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
  document.querySelectorAll(".sidebar .nav-item[data-page]").forEach((el) => {
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
  if (!document.querySelector(".sidebar")) return;
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
