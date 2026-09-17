/* /ref:dashboard static-mode viewer (LIBRARY_VIEWER_IMPLEMENTATION_PLAN.md §6).
 *
 * Everything here is read-only except the notes composer, which only ever
 * writes to this browser's localStorage (§6.2) -- there is no write path
 * back into the library in static mode, that's Phase 4 (--serve).
 *
 * Security note (§6.3): every place a paper's title/abstract/notes/etc. is
 * rendered uses `text()` (an element with `textContent` set) or a `.value`
 * assignment, never raw HTML injection of untrusted data, so a title containing
 * `</script>` or an abstract containing `<img onerror=...>` can never
 * execute -- it just renders as literal text.
 */
(function () {
  "use strict";

  var DATA = JSON.parse(document.getElementById("dashboard-data").textContent);
  var LIVE = !!DATA.live; // set by dashboard.py's serve() -- fetch the API instead of using embedded rows

  var TOKEN = (function () {
    try { return new URLSearchParams(location.search).get("token") || ""; } catch (e) { return ""; }
  })();

  // /ref:read deep-link (?paper=<pmid>&tab=pdf|details): opens straight
  // into one paper's drawer instead of the library table, reusing this
  // same drawer/pdf.js/notes machinery rather than a separate reader page.
  var DEEPLINK = (function () {
    try {
      var params = new URLSearchParams(location.search);
      var paper = params.get("paper");
      return paper ? { pmid: paper, tab: params.get("tab") === "details" ? "details" : "pdf" } : null;
    } catch (e) { return null; }
  })();

  // Every fetch this page makes to its own server carries the per-run token
  // as a header (never a query param past the initial page load) --
  // LIBRARY_VIEWER_IMPLEMENTATION_PLAN.md §7.3.
  function apiFetch(path, opts) {
    opts = opts || {};
    var headers = {};
    for (var k in (opts.headers || {})) headers[k] = opts.headers[k];
    headers["X-Ref-Token"] = TOKEN;
    opts.headers = headers;
    return fetch(path, opts);
  }

  // P0.2: every live-data fetch goes through this so a non-2xx response
  // (403 token mismatch, 404, 5xx, ...) surfaces the endpoint + status
  // instead of silently handing bad JSON (or an {error:...} envelope) to
  // the renderers.
  function fetchJSON(path) {
    return apiFetch(path).then(function (r) {
      if (!r.ok) {
        var err = new Error("http " + r.status + " on " + path);
        err.endpoint = path;
        err.status = r.status;
        throw err;
      }
      return r.json();
    });
  }

  function describeFetchError(err) {
    if (err && err.endpoint) return err.endpoint + (err.status ? " (HTTP " + err.status + ")" : "");
    return (err && err.message) || "unknown error";
  }

  function showError(msg) {
    var banner = document.getElementById("errbanner");
    if (!banner) return;
    banner.textContent = msg;
    banner.hidden = false;
  }

  function clearError() {
    var banner = document.getElementById("errbanner");
    if (!banner) return;
    banner.hidden = true;
    banner.textContent = "";
  }

  var ROWS = [];
  var BY_PMID = {};
  function setRows(rows) {
    ROWS = rows || [];
    BY_PMID = {};
    ROWS.forEach(function (r) { BY_PMID[r.pmid] = r; });
  }
  setRows(DATA.rows || []);

  var SNAPSHOTS = DATA.snapshots || [];

  // Live mode has no build-time lint report / coverage matrix embedded in
  // DATA (§7 gap fixed here) -- LINT/MATRIX_COLUMNS/MATRIX_ROWS are filled
  // from DATA at static-build time and refetched via /api/lint + /api/matrix
  // on load and on refresh in live mode; renderHealth()/renderCoverageMatrix()
  // read these variables either way so the two modes share one code path.
  var LINT = DATA.lint || {};
  // /api/summary (or the build-time copy): drives the Next actions panel so
  // its ranking is computed once, in dashboard_insights.next_actions().
  var SUMMARY = DATA.summary || null;
  var MATRIX_COLUMNS_LIVE = DATA.matrix_columns || [];
  var MATRIX_ROWS_LIVE = DATA.matrix || [];

  // §6.1's project summaries, computed from rows() the same way
  // dashboard.py's `_project_summaries()` does at build time -- this lets
  // the Projects tab work identically in live mode without a dedicated
  // /api/projects route (there is only one inventory, §1.2).
  function projectSummaries() {
    var byslug = {};
    ROWS.forEach(function (row) {
      (row.projects || []).forEach(function (p) {
        if (!p.slug) return;
        byslug[p.slug] = byslug[p.slug] || [];
        byslug[p.slug].push({
          pmid: row.pmid, title: row.title, reading_status: p.reading_status,
          added_at: p.added_at, has_fulltext: row.has_fulltext, has_pdf: row.has_pdf,
          claims_active: row.claims_active, lint_flags: row.lint_flags,
        });
      });
    });
    return Object.keys(byslug).sort().map(function (slug) {
      var papers = byslug[slug].slice().sort(function (a, b) {
        return a.pmid < b.pmid ? -1 : a.pmid > b.pmid ? 1 : 0;
      });
      return { slug: slug, papers: papers };
    });
  }

  var SOURCE_BADGES = ["pdf-backed", "full-text", "oa-pending", "abstract-only", "metadata-only"];
  var SOURCE_COLOR = {
    "pdf-backed": "var(--s-pdf)", "full-text": "var(--s-full)", "oa-pending": "var(--s-oa)",
    "abstract-only": "var(--s-abs)", "metadata-only": "var(--s-meta)", "none": "var(--crit)"
  };
  var LINT_BUCKET_LABELS = {
    missing_meta: "missing meta.json", malformed_meta: "malformed meta.json",
    missing_title: "missing title", missing_year: "missing year",
    missing_journal: "missing journal", missing_abstract: "missing abstract",
    metadata_only: "metadata only", abstract_only: "abstract only", oa_pending: "OA pending",
    missing_doi: "missing DOI", missing_current: "no current version",
    missing_claim_registry: "no claim registry", stale_retraction_check: "stale retraction check",
  };
  var LINT_BUCKET_COMMAND = {
    metadata_only: "/ref:list --issue metadata_only --format pmids",
    abstract_only: "/ref:add-fetch",
    oa_pending: "/ref:fetch-pdf",
    missing_claim_registry: "/ref:extract",
    stale_retraction_check: "/ref:audit",
    missing_current: "/ref:fetch",
  };

  // ---------------------------------------------------------------- utils

  function el(tag, opts, kids) {
    var e = document.createElement(tag);
    opts = opts || {};
    if (opts.className) e.className = opts.className;
    if (opts.text !== undefined && opts.text !== null) e.textContent = String(opts.text);
    if (opts.attrs) {
      for (var k in opts.attrs) if (opts.attrs[k] !== undefined && opts.attrs[k] !== null) e.setAttribute(k, opts.attrs[k]);
    }
    if (opts.on) {
      for (var ev in opts.on) e.addEventListener(ev, opts.on[ev]);
    }
    (kids || []).forEach(function (k) { if (k) e.appendChild(k); });
    return e;
  }

  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

  function fmtDays(d) {
    if (d === null || d === undefined) return "";
    if (d === 0) return "today";
    return d + "d ago";
  }

  function copyText(text) {
    var toast = document.getElementById("toast");
    function show() {
      toast.hidden = false;
      clearTimeout(toast._t);
      toast._t = setTimeout(function () { toast.hidden = true; }, 1400);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(show, function () { fallbackCopy(text); show(); });
    } else {
      fallbackCopy(text);
      show();
    }
  }

  function flash(msg, ms) {
    var toast = document.getElementById("toast");
    toast.textContent = msg;
    toast.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(function () { toast.hidden = true; toast.textContent = "Copied"; }, ms || 2200);
  }

  // Client-side file download (exports, synthesis draft) -- nothing is
  // written to the library.
  function downloadText(filename, text, mime) {
    var blob = new Blob([text], { type: mime || "text/plain;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var a = el("a", { attrs: { href: url, download: filename } });
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
  }

  function fallbackCopy(text) {
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); } catch (e) { /* best effort */ }
    document.body.removeChild(ta);
  }

  function needsFetch(row) {
    return !row.has_fulltext && !row.has_pdf;
  }
  function needsExtract(row) {
    return (row.lint_flags || []).indexOf("missing_claim_registry") >= 0;
  }
  function needsFetchPdf(row) {
    return row.has_fulltext && !row.has_pdf;
  }
  function needsAudit(row) {
    return !!row.stale_check;
  }

  // -------------------------------------------------------------- header

  document.getElementById("lib-path").textContent = DATA.library_root || "";
  document.getElementById("generated-line").textContent =
    "generated by /ref:dashboard · " + (DATA.generated_at || "");

  // -------------------------------------------------------------- health

  function renderHealth() {
    var summary = (LINT && LINT.summary) || {};
    var issues = (LINT && LINT.issues) || {};
    var dot = document.getElementById("health-dot");
    var label = document.getElementById("health-label");
    document.getElementById("health-count").textContent =
      summary.issues_total !== undefined ? String(summary.issues_total) + " open issues" : "";

    var crit = (issues.missing_meta || []).length + (issues.malformed_meta || []).length;
    var total = summary.issues_total || 0;
    if (crit > 0) {
      dot.className = "dot crit";
      label.textContent = "needs repair";
    } else if (total > 0 || summary.catalog_stale) {
      dot.className = "dot warn";
      var lead = ["metadata_only", "abstract_only", "oa_pending"].find(function (b) { return (issues[b] || []).length > 0; });
      label.textContent = lead ? "needs full text" : (summary.catalog_stale ? "catalog stale" : "needs attention");
    } else {
      dot.className = "dot";
      label.textContent = "healthy";
    }

    var attn = document.getElementById("attn");
    clear(attn);
    var order = Object.keys(issues);
    order.forEach(function (bucket) {
      var pmids = issues[bucket] || [];
      if (!pmids.length) return;
      var cmd = LINT_BUCKET_COMMAND[bucket] || "/ref:list --issue " + bucket + " --format pmids";
      var li = el("li", {}, [
        el("button", {
          attrs: { type: "button", "aria-pressed": "false" },
          on: { click: function () { applyIssueFilter(bucket, LINT_BUCKET_LABELS[bucket] || bucket); } }
        }, [
          el("span", { className: "n", text: pmids.length }),
          el("span", {}, [
            el("span", { text: LINT_BUCKET_LABELS[bucket] || bucket }),
            el("br"),
            el("span", { className: "cmd", text: cmd }),
          ]),
        ]),
      ]);
      attn.appendChild(li);
    });
    if (summary.catalog_stale) {
      var li2 = el("li", {}, [
        el("button", { attrs: { type: "button" } }, [
          el("span", { className: "n", text: "⚠" }),
          el("span", {}, [
            el("span", { text: "catalog is stale" }),
            el("br"),
            el("span", { className: "cmd", text: "/ref:index --rebuild" }),
          ]),
        ]),
      ]);
      attn.appendChild(li2);
    }
  }

  // -------------------------------------------------------- source coverage

  var sourceFilterSet = null; // null = no filter; Set of badges otherwise

  function renderSourceCoverage() {
    var counts = {};
    SOURCE_BADGES.forEach(function (b) { counts[b] = 0; });
    var none = 0;
    ROWS.forEach(function (r) {
      if (r.source_badge && counts.hasOwnProperty(r.source_badge)) counts[r.source_badge]++;
      else none++;
    });
    var total = ROWS.length;
    document.getElementById("src-total").textContent = total + " papers";

    var stack = document.getElementById("stack");
    clear(stack);
    var legend = document.getElementById("legend");
    clear(legend);

    var all = SOURCE_BADGES.concat(none ? ["none"] : []);
    all.forEach(function (badge) {
      var count = badge === "none" ? none : counts[badge];
      if (!count) return;
      var pct = total ? (count / total * 100) : 0;
      var active = !sourceFilterSet || sourceFilterSet.has(badge);
      stack.appendChild(el("button", {
        className: active ? "" : "dim",
        attrs: {
          type: "button", style: "flex:" + Math.max(pct, 0.5) + ";background:" + SOURCE_COLOR[badge],
          "aria-pressed": String(!!(sourceFilterSet && sourceFilterSet.has(badge))),
          title: badge + ": " + count,
        },
        on: { click: function () { toggleSourceFilter(badge); } },
      }));
      legend.appendChild(el("button", {
        attrs: { type: "button", "aria-pressed": String(!!(sourceFilterSet && sourceFilterSet.has(badge))) },
        on: { click: function () { toggleSourceFilter(badge); } },
      }, [
        el("i", { className: "sw", attrs: { style: "background:" + SOURCE_COLOR[badge] } }),
        el("span", { className: "lbl", text: badge === "none" ? "no meta" : badge }),
        el("span", { className: "ct", text: count }),
      ]));
    });
  }

  function toggleSourceFilter(badge) {
    if (!sourceFilterSet) sourceFilterSet = new Set();
    if (sourceFilterSet.has(badge)) sourceFilterSet.delete(badge);
    else sourceFilterSet.add(badge);
    if (!sourceFilterSet.size) sourceFilterSet = null;
    renderSourceCoverage();
    renderChips();
    renderTable();
  }

  // ------------------------------------------------------------- funnel

  function renderFunnel() {
    var svg = document.getElementById("funnel");
    clear(svg);
    var stages = [
      { label: "in library", n: ROWS.length },
      { label: "metadata ok", n: ROWS.filter(function (r) { return r.source_badge; }).length },
      { label: "abstract available", n: ROWS.filter(function (r) { return r.source_badge && r.source_badge !== "metadata-only"; }).length },
      { label: "full text / PDF", n: ROWS.filter(function (r) { return r.has_fulltext || r.has_pdf; }).length },
      { label: "claims extracted", n: ROWS.filter(function (r) { return r.claims_active > 0; }).length },
    ];
    var max = stages[0].n || 1;
    var barH = 24, gap = 10, top = 6, w = 420;
    stages.forEach(function (s, i) {
      var y = top + i * (barH + gap);
      var bw = Math.max(4, (s.n / max) * (w - 140));
      svg.appendChild(svgEl("rect", { x: 0, y: y, width: w - 140, height: barH, fill: "var(--hover)", rx: 3 }));
      svg.appendChild(svgEl("rect", { x: 0, y: y, width: bw, height: barH, fill: "var(--accent)", rx: 3, opacity: 0.85 }));
      var t1 = svgEl("text", { x: 0, y: y + barH + 9, "font-size": 10.5 });
      t1.textContent = s.label;
      svg.appendChild(t1);
      var t2 = svgEl("text", { x: w - 138, y: y + barH / 2 + 4, "text-anchor": "start", class: "v" });
      t2.textContent = String(s.n);
      svg.appendChild(t2);
    });
    svg.setAttribute("viewBox", "0 0 420 " + (top + stages.length * (barH + gap) + 14));
  }

  function svgEl(tag, attrs) {
    var e = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }

  // ------------------------------------------------------- papers by year

  function renderYearsChart() {
    var svg = document.getElementById("years");
    clear(svg);
    var byYear = {};
    ROWS.forEach(function (r) {
      var y = parseInt(r.year, 10);
      if (!y) return;
      byYear[y] = byYear[y] || {};
      var b = r.source_badge || "none";
      byYear[y][b] = (byYear[y][b] || 0) + 1;
    });
    var years = Object.keys(byYear).map(Number).sort();
    if (!years.length) {
      var t = svgEl("text", { x: 10, y: 20 });
      t.textContent = "no dated papers yet";
      svg.appendChild(t);
      return;
    }
    var w = 560, h = 190, padL = 30, padB = 20, padT = 10;
    var maxTotal = 0;
    years.forEach(function (y) {
      var total = Object.values(byYear[y]).reduce(function (a, b) { return a + b; }, 0);
      if (total > maxTotal) maxTotal = total;
    });
    var barW = (w - padL - 10) / years.length;
    years.forEach(function (y, i) {
      var x = padL + i * barW;
      var yOff = h - padB;
      SOURCE_BADGES.concat(["none"]).forEach(function (badge) {
        var count = byYear[y][badge] || 0;
        if (!count) return;
        var bh = (count / maxTotal) * (h - padT - padB);
        yOff -= bh;
        svg.appendChild(svgEl("rect", {
          x: x + 1, y: yOff, width: Math.max(1, barW - 2), height: bh,
          fill: SOURCE_COLOR[badge], opacity: 0.88,
        }));
      });
      if (i % Math.ceil(years.length / 10 || 1) === 0) {
        var lt = svgEl("text", { x: x + barW / 2, y: h - 4, "text-anchor": "middle" });
        lt.textContent = String(y);
        svg.appendChild(lt);
      }
    });
  }

  // --------------------------------------------------------- lint trend

  function renderTrendChart() {
    var svg = document.getElementById("trend");
    clear(svg);
    var snaps = SNAPSHOTS;
    document.getElementById("trend-caption").textContent = snaps.length + " snapshot" + (snaps.length === 1 ? "" : "s") + " · maintenance/*.json";
    if (!snaps.length) {
      var t = svgEl("text", { x: 10, y: 20 });
      t.textContent = "no /ref:lint --snapshot history yet";
      svg.appendChild(t);
      return;
    }
    var w = 560, h = 190, padL = 30, padB = 20, padT = 10;
    var totals = snaps.map(function (s) { return s.summary && s.summary.issues_total || 0; });
    var max = Math.max.apply(null, totals.concat([1]));
    var stepX = (w - padL - 10) / Math.max(1, snaps.length - 1);
    var pts = totals.map(function (v, i) {
      var x = padL + i * stepX;
      var y = padT + (1 - v / max) * (h - padT - padB);
      return x + "," + y;
    });
    svg.appendChild(svgEl("polyline", { points: pts.join(" "), fill: "none", stroke: "var(--accent)", "stroke-width": 2 }));
    totals.forEach(function (v, i) {
      var x = padL + i * stepX;
      var y = padT + (1 - v / max) * (h - padT - padB);
      svg.appendChild(svgEl("circle", { cx: x, cy: y, r: 2.5, fill: "var(--accent)" }));
    });
  }

  // -------------------------------------------------------------- tabs

  var TABS = ["papers", "coverage", "projects", "insights", "maint", "triage"];
  var activeTab = "papers";
  function selectTab(name) {
    if (TABS.indexOf(name) < 0) return;
    activeTab = name;
    TABS.forEach(function (t) {
      document.getElementById("tab-" + t).setAttribute("aria-selected", String(t === name));
      document.getElementById("p-" + t).hidden = t !== name;
    });
    syncUrl();
  }
  function renderTabContent(name) {
    if (name === "coverage") renderCoverageMatrix();
    if (name === "projects") renderProjects();
    if (name === "maint") renderMaintenance();
    if (name === "triage") renderTriageTab();
    if (name === "insights") renderInsights();
  }
  // P0.1: whichever tab is on screen when a manual refresh lands must be
  // redrawn from the fresh data immediately -- not just next time it's
  // clicked -- so maintenance/coverage/projects never show stale snapshots.
  function rerenderActiveTab() {
    renderTabContent(activeTab);
  }
  document.getElementById("tabs").addEventListener("click", function (e) {
    var btn = e.target.closest("button[data-tab]");
    if (!btn) return;
    selectTab(btn.dataset.tab);
    renderTabContent(btn.dataset.tab);
  });

  // ------------------------------------------------------------- papers

  var state = {
    query: "",
    project: "all",
    chips: [], // {id, label, pred}
    sort: null, // {field, dir}
    selected: new Set(),
  };

  function applyIssueFilter(bucket, label) {
    state.chips = state.chips.filter(function (c) { return c.id !== "issue:" + bucket; });
    state.chips.push({
      id: "issue:" + bucket, label: "issue: " + label,
      pred: function (r) { return (r.lint_flags || []).indexOf(bucket) >= 0; },
    });
    selectTab("papers");
    renderChips();
    renderTable();
  }

  function renderChips() {
    var wrap = document.getElementById("activefilters");
    clear(wrap);
    state.chips.forEach(function (c) {
      wrap.appendChild(el("span", { className: "fchip" }, [
        el("span", { text: c.label }),
        el("button", {
          className: "x", text: "×", attrs: { type: "button", "aria-label": "remove filter " + c.label },
          on: { click: function () { state.chips = state.chips.filter(function (x) { return x.id !== c.id; }); renderChips(); renderTable(); } },
        }),
      ]));
    });
    if (sourceFilterSet) {
      wrap.appendChild(el("span", { className: "fchip" }, [
        el("span", { text: "source: " + Array.from(sourceFilterSet).join(", ") }),
        el("button", {
          className: "x", text: "×", attrs: { type: "button" },
          on: { click: function () { sourceFilterSet = null; renderSourceCoverage(); renderChips(); renderTable(); } },
        }),
      ]));
    }
  }

  function projectLabel(r) {
    return (r.projects || []).map(function (p) { return p.slug; }).join(", ");
  }

  function filteredRows() {
    var q = state.query.trim().toLowerCase();
    return ROWS.filter(function (r) {
      if (sourceFilterSet && !sourceFilterSet.has(r.source_badge || "none")) return false;
      if (state.project !== "all") {
        var slugs = (r.projects || []).map(function (p) { return p.slug; });
        if (state.project === "none") { if (slugs.length) return false; }
        else if (slugs.indexOf(state.project) < 0) return false;
      }
      for (var i = 0; i < state.chips.length; i++) if (!state.chips[i].pred(r)) return false;
      if (q) {
        var hay = [r.title, r.citekey, r.journal, r.pmid].filter(Boolean).join(" ").toLowerCase();
        if (hay.indexOf(q) < 0) return false;
      }
      return true;
    });
  }

  function sortRows(rows) {
    if (!state.sort) return rows;
    var field = state.sort.field, dir = state.sort.dir;
    var copy = rows.slice();
    copy.sort(function (a, b) {
      var av = a[field], bv = b[field];
      if (field === "project") { av = projectLabel(a); bv = projectLabel(b); }
      if (av === null || av === undefined) av = "";
      if (bv === null || bv === undefined) bv = "";
      if (av < bv) return dir === "asc" ? -1 : 1;
      if (av > bv) return dir === "asc" ? 1 : -1;
      return 0;
    });
    return copy;
  }

  var currentVisible = []; // full filtered+sorted set -- drawer prev/next (n/p) walks all of this, not just the current page
  var currentPageRows = []; // the slice actually in the DOM right now
  var keyboardActiveIndex = -1; // P0.3: j/k or arrow-key row cursor, scoped to the current page
  var PAGE_SIZE = 100; // P2.1: keeps the DOM small on large libraries (target: 5k papers) without changing filter/sort semantics
  var currentPage = 0;

  function highlightActiveRow() {
    var tbody = document.getElementById("rows");
    Array.prototype.forEach.call(tbody.children, function (tr, i) {
      if (i === keyboardActiveIndex) {
        tr.setAttribute("aria-current", "true");
        tr.scrollIntoView({ block: "nearest" });
      } else {
        tr.removeAttribute("aria-current");
      }
    });
  }

  function moveKeyboardActive(delta) {
    if (!currentPageRows.length) return;
    keyboardActiveIndex = Math.max(0, Math.min(currentPageRows.length - 1, keyboardActiveIndex + delta));
    highlightActiveRow();
  }

  function renderTable() {
    var rows = sortRows(filteredRows());
    currentVisible = rows;
    var pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
    if (currentPage >= pages) currentPage = 0;
    document.getElementById("result").textContent = rows.length + " of " + ROWS.length + " papers";
    document.getElementById("c-papers").textContent = String(ROWS.length);
    renderTableRows();
    syncUrl();
    if (document.getElementById("next-scope").checked) scheduleNextActions();
  }

  function renderTableRows() {
    keyboardActiveIndex = -1;
    var start = currentPage * PAGE_SIZE;
    currentPageRows = currentVisible.slice(start, start + PAGE_SIZE);

    var tbody = document.getElementById("rows");
    clear(tbody);
    currentPageRows.forEach(function (r) {
      var tr = el("tr", { attrs: { "data-pmid": r.pmid } });
      if (state.selected.has(r.pmid)) tr.className = "sel";

      var cb = el("input", { attrs: { type: "checkbox", "aria-label": "Select " + (r.title || r.pmid) } });
      cb.checked = state.selected.has(r.pmid);
      cb.addEventListener("click", function (e) { e.stopPropagation(); });
      cb.addEventListener("change", function () {
        if (cb.checked) state.selected.add(r.pmid); else state.selected.delete(r.pmid);
        renderActionBar();
        tr.className = cb.checked ? "sel" : "";
      });
      tr.appendChild(el("td", { attrs: { "data-label": "Select" } }, [cb]));

      var badge = r.source_badge || "none";
      tr.appendChild(el("td", { attrs: { "data-label": "Source" } }, [
        el("span", { className: "badge", attrs: { style: "--c:" + SOURCE_COLOR[badge] } }, [
          el("i"), el("span", { text: badge === "none" ? "no meta" : badge }),
        ]),
      ]));

      var availSteps = [
        { label: "abs", ok: r.source_badge && r.source_badge !== "metadata-only" },
        { label: "full", ok: r.has_fulltext },
        { label: "pdf", ok: r.has_pdf },
      ];
      var titleCell = el("td", { attrs: { "data-label": "Paper" } }, [
        el("div", { className: "t-title", text: r.title || "(untitled)" }),
        el("div", { className: "t-meta" }, [
          el("span", { className: "t-key", text: (r.citekey || r.pmid) }),
          el("span", { className: "t-avail" }, availSteps.map(function (s) {
            return el("span", { className: "step-mini " + (s.ok ? "ok" : "bad"), text: s.label });
          })),
        ]),
      ]);
      tr.appendChild(titleCell);

      tr.appendChild(el("td", { className: "num", attrs: { "data-label": "Year" }, text: r.year || "" }));
      tr.appendChild(el("td", { attrs: { "data-label": "Journal" }, text: r.journal || "" }));
      tr.appendChild(el("td", { className: "proj", attrs: { "data-label": "Project" }, text: projectLabel(r) }));
      tr.appendChild(el("td", { className: "num", attrs: { "data-label": "Claims" }, text: r.claims_active }));
      var ageCell = el("td", { className: "num", attrs: { "data-label": "Last check" } }, [
        el("span", { className: "age" + (r.stale_check ? " stale" : ""), text: fmtDays(r.days_since_check) }),
      ]);
      tr.appendChild(ageCell);

      tr.addEventListener("click", function () { openDrawer(r.pmid); });
      if (LIVE) {
        tr.addEventListener("dragover", function (e) { if (hasFiles(e)) { e.preventDefault(); tr.classList.add("droptarget"); } });
        tr.addEventListener("dragleave", function () { tr.classList.remove("droptarget"); });
        tr.addEventListener("drop", function (e) {
          tr.classList.remove("droptarget");
          if (!hasFiles(e) || !e.dataTransfer.files[0]) return;
          e.preventDefault();
          var file = e.dataTransfer.files[0];
          openDrawer(r.pmid);
          setDrawerMode("pdf");
          startPdfUpload(r, file);
        });
      }
      tbody.appendChild(tr);
    });
    renderPager();
  }

  function renderPager() {
    var wrap = document.getElementById("pager");
    if (!wrap) return;
    clear(wrap);
    var total = currentVisible.length;
    var pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    if (pages <= 1) return; // nothing to page through -- keep the toolbar clean for small libraries
    wrap.appendChild(el("button", {
      text: "‹ Prev", attrs: { type: "button", disabled: currentPage <= 0 ? "disabled" : null },
      on: { click: function () { if (currentPage > 0) { currentPage--; renderTableRows(); } } },
    }));
    wrap.appendChild(el("span", { className: "pageinfo", text: "page " + (currentPage + 1) + " / " + pages + " · " + total + " papers" }));
    wrap.appendChild(el("button", {
      text: "Next ›", attrs: { type: "button", disabled: currentPage >= pages - 1 ? "disabled" : null },
      on: { click: function () { if (currentPage < pages - 1) { currentPage++; renderTableRows(); } } },
    }));
  }

  document.getElementById("q").addEventListener("input", function (e) { state.query = e.target.value; renderTable(); });
  document.getElementById("proj").addEventListener("change", function (e) { state.project = e.target.value; renderTable(); });

  // P0.3 keyboard shortcuts. Disabled while typing in a text field so "/"
  // and "j"/"k"/"n"/"p" keep working as ordinary characters in the search
  // box, note composer, etc.
  document.addEventListener("keydown", function (e) {
    var target = document.activeElement;
    var tag = (target && target.tagName) || "";
    var typing = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (target && target.isContentEditable);
    var drawerOpen = !document.getElementById("drawer").hidden;

    if (activeTab === "triage") {
      if (!typing && !drawerOpen && !e.metaKey && !e.ctrlKey && !e.altKey) triKeydown(e);
      return;
    }

    if (e.key === "/" && !typing) {
      e.preventDefault();
      document.getElementById("q").focus();
      return;
    }
    if (typing) return;

    if (drawerOpen) {
      if (e.key === "n") { e.preventDefault(); stepDrawer(1); }
      else if (e.key === "p") { e.preventDefault(); stepDrawer(-1); }
      return;
    }

    if (activeTab === "papers" && state.selected.size && !e.metaKey && !e.ctrlKey && !e.altKey) {
      if (e.key === "c") { e.preventDefault(); copyAllCommands(); return; }
      if (e.key === "e") { e.preventDefault(); exportSelectedCSV(); return; }
    }
    if (e.key === "j" || e.key === "ArrowDown") { e.preventDefault(); moveKeyboardActive(1); }
    else if (e.key === "k" || e.key === "ArrowUp") { e.preventDefault(); moveKeyboardActive(-1); }
    else if (e.key === "Enter") {
      if (keyboardActiveIndex >= 0 && currentPageRows[keyboardActiveIndex]) {
        e.preventDefault();
        openDrawer(currentPageRows[keyboardActiveIndex].pmid);
      }
    }
  });

  document.querySelectorAll("th button[data-sort]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var field = btn.dataset.sort;
      var dir = "asc";
      if (state.sort && state.sort.field === field && state.sort.dir === "asc") dir = "desc";
      document.querySelectorAll("th button[data-sort]").forEach(function (b) { b.removeAttribute("data-dir"); });
      btn.setAttribute("data-dir", dir);
      state.sort = { field: field, dir: dir };
      renderTable();
    });
  });

  document.getElementById("selall").addEventListener("change", function (e) {
    currentVisible.forEach(function (r) {
      if (e.target.checked) state.selected.add(r.pmid); else state.selected.delete(r.pmid);
    });
    renderTable();
    renderActionBar();
  });

  // FR-02/FR-03: exports and commands act on the selection *as currently
  // visible* -- selected papers hidden by the active filters are counted in
  // the summary line but never exported or put in a command -- and follow
  // the table's sort order so the output is deterministic.
  function selectedVisibleRows() {
    return currentVisible.filter(function (r) { return state.selected.has(r.pmid); });
  }

  function buildSelectedPMIDList() {
    return selectedVisibleRows().map(function (r) { return r.pmid; });
  }

  var CSV_COLUMNS = ["pmid", "citekey", "title", "year", "journal", "doi", "pmcid", "source_badge", "has_fulltext",
    "has_pdf", "claims_active", "notes_count", "projects", "lint_flags", "days_since_check", "retraction_status"];

  function csvCell(v) {
    if (v === null || v === undefined) return "";
    var s = Array.isArray(v) ? v.join("; ") : String(v);
    if (/^[=+\-@\t\r]/.test(s)) s = "'" + s; // keep spreadsheet apps from evaluating a title as a formula
    return /[",\r\n]/.test(s) ? "\"" + s.replace(/"/g, "\"\"") + "\"" : s;
  }

  function buildSelectedCSV() {
    var lines = [CSV_COLUMNS.join(",")];
    selectedVisibleRows().forEach(function (r) {
      lines.push(CSV_COLUMNS.map(function (c) {
        if (c === "projects") return csvCell(projectLabel(r));
        return csvCell(r[c]);
      }).join(","));
    });
    return lines.join("\r\n") + "\r\n";
  }

  function exportStamp() {
    return new Date().toISOString().slice(0, 10);
  }

  function exportSelectedPMIDs() {
    var pmids = buildSelectedPMIDList();
    if (!pmids.length) { flash("no visible papers selected"); return; }
    downloadText("papers-" + exportStamp() + "-" + pmids.length + ".txt", pmids.join("\n") + "\n");
    copyText(pmids.join("\n"));
  }

  function exportSelectedCSV() {
    var rows = selectedVisibleRows();
    if (!rows.length) { flash("no visible papers selected"); return; }
    downloadText("papers-" + exportStamp() + "-" + rows.length + ".csv", "\ufeff" + buildSelectedCSV(), "text/csv;charset=utf-8");
    flash("exported " + rows.length + " papers");
  }

  function selectionCommands() {
    var groups = { fetch: [], extract: [], fetchpdf: [], audit: [] };
    selectedVisibleRows().forEach(function (r) {
      if (needsFetch(r)) groups.fetch.push(r.pmid);
      if (needsExtract(r)) groups.extract.push(r.pmid);
      if (needsFetchPdf(r)) groups.fetchpdf.push(r.pmid);
      if (needsAudit(r)) groups.audit.push(r.pmid);
    });
    return groups;
  }

  function copyAllCommands() {
    var g = selectionCommands();
    var block = [
      g.fetch.length ? "/ref:fetch " + g.fetch.join(" ") : "",
      g.extract.length ? "/ref:extract " + g.extract.join(" ") : "",
      g.fetchpdf.length ? "/ref:fetch-pdf " + g.fetchpdf.join(" ") : "",
      g.audit.length ? "/ref:audit " + g.audit.join(" ") : "",
    ].filter(Boolean);
    if (!block.length) { flash("nothing in the visible selection needs a repair command"); return; }
    copyText(block.join("\n"));
  }

  function renderActionBar() {
    var bar = document.getElementById("actionbar");
    var n = state.selected.size;
    if (!n) { bar.hidden = true; return; }
    bar.hidden = false;
    document.getElementById("seln").textContent = String(n);
    var g = selectionCommands();
    var fetchPmids = g.fetch, extractPmids = g.extract, fetchPdfPmids = g.fetchpdf, auditPmids = g.audit;
    var visibleN = selectedVisibleRows().length;
    var parts = [
      fetchPmids.length + " need fetch", extractPmids.length + " need extract",
      fetchPdfPmids.length + " need PDF", auditPmids.length + " stale",
    ];
    if (visibleN < n) parts.push((n - visibleN) + " hidden by filters (left out)");
    document.getElementById("selsummary").textContent = "· " + parts.join(" · ");
    var fetchCmd = fetchPmids.length ? "/ref:fetch " + fetchPmids.join(" ") : "";
    var extractCmd = extractPmids.length ? "/ref:extract " + extractPmids.join(" ") : "";
    var fetchPdfCmd = fetchPdfPmids.length ? "/ref:fetch-pdf " + fetchPdfPmids.join(" ") : "";
    var auditCmd = auditPmids.length ? "/ref:audit " + auditPmids.join(" ") : "";
    document.getElementById("cmd-fetch").textContent = fetchCmd || "(none need /ref:fetch)";
    document.getElementById("cmd-extract").textContent = extractCmd || "(none need /ref:extract)";
    document.getElementById("cmd-fetchpdf").textContent = fetchPdfCmd || "(none need /ref:fetch-pdf)";
    document.getElementById("cmd-audit").textContent = auditCmd || "(none stale for /ref:audit)";
    document.querySelectorAll("[data-copy]").forEach(function (btn) {
      btn.onclick = function () {
        var text = document.getElementById(btn.dataset.copy).textContent;
        if (text.charAt(0) === "(") return;
        copyText(text);
      };
    });
  }
  document.getElementById("exp-pmids").addEventListener("click", exportSelectedPMIDs);
  document.getElementById("exp-csv").addEventListener("click", exportSelectedCSV);
  document.getElementById("copy-cmds").addEventListener("click", copyAllCommands);
  document.getElementById("clearsel").addEventListener("click", function () {
    state.selected.clear();
    renderTable();
    renderActionBar();
  });

  // ------------------------------------------------------- saved views (P1.1)
  //
  // Named filter/sort/project combinations, persisted in this browser's
  // localStorage only -- like the note drafts, there is no write path back
  // into the library, so saved views never leave the browser they were
  // created in.

  var VIEWS_KEY = "ref-dashboard-views";

  function loadViews() {
    try { return JSON.parse(localStorage.getItem(VIEWS_KEY) || "[]"); } catch (e) { return []; }
  }
  function saveViews(list) {
    try { localStorage.setItem(VIEWS_KEY, JSON.stringify(list)); } catch (e) { /* private mode etc. */ }
  }

  function captureView() {
    return {
      query: state.query,
      project: state.project,
      sort: state.sort,
      issues: state.chips.filter(function (c) { return c.id.indexOf("issue:") === 0; }).map(function (c) {
        return { bucket: c.id.slice("issue:".length), label: c.label.replace(/^issue: /, "") };
      }),
      source: sourceFilterSet ? Array.from(sourceFilterSet) : null,
    };
  }

  function applyView(v) {
    state.query = v.query || "";
    document.getElementById("q").value = state.query;
    state.project = v.project || "all";
    document.getElementById("proj").value = state.project;
    state.sort = v.sort || null;
    document.querySelectorAll("th button[data-sort]").forEach(function (b) { b.removeAttribute("data-dir"); });
    if (state.sort) {
      var sortBtn = document.querySelector('th button[data-sort="' + state.sort.field + '"]');
      if (sortBtn) sortBtn.setAttribute("data-dir", state.sort.dir);
    }
    state.chips = (v.issues || []).map(function (i) {
      return {
        id: "issue:" + i.bucket, label: "issue: " + i.label,
        pred: function (r) { return (r.lint_flags || []).indexOf(i.bucket) >= 0; },
      };
    });
    sourceFilterSet = v.source && v.source.length ? new Set(v.source) : null;
    renderSourceCoverage();
    renderChips();
    renderTable();
  }

  function renderViewSelect() {
    var sel = document.getElementById("viewselect");
    var current = sel.value;
    clear(sel);
    sel.appendChild(el("option", { attrs: { value: "" }, text: "Saved views…" }));
    loadViews().forEach(function (v) { sel.appendChild(el("option", { attrs: { value: v.name }, text: v.name })); });
    if (Array.prototype.some.call(sel.options, function (o) { return o.value === current; })) sel.value = current;
  }
  renderViewSelect();

  // ---------------------------------------------- shareable URL state (FR-01)
  //
  // The core view state (tab, search, project, issue chips, source filter,
  // sort, insight view) lives in the query string and is kept current with
  // history.replaceState. Precedence: the URL is read once on load; after
  // that the page state is the truth and the URL follows it -- applying a
  // saved view just changes page state, which rewrites the URL. Other params
  // (the live token, a ?paper= deep link) and the #triage/ hash are kept.
  // Set-of-PMIDs chips from the Insights tab are deliberately not encoded.

  var VIEW_PARAM_KEYS = ["tab", "q", "project", "issue", "source", "sort", "insight"];
  var SORT_FIELDS = ["source_badge", "title", "year", "journal", "project", "claims_active", "days_since_check"];
  var urlSyncEnabled = false;

  function encodeViewState() {
    var p = new URLSearchParams();
    if (activeTab !== "papers" && activeTab !== "triage") p.set("tab", activeTab);
    if (state.query) p.set("q", state.query);
    if (state.project !== "all") p.set("project", state.project);
    state.chips.forEach(function (c) { if (c.id.indexOf("issue:") === 0) p.append("issue", c.id.slice(6)); });
    if (sourceFilterSet) p.set("source", Array.from(sourceFilterSet).join(","));
    if (state.sort) p.set("sort", state.sort.field + ":" + state.sort.dir);
    if (activeTab === "insights" && ins.view !== "evidence") p.set("insight", ins.view);
    return p;
  }

  function decodeViewState(search) {
    var p;
    try { p = new URLSearchParams(search); } catch (e) { return null; }
    if (!VIEW_PARAM_KEYS.some(function (k) { return p.has(k); })) return null;
    var sort = null;
    var sm = /^([a-z_]+):(asc|desc)$/.exec(p.get("sort") || "");
    if (sm && SORT_FIELDS.indexOf(sm[1]) >= 0) sort = { field: sm[1], dir: sm[2] };
    var source = (p.get("source") || "").split(",").filter(function (b) {
      return SOURCE_BADGES.indexOf(b) >= 0 || b === "none";
    });
    return {
      tab: p.get("tab"),
      insight: p.get("insight"),
      query: p.get("q") || "",
      project: p.get("project") || "all",
      sort: sort,
      source: source.length ? source : null,
      issues: p.getAll("issue").filter(function (b) { return LINT_BUCKET_LABELS.hasOwnProperty(b); })
        .map(function (b) { return { bucket: b, label: LINT_BUCKET_LABELS[b] }; }),
    };
  }

  function applyViewState(v) {
    if (!v) return;
    if (v.project !== "all" && !Array.prototype.some.call(document.getElementById("proj").options, function (o) { return o.value === v.project; })) {
      document.getElementById("proj").appendChild(el("option", { attrs: { value: v.project }, text: v.project + " (no papers)" }));
    }
    if (v.insight && INSIGHT_VIEWS.some(function (x) { return x.id === v.insight; })) ins.view = v.insight;
    applyView(v);
    if (v.tab && TABS.indexOf(v.tab) >= 0 && v.tab !== "triage") {
      selectTab(v.tab);
      renderTabContent(v.tab);
    }
  }

  function syncUrl() {
    if (!urlSyncEnabled) return;
    try {
      var params = new URLSearchParams(location.search);
      VIEW_PARAM_KEYS.forEach(function (k) { params.delete(k); });
      encodeViewState().forEach(function (v, k) { params.append(k, v); });
      var qs = params.toString();
      history.replaceState(null, "", location.pathname + (qs ? "?" + qs : "") + location.hash);
    } catch (e) { /* file:// pages in some browsers refuse replaceState -- the link buttons still work */ }
  }

  function viewLink() {
    var params = new URLSearchParams(location.search);
    VIEW_PARAM_KEYS.forEach(function (k) { params.delete(k); });
    params.delete("paper");
    params.delete("tab");
    encodeViewState().forEach(function (v, k) { params.append(k, v); });
    var qs = params.toString();
    return location.origin + location.pathname + (qs ? "?" + qs : "");
  }

  document.getElementById("view-link").addEventListener("click", function () {
    copyText(viewLink());
    if (LIVE) flash("link copied -- it carries this server's token, so it works until the server stops", 3200);
  });
  document.getElementById("view-cmd").addEventListener("click", function () {
    var qs = encodeViewState().toString();
    copyText("/ref:dashboard" + (qs ? " --view '" + qs.replace(/'/g, "%27") + "'" : ""));
  });

  document.getElementById("view-apply").addEventListener("click", function () {
    var name = document.getElementById("viewselect").value;
    if (!name) return;
    var views = loadViews();
    for (var i = 0; i < views.length; i++) if (views[i].name === name) { applyView(views[i]); return; }
  });
  document.getElementById("view-save").addEventListener("click", function () {
    var name = (window.prompt("Save current filters as:") || "").trim();
    if (!name) return;
    var views = loadViews().filter(function (v) { return v.name !== name; });
    var view = captureView();
    view.name = name;
    views.push(view);
    saveViews(views);
    renderViewSelect();
    document.getElementById("viewselect").value = name;
  });
  document.getElementById("view-rename").addEventListener("click", function () {
    var sel = document.getElementById("viewselect");
    var oldName = sel.value;
    if (!oldName) return;
    var newName = (window.prompt("Rename view:", oldName) || "").trim();
    if (!newName || newName === oldName) return;
    var views = loadViews().filter(function (v) { return v.name !== newName; });
    views.forEach(function (v) { if (v.name === oldName) v.name = newName; });
    saveViews(views);
    renderViewSelect();
    sel.value = newName;
  });
  document.getElementById("view-delete").addEventListener("click", function () {
    var sel = document.getElementById("viewselect");
    var name = sel.value;
    if (!name) return;
    saveViews(loadViews().filter(function (v) { return v.name !== name; }));
    renderViewSelect();
  });

  // populate project select -- derived from rows() (projectSummaries()) so
  // it stays correct after a live refresh, not just at initial load.
  function renderProjectSelect() {
    var sel = document.getElementById("proj");
    var current = sel.value;
    clear(sel);
    sel.appendChild(el("option", { attrs: { value: "all" }, text: "All projects" }));
    var projects = projectSummaries();
    projects.forEach(function (p) {
      sel.appendChild(el("option", { attrs: { value: p.slug }, text: p.slug }));
    });
    sel.appendChild(el("option", { attrs: { value: "none" }, text: "No project" }));
    if (Array.prototype.some.call(sel.options, function (o) { return o.value === current; })) sel.value = current;
    document.getElementById("c-projects").textContent = String(projects.length);
  }

  // ---------------------------------------------------------- coverage

  var coverageRendered = false;
  var MATRIX_PAGE_SIZE = 200; // P2.2: windowed rendering so opening the tab stays instant on large libraries
  var matrixPage = 0;

  function renderCoverageMatrix() {
    if (coverageRendered) return;
    coverageRendered = true;
    matrixPage = 0;
    renderCoverageMatrixRows();
  }

  function renderCoverageMatrixRows() {
    var cols = MATRIX_COLUMNS_LIVE;
    var table = document.getElementById("heat");
    clear(table);
    var thead = el("tr", {}, [el("th", { className: "rowlbl", text: "pmid" })].concat(
      cols.map(function (c) { return el("th", { className: "col", text: c }); })
    ));
    table.appendChild(thead);
    var start = matrixPage * MATRIX_PAGE_SIZE;
    var pageRows = MATRIX_ROWS_LIVE.slice(start, start + MATRIX_PAGE_SIZE);
    pageRows.forEach(function (row) {
      var tr = el("tr", {}, [el("td", { className: "rowlbl", text: row.pmid })].concat(
        cols.map(function (c) {
          return el("td", {}, [el("div", { className: "cell" + (row[c] ? " on" : ""), attrs: { title: c + ": " + (row[c] ? "yes" : "no") } })]);
        })
      ));
      table.appendChild(tr);
    });
    renderMatrixPager();
  }

  function renderMatrixPager() {
    var wrap = document.getElementById("matrix-pager");
    if (!wrap) return;
    clear(wrap);
    var total = MATRIX_ROWS_LIVE.length;
    var pages = Math.max(1, Math.ceil(total / MATRIX_PAGE_SIZE));
    if (pages <= 1) return;
    wrap.appendChild(el("button", {
      text: "‹ Prev", attrs: { type: "button", disabled: matrixPage <= 0 ? "disabled" : null },
      on: { click: function () { if (matrixPage > 0) { matrixPage--; renderCoverageMatrixRows(); } } },
    }));
    wrap.appendChild(el("span", { className: "pageinfo", text: "page " + (matrixPage + 1) + " / " + pages + " · " + total + " papers" }));
    wrap.appendChild(el("button", {
      text: "Next ›", attrs: { type: "button", disabled: matrixPage >= pages - 1 ? "disabled" : null },
      on: { click: function () { if (matrixPage < pages - 1) { matrixPage++; renderCoverageMatrixRows(); } } },
    }));
  }

  // ---------------------------------------------------------- projects

  var READING_COLOR = { reading: "var(--accent)", to_read: "var(--s-oa)", done: "var(--good)", skipped: "var(--faint)" };

  function renderProjects() {
    var wrap = document.getElementById("p-projects");
    clear(wrap);
    var projects = projectSummaries();
    TRIAGES.forEach(function (t) {
      if (t.project && !projects.some(function (p) { return p.slug === t.project; })) {
        projects.push({ slug: t.project, papers: [] });
      }
    });
    projects.sort(function (a, b) { return a.slug < b.slug ? -1 : a.slug > b.slug ? 1 : 0; });
    if (!projects.length) {
      wrap.appendChild(el("div", { className: "empty", text: "no projects yet -- see /ref:project" }));
      return;
    }
    projects.forEach(function (p) {
      var statusCounts = {};
      var fulltext = 0, claimedPapers = 0, claims = 0;
      var fetchPmids = [], extractPmids = [];
      p.papers.forEach(function (paper) {
        var s = paper.reading_status || "unset";
        statusCounts[s] = (statusCounts[s] || 0) + 1;
        if (paper.has_fulltext) fulltext++;
        if (paper.claims_active > 0) claimedPapers++;
        claims += paper.claims_active || 0;
        if (needsFetch(paper)) fetchPmids.push(paper.pmid);
        if (needsExtract(paper)) extractPmids.push(paper.pmid);
      });
      var total = p.papers.length || 1;
      var pbar = el("div", { className: "pbar" });
      var plegend = el("div", { className: "plegend" });
      Object.keys(statusCounts).forEach(function (s) {
        var count = statusCounts[s];
        var color = READING_COLOR[s] || "var(--muted)";
        pbar.appendChild(el("div", { attrs: { style: "flex:" + count + ";background:" + color } }));
        plegend.appendChild(el("span", {}, [
          el("i", { attrs: { style: "background:" + color } }),
          document.createTextNode(s + " (" + count + ")"),
        ]));
      });
      var kv = el("dl", { className: "kv" }, [
        el("span", { text: "papers" }), el("span", { text: p.papers.length }),
        el("span", { text: "full text coverage" }), el("span", { text: fulltext + "/" + p.papers.length + " (" + Math.round(fulltext / total * 100) + "%)" }),
        el("span", { text: "claim extraction coverage" }), el("span", { text: claimedPapers + "/" + p.papers.length + " (" + Math.round(claimedPapers / total * 100) + "%)" }),
        el("span", { text: "active claims" }), el("span", { text: claims }),
      ]);
      var cmds = el("div", { className: "pcmds" });
      if (fetchPmids.length) {
        cmds.appendChild(el("button", {
          className: "cmdbtn", text: "Copy /ref:fetch (" + fetchPmids.length + ")", attrs: { type: "button" },
          on: { click: function () { copyText("/ref:fetch " + fetchPmids.join(" ")); } },
        }));
      }
      if (extractPmids.length) {
        cmds.appendChild(el("button", {
          className: "cmdbtn", text: "Copy /ref:extract (" + extractPmids.length + ")", attrs: { type: "button" },
          on: { click: function () { copyText("/ref:extract " + extractPmids.join(" ")); } },
        }));
      }
      cmds.appendChild(el("button", {
        className: "cmdbtn", text: "View in Papers", attrs: { type: "button" },
        on: {
          click: function () {
            state.project = p.slug;
            document.getElementById("proj").value = p.slug;
            selectTab("papers");
            renderTable();
          },
        },
      }));
      var triList = null;
      var linked = TRIAGES.filter(function (t) { return t.project === p.slug; });
      if (linked.length) {
        triList = el("dl", { className: "kv" });
        linked.forEach(function (t) {
          triList.appendChild(el("span", {}, [el("button", {
            className: "cmdbtn", text: "Triage: " + t.slug, attrs: { type: "button" },
            on: { click: function () { selectTab("triage"); selectTriage(t.slug); } },
          })]));
          triList.appendChild(el("span", { text: t.found + " found · " + t.loaded + " loaded · " + t.decided + " decided" }));
        });
      }
      wrap.appendChild(el("article", { className: "panel" }, [
        el("h2", { text: p.slug }),
        pbar, plegend, kv, triList, cmds,
      ]));
    });
  }

  // ---------------------------------------------------- next actions (FR-04)
  //
  // Ranking lives in dashboard_insights.next_actions() (weight x papers x
  // project boost); this only renders it. With "limit to the current
  // Papers filters" on, each action's papers are intersected with the
  // visible rows and re-scored with the same formula -- debounced, so the
  // list doesn't churn on every keystroke.

  var nextTimer = null;
  function scheduleNextActions() {
    clearTimeout(nextTimer);
    nextTimer = setTimeout(renderNextActions, 350);
  }

  function actionForScope(a, visible) {
    if (!visible || !a.pmids || a.type === "catalog_stale") return a;
    var pmids = a.pmids.filter(function (p) { return visible.has(p); });
    if (!pmids.length) return null;
    var copy = {};
    for (var k in a) copy[k] = a[k];
    copy.pmids = pmids;
    copy.count = pmids.length;
    copy.score = Math.round(a.weight * pmids.length * a.boost * 100) / 100;
    copy.label = a.template.replace("{n}", pmids.length + " paper" + (pmids.length === 1 ? "" : "s"));
    copy.suggested_command = a.command_base && pmids.length <= 50 ? a.command_base + " " + pmids.join(" ") : a.suggested_command;
    copy.why = a.why.replace(/× \d+/, "× " + pmids.length) + " · within current filters";
    return copy;
  }

  function renderNextActions() {
    var list = document.getElementById("next-actions");
    clear(list);
    var caption = document.getElementById("next-caption");
    if (!SUMMARY) {
      caption.textContent = "";
      list.appendChild(el("li", { className: "empty", text: LIVE ? "summary not loaded yet" : "rebuild the dashboard to rank next actions" }));
      return;
    }
    var scoped = document.getElementById("next-scope").checked;
    var visible = scoped ? new Set(currentVisible.map(function (r) { return r.pmid; })) : null;
    var actions = (SUMMARY.top_actions || []).map(function (a) { return actionForScope(a, visible); }).filter(Boolean);
    actions.sort(function (a, b) { return b.score - a.score || (a.id < b.id ? -1 : 1); });
    actions = actions.slice(0, 8);
    caption.textContent = SUMMARY.paper_count + " papers · " + SUMMARY.issues_total + " open issues · ranked " +
      String(SUMMARY.generated_at || "").slice(0, 16).replace("T", " ");
    if (!actions.length) {
      list.appendChild(el("li", { className: "empty", text: scoped ? "nothing to do for the papers in the current filters" : "nothing to do -- the library is healthy" }));
      return;
    }
    actions.forEach(function (a, i) {
      var btns = el("div", { className: "nextbtns" }, [
        el("button", {
          className: "cmdbtn", text: "Copy", attrs: { type: "button", "aria-label": "Copy command for: " + a.label },
          on: { click: function () { copyText(a.suggested_command); } },
        }),
      ]);
      if (a.type !== "catalog_stale" && LINT_BUCKET_LABELS[a.type]) {
        btns.appendChild(el("button", {
          className: "cmdbtn", text: "Show papers", attrs: { type: "button" },
          on: { click: function () {
            if (a.project) { state.project = a.project; document.getElementById("proj").value = a.project; }
            applyIssueFilter(a.type, LINT_BUCKET_LABELS[a.type]);
          } },
        }));
      }
      list.appendChild(el("li", {}, [
        el("span", { className: "rank", text: String(i + 1) }),
        el("div", { className: "nextbody" }, [
          el("div", {}, [
            el("b", { text: a.label }),
            a.project ? el("span", { className: "scope", text: a.project }) : null,
            el("span", { className: "score", text: "score " + a.score }),
          ]),
          el("div", { className: "why", text: a.why }),
          el("code", { text: a.suggested_command }),
        ]),
        btns,
      ]));
    });
  }
  document.getElementById("next-scope").addEventListener("change", renderNextActions);

  // /api/health indicator (live only). Uses apiFetch directly: a 503 "down"
  // body is still the health model we want to show.
  function loadHealth() {
    if (!LIVE) return;
    apiFetch("/api/health").then(function (r) { return r.json(); }).then(renderHealthPill, function () {
      renderHealthPill({ status: "down", warnings: ["/api/health unreachable"], data_sources: {} });
    });
  }

  function renderHealthPill(h) {
    var pill = document.getElementById("api-health");
    pill.hidden = false;
    pill.setAttribute("data-status", h.status || "down");
    pill.querySelector("span").textContent = "API " + (h.status || "down");
    var details = document.getElementById("health-details");
    clear(details);
    var failed = Object.keys(h.data_sources || {}).filter(function (k) { return h.data_sources[k] !== "ok"; });
    var lines = failed.map(function (k) { return k + ": " + h.data_sources[k]; }).concat(h.warnings || []);
    pill.title = lines.length ? lines.join("\n") : "all data sources ok";
    details.appendChild(el("b", { text: "API health: " + (h.status || "down") }));
    var ul = el("ul");
    (lines.length ? lines : ["rows, lint, matrix and snapshots all loaded"]).forEach(function (l) { ul.appendChild(el("li", { text: l })); });
    details.appendChild(ul);
  }
  document.getElementById("api-health").addEventListener("click", function () {
    var d = document.getElementById("health-details");
    d.hidden = !d.hidden;
    this.setAttribute("aria-expanded", String(!d.hidden));
  });

  // -------------------------------------------------------- maintenance

  var maintRendered = false;
  function renderMaintenance() {
    if (maintRendered) return;
    maintRendered = true;
    var snaps = SNAPSHOTS;
    document.getElementById("maint-caption").textContent = snaps.length ? (snaps[0].stamp + " → " + snaps[snaps.length - 1].stamp) : "";
    var sparksWrap = document.getElementById("sparks");
    clear(sparksWrap);
    if (!snaps.length) {
      sparksWrap.appendChild(el("div", { className: "empty", text: "no /ref:lint --snapshot history yet" }));
    } else {
      var buckets = Object.keys(snaps[snaps.length - 1].issues || {});
      buckets.forEach(function (bucket) {
        var series = snaps.map(function (s) { return (s.issues && s.issues[bucket] || []).length; });
        var last = series[series.length - 1];
        var prev = series.length > 1 ? series[series.length - 2] : last;
        var delta = last - prev;
        var svg = svgEl("svg", { viewBox: "0 0 120 24", class: "chart", style: "height:24px" });
        var max = Math.max.apply(null, series.concat([1]));
        var stepX = 120 / Math.max(1, series.length - 1);
        var pts = series.map(function (v, i) { return (i * stepX) + "," + (22 - (v / max) * 20); });
        svg.appendChild(svgEl("polyline", { points: pts.join(" "), fill: "none", stroke: "var(--accent)", "stroke-width": 1.5 }));
        sparksWrap.appendChild(el("div", { className: "spark" }, [
          el("span", { className: "k", text: LINT_BUCKET_LABELS[bucket] || bucket }),
          svg,
          el("span", { className: "val", text: last }),
          el("span", { className: "d " + (delta > 0 ? "up" : delta < 0 ? "down" : ""), text: (delta > 0 ? "+" : "") + delta }),
        ]));
      });
    }

    var changes = document.getElementById("changes");
    clear(changes);
    if (snaps.length < 2) {
      changes.appendChild(el("li", { text: "not enough snapshots yet" }));
    } else {
      var prevSnap = snaps[snaps.length - 2], lastSnap = snaps[snaps.length - 1];
      var buckets2 = Object.keys(lastSnap.issues || {});
      buckets2.forEach(function (bucket) {
        var before = new Set(prevSnap.issues && prevSnap.issues[bucket] || []);
        var after = new Set(lastSnap.issues && lastSnap.issues[bucket] || []);
        var added = Array.from(after).filter(function (p) { return !before.has(p); });
        var removed = Array.from(before).filter(function (p) { return !after.has(p); });
        if (!added.length && !removed.length) return;
        var parts = [];
        if (added.length) parts.push("+" + added.join(", +"));
        if (removed.length) parts.push("-" + removed.join(", -"));
        changes.appendChild(el("li", {}, [
          el("span", { className: "pm", text: LINT_BUCKET_LABELS[bucket] || bucket }),
          el("span", { text: parts.join("  ") }),
        ]));
      });
      if (!changes.children.length) changes.appendChild(el("li", { text: "no changes since the previous snapshot" }));
    }

    // P1.2: the same before/after diff, regrouped by pmid instead of
    // bucket -- "which papers changed and why" rather than "which buckets
    // grew/shrank", built from the identical two snapshots so the two
    // panels can never disagree.
    var changesByPaper = document.getElementById("changes-by-paper");
    clear(changesByPaper);
    if (snaps.length < 2) {
      changesByPaper.appendChild(el("li", { text: "not enough snapshots yet" }));
    } else {
      var prevSnap2 = snaps[snaps.length - 2], lastSnap2 = snaps[snaps.length - 1];
      var buckets3 = Object.keys(lastSnap2.issues || {});
      var byPmid = {}; // pmid -> {added: [bucket], removed: [bucket]}
      buckets3.forEach(function (bucket) {
        var before = new Set(prevSnap2.issues && prevSnap2.issues[bucket] || []);
        var after = new Set(lastSnap2.issues && lastSnap2.issues[bucket] || []);
        after.forEach(function (pmid) {
          if (before.has(pmid)) return;
          byPmid[pmid] = byPmid[pmid] || { added: [], removed: [] };
          byPmid[pmid].added.push(bucket);
        });
        before.forEach(function (pmid) {
          if (after.has(pmid)) return;
          byPmid[pmid] = byPmid[pmid] || { added: [], removed: [] };
          byPmid[pmid].removed.push(bucket);
        });
      });
      var pmids = Object.keys(byPmid).sort();
      pmids.forEach(function (pmid) {
        var d = byPmid[pmid];
        var row = BY_PMID[pmid];
        var title = row ? (row.title || "(untitled)") : "(not in current library)";
        var parts = [];
        d.added.forEach(function (b) { parts.push("+" + (LINT_BUCKET_LABELS[b] || b)); });
        d.removed.forEach(function (b) { parts.push("resolved " + (LINT_BUCKET_LABELS[b] || b)); });
        changesByPaper.appendChild(el("li", {}, [
          el("span", { className: "pm", text: pmid }),
          el("span", {}, [
            el("span", { text: title }),
            el("br"),
            el("span", { className: "cmd", text: parts.join("  ") }),
          ]),
        ]));
      });
      if (!pmids.length) changesByPaper.appendChild(el("li", { text: "no changes since the previous snapshot" }));
    }
  }

  // -------------------------------------------------------------- drawer

  var drawerState = { pmid: null, mode: "details" };
  var loadedDetails = {};

  function loadDetail(pmid, cb) {
    if (loadedDetails[pmid]) { cb(loadedDetails[pmid]); return; }
    if (LIVE) {
      apiFetch("/api/paper/" + encodeURIComponent(pmid))
        .then(function (r) { if (!r.ok) throw new Error("http " + r.status); return r.json(); })
        .then(function (detail) { loadedDetails[pmid] = detail; cb(detail); })
        .catch(function () { cb(null); });
      return;
    }
    window.__paperDetail = function (loadedPmid, detail) {
      loadedDetails[loadedPmid] = detail;
      if (loadedPmid === pmid) cb(detail);
    };
    var script = document.createElement("script");
    script.src = "details/" + encodeURIComponent(pmid) + ".js";
    script.onerror = function () { cb(null); };
    document.body.appendChild(script);
  }

  // P0.4: the element focused right before the drawer opens (a table row's
  // checkbox, or nothing if opened via keyboard Enter) gets focus back on
  // close, so keyboard-only browsing of the table can continue where it
  // left off instead of dropping focus to <body>.
  var lastFocusedBeforeDrawer = null;

  function drawerFocusables() {
    var drawer = document.getElementById("drawer");
    return Array.prototype.filter.call(
      drawer.querySelectorAll('button:not([disabled]), [href], input, textarea, select, [tabindex]:not([tabindex="-1"])'),
      function (node) { return node.offsetParent !== null; }
    );
  }

  function openDrawer(pmid) {
    lastFocusedBeforeDrawer = document.activeElement;
    drawerState.pmid = pmid;
    drawerState.mode = "details";
    document.getElementById("scrim").hidden = false;
    document.getElementById("drawer").hidden = false;
    // P2.4: hide the (still visible, but now non-interactive) background
    // content from assistive tech while the drawer is modal -- the drawer
    // itself is a sibling of .wrap, not inside it, so this never hides the
    // drawer.
    var wrap = document.querySelector(".wrap");
    if (wrap) wrap.setAttribute("aria-hidden", "true");
    setDrawerMode("details");
    renderDrawerHeader();
    loadDetail(pmid, function (detail) { renderDrawerBody(detail); });
    var focusables = drawerFocusables();
    if (focusables.length) focusables[0].focus();
  }

  function closeDrawer() {
    document.getElementById("scrim").hidden = true;
    document.getElementById("drawer").hidden = true;
    drawerState.pmid = null;
    var wrap = document.querySelector(".wrap");
    if (wrap) wrap.removeAttribute("aria-hidden");
    if (lastFocusedBeforeDrawer && document.contains(lastFocusedBeforeDrawer)) lastFocusedBeforeDrawer.focus();
    lastFocusedBeforeDrawer = null;
  }

  document.getElementById("d-close").addEventListener("click", closeDrawer);
  document.getElementById("scrim").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !document.getElementById("drawer").hidden) closeDrawer(); });

  // Focus trap (P0.4): Tab/Shift+Tab cycles within the drawer's focusable
  // elements while it's open, so keyboard focus never escapes to the
  // (visually dimmed, non-interactive) background content.
  document.getElementById("drawer").addEventListener("keydown", function (e) {
    if (e.key !== "Tab") return;
    var focusables = drawerFocusables();
    if (!focusables.length) return;
    var first = focusables[0], last = focusables[focusables.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });

  document.getElementById("d-prev").addEventListener("click", function () { stepDrawer(-1); });
  document.getElementById("d-next").addEventListener("click", function () { stepDrawer(1); });

  function stepDrawer(delta) {
    var idx = currentVisible.findIndex(function (r) { return r.pmid === drawerState.pmid; });
    if (idx < 0) return;
    var next = idx + delta;
    if (next < 0 || next >= currentVisible.length) return;
    openDrawer(currentVisible[next].pmid);
  }

  document.getElementById("m-details").addEventListener("click", function () { setDrawerMode("details"); });
  document.getElementById("m-pdf").addEventListener("click", function () { setDrawerMode("pdf"); });

  function setDrawerMode(mode) {
    drawerState.mode = mode;
    document.getElementById("m-details").setAttribute("aria-pressed", String(mode === "details"));
    document.getElementById("m-pdf").setAttribute("aria-pressed", String(mode === "pdf"));
    document.getElementById("d-body").hidden = mode !== "details";
    document.getElementById("d-sections").hidden = mode !== "details";
    document.getElementById("d-pdf").hidden = mode !== "pdf";
    if (mode === "pdf") renderPdfTab();
  }

  function renderDrawerHeader() {
    var row = BY_PMID[drawerState.pmid];
    if (!row) return;
    var idx = currentVisible.findIndex(function (r) { return r.pmid === drawerState.pmid; });
    document.getElementById("d-pos").textContent = (idx >= 0 ? (idx + 1) + " / " + currentVisible.length : "");
    document.getElementById("d-prev").disabled = idx <= 0;
    document.getElementById("d-next").disabled = idx < 0 || idx >= currentVisible.length - 1;

    var badges = document.getElementById("d-badges");
    clear(badges);
    var badge = row.source_badge || "none";
    badges.appendChild(el("span", { className: "badge", attrs: { style: "--c:" + SOURCE_COLOR[badge] } }, [
      el("i"), el("span", { text: badge === "none" ? "no meta" : badge }),
    ]));
    if (row.retraction_status && row.retraction_status !== "unknown") {
      badges.appendChild(el("span", { className: "flag crit", text: row.retraction_status }));
    }
    if (row.stale_check) badges.appendChild(el("span", { className: "flag", text: "stale check" }));

    document.getElementById("d-title").textContent = row.title || "(untitled)";
    var byline = [row.journal, row.year, row.authors_count ? row.authors_count + " authors" : null]
      .filter(Boolean).join(" · ");
    document.getElementById("d-byline").textContent = byline;
  }

  var SECTIONS = ["overview", "notes", "authors", "abstract", "funding", "figures", "claims", "files"];
  var SECTION_LABELS = {
    overview: "Overview", notes: "Notes", authors: "Authors", abstract: "Abstract",
    funding: "Funding & acknowledgements", figures: "Figures", claims: "Claims", files: "Files",
  };

  function renderDrawerBody(detail) {
    var body = document.getElementById("d-body");
    clear(body);
    var navWrap = document.getElementById("d-sections");
    clear(navWrap);
    var footWrap = document.getElementById("d-foot");
    clear(footWrap);
    var row = BY_PMID[drawerState.pmid];

    if (!detail) {
      body.appendChild(el("div", { className: "empty", text: "could not load details for this paper." }));
      return;
    }

    SECTIONS.forEach(function (sec) {
      var btn = el("button", { text: SECTION_LABELS[sec], attrs: { type: "button" } });
      btn.addEventListener("click", function () {
        var target = document.getElementById("sec-" + sec);
        if (target) target.scrollIntoView({ block: "start" });
      });
      navWrap.appendChild(btn);
    });

    body.appendChild(sectionOverview(row, detail));
    body.appendChild(sectionNotes(row, detail));
    body.appendChild(sectionAuthors(detail));
    body.appendChild(sectionAbstract(detail));
    body.appendChild(sectionFunding(detail));
    body.appendChild(sectionFigures(detail));
    body.appendChild(sectionClaims(detail));
    body.appendChild(sectionFiles(detail));

    if (needsFetch(row)) {
      footWrap.appendChild(el("button", {
        className: "cmdbtn primary", text: "/ref:fetch " + row.pmid,
        on: { click: function () { copyText("/ref:fetch " + row.pmid); } },
      }));
    }
    if (needsExtract(row)) {
      footWrap.appendChild(el("button", {
        className: "cmdbtn", text: "/ref:extract " + row.pmid,
        on: { click: function () { copyText("/ref:extract " + row.pmid); } },
      }));
    }
    footWrap.appendChild(el("button", {
      className: "cmdbtn", text: "/ref:cite " + row.pmid,
      on: { click: function () { copyText("/ref:cite " + row.pmid); } },
    }));
  }

  function sec(id, title, kids) {
    return el("div", { className: "d-sec", attrs: { id: "sec-" + id } }, [
      el("h3", { text: title }),
    ].concat(kids));
  }

  function sectionOverview(row, detail) {
    var steps = [
      { label: "metadata", ok: !!row.source_badge },
      { label: "abstract", ok: row.source_badge && row.source_badge !== "metadata-only" },
      { label: "full text", ok: row.has_fulltext },
      { label: "pdf", ok: row.has_pdf },
      { label: "claims", ok: row.claims_active > 0 },
      { label: "indexed", ok: row.in_catalog },
    ];
    var stepsWrap = el("div", { className: "steps" }, steps.map(function (s) {
      return el("span", { className: "step " + (s.ok ? "ok" : "bad"), text: s.label });
    }));
    var facts = el("dl", { className: "facts" }, [
      el("dt", { text: "PMID" }), el("dd", { text: row.pmid }),
      el("dt", { text: "citekey" }), el("dd", { text: row.citekey || "" }),
      el("dt", { text: "DOI" }), el("dd", { text: row.doi || "" }),
      el("dt", { text: "PMCID" }), el("dd", { text: row.pmcid || "" }),
      el("dt", { text: "extraction tier" }), el("dd", { text: row.extraction_tier || "" }),
      el("dt", { text: "checked" }), el("dd", { text: row.checked_at || "" }),
      el("dt", { text: "projects" }), el("dd", { text: projectLabel(row) || "(none)" }),
    ]);
    return sec("overview", "Overview & pipeline", [stepsWrap, facts]);
  }

  var PAGE_NOTE_RE = /^p\.\s*(\d+):\s*/;

  function sectionNotes(row, detail) {
    var wrap = el("div", { className: "notes" });
    var draftKey = "ref-dashboard-draft-" + row.pmid;
    var textarea = el("textarea", {
      attrs: { placeholder: LIVE ? "New note" : "New note (kept only in this browser until you run /ref:note)" },
    });
    try { textarea.value = localStorage.getItem(draftKey) || ""; } catch (e) { /* private mode etc. */ }
    textarea.addEventListener("input", function () {
      try { localStorage.setItem(draftKey, textarea.value); } catch (e) { /* ignore */ }
    });

    var list = el("ul", { className: "notelist" });
    function noteListItem(n) {
      var li = el("li", { className: "note" }, [
        el("div", { className: "nm" }, [el("span", { text: n.at || "" })]),
      ]);
      var m = LIVE ? PAGE_NOTE_RE.exec(n.text || "") : null;
      if (m) {
        li.appendChild(el("button", {
          className: "cmdbtn", text: "jump to p. " + m[1], attrs: { type: "button" },
          on: { click: function () { setDrawerMode("pdf"); pdfGoToPage(parseInt(m[1], 10)); } },
        }));
      }
      li.appendChild(el("div", { className: "nt", text: n.text || "" }));
      return li;
    }
    function renderNoteList(notes) {
      clear(list);
      (notes || []).forEach(function (n) { list.appendChild(noteListItem(n)); });
      if (!(notes || []).length) list.appendChild(el("li", { className: "empty", text: "no committed notes yet" }));
    }
    renderNoteList(detail.notes);

    function showSaveError() {
      var toast = document.getElementById("toast");
      var prevText = toast.textContent;
      toast.textContent = "save failed -- kept as a local draft";
      toast.hidden = false;
      clearTimeout(toast._t);
      toast._t = setTimeout(function () { toast.hidden = true; toast.textContent = prevText; }, 2200);
    }

    var rowKids = [
      el("span", {
        className: "hint",
        text: LIVE ? "saved to notes.md immediately" : "draft saved locally · no write path in static mode",
      }),
    ];
    if (LIVE) {
      rowKids.push(el("button", {
        className: "cmdbtn", text: "Attach current page", attrs: { type: "button" },
        on: {
          click: function () {
            var page = pdfCurrentPage();
            if (!page) return;
            var stripped = textarea.value.replace(PAGE_NOTE_RE, "");
            textarea.value = "p. " + page + ": " + stripped;
            try { localStorage.setItem(draftKey, textarea.value); } catch (e) { /* ignore */ }
          },
        },
      }));
    }
    rowKids.push(el("button", {
      className: "cmdbtn primary", text: LIVE ? "Save note" : "Copy /ref:note",
      attrs: { type: "button" },
      on: {
        click: function () {
          var text = textarea.value.trim();
          if (!text) return;
          if (!LIVE) {
            var quoted = "\"" + text.replace(/\\/g, "\\\\").replace(/"/g, "\\\"") + "\"";
            copyText("/ref:note " + row.pmid + " " + quoted);
            return;
          }
          var m = PAGE_NOTE_RE.exec(text);
          var page = m ? parseInt(m[1], 10) : undefined;
          var body = m ? text.slice(m[0].length) : text;
          var payload = { text: body };
          if (page !== undefined) payload.page = page;
          apiFetch("/api/paper/" + encodeURIComponent(row.pmid) + "/notes", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          }).then(function (r) {
            if (!r.ok) throw new Error("http " + r.status);
            return r.json();
          }).then(function (entry) {
            textarea.value = "";
            try { localStorage.removeItem(draftKey); } catch (e) { /* ignore */ }
            detail.notes = (detail.notes || []).concat([entry]);
            renderNoteList(detail.notes);
          }).catch(function () {
            // Fall back to the static-mode draft behaviour -- never lose
            // what the user typed (§7.2).
            try { localStorage.setItem(draftKey, textarea.value); } catch (e) { /* ignore */ }
            showSaveError();
          });
        },
      },
    }));

    var composer = el("div", { className: "composer" }, [textarea, el("div", { className: "row" }, rowKids)]);
    wrap.appendChild(composer);
    wrap.appendChild(list);
    return sec("notes", "Notes", [wrap]);
  }

  function sectionAuthors(detail) {
    var list = el("ul", { className: "authors" });
    (detail.authors || []).forEach(function (a) {
      var name = [a.first, a.last].filter(Boolean).join(" ") || a.raw || "";
      list.appendChild(el("li", { text: name }));
    });
    if (!(detail.authors || []).length) return sec("authors", "Authors", [el("div", { className: "empty", text: "no author list yet" })]);
    return sec("authors", "Authors", [list]);
  }

  function sectionAbstract(detail) {
    if (!detail.abstract) return sec("abstract", "Abstract", [el("div", { className: "empty", text: "no abstract on file" })]);
    return sec("abstract", "Abstract", [el("p", { className: "prose", text: detail.abstract })]);
  }

  function sectionFunding(detail) {
    var kids = [];
    var funding = detail.funding || {};
    kids.push(el("div", { text: "state: " + (funding.state || "unknown"), className: "sub" }));
    if ((funding.observations || []).length) {
      var table = el("table", { className: "fund" });
      (funding.observations || []).forEach(function (o) {
        table.appendChild(el("tr", {}, [
          el("td", {}, [
            el("span", { text: o.funder || "" }),
            o.fundref_id ? el("span", { className: "fundref", text: o.fundref_id }) : null,
          ]),
          el("td", { text: o.award_number || "" }),
          el("td", { text: o.kind || "" }),
        ]));
      });
      kids.push(table);
    } else {
      kids.push(el("div", { className: "empty", text: "no funding observations recorded" }));
    }
    (detail.acknowledgements || []).forEach(function (text) {
      kids.push(el("div", { className: "sub", text: "acknowledgements" }));
      kids.push(el("p", { className: "prose", text: text }));
    });
    (detail.conflicts || []).forEach(function (text) {
      kids.push(el("div", { className: "sub", text: "conflicts of interest" }));
      kids.push(el("p", { className: "prose", text: text }));
    });
    (detail.data_availability || []).forEach(function (text) {
      kids.push(el("div", { className: "sub", text: "data availability" }));
      kids.push(el("p", { className: "prose", text: text }));
    });
    return sec("funding", "Funding & acknowledgements", kids);
  }

  function sectionFigures(detail) {
    var figs = detail.figures || [];
    if (!figs.length) return sec("figures", "Figures", [el("div", { className: "empty", text: "no figures recorded" })]);
    var list = el("ul", { className: "figs" });
    figs.forEach(function (f) {
      list.appendChild(el("li", {}, [
        el("span", { className: "fl", text: (f.label || "") + (f.asset_available ? "" : " (no image)") }),
        el("span", { text: f.caption || "" }),
      ]));
    });
    return sec("figures", "Figures", [list]);
  }

  function sectionClaims(detail) {
    var claims = detail.claims || [];
    if (!claims.length) return sec("claims", "Claims", [el("div", { className: "empty", text: "no active claims" })]);
    var wrap = el("div", {}, claims.map(function (c) {
      return el("div", { className: "claim" }, [
        el("div", { className: "cm" }, [
          el("span", { text: c.locator || "" }),
          el("span", { text: c.evidence_tier || "" }),
          el("span", { text: c.direction || "" }),
          el("span", { text: c.outcome || "" }),
          el("span", { text: c.population || "" }),
        ]),
        c.evidence_span ? el("q", { text: c.evidence_span }) : null,
      ]);
    }));
    return sec("claims", "Claims", [wrap]);
  }

  function sectionFiles(detail) {
    var list = el("ul", { className: "files" });
    (detail.files || []).forEach(function (f) {
      list.appendChild(el("li", {}, [
        el("span", { className: f.exists ? "yes" : "no", text: f.exists ? "✓" : "·" }),
        el("span", { text: f.path }),
        el("small", { text: f.note || "" }),
      ]));
    });
    return sec("files", "Files", [list]);
  }

  // ------------------------------------------------------------- pdf.js
  //
  // Only reachable in live mode (§7.2/§7.4): vendored pdfjs-dist 3.11.174
  // UMD build, lazy-loaded on first use of the PDF tab so static mode (and
  // a live session that never opens a PDF) never pays for it.

  var PDFJS_LOAD_PROMISE = null;
  function loadPdfJs() {
    if (window.pdfjsLib) return Promise.resolve(window.pdfjsLib);
    if (!PDFJS_LOAD_PROMISE) {
      PDFJS_LOAD_PROMISE = new Promise(function (resolve, reject) {
        var script = document.createElement("script");
        script.src = "/vendor/pdfjs/pdf.min.js";
        script.onload = function () {
          window.pdfjsLib.GlobalWorkerOptions.workerSrc = "/vendor/pdfjs/pdf.worker.min.js";
          resolve(window.pdfjsLib);
        };
        script.onerror = function () { reject(new Error("failed to load pdf.js")); };
        document.body.appendChild(script);
      });
    }
    return PDFJS_LOAD_PROMISE;
  }

  // Vendored pdf-lib 1.17.1 UMD build -- only pulled in when the user
  // actually exports a highlighted PDF, so viewing a PDF never pays for it.
  var PDFLIB_LOAD_PROMISE = null;
  function loadPdfLib() {
    if (window.PDFLib) return Promise.resolve(window.PDFLib);
    if (!PDFLIB_LOAD_PROMISE) {
      PDFLIB_LOAD_PROMISE = new Promise(function (resolve, reject) {
        var script = document.createElement("script");
        script.src = "/vendor/pdf-lib/pdf-lib.min.js";
        script.onload = function () { resolve(window.PDFLib); };
        script.onerror = function () { reject(new Error("failed to load pdf-lib")); };
        document.body.appendChild(script);
      });
    }
    return PDFLIB_LOAD_PROMISE;
  }

  var pdfState = { doc: null, pageNum: 1, scale: null, matches: [], matchIdx: -1, pmid: null, highlights: [] };

  function pdfCurrentPage() {
    return pdfState.doc ? pdfState.pageNum : null;
  }

  function pdfGoToPage(n) {
    if (!pdfState.doc || !n) return;
    pdfState.pageNum = Math.max(1, Math.min(pdfState.doc.numPages, n));
    renderPdfPage();
  }

  function renderPdfPage() {
    var canvas = document.getElementById("pdf-canvas");
    if (!canvas || !pdfState.doc) return;
    closeHlPopup();
    pdfState.doc.getPage(pdfState.pageNum).then(function (page) {
      var container = document.getElementById("pdf-pagewrap");
      var viewport0 = page.getViewport({ scale: 1 });
      var scale = pdfState.scale;
      if (!scale) {
        scale = container && container.clientWidth ? Math.max(0.1, (container.clientWidth - 24) / viewport0.width) : 1;
        pdfState.scale = scale;
      }
      var viewport = page.getViewport({ scale: scale });
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      page.render({ canvasContext: canvas.getContext("2d"), viewport: viewport });

      var pageEl = document.getElementById("pdf-page");
      if (pageEl) { pageEl.style.width = viewport.width + "px"; pageEl.style.height = viewport.height + "px"; }

      var textLayerDiv = document.getElementById("pdf-textlayer");
      if (textLayerDiv && window.pdfjsLib) {
        clear(textLayerDiv);
        textLayerDiv.style.setProperty("--scale-factor", String(scale));
        page.getTextContent().then(function (textContent) {
          if (pdfState.pageNum !== page.pageNumber) return; // stale response from a fast page flip
          window.pdfjsLib.renderTextLayer({
            textContentSource: textContent, container: textLayerDiv, viewport: viewport, textDivs: [],
          });
        });
      }
      renderPdfMarks();

      var pageInput = document.getElementById("pdf-pagenum");
      if (pageInput) pageInput.value = pdfState.pageNum;
      var total = document.getElementById("pdf-pagetotal");
      if (total) total.textContent = "/ " + pdfState.doc.numPages;
    });
  }

  // --------------------------------------------------------- pdf highlights

  function renderPdfMarks() {
    var wrap = document.getElementById("pdf-marks");
    if (!wrap) return;
    clear(wrap);
    var scale = pdfState.scale || 1;
    (pdfState.highlights || []).forEach(function (h) {
      if (h.page !== pdfState.pageNum) return;
      (h.rects || []).forEach(function (r) {
        var mark = el("span", { className: "pdf-mark", attrs: { "data-color": h.color, title: h.note || h.text || "" } });
        mark.style.left = (r.x * scale) + "px";
        mark.style.top = (r.y * scale) + "px";
        mark.style.width = (r.w * scale) + "px";
        mark.style.height = (r.h * scale) + "px";
        mark.addEventListener("click", function (e) { e.stopPropagation(); showRemovePopup(mark, h); });
        wrap.appendChild(mark);
      });
    });
  }

  function closeHlPopup() {
    var p = document.getElementById("hl-popup");
    if (p) p.remove();
  }

  function handlePdfSelection() {
    closeHlPopup();
    var sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) return;
    var range = sel.getRangeAt(0);
    var textLayerDiv = document.getElementById("pdf-textlayer");
    if (!textLayerDiv || !textLayerDiv.contains(range.commonAncestorContainer)) return;
    var text = sel.toString().trim();
    if (!text) return;
    var clientRects = Array.prototype.slice.call(range.getClientRects());
    if (!clientRects.length) return;

    var pageRect = textLayerDiv.getBoundingClientRect();
    var scale = pdfState.scale || 1;
    var rects = clientRects.map(function (r) {
      return {
        x: (r.left - pageRect.left) / scale, y: (r.top - pageRect.top) / scale,
        w: r.width / scale, h: r.height / scale,
      };
    });
    var last = clientRects[clientRects.length - 1];
    showColorPopup(last.right - pageRect.left, last.bottom - pageRect.top, function (color) {
      savePdfHighlight(rects, text, color);
      sel.removeAllRanges();
    });
  }

  function showColorPopup(x, y, onPick) {
    closeHlPopup();
    var marks = document.getElementById("pdf-marks");
    if (!marks) return;
    var popup = el("div", { className: "hl-popup", attrs: { id: "hl-popup" } },
      ["yellow", "green", "red"].map(function (c) {
        return el("button", {
          className: "sw", attrs: { type: "button", "data-color": c, title: "highlight " + c },
          on: { click: function () { onPick(c); closeHlPopup(); } },
        });
      }));
    popup.style.left = Math.max(0, x - 40) + "px";
    popup.style.top = (y + 6) + "px";
    marks.appendChild(popup);
  }

  function showRemovePopup(anchorEl, h) {
    closeHlPopup();
    var marks = document.getElementById("pdf-marks");
    if (!marks) return;
    var rect = anchorEl.getBoundingClientRect();
    var parentRect = marks.getBoundingClientRect();
    var popup = el("div", { className: "hl-popup", attrs: { id: "hl-popup" } }, [
      el("button", {
        className: "del", text: "Remove highlight", attrs: { type: "button" },
        on: { click: function () { deletePdfHighlight(h.id); closeHlPopup(); } },
      }),
    ]);
    popup.style.left = (rect.left - parentRect.left) + "px";
    popup.style.top = (rect.bottom - parentRect.top + 4) + "px";
    marks.appendChild(popup);
  }

  function savePdfHighlight(rects, text, color) {
    var pmid = pdfState.pmid;
    if (!pmid) return;
    apiFetch("/api/paper/" + encodeURIComponent(pmid) + "/highlights", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ page: pdfState.pageNum, rects: rects, text: text, color: color }),
    }).then(function (r) { if (!r.ok) throw new Error("http " + r.status); return r.json(); })
      .then(function (entry) { pdfState.highlights.push(entry); renderPdfMarks(); })
      .catch(function () {
        var toast = document.getElementById("toast");
        toast.textContent = "highlight save failed";
        toast.hidden = false;
        clearTimeout(toast._t);
        toast._t = setTimeout(function () { toast.hidden = true; }, 2200);
      });
  }

  function deletePdfHighlight(id) {
    var pmid = pdfState.pmid;
    if (!pmid) return;
    apiFetch("/api/paper/" + encodeURIComponent(pmid) + "/highlights/" + encodeURIComponent(id), { method: "DELETE" })
      .then(function () {
        pdfState.highlights = pdfState.highlights.filter(function (x) { return x.id !== id; });
        renderPdfMarks();
      });
  }

  // Same hex per color as .pdf-mark's CSS (app.css), as 0-1 RGB triples for pdf-lib.
  var PDF_EXPORT_COLORS = { yellow: [0.910, 0.784, 0.290], green: [0.561, 0.749, 0.435], red: [0.878, 0.541, 0.420] };

  // "Save PDF with highlights" (§ PDF annotations, option 01): fetches the
  // source PDF bytes fresh, draws each saved highlight as a flattened
  // semi-transparent rectangle (Multiply blend, so it reads like a real
  // marker on any page background) at its stored page -- unscaled, so this
  // is independent of whatever zoom level is on screen right now -- and
  // triggers a browser download of the result. Nothing is written back to
  // the library; the export is a client-side copy only.
  function pdfExportWithHighlights(row) {
    var btn = document.getElementById("pdf-export");
    var paths = (row && row.pdf_paths) || [];
    if (!paths.length || !btn) return;
    var path = paths.indexOf(pdfState.variant) >= 0 ? pdfState.variant : paths[0];
    var origText = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Saving…";

    Promise.all([
      loadPdfLib(),
      apiFetch("/files/" + encodeURIComponent(row.pmid) + "/" + path.split("/").map(encodeURIComponent).join("/"))
        .then(function (r) { if (!r.ok) throw new Error("http " + r.status); return r.arrayBuffer(); }),
      apiFetch("/api/paper/" + encodeURIComponent(row.pmid) + "/highlights")
        .then(function (r) { return r.ok ? r.json() : []; }),
    ]).then(function (results) {
      var PDFLib = results[0], bytes = results[1], highlights = results[2] || [];
      return PDFLib.PDFDocument.load(bytes).then(function (pdfDoc) {
        var pages = pdfDoc.getPages();
        highlights.forEach(function (h) {
          var page = pages[h.page - 1];
          if (!page) return;
          var pageHeight = page.getHeight();
          var rgb = PDF_EXPORT_COLORS[h.color] || PDF_EXPORT_COLORS.yellow;
          (h.rects || []).forEach(function (r) {
            page.drawRectangle({
              x: r.x, y: pageHeight - r.y - r.h, width: r.w, height: r.h,
              color: PDFLib.rgb(rgb[0], rgb[1], rgb[2]), opacity: 0.4, blendMode: PDFLib.BlendMode.Multiply,
            });
          });
        });
        return pdfDoc.save();
      });
    }).then(function (outBytes) {
      var blob = new Blob([outBytes], { type: "application/pdf" });
      var url = URL.createObjectURL(blob);
      var a = document.createElement("a");
      a.href = url;
      a.download = (row.citekey || row.pmid) + "-highlighted.pdf";
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
    }).catch(function () {
      var toast = document.getElementById("toast");
      toast.textContent = "export failed";
      toast.hidden = false;
      clearTimeout(toast._t);
      toast._t = setTimeout(function () { toast.hidden = true; }, 2200);
    }).then(function () {
      btn.disabled = false;
      btn.textContent = origText;
    });
  }

  function pdfZoom(delta) {
    if (!pdfState.doc) return;
    pdfState.scale = Math.max(0.25, Math.min(4, (pdfState.scale || 1) + delta));
    renderPdfPage();
  }

  function pdfFitWidth() {
    pdfState.scale = null;
    renderPdfPage();
  }

  function renderThumbnails() {
    var wrap = document.getElementById("pdf-thumbs");
    if (!wrap || !pdfState.doc) return;
    clear(wrap);
    var doc = pdfState.doc;
    for (var i = 1; i <= doc.numPages; i++) {
      (function (pageNo) {
        var thumb = el("canvas", { className: "pdf-thumb", attrs: { "data-page": pageNo, title: "page " + pageNo } });
        thumb.addEventListener("click", function () { pdfGoToPage(pageNo); });
        wrap.appendChild(thumb);
        doc.getPage(pageNo).then(function (page) {
          var vp = page.getViewport({ scale: 0.15 });
          thumb.width = vp.width;
          thumb.height = vp.height;
          page.render({ canvasContext: thumb.getContext("2d"), viewport: vp });
        });
      })(i);
    }
  }

  function pdfFind(query) {
    if (!pdfState.doc || !query) { pdfState.matches = []; pdfState.matchIdx = -1; return Promise.resolve([]); }
    var doc = pdfState.doc;
    var q = query.toLowerCase();
    var matches = [];
    var chain = Promise.resolve();
    for (var i = 1; i <= doc.numPages; i++) {
      (function (pageNo) {
        chain = chain.then(function () {
          return doc.getPage(pageNo).then(function (page) { return page.getTextContent(); }).then(function (tc) {
            var text = tc.items.map(function (it) { return it.str; }).join(" ").toLowerCase();
            if (text.indexOf(q) >= 0) matches.push(pageNo);
          });
        });
      })(i);
    }
    return chain.then(function () {
      pdfState.matches = matches;
      pdfState.matchIdx = matches.length ? 0 : -1;
      return matches;
    });
  }

  function pdfFindNext(delta) {
    if (!pdfState.matches.length) return;
    pdfState.matchIdx = (pdfState.matchIdx + delta + pdfState.matches.length) % pdfState.matches.length;
    pdfGoToPage(pdfState.matches[pdfState.matchIdx]);
  }

  function renderPdfTab() {
    var wrap = document.getElementById("d-pdf");
    clear(wrap);
    var row = BY_PMID[drawerState.pmid];
    var paths = (row && row.pdf_paths) || [];
    if (!paths.length) {
      var none = el("div", { className: "pdf-status" }, [
        el("h4", { text: "No PDF attached" }),
        el("p", { text: LIVE ? "Drop a PDF here or choose a file -- it's checked against this paper's DOI/title and stored like /ref:attach." : "Run /ref:fetch-pdf or /ref:attach to add one." }),
      ]);
      if (LIVE) none.appendChild(pdfDropZone(row));
      wrap.appendChild(none);
      return;
    }

    if (!LIVE) {
      var status = el("div", { className: "pdf-status" }, [
        el("h4", { text: "Open in your PDF viewer" }),
        el("p", { text: "Static mode opens the PDF in a new browser tab (file:// pages can't render pdf.js inline reliably) -- see LIBRARY_VIEWER_IMPLEMENTATION_PLAN.md §6.2." }),
      ]);
      paths.forEach(function (p) {
        var href = "../../papers/" + encodeURIComponent(row.pmid) + "/" + p.split("/").map(encodeURIComponent).join("/");
        status.appendChild(el("a", {
          className: "cmdbtn primary", text: "Open " + p,
          attrs: { href: href, target: "_blank", rel: "noopener" },
        }));
      });
      wrap.appendChild(status);
      return;
    }

    // live mode: in-page pdf.js viewer (§7.2)
    pdfState.doc = null;
    pdfState.pageNum = 1;
    pdfState.scale = null;
    if (pdfState.variantPmid !== row.pmid || paths.indexOf(pdfState.variant) < 0) {
      pdfState.variantPmid = row.pmid;
      pdfState.variant = paths[0];
    }
    var path = pdfState.variant;
    var toolbar = el("div", { className: "pdf-toolbar" }, [
      el("button", { text: "−", attrs: { type: "button", title: "Zoom out" }, on: { click: function () { pdfZoom(-0.15); } } }),
      el("button", { text: "+", attrs: { type: "button", title: "Zoom in" }, on: { click: function () { pdfZoom(0.15); } } }),
      el("button", { text: "Fit width", attrs: { type: "button" }, on: { click: pdfFitWidth } }),
      el("button", { text: "‹", attrs: { type: "button", title: "Previous page" }, on: { click: function () { pdfGoToPage(pdfState.pageNum - 1); } } }),
      el("input", {
        attrs: { type: "number", id: "pdf-pagenum", min: "1", style: "width:52px" },
        on: { change: function (e) { pdfGoToPage(parseInt(e.target.value, 10) || 1); } },
      }),
      el("span", { attrs: { id: "pdf-pagetotal" } }),
      el("button", { text: "›", attrs: { type: "button", title: "Next page" }, on: { click: function () { pdfGoToPage(pdfState.pageNum + 1); } } }),
      el("input", {
        attrs: { type: "search", placeholder: "Find in PDF", id: "pdf-find" },
        on: { keydown: function (e) {
          if (e.key !== "Enter") return;
          pdfFind(e.target.value).then(function (matches) { if (matches.length) pdfGoToPage(matches[0]); });
        } },
      }),
      el("button", { text: "↑", attrs: { type: "button", title: "Previous match" }, on: { click: function () { pdfFindNext(-1); } } }),
      el("button", { text: "↓", attrs: { type: "button", title: "Next match" }, on: { click: function () { pdfFindNext(1); } } }),
      paths.length > 1 ? el("select", {
        attrs: { id: "pdf-variant", "aria-label": "PDF variant", title: "Older PDFs stay attached; pick which one to view" },
        on: { change: function (e) { pdfState.variant = e.target.value; renderPdfTab(); } },
      }, paths.map(function (pth, i) {
        var o = el("option", { attrs: { value: pth }, text: (i === 0 ? "newest: " : "") + pth });
        if (pth === path) o.selected = true;
        return o;
      })) : null,
      el("button", {
        text: "Replace PDF…", attrs: { type: "button", title: "Attach a newer PDF; the current one is kept as a variant" },
        on: { click: function () { pickPdfFile(function (file) { startPdfUpload(row, file); }); } },
      }),
      el("button", {
        text: "Save PDF with highlights", attrs: { type: "button", id: "pdf-export", style: "margin-left:auto" },
        on: { click: function () { pdfExportWithHighlights(row); } },
      }),
    ]);
    var thumbs = el("div", { className: "pdf-thumbs", attrs: { id: "pdf-thumbs" } });
    var textLayerDiv = el("div", { className: "textLayer", attrs: { id: "pdf-textlayer" } });
    var marksDiv = el("div", { className: "pdf-marks", attrs: { id: "pdf-marks" } });
    var pageInner = el("div", { className: "pdf-page", attrs: { id: "pdf-page" } }, [
      el("canvas", { attrs: { id: "pdf-canvas" } }),
      textLayerDiv,
      marksDiv,
    ]);
    var pageWrap = el("div", { className: "pdf-pagewrap", attrs: { id: "pdf-pagewrap" } }, [pageInner]);
    wrap.appendChild(toolbar);
    wrap.appendChild(el("div", { className: "pdf-upload", attrs: { id: "pdf-upload-status", role: "status", "aria-live": "polite" }, }));
    wrap.appendChild(el("div", { className: "pdf-body" }, [thumbs, pageWrap]));

    // Highlighting (§ PDF annotations): select text in the layer above the
    // canvas -> a small popup offers a highlight color -> saved through
    // highlight.py's POST route, keyed by page + unscaled (scale=1)
    // rects so a mark stays put across zoom levels (§ pdfState.scale below).
    textLayerDiv.addEventListener("mouseup", function () { setTimeout(handlePdfSelection, 0); });

    pdfState.pmid = row.pmid;
    pdfState.highlights = [];
    apiFetch("/api/paper/" + encodeURIComponent(row.pmid) + "/highlights")
      .then(function (r) { return r.ok ? r.json() : []; })
      .then(function (list) { pdfState.highlights = list || []; renderPdfMarks(); })
      .catch(function () { /* highlights are a nice-to-have; the PDF still renders without them */ });

    loadPdfJs().then(function (pdfjsLib) {
      return apiFetch("/files/" + encodeURIComponent(row.pmid) + "/" + path.split("/").map(encodeURIComponent).join("/"))
        .then(function (r) { if (!r.ok) throw new Error("http " + r.status); return r.arrayBuffer(); })
        .then(function (buf) { return pdfjsLib.getDocument({ data: buf }).promise; })
        .then(function (doc) {
          pdfState.doc = doc;
          renderPdfPage();
          renderThumbnails();
        });
    }).catch(function () {
      pageWrap.appendChild(el("div", { className: "empty", text: "could not load the PDF." }));
    });
  }

  // ------------------------------------------------- PDF upload (FR-07/FR-08)
  //
  // Live mode only. The file goes as a raw application/pdf body to
  // POST /api/paper/<pmid>/pdf, which commits it through attach.py like
  // /ref:attach. Two server-side confirmations come back as 409/422 and are
  // answered inline (never a browser dialog): replacing an existing PDF
  // (the old one stays as a variant) and attaching a PDF whose DOI/title
  // identity check failed.

  var MAX_PDF_UPLOAD = 64 * 1024 * 1024;

  function pickPdfFile(onFile) {
    var input = el("input", { attrs: { type: "file", accept: "application/pdf,.pdf", hidden: "hidden" } });
    input.addEventListener("change", function () {
      if (input.files && input.files[0]) onFile(input.files[0]);
      input.remove();
    });
    document.body.appendChild(input);
    input.click();
  }

  function pdfDropZone(row) {
    var zone = el("div", { className: "dropzone", attrs: { tabindex: "0", role: "button", "aria-label": "Attach a PDF to this paper" } }, [
      el("b", { text: "Drop PDF here" }),
      el("span", { text: "or click to choose a file · max 64 MB" }),
    ]);
    zone.addEventListener("click", function () { pickPdfFile(function (f) { startPdfUpload(row, f); }); });
    zone.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pickPdfFile(function (f) { startPdfUpload(row, f); }); }
    });
    return el("div", {}, [zone, el("div", { className: "pdf-upload", attrs: { id: "pdf-upload-status", role: "status", "aria-live": "polite" } })]);
  }

  function uploadStatus(msg, kids, isError) {
    var box = document.getElementById("pdf-upload-status");
    if (!box) { if (msg) flash(msg, 3200); return; }
    clear(box);
    box.classList.toggle("err", !!isError);
    if (msg) box.appendChild(el("span", { text: msg }));
    (kids || []).forEach(function (k) { box.appendChild(k); });
  }

  function validatePdfFile(file) {
    var named = /\.pdf$/i.test(file.name || "");
    if (file.type && file.type !== "application/pdf" && !named) return Promise.resolve("“" + file.name + "” isn't a PDF");
    if (!file.type && !named) return Promise.resolve("“" + file.name + "” isn't a PDF");
    if (file.size > MAX_PDF_UPLOAD) return Promise.resolve("file is larger than 64 MB");
    if (!file.size) return Promise.resolve("file is empty");
    return file.slice(0, 5).arrayBuffer().then(function (buf) {
      var head = String.fromCharCode.apply(null, new Uint8Array(buf));
      return head === "%PDF-" ? null : "“" + file.name + "” doesn't start with a PDF header";
    });
  }

  function startPdfUpload(row, file, opts) {
    opts = opts || {};
    validatePdfFile(file).then(function (problem) {
      if (problem) { uploadStatus("Not attached: " + problem, [], true); return; }
      var qs = [];
      if (opts.replace) qs.push("replace=1");
      if (opts.force) qs.push("force=1");
      var xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/paper/" + encodeURIComponent(row.pmid) + "/pdf" + (qs.length ? "?" + qs.join("&") : ""));
      xhr.setRequestHeader("X-Ref-Token", TOKEN);
      xhr.setRequestHeader("Content-Type", "application/pdf");
      xhr.setRequestHeader("X-Filename", encodeURIComponent(file.name || "upload.pdf"));
      xhr.upload.onprogress = function (e) {
        if (e.lengthComputable) uploadStatus("Uploading " + file.name + "… " + Math.round(e.loaded / e.total * 100) + "%");
      };
      xhr.upload.onload = function () { uploadStatus("Checking identity and storing " + file.name + "…"); };
      xhr.onerror = function () { uploadStatus("Upload failed -- is the dashboard server still running?", [], true); };
      xhr.onload = function () {
        var body = {};
        try { body = JSON.parse(xhr.responseText || "{}"); } catch (e) { /* keep {} */ }
        if (xhr.status === 409 && body.needs === "replace") {
          uploadStatus("This paper already has a PDF. Use " + file.name + " as the active PDF? The current one is kept as a variant.", [
            el("button", { className: "cmdbtn primary", text: "Replace", attrs: { type: "button" },
              on: { click: function () { startPdfUpload(row, file, { replace: true, force: opts.force }); } } }),
            el("button", { className: "cmdbtn", text: "Cancel", attrs: { type: "button" },
              on: { click: function () { uploadStatus(""); } } }),
          ]);
        } else if (xhr.status === 422 && body.needs === "force") {
          uploadStatus("Identity check failed: " + body.error + ".", [
            el("button", { className: "cmdbtn primary", text: "Attach anyway", attrs: { type: "button" },
              on: { click: function () { startPdfUpload(row, file, { replace: opts.replace, force: true }); } } }),
            el("button", { className: "cmdbtn", text: "Cancel", attrs: { type: "button" },
              on: { click: function () { uploadStatus(""); } } }),
          ], true);
        } else if (xhr.status === 200 && body.result === "duplicate_noop") {
          uploadStatus("That exact PDF is already attached -- nothing changed.");
        } else if (xhr.status === 201) {
          var msg = "Attached " + file.name + ".";
          if (!body.version) msg += " Stored as PDF only (not converted to full text" + ((body.diagnostics || [])[0] ? ": " + body.diagnostics[0] : "") + ").";
          afterPdfUpload(row.pmid, msg);
        } else {
          uploadStatus("Not attached: " + (body.error || "HTTP " + xhr.status), [], true);
        }
      };
      uploadStatus("Uploading " + file.name + "…");
      xhr.send(file);
    });
  }

  function afterPdfUpload(pmid, msg) {
    fetchJSON("/api/rows").then(function (rows) {
      setRows(rows);
      delete loadedDetails[pmid];
      pdfState.variantPmid = null; // newest PDF (the upload) becomes the viewed one
      renderAll();
      if (drawerState.pmid === pmid) {
        renderDrawerHeader();
        setDrawerMode("pdf");
      }
      flash(msg, 3600);
      uploadStatus(msg);
    }).catch(function (err) { uploadStatus(msg + " (couldn't refresh rows: " + describeFetchError(err) + ")", [], true); });
  }

  function hasFiles(e) {
    return e.dataTransfer && Array.prototype.indexOf.call(e.dataTransfer.types || [], "Files") >= 0;
  }

  if (LIVE) {
    // A file dropped anywhere else must not navigate the tab away from the dashboard.
    window.addEventListener("dragover", function (e) { if (hasFiles(e)) e.preventDefault(); });
    window.addEventListener("drop", function (e) { if (hasFiles(e)) e.preventDefault(); });
    var pdfPane = document.getElementById("d-pdf");
    pdfPane.addEventListener("dragover", function (e) { if (hasFiles(e)) { e.preventDefault(); pdfPane.classList.add("dragging"); } });
    pdfPane.addEventListener("dragleave", function (e) { if (!pdfPane.contains(e.relatedTarget)) pdfPane.classList.remove("dragging"); });
    pdfPane.addEventListener("drop", function (e) {
      pdfPane.classList.remove("dragging");
      if (!hasFiles(e) || !drawerState.pmid) return;
      e.preventDefault();
      var row = BY_PMID[drawerState.pmid];
      if (row && e.dataTransfer.files[0]) startPdfUpload(row, e.dataTransfer.files[0]);
    });
  }

  // ------------------------------------------------------------- triage
  // PUBMED_TRIAGE_IMPLEMENTATION_PLAN.md §6.5 -- live mode only. One table
  // per saved search: decisions (Include adds the paper), an optional
  // project link, batch loading after a confirm, PDF jobs, and the
  // "needs Claude" pending strip. Every write goes through /api/triage/*;
  // the page re-reads the view after each one instead of guessing state.

  var TRIAGES = [];
  var tri = {
    slug: null, view: null, filter: "all", query: "", page: 0,
    selected: new Set(), open: new Set(), active: -1, pageRows: [], visible: [],
    busy: false, confirmBatch: false, job: null, pollTimer: null, pendingTimer: null, lastStatus: "",
    scope: "all", yfrom: null, yto: null, type: "", journal: "", lib: "",
    bulkConfirm: null, bulkSkipDecided: true,
  };
  var TRI_PAGE_SIZE = 100;
  var TRI_DEC_LABEL = { included: "Include", pending: "Maybe", excluded: "Exclude" };
  var TRI_DEC_COLOR = { included: "var(--good)", pending: "var(--warn)", excluded: "var(--crit)" };

  function postJSON(path, body) {
    return apiFetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) {
          var err = new Error((data && data.error) || ("http " + r.status + " on " + path));
          err.endpoint = path;
          err.status = r.status;
          throw err;
        }
        return data;
      });
    });
  }

  function triStatus(msg) {
    tri.lastStatus = msg || "";
    document.getElementById("t-status").textContent = tri.lastStatus;
    renderTriResult();
  }

  function renderTriResult() {
    var text = tri.visible.length + " of " + triPapers().length + " loaded";
    if (tri.lastStatus && document.getElementById("t-actionbar").hidden) text += " · " + tri.lastStatus;
    document.getElementById("t-result").textContent = text;
  }

  // Include / Get PDFs add papers to the library -- keep the other tabs'
  // rows (Papers, Projects, health) in step without a manual refresh.
  function syncLibraryRows() {
    fetchJSON("/api/rows").then(function (rows) {
      setRows(rows);
      renderAll();
    }).catch(function () { /* the next manual refresh reports it */ });
  }

  function triageFromHash() {
    var m = /^#triage\/([a-z0-9-]+)$/.exec(location.hash || "");
    return m ? m[1] : null;
  }

  function loadTriages(openSlug) {
    if (!LIVE) return Promise.resolve();
    return fetchJSON("/api/triages").then(function (list) {
      TRIAGES = list || [];
      var tab = document.getElementById("tab-triage");
      tab.hidden = !TRIAGES.length;
      document.getElementById("c-triage").textContent = TRIAGES.length ? String(TRIAGES.length) : "";
      var pick = document.getElementById("t-pick");
      clear(pick);
      TRIAGES.forEach(function (t) {
        pick.appendChild(el("option", { text: t.slug + " (" + t.loaded + "/" + t.found + ")", attrs: { value: t.slug } }));
      });
      var want = openSlug || tri.slug || (TRIAGES[0] && TRIAGES[0].slug);
      if (want && TRIAGES.some(function (t) { return t.slug === want; })) {
        pick.value = want;
        tri.slug = want;
      }
      if (activeTab === "projects") renderProjects();
    }).catch(function (err) {
      showError("could not load triages: " + describeFetchError(err));
    });
  }

  function loadTriageView(onlyIfChanged) {
    if (!tri.slug) return Promise.resolve();
    return fetchJSON("/api/triage/" + encodeURIComponent(tri.slug)).then(function (v) {
      // The pending poll must not rebuild the table (and drop focus or an
      // open confirm) when nothing changed on disk.
      if (onlyIfChanged && tri.view && JSON.stringify(v) === JSON.stringify(tri.view)) {
        schedulePendingPoll();
        return;
      }
      tri.view = v;
      renderTriage();
      schedulePendingPoll();
    }).catch(function (err) {
      showError("could not load triage " + tri.slug + ": " + describeFetchError(err));
    });
  }

  function triPapers() {
    return tri.view ? tri.view.papers.filter(function (p) { return p.loaded; }) : [];
  }

  function isReview(p) {
    return (p.metadata.publication_types || []).some(function (t) { return /review/i.test(t); });
  }

  var TRI_FILTERS = [
    { id: "all", label: "All", pred: function () { return true; } },
    { id: "new", label: "New since last run", pred: function (p) { return !!p.new_since; } },
    { id: "undecided", label: "Undecided", pred: function (p) { return !p.decision; } },
    { id: "included", label: "Included", pred: function (p) { return p.decision && p.decision.decision === "included"; } },
    { id: "pending", label: "Maybe", pred: function (p) { return p.decision && p.decision.decision === "pending"; } },
    { id: "excluded", label: "Excluded", pred: function (p) { return p.decision && p.decision.decision === "excluded"; } },
    { id: "nopdf", label: "Included, no PDF", pred: function (p) { return p.decision && p.decision.decision === "included" && !(p.library && p.library.has_pdf); } },
    { id: "waiting", label: "Waiting for Claude", pred: function (p) { return !!p.pending; } },
    { id: "pmc", label: "In PMC", pred: function (p) { return !!p.metadata.pmcid; } },
    { id: "reviews", label: "Reviews", pred: isReview },
    { id: "dropped", label: "Not in latest run", pred: function (p) { return !p.in_latest_run; } },
  ];

  // "cortical thickness" -rat -mouse  ->  must contain each plain word or
  // quoted phrase, must not contain any -word.
  function parseTriQuery(q) {
    var terms = { want: [], not: [] };
    var re = /(-?)"([^"]+)"|(-?)(\S+)/g, m;
    while ((m = re.exec(q.toLowerCase()))) {
      var neg = m[1] || m[3];
      var word = m[2] || m[4];
      if (!word || word === "-") continue;
      (neg ? terms.not : terms.want).push(word);
    }
    return terms;
  }

  function triHaystack(p) {
    var m = p.metadata;
    var parts = {
      title: m.title || "",
      abstract: m.abstract || "",
      mesh: (m.mesh_terms || []).join(" | "),
      authors: (m.authors || []).join(" "),
    };
    if (tri.scope !== "all") return parts[tri.scope] || "";
    return [p.pmid, parts.title, parts.abstract, parts.mesh, parts.authors, m.journal || "", (m.publication_types || []).join(" ")].join(" \n ");
  }

  function libState(p) {
    var lib = p.library;
    if (tri.lib === "none") return !lib;
    if (tri.lib === "in") return !!lib;
    if (tri.lib === "nopdf") return !!lib && !lib.has_pdf;
    if (tri.lib === "pdf") return !!lib && lib.has_pdf;
    if (tri.lib === "noabstract") return !p.metadata.abstract;
    return true;
  }

  function triVisible() {
    var f = TRI_FILTERS.filter(function (x) { return x.id === tri.filter; })[0] || TRI_FILTERS[0];
    var terms = parseTriQuery(tri.query);
    return triPapers().filter(function (p) {
      if (!f.pred(p)) return false;
      var m = p.metadata;
      var year = parseInt(m.year, 10);
      if (tri.yfrom && !(year >= tri.yfrom)) return false;
      if (tri.yto && !(year <= tri.yto)) return false;
      if (tri.type && (m.publication_types || []).indexOf(tri.type) === -1) return false;
      if (tri.journal && m.journal !== tri.journal) return false;
      if (tri.lib && !libState(p)) return false;
      if (terms.want.length || terms.not.length) {
        var hay = triHaystack(p).toLowerCase();
        if (!terms.want.every(function (w) { return hay.indexOf(w) !== -1; })) return false;
        if (terms.not.some(function (w) { return hay.indexOf(w) !== -1; })) return false;
      }
      return true;
    });
  }

  function fillSelect(id, values, anyLabel, current) {
    var sel = document.getElementById(id);
    clear(sel);
    sel.appendChild(el("option", { text: anyLabel, attrs: { value: "" } }));
    values.forEach(function (v) {
      sel.appendChild(el("option", { text: v[0] + " (" + v[1] + ")", attrs: { value: v[0] } }));
    });
    sel.value = values.some(function (v) { return v[0] === current; }) ? current : "";
  }

  function countValues(list) {
    var counts = {};
    list.forEach(function (v) { if (v) counts[v] = (counts[v] || 0) + 1; });
    return Object.keys(counts).sort(function (a, b) { return counts[b] - counts[a] || (a < b ? -1 : 1); })
      .map(function (k) { return [k, counts[k]]; });
  }

  function renderTriFilterOptions() {
    var papers = triPapers();
    var types = [];
    papers.forEach(function (p) { types = types.concat(p.metadata.publication_types || []); });
    fillSelect("t-type", countValues(types), "Any article type", tri.type);
    fillSelect("t-journal", countValues(papers.map(function (p) { return p.metadata.journal; })), "Any journal", tri.journal);
    tri.type = document.getElementById("t-type").value;
    tri.journal = document.getElementById("t-journal").value;
  }

  function renderTriBulk() {
    var wrap = document.getElementById("t-bulk");
    clear(wrap);
    var shown = tri.visible;
    var filtered = shown.length !== triPapers().length;
    var c = tri.bulkConfirm;
    if (c) {
      var n = c.pmids.length;
      var verb = { included: "Include", pending: "Mark as maybe", excluded: "Exclude" }[c.decision];
      var question = c.decision === "included"
        ? "Include " + n + " paper" + (n === 1 ? "" : "s") + " and add them to the library?"
        : verb + " " + n + " paper" + (n === 1 ? "" : "s") + "?";
      wrap.appendChild(el("span", { className: "confirm", text: question }));
      wrap.appendChild(el("button", {
        className: "cmdbtn primary", text: "Yes, " + verb.toLowerCase() + " " + n, attrs: { type: "button" },
        on: { click: function () { tri.bulkConfirm = null; triDecide(c.pmids, c.decision); renderTriBulk(); } },
      }));
      wrap.appendChild(el("button", {
        className: "cmdbtn", text: "Cancel", attrs: { type: "button" },
        on: { click: function () { tri.bulkConfirm = null; renderTriBulk(); } },
      }));
      return;
    }
    var undecided = shown.filter(function (p) { return !p.decision; });
    var targets = tri.bulkSkipDecided ? undecided : shown;
    wrap.appendChild(el("span", { className: "lbl" }, [
      document.createTextNode(filtered ? "All papers matching these filters: " : "All loaded papers: "),
      el("b", { text: String(targets.length) }),
      document.createTextNode(tri.bulkSkipDecided ? " undecided of " + shown.length : ""),
    ]));
    [["included", "Include all", "inc"], ["pending", "Maybe all", "may"], ["excluded", "Exclude all", "exc"]].forEach(function (b) {
      wrap.appendChild(el("button", {
        className: "cmdbtn " + b[2], text: b[1] + " (" + targets.length + ")",
        attrs: { type: "button", disabled: (tri.busy || !targets.length) ? "disabled" : null },
        on: { click: function () {
          tri.bulkConfirm = { decision: b[0], pmids: targets.map(function (p) { return p.pmid; }) };
          renderTriBulk();
        } },
      }));
    });
    wrap.appendChild(el("button", {
      className: "cmdbtn", text: "Select all (" + shown.length + ")",
      attrs: { type: "button", disabled: shown.length ? null : "disabled" },
      on: { click: function () {
        shown.forEach(function (p) { tri.selected.add(p.pmid); });
        renderTriRows();
        renderTriActionBar();
      } },
    }));
    var skip = el("input", { attrs: { type: "checkbox", id: "t-skipdecided" } });
    skip.checked = tri.bulkSkipDecided;
    skip.addEventListener("change", function () { tri.bulkSkipDecided = skip.checked; renderTriBulk(); });
    wrap.appendChild(el("label", { className: "lbl", attrs: { for: "t-skipdecided" } }, [
      skip, document.createTextNode(" leave papers that already have a decision alone"),
    ]));
  }

  function renderTriage() {
    var v = tri.view;
    if (!v) return;
    var c = v.counts;

    var meta = document.getElementById("t-runmeta");
    clear(meta);
    var last = v.runs[v.runs.length - 1];
    [
      ["runs", String(v.runs.length)],
      ["latest", last ? last.retrieved_at.slice(0, 16).replace("T", " ") : "-"],
      ["found", String(c.found)],
      ["metadata loaded", String(c.loaded)],
    ].forEach(function (kv) {
      meta.appendChild(el("span", {}, [document.createTextNode(kv[0] + " "), el("b", { text: kv[1] })]));
    });
    document.getElementById("t-query").textContent = v.query || "";

    var projSel = document.getElementById("t-project");
    clear(projSel);
    projSel.appendChild(el("option", { text: "None: topic search only", attrs: { value: "" } }));
    (v.projects || []).forEach(function (slug) {
      projSel.appendChild(el("option", { text: slug, attrs: { value: slug } }));
    });
    projSel.value = v.triage.project || "";
    document.getElementById("t-projhint").textContent = v.triage.project
      ? "Included papers join " + v.triage.project + "; every decision goes to its screening log."
      : "Decisions stay with this search. Pick a project to copy them into its screening log.";

    triBar("t-decbar", "t-declegend", [
      ["included", c.decisions.included, TRI_DEC_COLOR.included],
      ["maybe", c.decisions.pending, TRI_DEC_COLOR.pending],
      ["excluded", c.decisions.excluded, TRI_DEC_COLOR.excluded],
      ["undecided", c.decisions.undecided, "var(--line)"],
    ]);
    document.getElementById("t-dec-total").textContent = c.loaded + " loaded";
    triBar("t-libbar", "t-liblegend", [
      ["PDF", c.library.pdf, "var(--s-pdf)"],
      ["full text", c.library.fulltext, "var(--s-full)"],
      ["abstract", c.library.abstract, "var(--s-abs)"],
      ["not added", c.library.none, "var(--line)"],
    ]);
    document.getElementById("t-lib-total").textContent = c.found + " found";
    triBar("t-oabar", "t-oalegend", [
      ["in PMC", c.pmc, "var(--accent)"],
      ["not in PMC", c.loaded - c.pmc, "var(--line)"],
    ]);
    document.getElementById("t-oa-total").textContent = c.loaded + " loaded";

    renderTriFilterOptions();
    renderTriChips();
    renderTriRows();
    renderTriBatch();
    renderTriPending();
    renderTriActionBar();
  }

  function triBar(barId, legendId, parts) {
    var total = parts.reduce(function (a, p) { return a + p[1]; }, 0) || 1;
    var bar = document.getElementById(barId);
    var legend = document.getElementById(legendId);
    clear(bar);
    clear(legend);
    parts.forEach(function (p) {
      if (p[1]) bar.appendChild(el("i", { attrs: { style: "width:" + (p[1] / total * 100) + "%;background:" + p[2] } }));
      legend.appendChild(el("span", {}, [
        el("i", { attrs: { style: "background:" + p[2] } }),
        document.createTextNode(p[0]), el("b", { text: p[1] }),
      ]));
    });
  }

  function renderTriChips() {
    var wrap = document.getElementById("t-chips");
    clear(wrap);
    var papers = triPapers();
    TRI_FILTERS.forEach(function (f) {
      var n = papers.filter(f.pred).length;
      if (!n && f.id !== "all" && f.id !== tri.filter && (f.id === "new" || f.id === "dropped" || f.id === "waiting")) return;
      wrap.appendChild(el("button", {
        className: "fchip", attrs: { type: "button", "aria-pressed": String(tri.filter === f.id) },
        on: { click: function () { tri.filter = f.id; tri.page = 0; tri.bulkConfirm = null; renderTriChips(); renderTriRows(); } },
      }, [document.createTextNode(f.label), el("span", { className: "x", text: String(n) })]));
    });
  }

  function libraryCell(p) {
    var lib = p.library;
    var dot, label;
    if (tri.job && tri.job.kind === "pdf" && tri.job.state === "running" && tri.job.pmids.indexOf(p.pmid) !== -1 &&
        !tri.job.results.some(function (r) { return r.pmid === p.pmid; })) {
      dot = "var(--accent)"; label = "getting PDF…";
    } else if (!lib) { dot = "var(--faint)"; label = "not added"; }
    else if (lib.has_pdf) { dot = "var(--s-pdf)"; label = "PDF"; }
    else if (lib.has_fulltext) { dot = "var(--s-full)"; label = "full text"; }
    else { dot = "var(--s-abs)"; label = lib.extraction_tier === "unavailable" ? "metadata only" : "abstract only"; }
    var kids = [el("i", { attrs: { style: "background:" + dot } }), document.createTextNode(label)];
    var sub = null;
    if (p.pending) sub = "waiting for Claude (" + p.pending.why + ")";
    else if (lib && p.decision && p.decision.decision === "excluded") sub = "stays in library";
    else if (lib && tri.view.triage.project && lib.projects.indexOf(tri.view.triage.project) !== -1) sub = "in " + tri.view.triage.project;
    if (sub) kids.push(el("small", { text: sub }));
    return el("td", { className: "tri-lib" }, kids);
  }

  function renderTriRows() {
    var rows = triVisible();
    tri.visible = rows;
    var pages = Math.max(1, Math.ceil(rows.length / TRI_PAGE_SIZE));
    if (tri.page >= pages) tri.page = 0;
    var start = tri.page * TRI_PAGE_SIZE;
    tri.pageRows = rows.slice(start, start + TRI_PAGE_SIZE);
    if (tri.active >= tri.pageRows.length) tri.active = tri.pageRows.length - 1;

    renderTriResult();
    var tbody = document.getElementById("t-rows");
    clear(tbody);
    if (!tri.pageRows.length) {
      tbody.appendChild(el("tr", {}, [el("td", { attrs: { colspan: "7" } }, [
        el("div", { className: "empty", text: triPapers().length ? "No papers match this filter." : "No metadata loaded yet -- use Load next below." }),
      ])]));
    }
    tri.pageRows.forEach(function (p, i) {
      var m = p.metadata;
      var dec = p.decision ? p.decision.decision : null;
      var tr = el("tr", { attrs: { "data-pmid": p.pmid } });
      tr.className = [tri.selected.has(p.pmid) ? "sel" : "", dec ? "d-" + dec : "", i === tri.active ? "kbd-active" : ""].join(" ").trim();

      var cb = el("input", { attrs: { type: "checkbox", "aria-label": "Select PMID " + p.pmid } });
      cb.checked = tri.selected.has(p.pmid);
      cb.addEventListener("change", function () {
        if (cb.checked) tri.selected.add(p.pmid); else tri.selected.delete(p.pmid);
        tr.classList.toggle("sel", cb.checked);
        renderTriActionBar();
      });
      tr.appendChild(el("td", {}, [cb]));

      var pmidKids = [el("div", { className: "tri-pmid", text: p.pmid })];
      if (p.new_since) pmidKids.push(el("span", { className: "tri-tag", text: "new", attrs: { title: "first returned after the run of " + p.new_since.slice(0, 10) } }));
      if (!p.in_latest_run) pmidKids.push(el("span", { className: "tri-tag muted", text: "not in latest run" }));
      tr.appendChild(el("td", {}, pmidKids));

      var authors = (m.authors || []).join(", ") + (m.authors_count > (m.authors || []).length ? " et al." : "");
      var byline = el("div", { className: "tri-byline" }, [
        document.createTextNode(authors + (authors && m.journal ? " · " : "")),
        el("i", { text: m.journal || "" }),
      ]);
      if (isReview(p)) byline.appendChild(el("span", { className: "tri-type", text: "Review" }));
      tr.appendChild(el("td", {}, [
        el("button", {
          className: "tri-title", text: m.title || "(untitled)",
          attrs: { type: "button", "aria-expanded": String(tri.open.has(p.pmid)) },
          on: { click: function () { toggleAbstract(p.pmid); } },
        }),
        byline,
      ]));
      tr.appendChild(el("td", { className: "num", text: m.year || "" }));
      tr.appendChild(el("td", {}, [
        el("span", { className: "step-mini " + (m.pmcid ? "ok" : "bad"), text: "PMC" }),
        document.createTextNode(" "),
        el("span", { className: "step-mini " + (m.doi ? "ok" : "bad"), text: "DOI" }),
      ]));
      tr.appendChild(libraryCell(p));

      var decWrap = el("div", { className: "tri-dec", attrs: { role: "group", "aria-label": "Decision for " + p.pmid } });
      ["included", "pending", "excluded"].forEach(function (d) {
        decWrap.appendChild(el("button", {
          className: d, text: TRI_DEC_LABEL[d],
          attrs: { type: "button", "aria-pressed": String(dec === d), disabled: tri.busy ? "disabled" : null },
          on: { click: function () { triDecide([p.pmid], dec === d ? "cleared" : d); } },
        }));
      });
      var decKids = [decWrap];
      var why = p.decision && p.decision.reason;
      if (why && why !== "triage:" + tri.slug) decKids.push(el("small", { className: "tri-why", text: why }));
      tr.appendChild(el("td", {}, decKids));
      tbody.appendChild(tr);

      if (tri.open.has(p.pmid)) {
        var extras = el("div", { className: "tri-mesh" });
        if (m.pmcid) extras.appendChild(el("span", { text: m.pmcid }));
        if (m.doi) extras.appendChild(el("span", { text: "doi:" + m.doi }));
        (m.mesh_terms || []).forEach(function (t) { extras.appendChild(el("span", { text: t })); });
        if (p.library) {
          extras.appendChild(el("button", {
            text: "Open paper panel", attrs: { type: "button" },
            on: { click: function () { openInLibrary(p.pmid); } },
          }));
        }
        tbody.appendChild(el("tr", { className: "tri-abs" }, [
          el("td"), el("td"),
          el("td", { attrs: { colspan: "5" } }, [
            el("div", { className: "tri-abstext", text: m.abstract || "No abstract in PubMed." }),
            extras,
          ]),
        ]));
      }
    });
    document.getElementById("t-selall").checked = rows.length > 0 && rows.every(function (p) { return tri.selected.has(p.pmid); });
    renderTriPager(pages);
    renderTriBulk();
  }

  function renderTriPager(pages) {
    var wrap = document.getElementById("t-pager");
    clear(wrap);
    if (pages <= 1) return;
    wrap.appendChild(el("button", {
      text: "‹ Prev", attrs: { type: "button", disabled: tri.page <= 0 ? "disabled" : null },
      on: { click: function () { tri.page--; tri.active = -1; renderTriRows(); } },
    }));
    wrap.appendChild(el("span", { className: "pageinfo", text: "page " + (tri.page + 1) + " of " + pages }));
    wrap.appendChild(el("button", {
      text: "Next ›", attrs: { type: "button", disabled: tri.page >= pages - 1 ? "disabled" : null },
      on: { click: function () { tri.page++; tri.active = -1; renderTriRows(); } },
    }));
  }

  function toggleAbstract(pmid) {
    if (tri.open.has(pmid)) tri.open.delete(pmid); else tri.open.add(pmid);
    renderTriRows();
  }

  function openInLibrary(pmid) {
    fetchJSON("/api/rows").then(function (rows) {
      setRows(rows);
      if (BY_PMID[pmid]) openDrawer(pmid);
    }).catch(function (err) { showError("could not open paper: " + describeFetchError(err)); });
  }

  function renderTriBatch() {
    var v = tri.view;
    var wrap = document.getElementById("t-batch");
    clear(wrap);
    var c = v.counts;
    var next = Math.min(v.triage.batch_size || 100, v.remaining);
    var info = "Metadata loaded for " + c.loaded + " of " + c.found + " PMIDs";
    if (c.missing) info += " · " + c.missing + " not returned by PubMed";
    wrap.appendChild(el("span", { className: "grow", text: info + "." }));
    var batchRunning = tri.job && tri.job.kind === "batch" && tri.job.state === "running";
    if (batchRunning) {
      wrap.appendChild(el("span", { text: "Loading " + next + " records from NCBI…" }));
    } else if (!v.remaining) {
      wrap.appendChild(el("span", { text: "All loaded." }));
    } else if (!tri.confirmBatch) {
      wrap.appendChild(el("button", {
        className: "cmdbtn", text: "Load next " + next + "…", attrs: { type: "button" },
        on: { click: function () { tri.confirmBatch = true; renderTriBatch(); } },
      }));
    } else {
      wrap.appendChild(el("span", { text: "Load metadata for PMIDs " + (c.loaded + c.missing + 1) + "–" + (c.loaded + c.missing + next) + " from NCBI?" }));
      wrap.appendChild(el("button", {
        className: "cmdbtn primary", text: "Load " + next, attrs: { type: "button" },
        on: { click: triLoadBatch },
      }));
      wrap.appendChild(el("button", {
        className: "cmdbtn", text: "Not now", attrs: { type: "button" },
        on: { click: function () { tri.confirmBatch = false; renderTriBatch(); } },
      }));
    }
  }

  function renderTriPending() {
    var wrap = document.getElementById("t-pending");
    clear(wrap);
    var n = tri.view.counts.pending;
    wrap.hidden = !n;
    if (!n) return;
    var cmd = "/ref:triage apply " + tri.slug;
    wrap.appendChild(el("span", { className: "grow" }, [
      el("b", { text: String(n) }),
      document.createTextNode(" paper" + (n === 1 ? "" : "s") + " need Claude for full text (PMC XML, PubMed text or publisher page). This tab updates when Claude is done."),
    ]));
    wrap.appendChild(el("code", { text: cmd }));
    wrap.appendChild(el("button", {
      className: "cmdbtn", text: "Copy command", attrs: { type: "button" },
      on: { click: function () { copyText(cmd); } },
    }));
  }

  function renderTriActionBar() {
    var bar = document.getElementById("t-actionbar");
    var n = tri.selected.size;
    bar.hidden = n === 0 && !(tri.job && tri.job.state === "running");
    document.getElementById("t-seln").textContent = String(n);
    bar.querySelectorAll("button[data-tdec],button[data-tjob]").forEach(function (b) {
      b.disabled = tri.busy || n === 0;
    });
    renderTriReasons(n);
  }

  // P3 reason chips: the linked project's `screening_reasons` (defaults when
  // unlinked or unset -- /ref:project set-reasons). One click decides the
  // selection with that reason; keys 1-9 pick the first nine exclusion reasons.
  function triReasons() {
    return (tri.view && tri.view.reasons) || {};
  }

  function renderTriReasons(n) {
    var wrap = document.getElementById("t-reasons");
    clear(wrap);
    [["excluded", "Exclude:"], ["pending", "Maybe:"], ["included", "Include:"]].forEach(function (g) {
      var list = triReasons()[g[0]] || [];
      if (!list.length) return;
      wrap.appendChild(el("span", { className: "lbl", text: g[1] }));
      list.forEach(function (reason, i) {
        wrap.appendChild(el("button", {
          className: "chip " + g[0], text: reason,
          attrs: { type: "button", disabled: (tri.busy || !n) ? "disabled" : null, title: g[0] === "excluded" && i < 9 ? "key " + (i + 1) : null },
          on: { click: function () { triDecide(Array.from(tri.selected), g[0], reason); } },
        }, g[0] === "excluded" && i < 9 ? [el("kbd", { text: String(i + 1) })] : []));
      });
    });
  }

  function triDecide(pmids, decision, reason) {
    if (!pmids.length || tri.busy) return;
    tri.busy = true;
    triStatus((decision === "included" ? "Including and adding " : "Saving ") + pmids.length + "…");
    renderTriRows();
    renderTriActionBar();
    var url = "/api/triage/" + encodeURIComponent(tri.slug) + "/decisions";
    var chunks = [];
    for (var i = 0; i < pmids.length; i += 500) chunks.push(pmids.slice(i, i + 500));
    var all = [];
    chunks.reduce(function (prev, chunk, idx) {
      return prev.then(function () {
        if (chunks.length > 1) triStatus("Saving " + (idx * 500 + chunk.length) + " / " + pmids.length + "…");
        var body = { pmids: chunk, decision: decision };
        if (reason) body.reason = reason;
        return postJSON(url, body).then(function (res) { all = all.concat(res.results || []); });
      });
    }, Promise.resolve())
      .then(function () {
        var res = { results: all };
        var failed = (res.results || []).filter(function (r) { return r.result !== "recorded"; });
        var added = (res.results || []).filter(function (r) { return r.add === "added"; }).length;
        var msg = decision === "cleared" ? "Cleared " : "Marked ";
        msg += (pmids.length - failed.length) + (decision === "cleared" ? "" : " as " + (TRI_DEC_LABEL[decision] || decision).toLowerCase());
        if (reason) msg += " (" + reason + ")";
        if (added) msg += " · added " + added + " to library";
        if (failed.length) msg += " · " + failed.length + " failed: " + failed[0].pmid + " " + (failed[0].error || "");
        triStatus(msg);
      })
      .catch(function (err) { triStatus("Not saved: " + err.message); })
      .then(function () {
        tri.busy = false;
        if (decision === "included") syncLibraryRows();
        return loadTriageView();
      });
  }

  function triLoadBatch() {
    tri.confirmBatch = false;
    postJSON("/api/triage/" + encodeURIComponent(tri.slug) + "/batch", { confirm: true })
      .then(function (res) {
        tri.job = { id: res.job_id, kind: "batch", state: "running", pmids: [], results: [] };
        renderTriBatch();
        pollJob();
      })
      .catch(function (err) { triStatus("Could not load: " + err.message); renderTriBatch(); });
  }

  function triStartJob(kind) {
    var pmids = Array.from(tri.selected);
    if (!pmids.length) return;
    var url = "/api/triage/" + encodeURIComponent(tri.slug) + "/jobs";
    if (kind === "full_text") {
      tri.busy = true;
      renderTriActionBar();
      postJSON(url, { kind: kind, pmids: pmids }).then(function (res) {
        var r = res.results || [];
        var queued = r.filter(function (x) { return x.result === "queued"; }).length;
        var have = r.filter(function (x) { return x.result === "already_full_text"; }).length;
        var failed = r.filter(function (x) { return x.result === "failed"; }).length;
        triStatus(queued + " queued for Claude" + (have ? " · " + have + " already have full text" : "") + (failed ? " · " + failed + " failed" : ""));
      }).catch(function (err) { triStatus("Not queued: " + err.message); })
        .then(function () { tri.busy = false; syncLibraryRows(); return loadTriageView(); });
      return;
    }
    postJSON(url, { kind: kind, pmids: pmids }).then(function (res) {
      tri.job = { id: res.job_id, kind: kind, state: "running", pmids: pmids, results: [] };
      triStatus("Getting PDFs for " + pmids.length + "…");
      renderTriRows();
      renderTriActionBar();
      pollJob();
    }).catch(function (err) { triStatus("Could not start: " + err.message); });
  }

  function pollJob() {
    clearTimeout(tri.pollTimer);
    if (!tri.job) return;
    fetchJSON("/api/jobs/" + tri.job.id).then(function (job) {
      tri.job.state = job.state;
      tri.job.results = job.results || [];
      if (job.state === "running") {
        if (tri.job.kind === "pdf") {
          triStatus("Getting PDFs… " + job.done + " / " + job.total);
          renderTriRows();
        }
        tri.pollTimer = setTimeout(pollJob, 1000);
        return;
      }
      if (job.state === "failed") {
        triStatus((tri.job.kind === "batch" ? "Loading failed: " : "PDF job failed: ") + (job.error || "unknown error"));
      } else if (tri.job.kind === "batch") {
        var o = job.outcome || {};
        triStatus("Loaded " + (o.loaded || 0) + " records" + ((o.missing || []).length ? " · " + o.missing.length + " not returned" : ""));
      } else {
        var attached = tri.job.results.filter(function (r) { return r.result === "attached" || r.result === "duplicate_noop"; }).length;
        var toClaude = tri.job.results.filter(function (r) { return r.pending; }).length;
        triStatus(attached + " PDFs attached · " + toClaude + " sent to Claude");
      }
      tri.job = null;
      loadTriageView();
      loadTriages();
      syncLibraryRows();
    }).catch(function (err) {
      triStatus("Lost track of the job: " + describeFetchError(err));
      tri.job = null;
    });
  }

  function schedulePendingPoll() {
    clearTimeout(tri.pendingTimer);
    if (!tri.view || !tri.view.counts.pending) return;
    tri.pendingTimer = setTimeout(function () {
      if (activeTab === "triage" && !tri.busy && !tri.job) loadTriageView(true); else schedulePendingPoll();
    }, 5000);
  }

  function triMoveActive(delta) {
    if (!tri.pageRows.length) return;
    tri.active = Math.max(0, Math.min(tri.pageRows.length - 1, tri.active + delta));
    renderTriRows();
    var row = document.querySelector('#t-rows tr[data-pmid="' + tri.pageRows[tri.active].pmid + '"]');
    if (row) row.scrollIntoView({ block: "nearest" });
  }

  function triKeydown(e) {
    var current = tri.pageRows[tri.active];
    var targets = tri.selected.size ? Array.from(tri.selected) : (current ? [current.pmid] : []);
    if (e.key === "/") { e.preventDefault(); document.getElementById("t-q").focus(); }
    else if (e.key === "j" || e.key === "ArrowDown") { e.preventDefault(); triMoveActive(1); }
    else if (e.key === "k" || e.key === "ArrowUp") { e.preventDefault(); triMoveActive(-1); }
    else if (e.key === "i") { e.preventDefault(); triDecide(targets, "included"); }
    else if (e.key === "m") { e.preventDefault(); triDecide(targets, "pending"); }
    else if (e.key === "x") { e.preventDefault(); triDecide(targets, "excluded"); }
    else if (/^[1-9]$/.test(e.key) && (triReasons().excluded || [])[+e.key - 1]) {
      e.preventDefault();
      triDecide(targets, "excluded", triReasons().excluded[+e.key - 1]);
    }
    else if (e.key === " " && current) {
      e.preventDefault();
      if (tri.selected.has(current.pmid)) tri.selected.delete(current.pmid); else tri.selected.add(current.pmid);
      renderTriRows();
      renderTriActionBar();
    } else if (e.key === "Enter" && current) { e.preventDefault(); toggleAbstract(current.pmid); }
  }

  function selectTriage(slug) {
    if (!slug) return;
    tri.slug = slug;
    tri.selected = new Set();
    tri.open = new Set();
    tri.page = 0;
    tri.active = -1;
    tri.filter = "all";
    tri.confirmBatch = false;
    tri.bulkConfirm = null;
    try { history.replaceState(null, "", location.search + "#triage/" + slug); } catch (e) { /* best effort */ }
    loadTriageView();
  }

  document.getElementById("t-pick").addEventListener("change", function (e) { selectTriage(e.target.value); });
  function onTriFilterChange() {
    tri.query = document.getElementById("t-q").value;
    tri.scope = document.getElementById("t-qscope").value;
    tri.yfrom = parseInt(document.getElementById("t-yfrom").value, 10) || null;
    tri.yto = parseInt(document.getElementById("t-yto").value, 10) || null;
    tri.type = document.getElementById("t-type").value;
    tri.journal = document.getElementById("t-journal").value;
    tri.lib = document.getElementById("t-libstate").value;
    tri.page = 0;
    tri.active = -1;
    tri.bulkConfirm = null;
    renderTriRows();
  }
  ["t-q", "t-yfrom", "t-yto"].forEach(function (id) {
    document.getElementById(id).addEventListener("input", onTriFilterChange);
  });
  ["t-qscope", "t-type", "t-journal", "t-libstate"].forEach(function (id) {
    document.getElementById(id).addEventListener("change", onTriFilterChange);
  });
  document.getElementById("t-fclear").addEventListener("click", function () {
    ["t-q", "t-yfrom", "t-yto"].forEach(function (id) { document.getElementById(id).value = ""; });
    ["t-type", "t-journal", "t-libstate"].forEach(function (id) { document.getElementById(id).value = ""; });
    document.getElementById("t-qscope").value = "all";
    tri.filter = "all";
    renderTriChips();
    onTriFilterChange();
  });
  document.getElementById("t-selall").addEventListener("change", function (e) {
    tri.visible.forEach(function (p) {
      if (e.target.checked) tri.selected.add(p.pmid); else tri.selected.delete(p.pmid);
    });
    renderTriRows();
    renderTriActionBar();
  });
  document.getElementById("t-project").addEventListener("change", function (e) {
    var project = e.target.value || null;
    postJSON("/api/triage/" + encodeURIComponent(tri.slug) + "/project", { project: project })
      .then(function (res) {
        triStatus(project ? "Linked to " + project + (res.replayed ? " · copied " + res.replayed + " decisions" : "") : "Unlinked from project");
      })
      .catch(function (err) { triStatus("Not linked: " + err.message); })
      .then(function () { loadTriageView(); loadTriages(); });
  });
  document.getElementById("t-actionbar").addEventListener("click", function (e) {
    var dec = e.target.closest("button[data-tdec]");
    if (dec) { triDecide(Array.from(tri.selected), dec.dataset.tdec); return; }
    var job = e.target.closest("button[data-tjob]");
    if (job) triStartJob(job.dataset.tjob);
  });
  document.getElementById("t-export").addEventListener("click", function () {
    if (!tri.slug) return;
    var n = tri.view ? tri.view.counts.decisions.included : 0;
    copyText("/ref:export-papers --triage " + tri.slug);
    if (!n) flash("copied -- no papers are included in this search yet");
  });
  document.getElementById("t-clearsel").addEventListener("click", function () {
    tri.selected = new Set();
    renderTriRows();
    renderTriActionBar();
  });

  function renderTriageTab() {
    if (!tri.view || tri.view.triage.slug !== tri.slug) loadTriageView(); else renderTriage();
  }

  // ------------------------------------------------------------ insights
  //
  // DASHBOARD_FEATURE_REQUESTS.md FR-09..FR-17. Everything here is derived
  // in the browser from one payload -- dashboard_insights.knowledge():
  // active claims, the concept registry, relations, per-paper MeSH terms,
  // authors and note excerpts -- intersected with the papers in scope (the
  // Papers filters when "follow" is on, plus an optional year range). No
  // LLM judgment and no writes: the synthesis draft is a deterministic
  // roll-up, and gap suggestions are copyable commands.

  var KNOW = DATA.knowledge || null;
  var knowPromise = null;

  function loadKnowledge() {
    if (KNOW || !LIVE) return Promise.resolve(KNOW);
    if (!knowPromise) {
      knowPromise = fetchJSON("/api/knowledge").then(
        function (k) { KNOW = k; knowPromise = null; return k; },
        function (err) { knowPromise = null; throw err; }
      );
    }
    return knowPromise;
  }

  var INSIGHT_VIEWS = [
    { id: "evidence", label: "Evidence map" },
    { id: "gaps", label: "Gaps" },
    { id: "timeline", label: "Topic timeline" },
    { id: "graph", label: "Knowledge graph" },
    { id: "clusters", label: "Clusters" },
    { id: "synthesis", label: "Synthesis draft" },
  ];
  var ins = {
    view: "evidence", rowDim: "population", colDim: "outcome", fixDim: "", fixVal: "", color: "direction",
    gapMax: 0, topics: null, metric: "papers", graphMode: "concepts", graphN: 60, zoom: 1, selected: null,
    yfrom: null, yto: null, follow: true, clusterQuery: "", graphCache: null, detail: null,
  };
  var CLAIM_DIMS = {
    population: "Population", intervention: "Intervention", comparator: "Comparator",
    outcome: "Outcome", study_type: "Study design", tier: "Evidence tier",
  };
  var DIR_KEYS = ["up", "down", "null", "other"];
  var DIR_LABEL = { up: "increase", down: "decrease", "null": "no difference", other: "other", mixed: "conflicting" };
  var DIR_COLOR = { up: "var(--accent)", down: "var(--s-oa)", "null": "var(--faint)", other: "var(--muted)", mixed: "var(--crit)" };
  var PALETTE = ["var(--c1)", "var(--c2)", "var(--c3)", "var(--c4)", "var(--c5)", "var(--c6)", "var(--c7)", "var(--c8)"];
  var MESH_NOISE = new Set([
    "humans", "animals", "male", "female", "adult", "aged", "aged, 80 and over", "middle aged", "young adult",
    "adolescent", "child", "child, preschool", "infant", "infant, newborn", "mice", "rats", "pregnancy",
    "retrospective studies", "prospective studies", "cross-sectional studies", "cohort studies",
    "case-control studies", "follow-up studies", "longitudinal studies", "surveys and questionnaires",
    "treatment outcome", "risk factors", "time factors", "reproducibility of results",
    "sensitivity and specificity", "severity of illness index", "disease models, animal", "cells, cultured",
  ]);

  function filtersActive() {
    return !!(state.query || state.project !== "all" || state.chips.length || sourceFilterSet);
  }

  function insightScope() {
    var base = ins.follow ? filteredRows() : ROWS;
    var rows = base.filter(function (r) {
      var y = parseInt(r.year, 10);
      if (ins.yfrom && !(y >= ins.yfrom)) return false;
      if (ins.yto && !(y <= ins.yto)) return false;
      return true;
    });
    var pmids = new Set(rows.map(function (r) { return r.pmid; }));
    var claims = ((KNOW && KNOW.claims) || []).filter(function (c) { return pmids.has(c.pmid); });
    return { rows: rows, pmids: pmids, claims: claims, papers: (KNOW && KNOW.papers) || {} };
  }

  // Apply an ad-hoc paper set (a map cell, a gap, a topic-year point...) as a
  // removable chip on the Papers tab. Not URL state: it is a drill-down.
  function applyPmidFilter(label, pmids) {
    var set = new Set(pmids);
    state.chips = state.chips.filter(function (c) { return c.id.indexOf("set:") !== 0; });
    state.chips.push({ id: "set:" + label, label: label + " (" + set.size + ")", pred: function (r) { return set.has(r.pmid); } });
    currentPage = 0;
    selectTab("papers");
    renderChips();
    renderTable();
    document.getElementById("p-papers").scrollIntoView({ block: "start" });
  }

  function paperButton(pmid) {
    var row = BY_PMID[pmid];
    return el("button", {
      className: "plink", attrs: { type: "button", title: row ? row.title || pmid : pmid },
      text: row ? (row.citekey || pmid) : pmid,
      on: { click: function () { if (BY_PMID[pmid]) openDrawer(pmid); } },
    });
  }

  function paperList(pmids, limit) {
    var ul = el("ul", { className: "ins-papers" });
    var list = Array.from(pmids).sort(function (a, b) {
      var ya = parseInt((BY_PMID[a] || {}).year, 10) || 0, yb = parseInt((BY_PMID[b] || {}).year, 10) || 0;
      return yb - ya || (a < b ? -1 : 1);
    });
    list.slice(0, limit || 25).forEach(function (pmid) {
      var row = BY_PMID[pmid] || {};
      ul.appendChild(el("li", {}, [
        paperButton(pmid),
        el("span", { text: row.title || "(untitled)" }),
        el("small", { text: row.year || "" }),
      ]));
    });
    if (list.length > (limit || 25)) ul.appendChild(el("li", { className: "more", text: "+" + (list.length - (limit || 25)) + " more" }));
    return ul;
  }

  function selectControl(label, value, options, onChange) {
    var sel = el("select", { attrs: { "aria-label": label } });
    options.forEach(function (o) {
      var opt = el("option", { attrs: { value: o[0] }, text: o[1] });
      if (o[0] === value) opt.selected = true;
      sel.appendChild(opt);
    });
    sel.addEventListener("change", function () { onChange(sel.value); });
    return el("label", {}, [document.createTextNode(label + " "), sel]);
  }

  function dimOptions(exclude) {
    return Object.keys(CLAIM_DIMS).filter(function (d) { return d !== exclude; }).map(function (d) { return [d, CLAIM_DIMS[d]]; });
  }

  function tally(claims, dim) {
    var by = {};
    claims.forEach(function (c) {
      var v = c[dim];
      if (!v) return;
      var t = by[v] || (by[v] = { value: v, claims: 0, pmids: new Set() });
      t.claims++;
      t.pmids.add(c.pmid);
    });
    return Object.keys(by).map(function (k) { return by[k]; }).sort(function (a, b) {
      return b.pmids.size - a.pmids.size || b.claims - a.claims || (a.value < b.value ? -1 : 1);
    });
  }

  function fixedClaims(scope) {
    if (!ins.fixDim || !ins.fixVal) return scope.claims;
    return scope.claims.filter(function (c) { return c[ins.fixDim] === ins.fixVal; });
  }

  function newCell() {
    return { claims: [], pmids: new Set(), dir: { up: 0, down: 0, "null": 0, other: 0 }, tier: {} };
  }

  function addToCell(cell, c) {
    cell.claims.push(c);
    cell.pmids.add(c.pmid);
    if (c.dir) cell.dir[c.dir]++;
    if (c.tier) cell.tier[c.tier] = (cell.tier[c.tier] || 0) + 1;
  }

  function dominantDir(d) {
    if (d.up && d.down) return "mixed";
    var best = null, n = 0;
    DIR_KEYS.forEach(function (k) { if (d[k] > n) { n = d[k]; best = k; } });
    return best || "other";
  }

  function evidenceMatrix(claims, rowDim, colDim, maxRows, maxCols) {
    var rowsT = tally(claims, rowDim).slice(0, maxRows);
    var colsT = tally(claims, colDim).slice(0, maxCols);
    var rset = {}, cset = {};
    rowsT.forEach(function (t) { rset[t.value] = true; });
    colsT.forEach(function (t) { cset[t.value] = true; });
    var cells = {};
    claims.forEach(function (c) {
      var rv = c[rowDim], cv = c[colDim];
      if (!rv || !cv || !rset.hasOwnProperty(rv) || !cset.hasOwnProperty(cv)) return;
      var key = rv + " " + cv;
      addToCell(cells[key] || (cells[key] = newCell()), c);
    });
    return { rows: rowsT, cols: colsT, cells: cells };
  }

  function renderInsightNav() {
    var nav = document.getElementById("ins-nav");
    clear(nav);
    INSIGHT_VIEWS.forEach(function (v) {
      nav.appendChild(el("button", {
        text: v.label, attrs: { type: "button", "aria-pressed": String(ins.view === v.id) },
        on: { click: function () { ins.view = v.id; ins.detail = null; renderInsights(); syncUrl(); } },
      }));
    });
  }

  function renderInsights() {
    renderInsightNav();
    var body = document.getElementById("ins-body");
    var scopeLine = document.getElementById("ins-scope");
    if (!KNOW) {
      clear(body);
      scopeLine.textContent = "";
      if (!LIVE) {
        body.appendChild(el("div", { className: "empty", text: "this static build has no knowledge payload -- rebuild it with /ref:dashboard --static" }));
        return;
      }
      body.appendChild(el("div", { className: "empty", text: "loading claims, concepts and topics…" }));
      loadKnowledge().then(function () { if (KNOW && activeTab === "insights") renderInsights(); }, function (err) {
        clear(body);
        body.appendChild(el("div", { className: "empty", text: "could not load /api/knowledge: " + describeFetchError(err) }));
      });
      return;
    }
    var scope = insightScope();
    scopeLine.textContent = scope.rows.length + " papers · " + scope.claims.length + " active claims in scope" +
      (ins.follow && filtersActive() ? " · following the Papers filters" : "");
    clear(body);
    if (!scope.rows.length) {
      body.appendChild(el("div", { className: "empty", text: "no papers in scope -- loosen the Papers filters or the year range" }));
      return;
    }
    ({
      evidence: renderEvidenceMap, gaps: renderGaps, timeline: renderTimeline,
      graph: renderGraph, clusters: renderClusters, synthesis: renderSynthesis,
    }[ins.view] || renderEvidenceMap)(body, scope);
  }

  document.getElementById("ins-follow").addEventListener("change", function (e) { ins.follow = e.target.checked; renderInsights(); });
  ["ins-yfrom", "ins-yto"].forEach(function (id) {
    document.getElementById(id).addEventListener("change", function () {
      ins.yfrom = parseInt(document.getElementById("ins-yfrom").value, 10) || null;
      ins.yto = parseInt(document.getElementById("ins-yto").value, 10) || null;
      renderInsights();
    });
  });

  function noClaimsNotice(body) {
    body.appendChild(el("div", { className: "empty", text: "no extracted claims among these papers yet -- run /ref:extract on them to populate the evidence views" }));
  }

  function matrixControls(scope, extra) {
    var bar = el("div", { className: "ins-controls" });
    bar.appendChild(selectControl("Rows", ins.rowDim, dimOptions(ins.colDim), function (v) { ins.rowDim = v; ins.detail = null; renderInsights(); }));
    bar.appendChild(selectControl("Columns", ins.colDim, dimOptions(ins.rowDim), function (v) { ins.colDim = v; ins.detail = null; renderInsights(); }));
    bar.appendChild(selectControl("Only where", ins.fixDim, [["", "(all claims)"]].concat(dimOptions()), function (v) {
      ins.fixDim = v; ins.fixVal = ""; ins.detail = null; renderInsights();
    }));
    if (ins.fixDim) {
      var values = tally(scope.claims, ins.fixDim).slice(0, 80);
      if (ins.fixVal && !values.some(function (t) { return t.value === ins.fixVal; })) ins.fixVal = "";
      bar.appendChild(selectControl("is", ins.fixVal, [["", "(choose)"]].concat(values.map(function (t) {
        return [t.value, t.value + " (" + t.pmids.size + ")"];
      })), function (v) { ins.fixVal = v; ins.detail = null; renderInsights(); }));
    }
    (extra || []).forEach(function (x) { bar.appendChild(x); });
    return bar;
  }

  function pubmedQuery(values) {
    return values.filter(Boolean).map(function (v) { return '("' + v.replace(/["']/g, "") + '")'; }).join(" AND ");
  }

  function gapActions(values, candidates) {
    var q = pubmedQuery(values);
    var slug = ("gap-" + values.filter(Boolean).join("-")).toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 48).replace(/^-+|-+$/g, "");
    var wrap = el("div", { className: "pcmds" }, [
      el("button", { className: "cmdbtn", text: "Copy PubMed query", attrs: { type: "button", title: q }, on: { click: function () { copyText(q); } } }),
      el("button", {
        className: "cmdbtn", text: "Copy /ref:search-pubmed", attrs: { type: "button" },
        on: { click: function () { copyText("/ref:search-pubmed '" + q + "' --slug " + slug + " --create"); } },
      }),
    ]);
    if (candidates && candidates.size) {
      wrap.appendChild(el("button", {
        className: "cmdbtn", text: "Candidate papers (" + candidates.size + ")", attrs: { type: "button" },
        on: { click: function () { applyPmidFilter("gap: " + values.filter(Boolean).join(" × "), Array.from(candidates)); } },
      }));
    }
    return wrap;
  }

  function claimTable(claims, limit) {
    var table = el("table", { className: "ins-table" }, [el("tr", {}, [
      el("th", { text: "Paper" }), el("th", { text: "Intervention" }), el("th", { text: "Outcome" }),
      el("th", { text: "Direction" }), el("th", { text: "Tier" }), el("th", { text: "Design" }),
    ])]);
    claims.slice(0, limit || 60).forEach(function (c) {
      table.appendChild(el("tr", {}, [
        el("td", {}, [paperButton(c.pmid)]),
        el("td", { text: c.intervention || "–" }),
        el("td", { text: c.outcome || "–" }),
        el("td", {}, [el("span", { className: "dirtag", attrs: { style: "--c:" + DIR_COLOR[c.dir || "other"] }, text: c.direction || "–" })]),
        el("td", { text: c.tier || "–" }),
        el("td", { text: c.study_type || "–" }),
      ]));
    });
    return el("div", { className: "tablewrap ins-tablewrap" }, [table]);
  }

  // ------------------------------------------------ evidence map (FR-09)

  function renderEvidenceMap(body, scope) {
    body.appendChild(matrixControls(scope, [
      selectControl("Colour by", ins.color, [["direction", "effect direction"], ["tier", "evidence tier"], ["count", "paper count"]],
        function (v) { ins.color = v; renderInsights(); }),
    ]));
    var claims = fixedClaims(scope);
    if (!claims.length) { noClaimsNotice(body); return; }
    var m = evidenceMatrix(claims, ins.rowDim, ins.colDim, 18, 14);
    if (!m.rows.length || !m.cols.length) {
      body.appendChild(el("div", { className: "empty", text: "no claims record both a " + CLAIM_DIMS[ins.rowDim].toLowerCase() + " and a " + CLAIM_DIMS[ins.colDim].toLowerCase() + " -- pick other dimensions" }));
      return;
    }
    var maxPapers = 1;
    Object.keys(m.cells).forEach(function (k) { maxPapers = Math.max(maxPapers, m.cells[k].pmids.size); });

    var table = el("table", { className: "evmap" });
    table.appendChild(el("tr", {}, [el("th", { className: "corner", text: CLAIM_DIMS[ins.rowDim] + " ↓ · " + CLAIM_DIMS[ins.colDim] + " →" })]
      .concat(m.cols.map(function (c) { return el("th", { className: "col", attrs: { title: c.value + " · " + c.pmids.size + " papers" } }, [el("span", { text: c.value })]); }))));
    m.rows.forEach(function (r) {
      var tr = el("tr", {}, [el("th", { className: "rowlbl", attrs: { title: r.value } }, [
        el("span", { text: r.value }), el("small", { text: String(r.pmids.size) }),
      ])]);
      m.cols.forEach(function (c) {
        var cell = m.cells[r.value + " " + c.value];
        var n = cell ? cell.pmids.size : 0;
        var gap = !cell && r.pmids.size >= 2 && c.pmids.size >= 2;
        var style = "";
        if (cell) {
          var color = ins.color === "count" ? "var(--accent)"
            : ins.color === "tier" ? ((cell.tier.full || 0) >= (cell.tier.abstract || 0) ? "var(--s-pdf)" : "var(--s-abs)")
              : DIR_COLOR[dominantDir(cell.dir)];
          style = "background:color-mix(in srgb," + color + " " + Math.round(25 + 75 * n / maxPapers) + "%,transparent)";
        }
        var label = r.value + " × " + c.value + ": " + (cell ? n + " papers, " + cell.claims.length + " claims, " + DIR_LABEL[dominantDir(cell.dir)] : gap ? "no claims (gap)" : "no claims");
        tr.appendChild(el("td", {}, [el("button", {
          className: "evcell" + (gap ? " gap" : "") + (cell ? "" : " none"),
          attrs: { type: "button", style: style || null, title: label, "aria-label": label },
          on: { click: function () { ins.detail = { rv: r.value, cv: c.value }; renderInsights(); } },
        }, cell ? [el("span", { className: "ct", text: String(n) })] : [])]));
      });
      table.appendChild(tr);
    });
    body.appendChild(el("div", { className: "evwrap" }, [table]));

    var legend = el("div", { className: "tri-legend" });
    var swatches = ins.color === "tier" ? [["full text", "var(--s-pdf)"], ["abstract", "var(--s-abs)"]]
      : ins.color === "count" ? [["more papers = stronger colour", "var(--accent)"]]
        : ["up", "down", "null", "mixed"].map(function (k) { return [DIR_LABEL[k], DIR_COLOR[k]]; });
    swatches.forEach(function (s) { legend.appendChild(el("span", {}, [el("i", { attrs: { style: "background:" + s[1] } }), document.createTextNode(s[0])])); });
    legend.appendChild(el("span", {}, [el("i", { className: "gapsw" }), document.createTextNode("gap: both sides studied, never together")]));
    body.appendChild(legend);

    var d = null;
    if (ins.detail && ins.detail.rv !== undefined) {
      var dr = m.rows.filter(function (t) { return t.value === ins.detail.rv; })[0];
      var dc = m.cols.filter(function (t) { return t.value === ins.detail.cv; })[0];
      if (dr && dc) d = { r: dr, c: dc, cell: m.cells[dr.value + "\u0000" + dc.value] };
    }
    if (!d) return;
    var panel = el("div", { className: "panel ins-detail" }, [el("h2", { text: d.r.value + " × " + d.c.value })]);
    if (d.cell) {
      var dirs = DIR_KEYS.filter(function (k) { return d.cell.dir[k]; }).map(function (k) { return DIR_LABEL[k] + " " + d.cell.dir[k]; });
      panel.appendChild(el("div", { className: "sub", text: d.cell.pmids.size + " papers · " + d.cell.claims.length + " claims · " + (dirs.join(" · ") || "direction not reported") }));
      panel.appendChild(el("div", { className: "pcmds" }, [el("button", {
        className: "cmdbtn primary", text: "Show " + d.cell.pmids.size + " papers", attrs: { type: "button" },
        on: { click: function () { applyPmidFilter(d.r.value + " × " + d.c.value, Array.from(d.cell.pmids)); } },
      })]));
      panel.appendChild(claimTable(d.cell.claims));
    } else {
      var union = new Set(Array.from(d.r.pmids).concat(Array.from(d.c.pmids)));
      panel.appendChild(el("p", { className: "prose", text: "No claim in scope links these. “" + d.r.value + "” appears in " + d.r.pmids.size + " papers and “" + d.c.value + "” in " + d.c.pmids.size + "." }));
      panel.appendChild(gapActions([d.r.value, d.c.value, ins.fixVal], union));
    }
    body.appendChild(panel);
  }

  // ---------------------------------------------- gaps (FR-12 / FR-16)

  function ioPairs(claims) {
    var pairs = {};
    claims.forEach(function (c) {
      if (!c.intervention || !c.outcome) return;
      var key = c.intervention + " " + c.outcome;
      var p = pairs[key] || (pairs[key] = newCell());
      p.i = c.intervention;
      p.o = c.outcome;
      addToCell(p, c);
    });
    return Object.keys(pairs).map(function (k) { return pairs[k]; });
  }

  function findGaps(claims, rowDim, colDim, maxCount) {
    var m = evidenceMatrix(claims, rowDim, colDim, 30, 30);
    var gaps = [];
    m.rows.forEach(function (r) {
      if (r.pmids.size < 2) return;
      m.cols.forEach(function (c) {
        if (c.pmids.size < 2) return;
        var cell = m.cells[r.value + " " + c.value];
        var n = cell ? cell.pmids.size : 0;
        if (n > maxCount) return;
        gaps.push({ r: r, c: c, cell: cell, n: n, score: r.pmids.size * c.pmids.size / (1 + n) });
      });
    });
    return gaps.sort(function (a, b) { return b.score - a.score || (a.r.value < b.r.value ? -1 : 1); });
  }

  function unresolvedConflicts(scope) {
    var names = {};
    ((KNOW && KNOW.concepts) || []).forEach(function (c) { names[c.id] = c.name; });
    return ((KNOW && KNOW.relations) || []).filter(function (r) {
      var open = (r.type === "potential_conflict" && r.review_state !== "reviewed") || (r.type === "contradicts" && r.stale);
      return open && (!r.pmids.length || r.pmids.some(function (p) { return scope.pmids.has(p); }));
    }).map(function (r) {
      return { r: r, subject: names[r.subject] || r.subject, object: names[r.object] || r.object };
    });
  }

  function renderGaps(body, scope) {
    body.appendChild(matrixControls(scope, [
      selectControl("Show combinations with", String(ins.gapMax), [["0", "no claims"], ["1", "at most one paper"]],
        function (v) { ins.gapMax = parseInt(v, 10); renderInsights(); }),
    ]));
    var claims = fixedClaims(scope);
    if (!claims.length) { noClaimsNotice(body); return; }

    var gaps = findGaps(claims, ins.rowDim, ins.colDim, ins.gapMax).slice(0, 30);
    var sec1 = el("div", { className: "panel" }, [el("h2", {}, [
      document.createTextNode("Sparse " + CLAIM_DIMS[ins.rowDim].toLowerCase() + " × " + CLAIM_DIMS[ins.colDim].toLowerCase() + " combinations"),
      el("span", { text: "ranked by papers on each side ÷ (1 + papers together)" }),
    ])]);
    if (!gaps.length) {
      sec1.appendChild(el("div", { className: "empty", text: "no sparse combinations -- every pair of well-studied values is covered (or too few claims to tell)" }));
    }
    var ol = el("ol", { className: "gaplist" });
    gaps.forEach(function (g, i) {
      var open = ins.detail && ins.detail.gap === i;
      var li = el("li", {}, [el("button", {
        className: "gaprow", attrs: { type: "button", "aria-expanded": String(!!open) },
        on: { click: function () { ins.detail = open ? null : { gap: i }; renderInsights(); } },
      }, [
        el("b", { text: g.r.value + " × " + g.c.value }),
        el("span", { text: (g.n ? "only " + g.n + " paper" : "no claims") + " · " + g.r.pmids.size + " / " + g.c.pmids.size + " papers on each side" }),
      ])]);
      if (open) {
        var union = new Set(Array.from(g.r.pmids).concat(Array.from(g.c.pmids)));
        li.appendChild(gapActions([g.r.value, g.c.value, ins.fixVal], union));
        if (g.cell) li.appendChild(claimTable(g.cell.claims));
        li.appendChild(paperList(union, 10));
      }
      ol.appendChild(li);
    });
    sec1.appendChild(ol);
    body.appendChild(sec1);

    var singles = ioPairs(scope.claims).filter(function (p) { return p.pmids.size === 1; })
      .sort(function (a, b) { return b.claims.length - a.claims.length || (a.i < b.i ? -1 : 1); });
    var sec2 = el("div", { className: "panel" }, [el("h2", {}, [
      document.createTextNode("Single-study findings"), el("span", { text: singles.length + " intervention → outcome pairs rest on one paper" }),
    ])]);
    if (!singles.length) sec2.appendChild(el("div", { className: "empty", text: "every intervention → outcome pair in scope has at least two papers" }));
    var ul2 = el("ul", { className: "ins-list" });
    singles.slice(0, 15).forEach(function (p) {
      var pmid = Array.from(p.pmids)[0];
      ul2.appendChild(el("li", {}, [paperButton(pmid), el("span", { text: p.i + " → " + p.o + " (" + DIR_LABEL[dominantDir(p.dir)] + ")" })]));
    });
    sec2.appendChild(ul2);

    var conflicts = unresolvedConflicts(scope);
    var sec3 = el("div", { className: "panel" }, [el("h2", {}, [
      document.createTextNode("Unresolved conflicts"), el("span", { text: conflicts.length + " relation" + (conflicts.length === 1 ? "" : "s") }),
    ])]);
    if (!conflicts.length) sec3.appendChild(el("div", { className: "empty", text: "no unreviewed potential conflicts or stale contradictions" }));
    var ul3 = el("ul", { className: "ins-list" });
    conflicts.slice(0, 15).forEach(function (x) {
      ul3.appendChild(el("li", {}, [
        el("span", { className: "dirtag", attrs: { style: "--c:var(--crit)" }, text: x.r.type + (x.r.stale ? " (stale)" : "") }),
        el("span", { text: x.subject + " ↔ " + x.object }),
      ].concat(x.r.pmids.slice(0, 6).map(paperButton))));
    });
    sec3.appendChild(ul3);

    var pmids = Array.from(scope.pmids);
    var gapsCmd = state.project !== "all" && state.project !== "none" && ins.follow
      ? "/ref:gaps --project " + state.project
      : pmids.length <= 50 ? "/ref:gaps " + pmids.join(" ") : "/ref:gaps --project <slug>";
    sec3.appendChild(el("div", { className: "pcmds" }, [
      el("code", { text: gapsCmd }),
      el("button", { className: "cmdbtn", text: "Copy", attrs: { type: "button" }, on: { click: function () { copyText(gapsCmd); } } }),
    ]));
    body.appendChild(el("div", { className: "grid g2" }, [sec2, sec3]));
  }

  // --------------------------------------------- topics (FR-11, FR-13/14)

  function normWords(s) {
    return " " + String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim() + " ";
  }

  // Topic terms per paper: MeSH headings (minus check tags), concept names
  // whose name/alias appears in the title, and claim population /
  // intervention / outcome values -- all folded onto the concept registry's
  // canonical name when an alias matches.
  function topicIndex(scope) {
    var aliases = {};
    ((KNOW && KNOW.concepts) || []).forEach(function (c) {
      [c.name].concat(c.aliases || []).forEach(function (a) {
        var k = normWords(a).trim();
        if (k.length >= 3) aliases[k] = c.name;
      });
    });
    var aliasKeys = Object.keys(aliases);
    var terms = {};
    function add(label, kind, pmid) {
      if (!label) return;
      var nk = normWords(label).trim();
      if (!nk) return;
      var canon = aliases[nk] || label;
      var key = normWords(canon).trim();
      if (MESH_NOISE.has(label.toLowerCase()) || MESH_NOISE.has(key)) return;
      var t = terms[key] || (terms[key] = { key: key, label: canon, kinds: {}, pmids: new Set() });
      t.kinds[aliases[nk] ? "concept" : kind] = true;
      t.pmids.add(pmid);
    }
    scope.rows.forEach(function (r) {
      var info = scope.papers[r.pmid] || {};
      (info.mesh || []).forEach(function (m) { add(m, "mesh", r.pmid); });
      var title = normWords(r.title);
      aliasKeys.forEach(function (a) { if (title.indexOf(" " + a + " ") >= 0) add(aliases[a], "concept", r.pmid); });
    });
    scope.claims.forEach(function (c) {
      add(c.population, "population", c.pmid);
      add(c.intervention, "intervention", c.pmid);
      add(c.outcome, "outcome", c.pmid);
    });
    return Object.keys(terms).map(function (k) { return terms[k]; }).sort(function (a, b) {
      return b.pmids.size - a.pmids.size || (a.label < b.label ? -1 : 1);
    });
  }

  function termKind(t) {
    var order = ["concept", "intervention", "outcome", "population", "mesh"];
    for (var i = 0; i < order.length; i++) if (t.kinds[order[i]]) return order[i];
    return "mesh";
  }

  function renderTimeline(body, scope) {
    var terms = topicIndex(scope);
    if (!terms.length) {
      body.appendChild(el("div", { className: "empty", text: "no topic terms in scope -- MeSH terms come with /ref:add metadata, concepts and claim fields with /ref:extract" }));
      return;
    }
    var byKey = {};
    terms.forEach(function (t) { byKey[t.key] = t; });
    if (!ins.topics) ins.topics = terms.slice(0, 4).map(function (t) { return t.key; });
    var chosen = ins.topics.filter(function (k) { return byKey[k]; }).slice(0, 8);

    var addSel = el("select", { attrs: { "aria-label": "Add a topic" } }, [el("option", { attrs: { value: "" }, text: "Add a topic…" })]
      .concat(terms.slice(0, 120).filter(function (t) { return chosen.indexOf(t.key) < 0; }).map(function (t) {
        return el("option", { attrs: { value: t.key }, text: t.label + " (" + t.pmids.size + ")" });
      })));
    addSel.addEventListener("change", function () {
      if (!addSel.value) return;
      ins.topics = chosen.concat([addSel.value]).slice(-8);
      renderInsights();
    });
    var controls = el("div", { className: "ins-controls" }, [
      el("label", {}, [addSel]),
      selectControl("Measure", ins.metric, [["papers", "papers per year"], ["share", "% of that year's papers"]], function (v) { ins.metric = v; renderInsights(); }),
      el("button", { className: "cmdbtn", text: "Top topics", attrs: { type: "button" }, on: { click: function () { ins.topics = null; renderInsights(); } } }),
    ]);
    body.appendChild(controls);

    var chips = el("div", { className: "toolbar" });
    chosen.forEach(function (k, i) {
      chips.appendChild(el("span", { className: "fchip", attrs: { style: "border-color:" + PALETTE[i % PALETTE.length] } }, [
        el("i", { className: "sw", attrs: { style: "background:" + PALETTE[i % PALETTE.length] } }),
        el("span", { text: byKey[k].label }),
        el("button", {
          className: "x", text: "×", attrs: { type: "button", "aria-label": "remove topic " + byKey[k].label },
          on: { click: function () { ins.topics = chosen.filter(function (x) { return x !== k; }); renderInsights(); } },
        }),
      ]));
    });
    body.appendChild(chips);

    var perYear = {};
    scope.rows.forEach(function (r) { var y = parseInt(r.year, 10); if (y) perYear[y] = (perYear[y] || 0) + 1; });
    var years = Object.keys(perYear).map(Number).sort(function (a, b) { return a - b; });
    if (!years.length) { body.appendChild(el("div", { className: "empty", text: "no dated papers in scope" })); return; }
    var y0 = Math.max(years[0], years[years.length - 1] - 59), y1 = years[years.length - 1];

    var series = chosen.map(function (k) {
      var t = byKey[k];
      var counts = {};
      t.pmids.forEach(function (p) {
        var y = parseInt((BY_PMID[p] || {}).year, 10);
        if (!y || y < y0) return;
        (counts[y] = counts[y] || []).push(p);
      });
      var pts = [];
      for (var y = y0; y <= y1; y++) {
        var n = (counts[y] || []).length;
        pts.push({ year: y, pmids: counts[y] || [], n: n, v: ins.metric === "share" ? (perYear[y] ? 100 * n / perYear[y] : 0) : n });
      }
      return { t: t, pts: pts };
    });

    var W = 760, H = 260, padL = 40, padR = 12, padT = 12, padB = 26;
    var max = 1;
    series.forEach(function (s) { s.pts.forEach(function (p) { max = Math.max(max, p.v); }); });
    var span = Math.max(1, y1 - y0);
    function X(y) { return padL + (y - y0) / span * (W - padL - padR); }
    function Y(v) { return padT + (1 - v / max) * (H - padT - padB); }
    var svg = svgEl("svg", { viewBox: "0 0 " + W + " " + H, class: "chart", role: "img", "aria-label": "Topic trends over time" });
    [0, max / 2, max].forEach(function (v) {
      svg.appendChild(svgEl("line", { x1: padL, x2: W - padR, y1: Y(v), y2: Y(v), stroke: "var(--line)" }));
      var t = svgEl("text", { x: padL - 6, y: Y(v) + 4, "text-anchor": "end" });
      t.textContent = ins.metric === "share" ? Math.round(v) + "%" : String(Math.round(v * 10) / 10);
      svg.appendChild(t);
    });
    var step = Math.max(1, Math.ceil((y1 - y0 + 1) / 12));
    for (var yy = y0; yy <= y1; yy += step) {
      var lt = svgEl("text", { x: X(yy), y: H - 6, "text-anchor": "middle" });
      lt.textContent = String(yy);
      svg.appendChild(lt);
    }
    series.forEach(function (s, i) {
      var color = PALETTE[i % PALETTE.length];
      svg.appendChild(svgEl("polyline", {
        points: s.pts.map(function (p) { return X(p.year) + "," + Y(p.v); }).join(" "),
        fill: "none", stroke: color, "stroke-width": 2,
      }));
      s.pts.forEach(function (p) {
        if (!p.n) return;
        var c = svgEl("circle", { cx: X(p.year), cy: Y(p.v), r: 3.5, fill: color, tabindex: "0", role: "button", class: "pt",
          "aria-label": s.t.label + " " + p.year + ": " + p.n + " papers" });
        var title = svgEl("title", {});
        title.textContent = s.t.label + " · " + p.year + ": " + p.n + " paper" + (p.n === 1 ? "" : "s");
        c.appendChild(title);
        function go() { applyPmidFilter(s.t.label + " · " + p.year, p.pmids); }
        c.addEventListener("click", go);
        c.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
        svg.appendChild(c);
      });
    });
    body.appendChild(el("div", { className: "panel" }, [svg]));

    var table = el("table", { className: "ins-table" }, [el("tr", {}, [
      el("th", { text: "Topic" }), el("th", { text: "Source" }), el("th", { className: "num", text: "Papers" }),
      el("th", { className: "num", text: "First" }), el("th", { className: "num", text: "Peak" }), el("th", { text: "Last 3 years vs 3 before" }), el("th", { text: "" }),
    ])]);
    series.forEach(function (s, i) {
      var first = null, peak = null;
      s.pts.forEach(function (p) { if (p.n && first === null) first = p.year; if (p.n && (!peak || p.n > peak.n)) peak = p; });
      var recent = 0, before = 0;
      s.pts.forEach(function (p) { if (p.year > y1 - 3) recent += p.n; else if (p.year > y1 - 6) before += p.n; });
      var trend = recent > before ? "rising (" + before + " → " + recent + ")" : recent < before ? "falling (" + before + " → " + recent + ")" : "steady (" + recent + ")";
      table.appendChild(el("tr", {}, [
        el("td", {}, [el("i", { className: "sw", attrs: { style: "background:" + PALETTE[i % PALETTE.length] } }), document.createTextNode(" " + s.t.label)]),
        el("td", { text: termKind(s.t) }),
        el("td", { className: "num", text: String(s.t.pmids.size) }),
        el("td", { className: "num", text: first || "–" }),
        el("td", { className: "num", text: peak ? peak.year : "–" }),
        el("td", { text: trend }),
        el("td", {}, [el("button", {
          className: "cmdbtn", text: "Papers", attrs: { type: "button" },
          on: { click: function () { applyPmidFilter("topic: " + s.t.label, Array.from(s.t.pmids)); } },
        })]),
      ]));
    });
    body.appendChild(el("div", { className: "tablewrap ins-tablewrap" }, [table]));
  }

  // ------------------------------------ knowledge graph (FR-10/13/15)

  function cooccurrence(terms, maxTerms, minPapers) {
    var chosen = terms.filter(function (t) { return t.pmids.size >= minPapers; }).slice(0, maxTerms);
    var byPaper = {};
    chosen.forEach(function (t) { t.pmids.forEach(function (p) { (byPaper[p] = byPaper[p] || []).push(t.key); }); });
    var adj = {};
    chosen.forEach(function (t) { adj[t.key] = {}; });
    Object.keys(byPaper).forEach(function (p) {
      var ks = byPaper[p];
      for (var i = 0; i < ks.length; i++) {
        for (var j = i + 1; j < ks.length; j++) {
          adj[ks[i]][ks[j]] = (adj[ks[i]][ks[j]] || 0) + 1;
          adj[ks[j]][ks[i]] = (adj[ks[j]][ks[i]] || 0) + 1;
        }
      }
    });
    return { chosen: chosen, adj: adj };
  }

  // Deterministic label propagation: good enough to colour neighbourhoods
  // and name clusters, and stable across re-renders of the same data.
  function labelPropagation(ids, adj) {
    var label = {};
    ids.forEach(function (id, i) { label[id] = i; });
    for (var it = 0; it < 15; it++) {
      var changed = false;
      ids.forEach(function (id) {
        var score = {};
        var nbrs = adj[id] || {};
        Object.keys(nbrs).forEach(function (n) { if (label.hasOwnProperty(n)) score[label[n]] = (score[label[n]] || 0) + nbrs[n]; });
        var best = label[id], bestS = 0;
        Object.keys(score).forEach(function (l) {
          var sc = score[l];
          if (sc > bestS || (sc === bestS && +l < best)) { bestS = sc; best = +l; }
        });
        if (bestS > 0 && best !== label[id]) { label[id] = best; changed = true; }
      });
      if (!changed) break;
    }
    return label;
  }

  function edgesFromAdj(nodes, adj, minW, maxEdges) {
    var keep = {};
    nodes.forEach(function (n) { keep[n.id] = true; });
    var edges = [];
    nodes.forEach(function (n) {
      Object.keys(adj[n.id] || {}).forEach(function (m) {
        if (n.id < m && keep[m] && adj[n.id][m] >= minW) edges.push({ a: n.id, b: m, w: adj[n.id][m], kind: "co" });
      });
    });
    edges.sort(function (x, y) { return y.w - x.w; });
    return edges.slice(0, maxEdges);
  }

  function buildGraph(scope) {
    var N = ins.graphN;
    var nodes = [], edges = [];
    if (ins.graphMode === "claims") {
      var take = function (dim, n, prefix) {
        return tally(scope.claims, dim).slice(0, n).map(function (t) {
          return { id: prefix + t.value.toLowerCase(), label: t.value, kind: dim, size: t.pmids.size, pmids: t.pmids };
        });
      };
      nodes = take("intervention", Math.round(N * 0.4), "i:").concat(take("outcome", Math.round(N * 0.4), "o:"), take("population", Math.round(N * 0.2), "p:"));
      var have = {};
      nodes.forEach(function (n) { have[n.id] = n; });
      var agg = {};
      function link(key, a, b, kind, c) {
        if (!have[a] || !have[b]) return;
        var e = agg[key] || (agg[key] = { a: a, b: b, kind: kind, cell: newCell() });
        addToCell(e.cell, c);
      }
      scope.claims.forEach(function (c) {
        var i = c.intervention && "i:" + c.intervention.toLowerCase();
        var o = c.outcome && "o:" + c.outcome.toLowerCase();
        var p = c.population && "p:" + c.population.toLowerCase();
        if (i && o) link(i + ">" + o, i, o, "io", c);
        if (p && i) link(p + ">" + i, p, i, "pi", c);
      });
      edges = Object.keys(agg).map(function (k) {
        var e = agg[k];
        return { a: e.a, b: e.b, w: e.cell.pmids.size, kind: e.kind, cell: e.cell, conflict: e.kind === "io" && e.cell.dir.up > 0 && e.cell.dir.down > 0 };
      });
      var names = {};
      ((KNOW && KNOW.concepts) || []).forEach(function (c) { names[c.id] = c.name.toLowerCase(); });
      var find = function (name) {
        if (!name) return null;
        return have["i:" + name] ? "i:" + name : have["o:" + name] ? "o:" + name : have["p:" + name] ? "p:" + name : null;
      };
      unresolvedConflicts(scope).concat(((KNOW && KNOW.relations) || []).filter(function (r) {
        return (r.type === "supports" || r.type === "contradicts" || r.type === "replicates" || r.type === "extends") &&
          r.pmids.some(function (p) { return scope.pmids.has(p); });
      }).map(function (r) { return { r: r }; })).forEach(function (x) {
        var a = find(names[x.r.subject]), b = find(names[x.r.object]);
        if (a && b && a !== b) {
          edges.push({ a: a, b: b, w: x.r.pmids.length || 1, kind: "rel", rel: x.r,
            conflict: x.r.type === "potential_conflict" || x.r.type === "contradicts" });
        }
      });
    } else if (ins.graphMode === "papers") {
      var terms = topicIndex(scope);
      var concepts = terms.slice(0, Math.max(8, Math.round(N / 3)));
      var paperTerms = {};
      concepts.forEach(function (t) { t.pmids.forEach(function (p) { (paperTerms[p] = paperTerms[p] || []).push(t); }); });
      var papers = Object.keys(paperTerms).sort(function (a, b) {
        return paperTerms[b].length - paperTerms[a].length || (a < b ? -1 : 1);
      }).slice(0, Math.max(5, N - concepts.length));
      var inGraph = new Set(papers);
      concepts.forEach(function (t) {
        var members = Array.from(t.pmids).filter(function (p) { return inGraph.has(p); });
        if (!members.length) return;
        nodes.push({ id: "t:" + t.key, label: t.label, kind: termKind(t), size: members.length, pmids: new Set(members) });
      });
      var authorPapers = {};
      papers.forEach(function (p) {
        var row = BY_PMID[p] || {};
        nodes.push({ id: "p:" + p, label: row.citekey || p, title: row.title, kind: "paper", size: 1, pmids: new Set([p]) });
        paperTerms[p].forEach(function (t) { edges.push({ a: "p:" + p, b: "t:" + t.key, w: 1, kind: "pt" }); });
        ((scope.papers[p] || {}).authors || []).forEach(function (name) {
          (authorPapers[name] = authorPapers[name] || new Set()).add(p);
        });
      });
      Object.keys(authorPapers).filter(function (a) { return authorPapers[a].size >= 2; })
        .sort(function (a, b) { return authorPapers[b].size - authorPapers[a].size || (a < b ? -1 : 1); })
        .slice(0, 15).forEach(function (a) {
          nodes.push({ id: "a:" + a, label: a, kind: "author", size: authorPapers[a].size, pmids: authorPapers[a] });
          authorPapers[a].forEach(function (p) { edges.push({ a: "a:" + a, b: "p:" + p, w: 1, kind: "pa" }); });
        });
    } else {
      var co = cooccurrence(topicIndex(scope), N, 1);
      nodes = co.chosen.map(function (t) { return { id: t.key, label: t.label, kind: termKind(t), size: t.pmids.size, pmids: t.pmids }; });
      edges = edgesFromAdj(nodes, co.adj, nodes.length > 40 ? 2 : 1, nodes.length * 3);
    }
    var adj = {};
    nodes.forEach(function (n) { adj[n.id] = {}; });
    edges.forEach(function (e) {
      if (!adj[e.a] || !adj[e.b]) return;
      adj[e.a][e.b] = (adj[e.a][e.b] || 0) + e.w;
      adj[e.b][e.a] = (adj[e.b][e.a] || 0) + e.w;
    });
    var labels = labelPropagation(nodes.map(function (n) { return n.id; }), adj);
    var clusterSizes = {};
    nodes.forEach(function (n) { clusterSizes[labels[n.id]] = (clusterSizes[labels[n.id]] || 0) + 1; });
    var clusterRank = Object.keys(clusterSizes).filter(function (l) { return clusterSizes[l] > 1; })
      .sort(function (a, b) { return clusterSizes[b] - clusterSizes[a] || a - b; });
    nodes.forEach(function (n) { n.cluster = clusterRank.indexOf(String(labels[n.id])); });
    return { nodes: nodes, edges: edges.filter(function (e) { return adj[e.a] && adj[e.b]; }), adj: adj };
  }

  // Fruchterman-Reingold with a golden-angle start: deterministic, O(n²)
  // per step, fine for the <=200 nodes the controls allow.
  function forceLayout(nodes, edges, W, H) {
    var n = nodes.length, pos = {};
    if (!n) return pos;
    var xs = new Float64Array(n), ys = new Float64Array(n), idx = {};
    nodes.forEach(function (nd, i) {
      var a = i * 2.399963, r = 14 * Math.sqrt(i + 1);
      xs[i] = W / 2 + r * Math.cos(a);
      ys[i] = H / 2 + r * Math.sin(a);
      idx[nd.id] = i;
    });
    var k = Math.sqrt(W * H / n) * 0.6, temp = W / 6;
    var dx = new Float64Array(n), dy = new Float64Array(n);
    for (var it = 0; it < 280; it++) {
      dx.fill(0); dy.fill(0);
      for (var i = 0; i < n; i++) {
        for (var j = i + 1; j < n; j++) {
          var ddx = xs[i] - xs[j], ddy = ys[i] - ys[j];
          var d2 = ddx * ddx + ddy * ddy || 0.01, d = Math.sqrt(d2), f = k * k / d;
          dx[i] += ddx / d * f; dy[i] += ddy / d * f;
          dx[j] -= ddx / d * f; dy[j] -= ddy / d * f;
        }
      }
      edges.forEach(function (e) {
        var a = idx[e.a], b = idx[e.b];
        if (a === undefined || b === undefined) return;
        var ex = xs[a] - xs[b], ey = ys[a] - ys[b];
        var dd = Math.sqrt(ex * ex + ey * ey) || 0.01, ff = dd * dd / k * (1 + 0.5 * Math.log(e.w || 1)) * 0.25;
        dx[a] -= ex / dd * ff; dy[a] -= ey / dd * ff;
        dx[b] += ex / dd * ff; dy[b] += ey / dd * ff;
      });
      for (var m = 0; m < n; m++) {
        dx[m] += (W / 2 - xs[m]) * 0.08;
        dy[m] += (H / 2 - ys[m]) * 0.08;
        var len = Math.sqrt(dx[m] * dx[m] + dy[m] * dy[m]) || 1, step = Math.min(len, temp);
        xs[m] = Math.max(24, Math.min(W - 24, xs[m] + dx[m] / len * step));
        ys[m] = Math.max(18, Math.min(H - 18, ys[m] + dy[m] / len * step));
      }
      temp = Math.max(1, temp * 0.97);
    }
    nodes.forEach(function (nd, i) { pos[nd.id] = { x: xs[i], y: ys[i] }; });
    return pos;
  }

  var KIND_COLOR = {
    paper: "var(--s-abs)", author: "var(--s-oa)", concept: "var(--accent)", mesh: "var(--s-full)",
    intervention: "var(--accent)", outcome: "var(--s-oa)", population: "var(--c5)",
  };

  function nodeColor(n) {
    if (ins.graphMode === "concepts") return n.cluster >= 0 ? PALETTE[n.cluster % PALETTE.length] : "var(--faint)";
    return KIND_COLOR[n.kind] || "var(--muted)";
  }

  function edgeStyle(e) {
    if (e.conflict) return { stroke: "var(--crit)", width: 2.4, dash: "5 3", opacity: 0.9 };
    if (e.kind === "io") return { stroke: DIR_COLOR[dominantDir(e.cell.dir)], width: 1 + Math.min(4, e.w), opacity: 0.7 };
    if (e.kind === "rel") return { stroke: "var(--good)", width: 2, dash: "2 2", opacity: 0.8 };
    if (e.kind === "pi") return { stroke: "var(--line)", width: 1, opacity: 0.9 };
    return { stroke: "var(--faint)", width: Math.min(4, 0.6 + Math.log(1 + e.w)), opacity: 0.45 };
  }

  function renderGraph(body, scope) {
    var modes = [["concepts", "Concepts"], ["papers", "Papers & authors"], ["claims", "Claim network"]];
    var seg = el("div", { className: "d-mode", attrs: { role: "group", "aria-label": "Graph mode" } }, modes.map(function (m) {
      return el("button", {
        text: m[1], attrs: { type: "button", "aria-pressed": String(ins.graphMode === m[0]) },
        on: { click: function () { ins.graphMode = m[0]; ins.selected = null; ins.zoom = 1; renderInsights(); } },
      });
    }));
    var range = el("input", { attrs: { type: "range", min: "20", max: "200", step: "10", value: String(ins.graphN), "aria-label": "Maximum nodes" } });
    range.addEventListener("change", function () { ins.graphN = parseInt(range.value, 10); renderInsights(); });
    body.appendChild(el("div", { className: "ins-controls" }, [
      seg,
      el("label", {}, [document.createTextNode("Nodes ≤ " + ins.graphN + " "), range]),
      el("span", { className: "zoom" }, [
        el("button", { className: "iconbtn", text: "−", attrs: { type: "button", "aria-label": "Zoom out" }, on: { click: function () { ins.zoom = Math.max(0.5, ins.zoom / 1.3); renderInsights(); } } }),
        el("button", { className: "iconbtn", text: "+", attrs: { type: "button", "aria-label": "Zoom in" }, on: { click: function () { ins.zoom = Math.min(5, ins.zoom * 1.3); renderInsights(); } } }),
        el("button", { className: "iconbtn", text: "⤢", attrs: { type: "button", "aria-label": "Reset zoom" }, on: { click: function () { ins.zoom = 1; renderInsights(); } } }),
      ]),
    ]));
    if (ins.graphMode === "claims" && !scope.claims.length) { noClaimsNotice(body); return; }

    var W = 900, H = 600;
    var key = ins.graphMode + "|" + ins.graphN + "|" + scope.claims.length + "|" + Array.from(scope.pmids).join(",");
    if (!ins.graphCache || ins.graphCache.key !== key) {
      var g = buildGraph(scope);
      ins.graphCache = { key: key, graph: g, pos: forceLayout(g.nodes, g.edges, W, H) };
    }
    var graph = ins.graphCache.graph, pos = ins.graphCache.pos;
    if (!graph.nodes.length) {
      body.appendChild(el("div", { className: "empty", text: "nothing to draw -- no topic terms or claims in scope" }));
      return;
    }
    var byId = {};
    graph.nodes.forEach(function (n) { byId[n.id] = n; });
    var sel = ins.selected && byId[ins.selected] ? byId[ins.selected] : null;
    var nbrs = sel ? graph.adj[sel.id] : null;

    var focus = sel ? pos[sel.id] : { x: W / 2, y: H / 2 };
    var vw = W / ins.zoom, vh = H / ins.zoom;
    var vx = Math.max(0, Math.min(W - vw, focus.x - vw / 2)), vy = Math.max(0, Math.min(H - vh, focus.y - vh / 2));
    var svg = svgEl("svg", { viewBox: vx + " " + vy + " " + vw + " " + vh, class: "graph", role: "group", "aria-label": "Knowledge graph, " + graph.nodes.length + " nodes" });
    graph.edges.forEach(function (e) {
      var a = pos[e.a], b = pos[e.b];
      if (!a || !b) return;
      var st = edgeStyle(e);
      var on = !sel || e.a === sel.id || e.b === sel.id;
      var line = svgEl("line", {
        x1: a.x, y1: a.y, x2: b.x, y2: b.y, stroke: st.stroke, "stroke-width": st.width,
        "stroke-opacity": on ? st.opacity : 0.08, "stroke-dasharray": st.dash || "none",
      });
      if (e.kind === "io" || e.kind === "rel") {
        var t = svgEl("title", {});
        t.textContent = byId[e.a].label + " → " + byId[e.b].label + (e.cell ? ": " + DIR_KEYS.filter(function (k) { return e.cell.dir[k]; }).map(function (k) { return DIR_LABEL[k] + " " + e.cell.dir[k]; }).join(", ") : " (" + e.rel.type + ")");
        line.appendChild(t);
      }
      svg.appendChild(line);
    });
    var maxSize = 1;
    graph.nodes.forEach(function (n) { maxSize = Math.max(maxSize, n.size); });
    var labelled = graph.nodes.slice().sort(function (a, b) { return b.size - a.size; }).slice(0, 22).map(function (n) { return n.id; });
    graph.nodes.forEach(function (n) {
      var p = pos[n.id];
      var on = !sel || n.id === sel.id || (nbrs && nbrs[n.id]);
      var r = 4 + 11 * Math.sqrt(n.size / maxSize);
      var gEl = svgEl("g", { class: "gnode" + (sel && n.id === sel.id ? " sel" : ""), tabindex: "0", role: "button", opacity: on ? 1 : 0.18,
        "aria-label": n.kind + " " + n.label + ", " + n.size + " paper" + (n.size === 1 ? "" : "s") });
      gEl.appendChild(svgEl("circle", { cx: p.x, cy: p.y, r: r, fill: nodeColor(n), stroke: "var(--panel)", "stroke-width": 1.5 }));
      var title = svgEl("title", {});
      title.textContent = (n.title || n.label) + " · " + n.kind + " · " + n.size + " paper" + (n.size === 1 ? "" : "s");
      gEl.appendChild(title);
      if (labelled.indexOf(n.id) >= 0 || (sel && on)) {
        var tx = svgEl("text", { x: p.x + r + 3, y: p.y + 4 });
        tx.textContent = n.label.length > 28 ? n.label.slice(0, 27) + "…" : n.label;
        gEl.appendChild(tx);
      }
      function pick() { ins.selected = sel && sel.id === n.id ? null : n.id; renderInsights(); }
      gEl.addEventListener("click", pick);
      gEl.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
      svg.appendChild(gEl);
    });

    var legend = el("div", { className: "tri-legend" });
    if (ins.graphMode === "concepts") {
      legend.appendChild(el("span", { text: "colour = cluster · size = papers · line = papers sharing both terms" }));
    } else if (ins.graphMode === "papers") {
      [["paper", "paper"], ["concept", "concept / claim term"], ["mesh", "MeSH term"], ["author", "shared author"]].forEach(function (k) {
        legend.appendChild(el("span", {}, [el("i", { attrs: { style: "background:" + KIND_COLOR[k[0]] } }), document.createTextNode(k[1])]));
      });
    } else {
      [["intervention", "intervention"], ["outcome", "outcome"], ["population", "population"]].forEach(function (k) {
        legend.appendChild(el("span", {}, [el("i", { attrs: { style: "background:" + KIND_COLOR[k[0]] } }), document.createTextNode(k[1])]));
      });
      ["up", "down", "null"].forEach(function (k) {
        legend.appendChild(el("span", {}, [el("i", { attrs: { style: "background:" + DIR_COLOR[k] } }), document.createTextNode("→ " + DIR_LABEL[k])]));
      });
      legend.appendChild(el("span", {}, [el("i", { attrs: { style: "background:var(--crit)" } }), document.createTextNode("conflicting findings (dashed)")]));
    }

    var side = el("div", { className: "panel gside" });
    if (!sel) {
      side.appendChild(el("h2", { text: "Explore" }));
      side.appendChild(el("p", { className: "sub", text: "Click or press Enter on a node to see its neighbourhood and papers. Raise the node limit for more detail; lower it on large libraries." }));
      if (ins.graphMode === "claims") {
        var conflicts = graph.edges.filter(function (e) { return e.conflict; });
        side.appendChild(el("h2", { text: "Conflicting findings (" + conflicts.length + ")" }));
        if (!conflicts.length) side.appendChild(el("div", { className: "empty", text: "no intervention → outcome pair has both increases and decreases in scope" }));
        conflicts.slice(0, 20).forEach(function (e) {
          var pm = e.cell ? Array.from(e.cell.pmids) : e.rel.pmids;
          side.appendChild(el("div", { className: "conflict" }, [
            el("b", { text: byId[e.a].label + " → " + byId[e.b].label }),
            el("span", { className: "sub", text: e.cell ? "↑ " + e.cell.dir.up + " · ↓ " + e.cell.dir.down + " · ~ " + e.cell.dir["null"] : e.rel.type + (e.rel.stale ? " (stale)" : "") }),
            el("div", { className: "pcmds" }, pm.slice(0, 8).map(paperButton).concat([el("button", {
              className: "cmdbtn", text: "Papers (" + pm.length + ")", attrs: { type: "button" },
              on: { click: function () { applyPmidFilter("conflict: " + byId[e.a].label + " → " + byId[e.b].label, pm); } },
            })])),
          ]));
        });
      } else {
        var clusters = {};
        graph.nodes.forEach(function (n) { if (n.cluster >= 0) (clusters[n.cluster] = clusters[n.cluster] || []).push(n); });
        var ul = el("ul", { className: "ins-list" });
        Object.keys(clusters).slice(0, 8).forEach(function (c) {
          var members = clusters[c].sort(function (a, b) { return b.size - a.size; });
          ul.appendChild(el("li", {}, [
            el("i", { className: "sw", attrs: { style: "background:" + (ins.graphMode === "concepts" ? PALETTE[c % PALETTE.length] : "var(--muted)") } }),
            el("span", { text: members.slice(0, 3).map(function (m) { return m.label; }).join(", ") + (members.length > 3 ? " +" + (members.length - 3) : "") }),
          ]));
        });
        side.appendChild(ul);
      }
    } else {
      side.appendChild(el("h2", {}, [document.createTextNode(sel.kind), el("button", {
        className: "cmdbtn", text: "Clear", attrs: { type: "button" }, on: { click: function () { ins.selected = null; renderInsights(); } },
      })]));
      side.appendChild(el("b", { className: "gtitle", text: sel.title || sel.label }));
      side.appendChild(el("div", { className: "pcmds" }, [el("button", {
        className: "cmdbtn primary", text: "Show " + sel.pmids.size + " papers", attrs: { type: "button" },
        on: { click: function () { applyPmidFilter(sel.kind + ": " + sel.label, Array.from(sel.pmids)); } },
      })].concat(sel.kind === "paper" ? [el("button", {
        className: "cmdbtn", text: "Open paper", attrs: { type: "button" },
        on: { click: function () { openDrawer(Array.from(sel.pmids)[0]); } },
      })] : [])));
      var outgoing = graph.edges.filter(function (e) { return (e.a === sel.id || e.b === sel.id) && e.cell && e.kind === "io"; });
      if (outgoing.length) {
        side.appendChild(el("h2", { text: "Findings" }));
        outgoing.sort(function (a, b) { return b.w - a.w; }).slice(0, 15).forEach(function (e) {
          var other = byId[e.a === sel.id ? e.b : e.a];
          side.appendChild(el("div", { className: "conflict" + (e.conflict ? " is" : "") }, [
            el("b", { text: (e.a === sel.id ? "→ " : "← ") + other.label }),
            el("span", { className: "sub", text: "↑ " + e.cell.dir.up + " · ↓ " + e.cell.dir.down + " · ~ " + e.cell.dir["null"] + " · " + e.cell.pmids.size + " papers" + (e.conflict ? " · conflicting" : "") }),
            el("div", { className: "pcmds" }, Array.from(e.cell.pmids).slice(0, 6).map(paperButton)),
          ]));
        });
      }
      side.appendChild(el("h2", { text: "Connected" }));
      var ul2 = el("ul", { className: "ins-list" });
      Object.keys(nbrs || {}).sort(function (a, b) { return nbrs[b] - nbrs[a]; }).slice(0, 20).forEach(function (id) {
        ul2.appendChild(el("li", {}, [el("button", {
          className: "plink", text: byId[id].label, attrs: { type: "button" },
          on: { click: function () { ins.selected = id; renderInsights(); } },
        }), el("small", { text: byId[id].kind + " · " + nbrs[id] })]));
      });
      if (!ul2.children.length) ul2.appendChild(el("li", { className: "more", text: "no connections at this node limit" }));
      side.appendChild(ul2);
      side.appendChild(el("h2", { text: "Papers" }));
      side.appendChild(paperList(sel.pmids, 15));
    }
    if (ins.selected && !sel) side.appendChild(el("div", { className: "empty", text: "the selected node isn't among the top " + ins.graphN + " -- raise the node limit" }));
    body.appendChild(el("div", { className: "gwrap" }, [el("div", { className: "panel" }, [svg, legend]), side]));
  }

  // ------------------------------------------------- clusters (FR-14)

  function computeClusters(scope, terms) {
    var co = cooccurrence(terms, 400, 2);
    var minW = scope.rows.length > 60 ? 2 : 1;
    var adj = {};
    co.chosen.forEach(function (t) {
      adj[t.key] = {};
      Object.keys(co.adj[t.key]).forEach(function (m) { if (co.adj[t.key][m] >= minW) adj[t.key][m] = co.adj[t.key][m]; });
    });
    var labels = labelPropagation(co.chosen.map(function (t) { return t.key; }), adj);
    var groups = {};
    co.chosen.forEach(function (t) { (groups[labels[t.key]] = groups[labels[t.key]] || []).push(t); });
    return Object.keys(groups).map(function (g) { return groups[g]; }).filter(function (ts) { return ts.length >= 2; }).map(function (ts) {
      ts.sort(function (a, b) { return b.pmids.size - a.pmids.size || (a.label < b.label ? -1 : 1); });
      var pmids = new Set();
      ts.forEach(function (t) { t.pmids.forEach(function (p) { pmids.add(p); }); });
      var years = Array.from(pmids).map(function (p) { return parseInt((BY_PMID[p] || {}).year, 10); }).filter(Boolean);
      return {
        terms: ts, pmids: pmids, name: ts.slice(0, 3).map(function (t) { return t.label; }).join(" · "),
        y0: years.length ? Math.min.apply(null, years) : null, y1: years.length ? Math.max.apply(null, years) : null,
      };
    }).sort(function (a, b) { return b.pmids.size - a.pmids.size || (a.name < b.name ? -1 : 1); });
  }

  function renderClusters(body, scope) {
    var q = el("input", { attrs: { type: "search", placeholder: "Filter clusters by term", value: ins.clusterQuery, "aria-label": "Filter clusters by term" } });
    q.addEventListener("change", function () { ins.clusterQuery = q.value; renderInsights(); });
    body.appendChild(el("div", { className: "ins-controls" }, [
      q, el("span", { className: "sub", text: "Terms (MeSH, concepts, claim population/intervention/outcome) that appear in at least two papers, grouped by how often they co-occur." }),
    ]));
    var clusters = computeClusters(scope, topicIndex(scope));
    var needle = ins.clusterQuery.trim().toLowerCase();
    if (needle) clusters = clusters.filter(function (c) { return c.terms.some(function (t) { return t.label.toLowerCase().indexOf(needle) >= 0; }); });
    if (!clusters.length) {
      body.appendChild(el("div", { className: "empty", text: needle ? "no cluster contains “" + needle + "”" : "not enough shared terms to form clusters in scope" }));
      return;
    }
    var max = clusters[0].pmids.size;
    clusters.forEach(function (c) { max = Math.max(max, c.pmids.size); });
    var grid = el("div", { className: "clgrid" });
    clusters.slice(0, 40).forEach(function (c, i) {
      var r = 8 + 26 * Math.sqrt(c.pmids.size / max);
      var bubble = svgEl("svg", { viewBox: "0 0 70 70", class: "clbubble", "aria-hidden": "true" });
      bubble.appendChild(svgEl("circle", { cx: 35, cy: 35, r: r, fill: PALETTE[i % PALETTE.length], "fill-opacity": 0.8 }));
      var num = svgEl("text", { x: 35, y: 39, "text-anchor": "middle" });
      num.textContent = String(c.pmids.size);
      bubble.appendChild(num);
      var chips = el("div", { className: "clterms" });
      c.terms.slice(0, 12).forEach(function (t) {
        chips.appendChild(el("button", {
          className: "fchip", attrs: { type: "button", title: t.pmids.size + " papers · " + termKind(t) },
          on: { click: function () { applyPmidFilter("topic: " + t.label, Array.from(t.pmids)); } },
        }, [document.createTextNode(t.label), el("span", { className: "x", text: String(t.pmids.size) })]));
      });
      if (c.terms.length > 12) chips.appendChild(el("span", { className: "sub", text: "+" + (c.terms.length - 12) + " more terms" }));
      grid.appendChild(el("article", { className: "panel clcard" }, [
        el("div", { className: "clhead" }, [bubble, el("div", {}, [
          el("b", { text: c.name }),
          el("div", { className: "sub", text: c.pmids.size + " papers · " + c.terms.length + " terms" + (c.y0 ? " · " + c.y0 + (c.y1 !== c.y0 ? "–" + c.y1 : "") : "") }),
        ])]),
        chips,
        el("div", { className: "pcmds" }, [
          el("button", { className: "cmdbtn primary", text: "Papers (" + c.pmids.size + ")", attrs: { type: "button" },
            on: { click: function () { applyPmidFilter("cluster: " + c.name, Array.from(c.pmids)); } } }),
          el("button", { className: "cmdbtn", text: "Open in graph", attrs: { type: "button" },
            on: { click: function () {
              ins.view = "graph"; ins.graphMode = "concepts"; ins.selected = c.terms[0].key; ins.zoom = 1;
              renderInsights(); syncUrl();
            } } }),
        ]),
      ]));
    });
    body.appendChild(grid);
  }

  // ------------------------------------------- synthesis draft (FR-17)

  function countsLine(obj) {
    return Object.keys(obj).sort(function (a, b) { return obj[b] - obj[a]; }).map(function (k) { return k + " " + obj[k]; }).join(", ");
  }

  function mdEscape(s) {
    return String(s || "").replace(/([\\`*_[\]])/g, "\\$1");
  }

  function buildSynthesis(scope) {
    var rows = scope.rows, claims = scope.claims;
    var L = [];
    var years = rows.map(function (r) { return parseInt(r.year, 10); }).filter(Boolean);
    var fulltext = rows.filter(function (r) { return r.has_fulltext || r.has_pdf; }).length;
    var withClaims = new Set(claims.map(function (c) { return c.pmid; }));
    var designs = {}, tiers = {}, projects = {};
    claims.forEach(function (c) {
      if (c.study_type) designs[c.study_type] = (designs[c.study_type] || 0) + 1;
      if (c.tier) tiers[c.tier] = (tiers[c.tier] || 0) + 1;
    });
    rows.forEach(function (r) { (r.projects || []).forEach(function (p) { projects[p.slug] = (projects[p.slug] || 0) + 1; }); });

    L.push("# Evidence synthesis draft", "");
    L.push("_Generated " + new Date().toISOString().slice(0, 16).replace("T", " ") + " UTC by /ref:dashboard from " + rows.length +
      " papers" + (ins.follow && filtersActive() ? " matching the current filters" : "") +
      ". A deterministic roll-up of metadata, extracted claims and notes -- not a narrative review; use /ref:brief or /ref:ask for a grounded narrative._", "");
    L.push("## Scope", "");
    L.push("- Papers: " + rows.length + (years.length ? " (" + Math.min.apply(null, years) + "–" + Math.max.apply(null, years) + ")" : ""));
    L.push("- Full text or PDF: " + fulltext + " · with extracted claims: " + withClaims.size + " (" + claims.length + " active claims)");
    if (Object.keys(projects).length) L.push("- Projects: " + countsLine(projects));
    if (Object.keys(designs).length) L.push("- Study designs (claims): " + countsLine(designs));
    if (Object.keys(tiers).length) L.push("- Evidence tiers (claims): " + countsLine(tiers));
    L.push("");

    var terms = topicIndex(scope);
    var clusters = computeClusters(scope, terms).slice(0, 6);
    L.push("## Main themes", "");
    if (!clusters.length) L.push("- Not enough shared topic terms to group papers into themes.");
    clusters.forEach(function (c, i) {
      L.push((i + 1) + ". **" + mdEscape(c.name) + "** — " + c.pmids.size + " papers" + (c.y0 ? ", " + c.y0 + (c.y1 !== c.y0 ? "–" + c.y1 : "") : "") +
        "; also: " + c.terms.slice(3, 8).map(function (t) { return mdEscape(t.label); }).join(", ") );
    });
    L.push("");

    var pairs = ioPairs(claims).sort(function (a, b) { return b.pmids.size - a.pmids.size || b.claims.length - a.claims.length; });
    L.push("## Key findings", "");
    if (!pairs.length) L.push("- No claims with both an intervention and an outcome yet -- run /ref:extract.");
    pairs.slice(0, 12).forEach(function (p) {
      var dom = dominantDir(p.dir);
      var parts = DIR_KEYS.filter(function (k) { return p.dir[k]; }).map(function (k) { return DIR_LABEL[k] + " " + p.dir[k]; });
      L.push("- **" + mdEscape(p.i) + " → " + mdEscape(p.o) + "**: " + (dom === "mixed" ? "conflicting" : DIR_LABEL[dom]) +
        " (" + (parts.join(", ") || "direction not reported") + ") across " + p.pmids.size + " paper" + (p.pmids.size === 1 ? "" : "s") +
        " [PMID " + Array.from(p.pmids).slice(0, 8).join(", ") + "]" + (p.tier.full ? "" : " — abstract-level evidence only"));
    });
    L.push("");

    var mixed = pairs.filter(function (p) { return p.dir.up && p.dir.down; });
    var conflicts = unresolvedConflicts(scope);
    L.push("## Contradictions", "");
    if (!mixed.length && !conflicts.length) L.push("- None detected among claims in scope.");
    mixed.slice(0, 10).forEach(function (p) {
      var ups = new Set(), downs = new Set();
      p.claims.forEach(function (c) { if (c.dir === "up") ups.add(c.pmid); if (c.dir === "down") downs.add(c.pmid); });
      L.push("- **" + mdEscape(p.i) + " → " + mdEscape(p.o) + "**: increase in PMID " + Array.from(ups).join(", ") + "; decrease in PMID " + Array.from(downs).join(", "));
    });
    conflicts.slice(0, 10).forEach(function (x) {
      L.push("- " + mdEscape(x.subject) + " ↔ " + mdEscape(x.object) + ": " + x.r.type + (x.r.stale ? " (stale)" : ", unreviewed") +
        (x.r.pmids.length ? " [PMID " + x.r.pmids.join(", ") + "]" : ""));
    });
    L.push("");

    L.push("## Open questions", "");
    var gaps = findGaps(claims, "population", "outcome", 0).slice(0, 6);
    gaps.forEach(function (g) {
      L.push("- No claims on **" + mdEscape(g.c.value) + "** in **" + mdEscape(g.r.value) + "** (each studied in " + g.c.pmids.size + " / " + g.r.pmids.size + " papers). PubMed: `" + pubmedQuery([g.r.value, g.c.value]) + "`");
    });
    var singles = pairs.filter(function (p) { return p.pmids.size === 1; });
    if (singles.length) L.push("- " + singles.length + " intervention → outcome finding" + (singles.length === 1 ? " rests" : "s rest") + " on a single paper, e.g. " +
      singles.slice(0, 3).map(function (p) { return mdEscape(p.i) + " → " + mdEscape(p.o) + " (PMID " + Array.from(p.pmids)[0] + ")"; }).join("; ") + ".");
    var noClaims = rows.filter(function (r) { return !withClaims.has(r.pmid); });
    if (noClaims.length) L.push("- " + noClaims.length + " paper" + (noClaims.length === 1 ? " has" : "s have") + " no extracted claims and aren't reflected above" +
      (noClaims.length <= 50 ? " — `/ref:extract " + noClaims.map(function (r) { return r.pmid; }).join(" ") + "`" : "") + ".");
    if (!gaps.length && !singles.length && !noClaims.length) L.push("- No structural gaps detected.");
    L.push("");

    var noted = rows.filter(function (r) { return (scope.papers[r.pmid] || {}).note; });
    if (noted.length) {
      L.push("## Reader notes", "");
      noted.slice(0, 15).forEach(function (r) {
        L.push("- **" + mdEscape(r.citekey || r.pmid) + "** (PMID " + r.pmid + "): " + mdEscape(scope.papers[r.pmid].note.replace(/\s+/g, " ")));
      });
      L.push("");
    }

    L.push("## Papers", "");
    rows.slice().sort(function (a, b) { return (parseInt(b.year, 10) || 0) - (parseInt(a.year, 10) || 0) || (a.pmid < b.pmid ? -1 : 1); }).forEach(function (r) {
      L.push("- " + mdEscape(r.citekey || r.pmid) + " — " + mdEscape(r.title || "(untitled)") + (r.year ? " (" + r.year + ")" : "") + " · PMID " + r.pmid);
    });
    return L.join("\n") + "\n";
  }

  function renderSynthesis(body, scope) {
    var md = buildSynthesis(scope);
    body.appendChild(el("div", { className: "ins-controls" }, [
      el("button", { className: "cmdbtn primary", text: "Copy markdown", attrs: { type: "button" }, on: { click: function () { copyText(md); } } }),
      el("button", { className: "cmdbtn", text: "Download .md", attrs: { type: "button" },
        on: { click: function () { downloadText("synthesis-" + new Date().toISOString().slice(0, 10) + ".md", md, "text/markdown;charset=utf-8"); } } }),
      el("span", { className: "sub", text: "Themes, findings, contradictions and open questions derived from the papers in scope." }),
    ]));
    body.appendChild(el("pre", { className: "panel synth", text: md }));
  }

  // --------------------------------------------------------------- init

  function renderAll() {
    renderHealth();
    renderProjectSelect();
    renderSourceCoverage();
    renderFunnel();
    renderYearsChart();
    renderTrendChart();
    renderTable();
    renderActionBar();
    renderChips();
    renderNextActions();
  }

  // P0.2: a refresh fetches all four live endpoints independently
  // (allSettled, not all-or-nothing) -- one endpoint returning non-2xx
  // must not blank out the others. Whatever succeeded replaces its slice
  // of state; whatever failed keeps its last known-good value and is
  // named in the error banner.
  var REFRESH_ENDPOINTS = [
    { key: "rows", path: "/api/rows" },
    { key: "snapshots", path: "/api/snapshots" },
    { key: "lint", path: "/api/lint" },
    { key: "matrix", path: "/api/matrix" },
    { key: "summary", path: "/api/summary?detail=pmids" },
  ];

  function refreshRows() {
    if (!LIVE) return;
    Promise.allSettled(REFRESH_ENDPOINTS.map(function (e) { return fetchJSON(e.path); }))
      .then(function (results) {
        var failed = [];
        results.forEach(function (res, i) {
          var key = REFRESH_ENDPOINTS[i].key;
          if (res.status === "fulfilled") {
            if (key === "rows") setRows(res.value);
            else if (key === "snapshots") SNAPSHOTS = res.value || [];
            else if (key === "lint") LINT = res.value || {};
            else if (key === "summary") SUMMARY = res.value || SUMMARY;
            else if (key === "matrix" && res.value) {
              MATRIX_COLUMNS_LIVE = res.value.columns || [];
              MATRIX_ROWS_LIVE = res.value.rows || [];
            }
          } else {
            failed.push(describeFetchError(res.reason));
          }
        });
        loadedDetails = {};
        coverageRendered = false;
        maintRendered = false;
        KNOW = null;
        ins.graphCache = null;
        renderAll();
        loadHealth();
        loadTriages().then(function () { if (activeTab === "triage") loadTriageView(); });
        rerenderActiveTab();
        if (failed.length) {
          showError("refresh partly failed (" + failed.join(", ") + ") -- showing last loaded data for those");
        } else {
          clearError();
        }
      });
  }

  var refreshBtn = document.getElementById("btn-refresh");
  if (refreshBtn) {
    refreshBtn.hidden = !LIVE;
    refreshBtn.addEventListener("click", refreshRows);
  }

  if (LIVE) {
    // /api/rows is load-bearing (everything else degrades gracefully) --
    // its failure is fatal and reported as such; the other three fall
    // back to an empty/last-resort value so a lint/matrix/snapshots
    // hiccup on first load doesn't block the papers table from appearing.
    Promise.all([
      fetchJSON("/api/rows"),
      fetchJSON("/api/snapshots").catch(function () { return []; }),
      fetchJSON("/api/lint").catch(function () { return {}; }),
      fetchJSON("/api/matrix").catch(function () { return null; }),
      fetchJSON("/api/summary?detail=pmids").catch(function () { return null; }),
    ]).then(function (results) {
      setRows(results[0]);
      SNAPSHOTS = results[1] || [];
      LINT = results[2] || {};
      if (results[3]) {
        MATRIX_COLUMNS_LIVE = results[3].columns || [];
        MATRIX_ROWS_LIVE = results[3].rows || [];
      }
      SUMMARY = results[4];
      clearError();
      renderAll();
      applyViewState(decodeViewState(location.search));
      urlSyncEnabled = true;
      syncUrl();
      loadHealth();
      var wantTriage = triageFromHash();
      loadTriages(wantTriage).then(function () {
        if (wantTriage && tri.slug === wantTriage) {
          selectTab("triage");
          renderTriageTab();
        }
      });
      if (DEEPLINK && BY_PMID[DEEPLINK.pmid]) {
        openDrawer(DEEPLINK.pmid);
        setDrawerMode(DEEPLINK.tab);
      }
    }).catch(function (err) {
      document.getElementById("result").textContent =
        "failed to load live data from " + describeFetchError(err) + " -- is the dashboard server running?";
      showError("initial load failed: " + describeFetchError(err));
    });
  } else {
    renderAll();
    applyViewState(decodeViewState(location.search));
    urlSyncEnabled = true;
    syncUrl();
  }
})();
