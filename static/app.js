/* ===========================================================================
   rtl-admin-starter — front end (no build step, no framework).

   The table is the interesting part. Server-side search and pagination mean the
   browser never holds more than one page of rows, and every cell carries a
   data-label so the same markup can render as cards on a phone through CSS
   alone — no second mobile template to keep in sync.
   =========================================================================== */
(function () {
  "use strict";

  var TOKEN_KEY = "rtl-admin-token";
  var PER_PAGE = 6;
  var state = { page: 1, q: "", pages: 1, total: 0 };

  /* Escaping is the default, not an opt-in: every value below goes through
     esc() before it reaches innerHTML. A category typed as <script> must show
     up as text, not run. */
  function esc(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function token(value) {
    if (value === undefined) { try { return localStorage.getItem(TOKEN_KEY) || ""; } catch (e) { return ""; } }
    try { value ? localStorage.setItem(TOKEN_KEY, value) : localStorage.removeItem(TOKEN_KEY); } catch (e) { /* private mode */ }
    return value;
  }

  function api(path, options) {
    options = options || {};
    options.headers = Object.assign(
      { "Content-Type": "application/json" },
      options.headers || {},
      token() ? { Authorization: "Bearer " + token() } : {}
    );
    return fetch(path, options).then(function (response) {
      if (response.status === 401) { showLogin(); throw new Error("unauthorized"); }
      if (!response.ok) { throw new Error("HTTP " + response.status); }
      return response.status === 204 ? null : response.json();
    });
  }

  var STATUS = {
    active: { label: "متاح", cls: "ok" },
    low: { label: "أوشك على النفاد", cls: "low" },
    out: { label: "منتهي", cls: "out" }
  };

  function render(page) {
    var body = document.getElementById("rows");
    if (!page.rows.length) {
      body.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--muted)">' +
        "مفيش نتائج للبحث ده</td></tr>";
    } else {
      body.innerHTML = page.rows.map(function (row) {
        var status = STATUS[row.status] || { label: row.status, cls: "" };
        return "<tr>" +
          '<td data-label="الصنف">' + esc(row.name) + "</td>" +
          '<td data-label="التصنيف">' + esc(row.category || "—") + "</td>" +
          '<td data-label="الكمية" class="num">' + esc(row.quantity) + "</td>" +
          '<td data-label="الحالة"><span class="tag ' + status.cls + '">' +
            esc(status.label) + "</span></td>" +
        "</tr>";
      }).join("");
    }
    state.page = page.page;
    state.pages = page.pages;
    state.total = page.total;
    document.getElementById("count").textContent = "إجمالي " + page.total + " صنف";
    document.getElementById("at").textContent = "صفحة " + page.page + " من " + page.pages;
    document.getElementById("prev").disabled = page.page <= 1;
    document.getElementById("next").disabled = page.page >= page.pages;
  }

  function load() {
    return api("/api/items?q=" + encodeURIComponent(state.q) + "&page=" + state.page + "&per_page=" + PER_PAGE)
      .then(render).catch(function () { /* showLogin already handled 401 */ });
  }

  function showLogin() {
    token("");
    document.getElementById("appView").hidden = true;
    document.getElementById("loginView").hidden = false;
  }

  function showApp() {
    document.getElementById("loginView").hidden = true;
    document.getElementById("appView").hidden = false;
    load();
  }

  /* --- events ------------------------------------------------------------ */
  document.getElementById("loginForm").addEventListener("submit", function (event) {
    event.preventDefault();
    var error = document.getElementById("loginError");
    error.textContent = "";
    fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: document.getElementById("username").value,
        password: document.getElementById("password").value
      })
    }).then(function (response) {
      if (!response.ok) { throw new Error("bad credentials"); }
      return response.json();
    }).then(function (data) {
      token(data.token);
      showApp();
    }).catch(function () {
      error.textContent = "اسم المستخدم أو كلمة السر غير صحيحة";
    });
  });

  var timer = null;
  document.getElementById("search").addEventListener("input", function (event) {
    var value = event.target.value;
    clearTimeout(timer);
    // Debounced: typing five letters should cost one query, not five.
    timer = setTimeout(function () { state.q = value; state.page = 1; load(); }, 180);
  });

  document.getElementById("prev").addEventListener("click", function () {
    if (state.page > 1) { state.page--; load(); }
  });
  document.getElementById("next").addEventListener("click", function () {
    if (state.page < state.pages) { state.page++; load(); }
  });
  document.getElementById("logoutBtn").addEventListener("click", showLogin);
  document.getElementById("contrastBtn").addEventListener("click", function () {
    var root = document.documentElement;
    root.setAttribute("data-contrast", root.getAttribute("data-contrast") === "sun" ? "" : "sun");
  });

  /* A stored token is only trusted after the server confirms it. */
  if (token()) {
    api("/api/auth/me").then(showApp).catch(showLogin);
  } else {
    showLogin();
  }
})();
