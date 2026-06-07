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

  // ---- Voice search (Web Speech API) --------------------------------------
  function wireVoice() {
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    document.querySelectorAll("[data-voice]").forEach(function (btn) {
      if (!SR) { btn.style.display = "none"; return; }  // unsupported browser
      var input = document.querySelector(btn.getAttribute("data-voice"));
      if (!input) return;
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        var rec = new SR();
        rec.lang = "en-US"; rec.interimResults = false; rec.maxAlternatives = 1;
        var prev = input.placeholder;
        btn.classList.add("listening"); input.placeholder = "Listening…";
        rec.onresult = function (ev) {
          input.value = ev.results[0][0].transcript;
          var form = input.closest("form");
          if (form) form.submit();
        };
        rec.onend = function () { btn.classList.remove("listening"); input.placeholder = prev; };
        rec.onerror = function () { btn.classList.remove("listening"); input.placeholder = prev; };
        try { rec.start(); } catch (e) {}
      });
    });
  }

  // ---- Camera barcode scanner (BarcodeDetector API) ------------------------
  function wireScanner() {
    var openers = document.querySelectorAll("[data-scan]");
    var modal = document.getElementById("scanner-modal");
    if (!openers.length || !modal) return;
    var video = document.getElementById("scanner-video");
    var statusEl = document.getElementById("scanner-status");
    var closeBtn = document.getElementById("scanner-close");
    var stream = null, detector = null, raf = null, stopped = true, lastMiss = "";

    function setStatus(m) { if (statusEl) statusEl.textContent = m; }
    function stop() {
      stopped = true;
      if (raf) cancelAnimationFrame(raf);
      if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
      stream = null; modal.classList.remove("open");
    }
    function loop() {
      if (stopped) return;
      detector.detect(video).then(function (codes) {
        if (codes && codes.length) { lookup(codes[0].rawValue); return; }
        raf = requestAnimationFrame(loop);
      }).catch(function () { raf = requestAnimationFrame(loop); });
    }
    function lookup(code) {
      if (code === lastMiss) { raf = requestAnimationFrame(loop); return; }  // avoid re-hammering
      setStatus("Found " + code + " — looking up…");
      fetch("/api/barcode/" + encodeURIComponent(code))
        .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
        .then(function (d) { stop(); location.href = "/product/" + d.product.id; })
        .catch(function (st) {
          lastMiss = code;
          setStatus(st === 404 ? "No catalog match for " + code + ". Keep scanning or use search." : "Lookup error.");
          raf = requestAnimationFrame(loop);
        });
    }
    function start() {
      stopped = false; lastMiss = ""; modal.classList.add("open");
      if (!("BarcodeDetector" in window)) {
        setStatus("This browser can't scan live. Try Chrome on Android, or type the barcode in search.");
        return;
      }
      detector = new window.BarcodeDetector({ formats: ["ean_13", "ean_8", "upc_a", "upc_e", "code_128"] });
      navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } })
        .then(function (s) {
          stream = s; video.srcObject = s;
          return video.play();
        })
        .then(function () { setStatus("Point your camera at a barcode…"); loop(); })
        .catch(function (err) { setStatus("Camera unavailable: " + err.message); });
    }
    openers.forEach(function (b) { b.addEventListener("click", function (e) { e.preventDefault(); start(); }); });
    if (closeBtn) closeBtn.addEventListener("click", stop);
    modal.addEventListener("click", function (e) { if (e.target === modal) stop(); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && modal.classList.contains("open")) stop(); });
  }

  // ---- Photo / visual search (canvas downscale -> Claude vision) -----------
  function downscale(file, max, cb) {
    var img = new Image();
    img.onload = function () {
      var scale = Math.min(1, max / Math.max(img.width, img.height));
      var w = Math.round(img.width * scale), h = Math.round(img.height * scale);
      var canvas = document.createElement("canvas");
      canvas.width = w; canvas.height = h;
      canvas.getContext("2d").drawImage(img, 0, 0, w, h);
      cb(canvas.toDataURL("image/jpeg", 0.85));
    };
    img.onerror = function () { cb(null); };
    img.src = URL.createObjectURL(file);
  }

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
  }); }

  function wirePhoto() {
    var openers = document.querySelectorAll("[data-photo]");
    var input = document.getElementById("photo-input");
    var modal = document.getElementById("photo-modal");
    var body = document.getElementById("photo-body");
    var closeBtn = document.getElementById("photo-close");
    if (!openers.length || !input || !modal || !body) return;

    function setBody(html) { body.innerHTML = html; }
    function open() { modal.classList.add("open"); }
    function close() { modal.classList.remove("open"); input.value = ""; }

    function card(c) {
      var price = c.best_price != null ? "$" + c.best_price.toFixed(2) + " at " + esc(c.best_retailer) : "—";
      var img = c.image_url
        ? '<img src="' + esc(c.image_url) + '" alt="" loading="lazy"/>'
        : '<span class="ph">' + esc((c.name || "?").charAt(0).toUpperCase()) + "</span>";
      return '<a class="ps-card" href="/product/' + c.id + '">' +
        '<div class="ps-thumb">' + img + "</div>" +
        '<div class="ps-info"><strong>' + esc(c.name) + "</strong>" +
        '<span class="muted small">' + esc(c.brand) + "</span>" +
        '<span class="ps-price">' + price + "</span></div></a>";
    }

    function render(d) {
      var id = d.identified || {};
      if (!id.ok) {
        setBody('<p class="ps-status">' + esc(id.reason || "Couldn't identify that photo.") +
          '</p><a class="btn-lite" href="/">Back to search</a>');
        return;
      }
      var conf = id.confidence ? " · " + id.confidence + "% sure" : "";
      var head = '<div class="ps-head">Looks like <strong>' + esc(id.name || id.query) +
        "</strong>" + '<span class="muted small">matched “' + esc(id.query) + '”' + conf + "</span></div>";
      var cta = '<a class="btn-lite" href="/?q=' + encodeURIComponent(id.query) + '">See all results for “' + esc(id.query) + '” →</a>';
      if (!d.results || !d.results.length) {
        setBody(head + '<p class="ps-status">No catalog matches yet. ' + cta + "</p>");
        return;
      }
      setBody(head + '<div class="ps-grid">' + d.results.slice(0, 6).map(card).join("") + "</div>" + cta);
    }

    openers.forEach(function (b) { b.addEventListener("click", function (e) { e.preventDefault(); input.click(); }); });
    if (closeBtn) closeBtn.addEventListener("click", close);
    modal.addEventListener("click", function (e) { if (e.target === modal) close(); });

    input.addEventListener("change", function () {
      var file = input.files && input.files[0];
      if (!file) return;
      open(); setBody('<p class="ps-status"><span class="spin"></span> Reading photo…</p>');
      downscale(file, 1024, function (dataUrl) {
        if (!dataUrl) { setBody('<p class="ps-status">Could not read that image.</p>'); return; }
        var b64 = dataUrl.slice(dataUrl.indexOf(",") + 1);
        setBody('<p class="ps-status"><span class="spin"></span> Identifying product with AI…</p>');
        fetch("/api/visual-search", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ image: b64, media_type: "image/jpeg" }),
        }).then(function (r) { return r.json(); })
          .then(render)
          .catch(function () { setBody('<p class="ps-status">Something went wrong. Please try again.</p>'); });
      });
    });
  }

  // ---- Search autocomplete (typeahead) ------------------------------------
  function wireAutocomplete() {
    document.querySelectorAll("input[data-autocomplete]").forEach(function (input) {
      var list = document.getElementById(input.getAttribute("aria-controls"));
      if (!list) return;
      var form = input.closest("form");
      var items = [];      // current suggestion strings
      var active = -1;     // highlighted index
      var timer = null;
      var lastQ = "";

      function close() {
        list.hidden = true; list.innerHTML = ""; items = []; active = -1;
        input.setAttribute("aria-expanded", "false");
      }
      function choose(text) { input.value = text; close(); if (form) form.submit(); }

      function render(suggestions) {
        items = suggestions.map(function (s) { return s.text; });
        if (!items.length) { close(); return; }
        list.innerHTML = suggestions.map(function (s, i) {
          var tag = s.kind && s.kind !== "product"
            ? ' <span class="ac-kind">' + esc(s.kind) + "</span>" : "";
          return '<li class="ac-item" role="option" data-i="' + i + '">' +
            '<span>' + esc(s.text) + "</span>" + tag + "</li>";
        }).join("");
        list.hidden = false; active = -1;
        input.setAttribute("aria-expanded", "true");
        list.querySelectorAll(".ac-item").forEach(function (li) {
          li.addEventListener("mousedown", function (e) {  // mousedown beats blur
            e.preventDefault(); choose(items[+li.dataset.i]);
          });
        });
      }

      function fetchSuggest() {
        var q = input.value.trim();
        if (q.length < 2) { close(); return; }
        if (q === lastQ) return;
        lastQ = q;
        fetch("/api/suggest?q=" + encodeURIComponent(q))
          .then(function (r) { return r.json(); })
          .then(function (d) {
            if (input.value.trim() === q) render(d.suggestions || []);
          })
          .catch(function () { close(); });
      }

      function highlight(n) {
        var els = list.querySelectorAll(".ac-item");
        if (!els.length) return;
        active = (n + els.length) % els.length;
        els.forEach(function (el, i) { el.classList.toggle("on", i === active); });
      }

      input.addEventListener("input", function () {
        clearTimeout(timer); timer = setTimeout(fetchSuggest, 140);
      });
      input.addEventListener("keydown", function (e) {
        if (list.hidden) return;
        if (e.key === "ArrowDown") { e.preventDefault(); highlight(active + 1); }
        else if (e.key === "ArrowUp") { e.preventDefault(); highlight(active - 1); }
        else if (e.key === "Enter" && active >= 0) { e.preventDefault(); choose(items[active]); }
        else if (e.key === "Escape") { close(); }
      });
      input.addEventListener("blur", function () { setTimeout(close, 120); });
    });
  }

  // ---- Toast ---------------------------------------------------------------
  function toast(msg) {
    var t = document.createElement("div");
    t.className = "toast"; t.textContent = msg;
    document.body.appendChild(t);
    requestAnimationFrame(function () { t.classList.add("on"); });
    setTimeout(function () { t.classList.remove("on"); setTimeout(function () { t.remove(); }, 300); }, 2200);
  }

  // ---- Share deal card (canvas -> Web Share / download) --------------------
  function wireShareCard() {
    var btns = document.querySelectorAll("[data-share-card]");
    if (!btns.length) return;

    function rr(ctx, x, y, w, h, r) {
      ctx.beginPath();
      ctx.moveTo(x + r, y);
      ctx.arcTo(x + w, y, x + w, y + h, r);
      ctx.arcTo(x + w, y + h, x, y + h, r);
      ctx.arcTo(x, y + h, x, y, r);
      ctx.arcTo(x, y, x + w, y, r);
      ctx.closePath();
    }
    function wrap(ctx, text, maxW, maxLines) {
      var words = text.split(/\s+/), lines = [], line = "";
      for (var i = 0; i < words.length; i++) {
        var test = line ? line + " " + words[i] : words[i];
        if (ctx.measureText(test).width > maxW && line) { lines.push(line); line = words[i]; }
        else line = test;
        if (lines.length === maxLines - 1 && ctx.measureText(line + "…").width > maxW) break;
      }
      if (line) lines.push(line);
      if (lines.length > maxLines) { lines = lines.slice(0, maxLines); lines[maxLines - 1] += "…"; }
      return lines;
    }

    function draw(d, img) {
      var W = 1200, H = 630, c = document.createElement("canvas");
      c.width = W; c.height = H;
      var x = c.getContext("2d");
      // Background
      var g = x.createLinearGradient(0, 0, W, H);
      g.addColorStop(0, "#0b1220"); g.addColorStop(1, "#15233f");
      x.fillStyle = g; x.fillRect(0, 0, W, H);
      x.fillStyle = "rgba(59,130,246,0.10)"; rr(x, 40, 40, W - 80, H - 80, 28); x.fill();

      // Brand wordmark
      x.fillStyle = "#5b8cff"; x.font = "700 34px Arial";
      x.fillText("◆", 72, 104);
      x.fillStyle = "#f2f4f7"; x.font = "800 34px Arial";
      x.fillText(" DealWise", 96, 104);
      x.fillStyle = "#5b8cff"; x.fillText(" AI", 96 + x.measureText(" DealWise").width, 104);

      // Product image (or branded placeholder)
      var ix = 72, iy = 150, isz = 320;
      x.save(); rr(x, ix, iy, isz, isz, 20); x.clip();
      x.fillStyle = "#ffffff"; x.fillRect(ix, iy, isz, isz);
      if (img) { x.drawImage(img, ix, iy, isz, isz); }
      else {
        x.fillStyle = "#1e293b"; x.fillRect(ix, iy, isz, isz);
        x.fillStyle = "#5b8cff"; x.font = "800 140px Arial"; x.textAlign = "center";
        x.fillText((d.name || "?").charAt(0).toUpperCase(), ix + isz / 2, iy + isz / 2 + 50);
        x.textAlign = "left";
      }
      x.restore();

      // Right column
      var rx = 440, rw = W - rx - 72;
      if (d.brand && d.brand !== "Unknown") {
        x.fillStyle = "#9aa1ab"; x.font = "700 22px Arial";
        x.fillText(d.brand.toUpperCase(), rx, 175);
      }
      x.fillStyle = "#f2f4f7"; x.font = "800 44px Arial";
      var lines = wrap(x, d.name || "", rw, 3);
      lines.forEach(function (ln, i) { x.fillText(ln, rx, 225 + i * 52); });

      var py = 225 + lines.length * 52 + 40;
      // Price
      x.fillStyle = "#ffffff"; x.font = "800 76px Arial";
      x.fillText("$" + d.price, rx, py);
      x.fillStyle = "#9aa1ab"; x.font = "400 26px Arial";
      x.fillText("at " + d.retailer, rx, py + 36);

      // Deal score badge
      var hue = Math.round((d.score / 100) * 130);
      var bx = rx, by = py + 70, bw = 150, bh = 70;
      x.fillStyle = "hsl(" + hue + ",70%,45%)"; rr(x, bx, by, bw, bh, 14); x.fill();
      x.fillStyle = "#fff"; x.font = "800 38px Arial";
      x.fillText(String(d.score), bx + 18, by + 48);
      x.font = "700 18px Arial"; x.fillText("/100 DEAL", bx + 18 + x.measureText(String(d.score)).width + 6, by + 46);
      // Recommendation pill
      x.fillStyle = "rgba(255,255,255,0.12)"; rr(x, bx + bw + 16, by, 200, bh, 14); x.fill();
      x.fillStyle = "#e2e8f0"; x.font = "800 28px Arial";
      x.fillText(d.rec || "", bx + bw + 38, by + 44);

      // Savings line
      var save = Math.max(0, (parseFloat(d.avg) - parseFloat(d.price)));
      x.fillStyle = "#34d399"; x.font = "700 30px Arial";
      var savetext = save >= 1
        ? "You save $" + save.toFixed(2) + " vs the 90-day average"
        : "Tracked live across multiple US retailers";
      x.fillText(savetext, rx, by + bh + 56);

      // Footer
      x.fillStyle = "#64748b"; x.font = "400 22px Arial";
      x.fillText("Smart shopping intelligence · dealwise", 72, H - 56);

      return c;
    }

    function exportAndShare(canvas, d) {
      canvas.toBlob(function (blob) {
        if (!blob) { toast("Couldn't make the card."); return; }
        var text = "I found the " + d.name + " for $" + d.price + " at " + d.retailer +
          " (deal score " + d.score + "/100) on DealWise AI";
        var file = new File([blob], "dealwise-deal.png", { type: "image/png" });
        if (navigator.canShare && navigator.canShare({ files: [file] })) {
          navigator.share({ files: [file], title: d.name, text: text }).catch(function () {});
        } else {
          var url = URL.createObjectURL(blob);
          var a = document.createElement("a");
          a.href = url; a.download = "dealwise-deal.png"; a.click();
          setTimeout(function () { URL.revokeObjectURL(url); }, 1500);
          toast("Deal card downloaded 📤");
        }
      }, "image/png");
    }

    btns.forEach(function (btn) {
      btn.addEventListener("click", function () {
        var d = {
          name: btn.dataset.name, brand: btn.dataset.brand, price: btn.dataset.price,
          retailer: btn.dataset.retailer, score: parseInt(btn.dataset.score, 10) || 0,
          rec: btn.dataset.rec, avg: btn.dataset.avg, img: btn.dataset.img,
        };
        var orig = btn.textContent; btn.disabled = true; btn.textContent = "Building…";
        function finish(canvas) { exportAndShare(canvas, d); btn.disabled = false; btn.textContent = orig; }
        if (d.img) {
          var im = new Image();
          im.crossOrigin = "anonymous";   // need a clean canvas to export
          im.onload = function () { finish(draw(d, im)); };
          im.onerror = function () { finish(draw(d, null)); };  // CORS/!found -> placeholder
          im.src = d.img;
        } else {
          finish(draw(d, null));
        }
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initTheme(); tint(); wireHearts(); wireShare(); wirePresets(); wireSubmitStates();
    wireVoice(); wireScanner(); wirePhoto(); wireAutocomplete(); wireShareCard();
  });
})();
