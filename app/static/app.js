/* DealWise AI — shared front-end behaviors: theme, wishlist, share, alert
   presets, score-badge tinting, and form loading states. No build step. */
(function () {
  // ---- Dark mode -----------------------------------------------------------
  function currentTheme() {
    return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
  }
  function applyTheme(t) {
    if (t === "dark") document.documentElement.setAttribute("data-theme", "dark");
    else document.documentElement.removeAttribute("data-theme");
  }
  function initTheme() {
    var btn = document.getElementById("theme-toggle");
    if (!btn) return;
    btn.addEventListener("click", function () {
      var next = currentTheme() === "dark" ? "light" : "dark";
      applyTheme(next);
      try { localStorage.setItem("dw-theme", next); } catch (e) {}
    });
  }

  // ---- Score / gauge tinting ----------------------------------------------
  function tint() {
    document.querySelectorAll(".score-badge[data-score]").forEach(function (el) {
      var s = parseInt(el.dataset.score, 10);
      if (isNaN(s)) return;
      var hue = Math.round((s / 100) * 130);
      el.style.background = "hsl(" + hue + ",70%,94%)";
      el.style.color = "hsl(" + hue + ",70%,30%)";
    });
    document.querySelectorAll(".gauge[data-score]").forEach(function (el) {
      var s = parseInt(el.dataset.score, 10);
      if (isNaN(s)) return;
      el.style.color = "hsl(" + Math.round((s / 100) * 130) + ",70%,38%)";
    });
  }

  // ---- Wishlist (localStorage, simple collections) -------------------------
  var WKEY = "dw-wishlist";
  function read() { try { return JSON.parse(localStorage.getItem(WKEY)) || {}; } catch (e) { return {}; } }
  function write(d) { try { localStorage.setItem(WKEY, JSON.stringify(d)); } catch (e) {} }
  function savedSet() {
    var d = read(), s = {};
    Object.keys(d).forEach(function (c) { (d[c] || []).forEach(function (id) { s[id] = true; }); });
    return s;
  }
  function isSaved(id) { return !!savedSet()[String(id)]; }
  function toggleSave(id) {
    id = String(id);
    var d = read();
    if (isSaved(id)) {
      Object.keys(d).forEach(function (c) {
        var j = d[c].indexOf(id); if (j >= 0) d[c].splice(j, 1);
      });
      write(d); return false;
    }
    if (!d.Saved) d.Saved = [];
    d.Saved.push(id); write(d); return true;
  }
  function wireHearts(root) {
    (root || document).querySelectorAll("[data-wishlist]").forEach(function (btn) {
      var id = btn.getAttribute("data-wishlist");
      btn.classList.toggle("on", isSaved(id));
      btn.setAttribute("aria-pressed", isSaved(id));
      if (btn.dataset.bound) return;
      btn.dataset.bound = "1";
      btn.addEventListener("click", function (e) {
        e.preventDefault(); e.stopPropagation();
        var on = toggleSave(id);
        btn.classList.toggle("on", on);
        btn.setAttribute("aria-pressed", on);
        if (btn.dataset.removeOnUnsave === "1" && !on) {
          var card = btn.closest("[data-card]");
          if (card) card.remove();
        }
      });
    });
  }

  // Public API for the wishlist page.
  window.DealWise = {
    savedIds: function () { return Object.keys(savedSet()); },
    isSaved: isSaved,
    toggleSave: toggleSave,
    wireHearts: wireHearts,
  };

  // ---- Share ---------------------------------------------------------------
  function wireShare() {
    document.querySelectorAll("[data-share]").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        var url = btn.getAttribute("data-share-url") || location.href;
        var title = btn.getAttribute("data-share-title") || document.title;
        if (navigator.share) {
          navigator.share({ title: title, url: url }).catch(function () {});
        } else if (navigator.clipboard) {
          navigator.clipboard.writeText(url).then(function () {
            var orig = btn.textContent;
            btn.textContent = "Link copied!";
            setTimeout(function () { btn.textContent = orig; }, 1500);
          }, function () { window.prompt("Copy link:", url); });
        } else {
          window.prompt("Copy link:", url);
        }
      });
    });
  }

  // ---- Alert target presets ------------------------------------------------
  function wirePresets() {
    document.querySelectorAll("[data-set-target]").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        var sel = btn.getAttribute("data-target-input") || "#target-price";
        var input = document.querySelector(sel);
        if (input) { input.value = btn.getAttribute("data-set-target"); }
        document.querySelectorAll("[data-set-target]").forEach(function (b) { b.classList.remove("on"); });
        btn.classList.add("on");
      });
    });
  }

  // ---- Form submit loading state ------------------------------------------
  function wireSubmitStates() {
    document.querySelectorAll("form[data-loading]").forEach(function (f) {
      f.addEventListener("submit", function () {
        var b = f.querySelector("button[type=submit], button:not([type])");
        if (b) { b.disabled = true; b.textContent = "…"; }
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initTheme(); tint(); wireHearts(); wireShare(); wirePresets(); wireSubmitStates();
  });
})();
