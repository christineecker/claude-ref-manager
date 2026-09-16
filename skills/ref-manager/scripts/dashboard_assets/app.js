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

  var TABS = ["papers", "coverage", "projects", "maint"];
  var activeTab = "papers";
  function selectTab(name) {
    activeTab = name;
    TABS.forEach(function (t) {
      document.getElementById("tab-" + t).setAttribute("aria-selected", String(t === name));
      document.getElementById("p-" + t).hidden = t !== name;
    });
  }
  function renderTabContent(name) {
    if (name === "coverage") renderCoverageMatrix();
    if (name === "projects") renderProjects();
    if (name === "maint") renderMaintenance();
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

      var titleCell = el("td", { attrs: { "data-label": "Paper" } }, [
        el("div", { className: "t-title", text: r.title || "(untitled)" }),
        el("div", { className: "t-key", text: (r.citekey || r.pmid) }),
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

  function renderActionBar() {
    var bar = document.getElementById("actionbar");
    var n = state.selected.size;
    if (!n) { bar.hidden = true; return; }
    bar.hidden = false;
    document.getElementById("seln").textContent = String(n);
    var fetchPmids = [], extractPmids = [], fetchPdfPmids = [], auditPmids = [];
    state.selected.forEach(function (pmid) {
      var r = BY_PMID[pmid];
      if (!r) return;
      if (needsFetch(r)) fetchPmids.push(pmid);
      if (needsExtract(r)) extractPmids.push(pmid);
      if (needsFetchPdf(r)) fetchPdfPmids.push(pmid);
      if (needsAudit(r)) auditPmids.push(pmid);
    });
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
      issues: state.chips.map(function (c) {
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
      wrap.appendChild(el("article", { className: "panel" }, [
        el("h2", { text: p.slug }),
        pbar, plegend, kv, cmds,
      ]));
    });
  }

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

  var pdfState = { doc: null, pageNum: 1, scale: null, matches: [], matchIdx: -1 };

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
      var pageInput = document.getElementById("pdf-pagenum");
      if (pageInput) pageInput.value = pdfState.pageNum;
      var total = document.getElementById("pdf-pagetotal");
      if (total) total.textContent = "/ " + pdfState.doc.numPages;
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
      wrap.appendChild(el("div", { className: "pdf-status" }, [
        el("h4", { text: "No PDF attached" }),
        el("p", { text: "Run /ref:fetch-pdf or /ref:attach to add one." }),
      ]));
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
    var path = paths[0];
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
    ]);
    var thumbs = el("div", { className: "pdf-thumbs", attrs: { id: "pdf-thumbs" } });
    var pageWrap = el("div", { className: "pdf-pagewrap", attrs: { id: "pdf-pagewrap" } }, [
      el("canvas", { attrs: { id: "pdf-canvas" } }),
    ]);
    wrap.appendChild(toolbar);
    wrap.appendChild(el("div", { className: "pdf-body" }, [thumbs, pageWrap]));

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
        renderAll();
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
    ]).then(function (results) {
      setRows(results[0]);
      SNAPSHOTS = results[1] || [];
      LINT = results[2] || {};
      if (results[3]) {
        MATRIX_COLUMNS_LIVE = results[3].columns || [];
        MATRIX_ROWS_LIVE = results[3].rows || [];
      }
      clearError();
      renderAll();
    }).catch(function (err) {
      document.getElementById("result").textContent =
        "failed to load live data from " + describeFetchError(err) + " -- is the dashboard server running?";
      showError("initial load failed: " + describeFetchError(err));
    });
  } else {
    renderAll();
  }
})();
