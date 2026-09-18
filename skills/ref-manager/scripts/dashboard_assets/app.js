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
      return paper ? { pmid: paper, tab: params.get("tab") === "details" ? "overview" : "pdf" } : null;
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

  // Phase 3 folder tree/Queries grouping (DASHBOARD_NAV_IMPLEMENTATION_PLAN.md
  // §3.3-§3.6): `/api/projects` payload, embedded at build time in static
  // mode and refetched (loadProjects()) alongside /api/rows in live mode.
  var PROJECTS = DATA.projects || [];

  // Live mode has no build-time lint report / coverage matrix embedded in
  // DATA (§7 gap fixed here) -- LINT/MATRIX_COLUMNS/MATRIX_ROWS are filled
  // from DATA at static-build time and refetched via /api/lint + /api/matrix
  // on load and on refresh in live mode; renderHealth()/the Papers table's
  // coverage strip read these variables either way so the two modes share
  // one code path.
  var LINT = DATA.lint || {};
  // /api/summary (or the build-time copy): drives the Next actions panel so
  // its ranking is computed once, in dashboard_insights.next_actions().
  var SUMMARY = DATA.summary || null;
  var MATRIX_COLUMNS_LIVE = [];
  var MATRIX_ROWS_LIVE = [];
  var MATRIX_BY_PMID = {}; // pmid -> matrix row; the Papers table's coverage strip reads this
  // Short labels for the strip's column headers (list.py MATRIX_COLUMNS order).
  var MATRIX_SHORT = { meta: "me", abstract: "ab", fulltext: "fu", pdf: "pd", figures: "fg", claims: "cl", indexed: "ix", retraction: "rt" };
  function setMatrix(payload) {
    MATRIX_COLUMNS_LIVE = (payload && payload.columns) || [];
    MATRIX_ROWS_LIVE = (payload && payload.rows) || [];
    MATRIX_BY_PMID = {};
    MATRIX_ROWS_LIVE.forEach(function (m) { MATRIX_BY_PMID[m.pmid] = m; });
  }
  setMatrix({ columns: DATA.matrix_columns, rows: DATA.matrix });
  function coverageCount(r) {
    var m = MATRIX_BY_PMID[r.pmid];
    if (!m) return 0;
    return MATRIX_COLUMNS_LIVE.reduce(function (n, c) { return n + (m[c] ? 1 : 0); }, 0);
  }

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
  (function () {
    var line = document.getElementById("generated-line");
    var iso = DATA.generated_at || "";
    var d = iso ? new Date(iso) : null;
    if (d && !isNaN(d.getTime())) {
      var hh = String(d.getUTCHours()).padStart(2, "0"), mm = String(d.getUTCMinutes()).padStart(2, "0");
      var today = new Date();
      var sameDay = d.getUTCFullYear() === today.getUTCFullYear() && d.getUTCMonth() === today.getUTCMonth() && d.getUTCDate() === today.getUTCDate();
      line.textContent = "updated " + (sameDay ? "" : iso.slice(0, 10) + " ") + hh + ":" + mm + " UTC";
    } else {
      line.textContent = iso ? "updated " + iso : "";
    }
    line.title = "generated by /ref:dashboard · " + iso;
  })();

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

    var kv = document.getElementById("health-kv");
    clear(kv);
    var last = SNAPSHOTS.length ? SNAPSHOTS[SNAPSHOTS.length - 1].stamp : "";
    // stamps are `<UTC-timestamp>.json` stems, e.g. 20260917T125935Z or 2026-09-17T12:59:35Z
    var m = last.match(/^(\d{4})-?(\d{2})-?(\d{2})T(\d{2}):?(\d{2})/);
    var lastLabel = m ? m[1] + "-" + m[2] + "-" + m[3] + " " + m[4] + ":" + m[5] : (last || "never");
    [
      ["papers", String(ROWS.length), ""],
      ["open issues", String(total), total > 0 ? "warn" : "good"],
      ["lint snapshots", String(SNAPSHOTS.length), ""],
      ["last lint", lastLabel, ""],
    ].forEach(function (row) {
      kv.appendChild(el("span", { text: row[0] }));
      kv.appendChild(el("span", { className: row[2], text: row[1] }));
    });

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
    legend.classList.add("onecol");

    var all = SOURCE_BADGES.concat(none ? ["none"] : []);
    all.forEach(function (badge) {
      var count = badge === "none" ? none : counts[badge];
      var pct = total ? (count / total * 100) : 0;
      var active = !sourceFilterSet || sourceFilterSet.has(badge);
      if (!count) {
        legend.appendChild(el("button", { className: "zero", attrs: { type: "button", disabled: "disabled", "aria-pressed": "false" } }, [
          el("i", { className: "sw", attrs: { style: "background:" + SOURCE_COLOR[badge] } }),
          el("span", { className: "lbl", text: badge === "none" ? "no meta" : badge }),
          el("span", { className: "ct", text: "0" }),
          el("span", { className: "pct", text: "—" }),
        ]));
        return;
      }
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
        el("span", { className: "pct", text: Math.round(pct) + "%" }),
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
    // Biggest single-stage loss drives the amber bar and the note below.
    var worst = null;
    stages.forEach(function (s, i) {
      if (!i) return;
      var lost = stages[i - 1].n - s.n;
      if (lost > 0 && (!worst || lost > worst.lost)) worst = { i: i, lost: lost, from: stages[i - 1].n };
    });
    stages.forEach(function (s, i) {
      var pct = Math.max(1, (s.n / max) * 100);
      var isWorst = worst && worst.i === i;
      svg.appendChild(el("span", { text: s.label }));
      svg.appendChild(el("div", { className: "bar" + (isWorst ? " drop" : ""), attrs: { title: s.label + ": " + s.n } }, [
        el("i", { attrs: { style: "width:" + pct.toFixed(1) + "%" } }),
      ]));
      svg.appendChild(el("span", { className: "n" + (isWorst ? " drop" : ""), text: String(s.n) }));
    });
    var note = document.getElementById("funnel-note");
    clear(note);
    if (worst) {
      var cmd = FUNNEL_STAGE_COMMAND[worst.i] || "";
      note.appendChild(el("span", { text: "Biggest drop: " }));
      note.appendChild(el("b", { text: stages[worst.i].label }));
      note.appendChild(el("span", { text: " loses " + worst.lost + " of " + worst.from + "." }));
      if (cmd) note.appendChild(el("code", { text: cmd }));
    } else if (ROWS.length) {
      note.textContent = "Every paper reaches every stage.";
    } else {
      note.textContent = "No papers yet.";
    }
  }
  var FUNNEL_STAGE_COMMAND = { 1: "/ref:audit", 2: "/ref:fetch", 3: "/ref:fetch", 4: "/ref:extract" };

  function svgEl(tag, attrs) {
    var e = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }

  // --------------------------------------------------------- lint trend

  function renderTrendChart() {
    var svg = document.getElementById("trend");
    clear(svg);
    var head = document.getElementById("trend-head");
    clear(head);
    var buckets = document.getElementById("trend-buckets");
    clear(buckets);
    var snaps = SNAPSHOTS;
    document.getElementById("trend-caption").textContent = snaps.length + " snapshot" + (snaps.length === 1 ? "" : "s") + " · maintenance/*.json";

    // Headline: open issues now (from the live lint report), delta vs the previous snapshot.
    var summary = (LINT && LINT.summary) || {};
    var now = summary.issues_total;
    if (now !== undefined) {
      head.appendChild(el("span", { className: "big " + (now > 0 ? "warn" : "good"), text: String(now) }));
      var prev = snaps.length >= 2 ? (snaps[snaps.length - 2].summary || {}).issues_total : undefined;
      var delta = el("span", { className: "delta", text: "open now" });
      if (prev !== undefined && prev !== null) {
        var d = now - prev;
        delta.appendChild(el("span", { text: " · " }));
        delta.appendChild(el("b", { className: d < 0 ? "down" : (d > 0 ? "up" : ""), text: (d > 0 ? "+" : "") + d }));
        delta.appendChild(el("span", { text: " since previous snapshot" }));
      }
      head.appendChild(delta);
    }

    // Per-bucket breakdown; each row filters the Papers table like the Health list does.
    var issues = (LINT && LINT.issues) || {};
    Object.keys(issues).forEach(function (bucket) {
      var n = (issues[bucket] || []).length;
      if (!n) return;
      var crit = bucket === "missing_meta" || bucket === "malformed_meta";
      buckets.appendChild(el("span", {}, [el("button", {
        text: LINT_BUCKET_LABELS[bucket] || bucket, attrs: { type: "button" },
        on: { click: function () { applyIssueFilter(bucket, LINT_BUCKET_LABELS[bucket] || bucket); } },
      })]));
      buckets.appendChild(el("span", { className: crit ? "crit" : "", text: String(n) }));
    });

    if (!snaps.length) {
      var t = svgEl("text", { x: 10, y: 20 });
      t.textContent = "no /ref:lint --snapshot history yet";
      svg.appendChild(t);
      return;
    }
    var w = 560, h = 150, padL = 30, padB = 20, padT = 10;
    var totals = snaps.map(function (s) { return s.summary && s.summary.issues_total || 0; });
    var max = Math.max.apply(null, totals.concat([1]));
    var stepX = (w - padL - 10) / Math.max(1, snaps.length - 1);
    var yOf = function (v) { return padT + (1 - v / max) * (h - padT - padB); };
    [0, max].forEach(function (v) {
      var y = yOf(v);
      svg.appendChild(svgEl("line", { x1: padL, y1: y, x2: w - 10, y2: y, stroke: "var(--line)", "stroke-width": 1, "stroke-dasharray": v ? "2 4" : "" }));
      var lbl = svgEl("text", { x: padL - 6, y: y + 4, "text-anchor": "end" });
      lbl.textContent = String(v);
      svg.appendChild(lbl);
    });
    var pts = totals.map(function (v, i) { return (padL + i * stepX) + "," + yOf(v); });
    svg.appendChild(svgEl("polyline", { points: pts.join(" "), fill: "none", stroke: "var(--accent)", "stroke-width": 2, "stroke-linejoin": "round" }));
    totals.forEach(function (v, i) {
      var last = i === totals.length - 1;
      svg.appendChild(svgEl("circle", { cx: padL + i * stepX, cy: yOf(v), r: last ? 3.5 : 2.5, fill: last && v > 0 ? "var(--warn)" : "var(--accent)" }));
    });
    // Date ticks: first, last, and a few in between when there is room.
    var every = Math.max(1, Math.ceil(snaps.length / 4));
    snaps.forEach(function (s, i) {
      var last = i === snaps.length - 1;
      if (i % every && !last) return;
      var m = /^(\d{4})-?(\d{2})-?(\d{2})/.exec(s.stamp || "");
      if (!m) return;
      var tx = svgEl("text", { x: padL + i * stepX, y: h - 4, "text-anchor": last ? "end" : (i ? "middle" : "start"), class: last ? "v" : "" });
      tx.textContent = m[2] + "-" + m[3];
      svg.appendChild(tx);
    });
  }

  // ------------------------------------------------------ app shell / nav
  //
  // D1/D2/D5: rail (Library/Overview/Projects/Queries/Insights) + a
  // per-section sidebar, replacing the old tab strip. `activeTab` and the
  // old TABS names are kept as an internal shim so every renderer, keydown
  // gate and URL-encode check that was written against "papers"/"triage"/
  // "maint"/etc keeps working unchanged; `selectTab(name)` is the same
  // shim in the other direction, for old call sites that still ask for a
  // tab by its old name.

  var SECTIONS = ["library", "overview", "projects", "queries", "insights"];
  var TAB_OF_SECTION = { library: "papers", overview: "overview", projects: "projects", queries: "triage", insights: "insights" };
  var LEGACY_TAB_TO_SECTION = { papers: "library", projects: "projects", insights: "insights", maint: "overview", triage: "queries" };

  var activeTab = "papers";
  var nav = { section: "library", item: { library: "all", overview: "status", projects: null }, sub: null };

  // Phase 3 §5 risk: the triage/screening view (#p-triage) is a single
  // id-based DOM subtree, so it's re-parented -- never cloned -- into
  // whichever mount is currently on screen. `mountedTriageOwner` names the
  // current owner only for bookkeeping; the DOM location is the truth.
  var mountedTriageOwner = "queries-section";
  function mountTriageInto(containerId, ownerId) {
    var node = document.getElementById("p-triage");
    var target = document.getElementById(containerId);
    if (!node || !target) return;
    if (node.parentNode !== target) target.appendChild(node);
    mountedTriageOwner = ownerId;
  }
  function ensureTriageMountForSection() {
    if (nav.section === "queries") mountTriageInto("triage-home", "queries-section");
    else if (nav.section === "projects" && nav.item.projects && nav.sub === "queries") {
      mountTriageInto("proj-queries-mount", "project:" + nav.item.projects);
    }
  }

  function renderTabContent(name) {
    if (name === "projects") renderProjectsMain();
    if (name === "overview") renderMaintenance(); // lint buckets + changed-since lists (D5: merged into Overview > Lint & changes)
    if (name === "triage") { ensureTriageMountForSection(); renderTriageTab(); }
    if (name === "insights") INSIGHTS.render();
  }
  // P0.1: whichever section is on screen when a manual refresh lands must be
  // redrawn from the fresh data immediately -- not just next time it's
  // clicked -- so maintenance/projects never show stale snapshots.
  function rerenderActiveTab() {
    renderTabContent(activeTab);
  }

  function applyOverviewSub(sub) {
    nav.item.overview = sub;
    document.querySelectorAll(".ovpage").forEach(function (n) { n.hidden = n.dataset.ov !== sub; });
    var label = { status: "Status", next: "Next actions", lint: "Lint & changes" }[sub] || "Status";
    var h = document.getElementById("ov-heading");
    if (h) h.textContent = label;
    document.title = label + " — Overview · Paper library";
  }

  // D12: `sec`/`item`/`sub` change with pushState (so Back walks section
  // history); everything else (filters/sort/search) keeps replaceState via
  // syncUrl(), unchanged.
  function showSection(sec, opts) {
    opts = opts || {};
    if (SECTIONS.indexOf(sec) < 0) sec = "library";
    nav.section = sec;
    activeTab = TAB_OF_SECTION[sec];
    document.querySelectorAll("#rail [data-sec]").forEach(function (b) {
      if (b.dataset.sec === sec) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
    });
    SECTIONS.forEach(function (s) { var v = document.getElementById("v-" + s); if (v) v.hidden = s !== sec; });
    renderTabContent(sec === "overview" ? "overview" : activeTab);
    if (sec === "overview") applyOverviewSub(nav.item.overview || "status");
    renderSidebar();
    if (opts.push) pushNavState();
    syncUrl();
    if (!opts.silent) {
      var main = document.getElementById("main-scroll");
      if (main) main.scrollTop = 0;
      var h = document.querySelector(".view:not([hidden]) .mainhead h2");
      if (h) h.focus({ preventScroll: true });
      if (narrowScreen()) document.body.classList.remove("side-open");
    }
  }

  // Old-name shim: existing call sites (applyIssueFilter, project cards,
  // triage links, ...) still call selectTab("papers"|"triage"|...).
  function selectTab(name) {
    var sec = LEGACY_TAB_TO_SECTION.hasOwnProperty(name) ? LEGACY_TAB_TO_SECTION[name] : name;
    if (SECTIONS.indexOf(sec) < 0) return;
    showSection(sec, { push: true });
  }

  function narrowScreen() {
    try { return matchMedia("(max-width:680px)").matches; } catch (e) { return false; }
  }

  function pushNavState() {
    try { history.pushState({ sec: nav.section, item: nav.item[nav.section] || null, sub: nav.sub }, ""); } catch (e) { /* file:// or unsupported */ }
  }

  window.addEventListener("popstate", function (e) {
    var s = e.state;
    if (s && s.sec) {
      nav.item[s.sec] = s.item || nav.item[s.sec];
      nav.sub = s.sub || null;
      showSection(s.sec, { silent: true });
    } else {
      // no state (initial load entry, or a page from before this history
      // scheme existed) -- fall back to decoding the current URL.
      applyViewState(decodeViewState(location.search));
    }
  });

  // D13/O2: clicking the active rail icon (or `[`) toggles the sidebar;
  // persisted in localStorage. Below 1180px it auto-collapses while the
  // paper drawer is open and restores on close -- manual toggle always wins.
  var SIDE_COLLAPSE_KEY = "ref-dash-side-collapsed";
  var sideManualOverride = null; // true/false once the user has toggled manually this session; null = follow the drawer-width heuristic
  function readSideCollapsed() {
    try { return localStorage.getItem(SIDE_COLLAPSE_KEY) === "1"; } catch (e) { return false; }
  }
  function writeSideCollapsed(v) {
    try { localStorage.setItem(SIDE_COLLAPSE_KEY, v ? "1" : "0"); } catch (e) { /* private mode etc */ }
  }
  function applySideCollapsed(v) {
    document.body.classList.toggle("side-collapsed", !!v);
  }
  function toggleSidebar() {
    if (narrowScreen()) { document.body.classList.toggle("side-open"); return; }
    var next = !document.body.classList.contains("side-collapsed");
    sideManualOverride = next;
    writeSideCollapsed(next);
    applySideCollapsed(next);
  }
  applySideCollapsed(readSideCollapsed());
  function autoCollapseForDrawer(open) {
    if (sideManualOverride !== null) return; // manual toggle always wins (O2)
    if (!open) { applySideCollapsed(readSideCollapsed()); return; }
    try { if (matchMedia("(max-width:1180px)").matches) applySideCollapsed(true); } catch (e) { /* ignore */ }
  }

  document.getElementById("rail").addEventListener("click", function (e) {
    var btn = e.target.closest("[data-sec]");
    if (!btn) return;
    if (btn.dataset.sec === nav.section) { toggleSidebar(); return; }
    showSection(btn.dataset.sec, { push: true });
    if (narrowScreen()) document.body.classList.add("side-open");
  });

  // -------------------------------------------------------------- sidebar
  //
  // Library's smart lists are presets over the existing `state` (no new
  // filter engine, D…/§3 phase1.3): applying one just sets state.* the same
  // way the old toolbar chips/select did. Highlighting is derived the other
  // way, from state back to the matching preset id, so there is never a
  // second source of truth -- if the user edits filters until no preset
  // matches, nothing is highlighted and the header shows "filtered · Clear".

  function currentLibraryPreset() {
    if (state.query) return null;
    var smart = state.chips.filter(function (c) { return c.id.indexOf("smart:") === 0; }).map(function (c) { return c.id; });
    var hasIssueChip = state.chips.some(function (c) { return c.id.indexOf("issue:") === 0; });
    if (hasIssueChip || sourceFilterSet) return null;
    if (state.project !== "all") {
      return (!state.missing && !smart.length) ? "p:" + state.project : null;
    }
    if (state.missing === "pdf" && !smart.length) return "nopdf";
    if (state.missing === "fulltext" && !smart.length) return "nofull";
    if (state.missing) return null;
    if (smart.length === 1) {
      if (smart[0] === "smart:toread") return "toread";
      if (smart[0] === "smart:recent") return "recent";
      if (smart[0] === "smart:retracted") return "retracted";
    }
    return smart.length ? null : "all";
  }

  function applyLibraryPreset(id) {
    state.chips = state.chips.filter(function (c) { return c.id.indexOf("smart:") !== 0; });
    sourceFilterSet = null;
    var projSel = document.getElementById("proj");
    if (id.indexOf("p:") === 0) {
      state.missing = null;
      state.project = id.slice(2);
    } else {
      state.project = "all";
      if (id !== "nopdf" && id !== "nofull") state.missing = null;
    }
    if (projSel) projSel.value = state.project;
    if (id === "toread") {
      state.chips.push({ id: "smart:toread", label: "to read", pred: isToRead });
    } else if (id === "recent") {
      var cutoff = Date.now() - 7 * 86400000;
      // No library-wide "added" date exists on a row (only per-project
      // membership has added_at) -- checked_at (ISO, sorts lexicographically
      // in date order) is the closest per-row signal without an API change.
      state.chips.push({
        id: "smart:recent", label: "added last 7 days",
        pred: function (r) { var t = Date.parse(r.checked_at || ""); return !isNaN(t) && t >= cutoff; },
      });
      state.sort = { field: "checked_at", dir: "desc" };
    } else if (id === "retracted") {
      state.chips.push({ id: "smart:retracted", label: "retracted", pred: retractionFlagged });
    }
    currentPage = 0;
    if (id === "nopdf") setMissingFilter("pdf");
    else if (id === "nofull") setMissingFilter("fulltext");
    else { renderChips(); renderTable(); }
  }

  function renderLibraryCrumb() {
    var crumb = document.getElementById("lib-crumb");
    var heading = document.getElementById("lib-heading");
    if (!crumb || !heading) return;
    clear(crumb);
    var preset = currentLibraryPreset();
    var LABELS = { all: "All papers", toread: "To read", recent: "Added last 7 days", nopdf: "Missing PDF", nofull: "Missing full text", retracted: "Retracted" };
    if (preset && preset.indexOf("p:") === 0) {
      var slug = preset.slice(2);
      heading.textContent = slug;
      crumb.appendChild(el("span", { text: "project filter · " }));
      crumb.appendChild(el("button", { text: "Open project →", attrs: { type: "button" }, on: { click: function () { showSection("projects", { push: true }); } } }));
    } else if (preset) {
      heading.textContent = LABELS[preset] || "Library";
    } else {
      heading.textContent = "Library";
      crumb.appendChild(el("span", { text: "filtered · " }));
      crumb.appendChild(el("button", {
        text: "Clear", attrs: { type: "button" },
        on: { click: function () { document.getElementById("q").value = ""; state.query = ""; applyLibraryPreset("all"); } },
      }));
    }
    document.title = heading.textContent + " — Library · Paper library";
  }

  function renderLibrarySidebar() {
    var preset = currentLibraryPreset();
    var rowsLen = ROWS.length;
    document.getElementById("n-lib-all").textContent = String(rowsLen);
    document.getElementById("n-lib-toread").textContent = String(ROWS.filter(isToRead).length);
    var cutoff = Date.now() - 7 * 86400000;
    document.getElementById("n-lib-recent").textContent = String(ROWS.filter(function (r) { var t = Date.parse(r.checked_at || ""); return !isNaN(t) && t >= cutoff; }).length);
    var nopdf = MATRIX_COLUMNS_LIVE.indexOf("pdf") >= 0 ? MATRIX_ROWS_LIVE.filter(function (m) { return !m.pdf; }).length : 0;
    var nofull = MATRIX_COLUMNS_LIVE.indexOf("fulltext") >= 0 ? MATRIX_ROWS_LIVE.filter(function (m) { return !m.fulltext; }).length : 0;
    document.getElementById("n-lib-nopdf").textContent = String(nopdf);
    document.getElementById("n-lib-nofull").textContent = String(nofull);
    document.getElementById("side-lib-needs").querySelector('[data-missing="pdf"]').hidden = MATRIX_COLUMNS_LIVE.indexOf("pdf") < 0;
    document.getElementById("side-lib-needs").querySelector('[data-missing="fulltext"]').hidden = MATRIX_COLUMNS_LIVE.indexOf("fulltext") < 0;
    document.getElementById("n-lib-retracted").textContent = String(ROWS.filter(retractionFlagged).length);

    ["all", "toread", "recent"].forEach(function (id) {
      var btn = document.querySelector('#side-lib-presets [data-preset="' + id + '"]');
      if (btn) btn.setAttribute("aria-current", String(preset === id));
    });
    document.querySelectorAll("#side-lib-needs button").forEach(function (btn) {
      var id = btn.getAttribute("data-missing") ? btn.getAttribute("data-missing").replace("pdf", "nopdf").replace("fulltext", "nofull") : "retracted";
      btn.setAttribute("aria-current", String(preset === id));
    });

    var wrap = document.getElementById("side-lib-projects");
    clear(wrap);
    var projects = projectSummaries();
    projects.forEach(function (p) {
      wrap.appendChild(el("li", {}, [el("button", {
        attrs: { type: "button", "data-preset": "p:" + p.slug, "aria-current": String(preset === "p:" + p.slug) },
        on: { click: function () { applyLibraryPreset("p:" + p.slug); } },
      }, [
        el("span", { className: "lbl", text: p.slug }),
        el("span", { className: "n", text: String(p.papers.length) }),
      ])]));
    });
    renderLibraryCrumb();
  }

  document.getElementById("side-lib-presets").addEventListener("click", function (e) {
    var b = e.target.closest("[data-preset]");
    if (b) applyLibraryPreset(b.dataset.preset);
  });
  document.getElementById("side-lib-needs").addEventListener("click", function (e) {
    var b = e.target.closest("[data-missing]");
    if (b) { applyLibraryPreset(b.dataset.missing === "pdf" ? "nopdf" : "nofull"); return; }
    var i = e.target.closest("[data-issue-preset]");
    if (i) applyLibraryPreset(i.dataset.issuePreset);
  });

  function renderOverviewSidebar() {
    var n = (SUMMARY && SUMMARY.top_actions && SUMMARY.top_actions.length) || 0;
    document.getElementById("n-ov-next").textContent = n ? String(n) : "";
    document.getElementById("rail-pip-next").hidden = !n;
    document.getElementById("rail-pip-next").textContent = n ? String(n) : "";
    var summary = (LINT && LINT.summary) || {};
    document.getElementById("n-ov-lint").textContent = summary.issues_total ? String(summary.issues_total) : "";
    document.querySelectorAll("#side-ov-list [data-ov]").forEach(function (b) {
      b.setAttribute("aria-current", String(b.dataset.ov === (nav.item.overview || "status")));
    });
  }
  document.getElementById("side-ov-list").addEventListener("click", function (e) {
    var b = e.target.closest("[data-ov]");
    if (!b) return;
    nav.sub = null;
    applyOverviewSub(b.dataset.ov);
    renderOverviewSidebar();
    pushNavState();
    syncUrl();
    if (b.dataset.ov === "lint") renderMaintenance();
  });

  // D6: the tree shows a row per project; the selected project expands to
  // its linked queries only (undecided counts) -- Summary/Papers/Queries/
  // Reports/Screening-log are in-page subtabs, never mirrored here.
  // Projects with no `projects/<slug>/project.yaml` (paper `.projects` tag
  // only, or a triage linked before the project existed) still get a leaf
  // row so nothing found by the old card grid disappears -- just no subtabs.
  function projectTreeRows() {
    var known = {};
    var rows = PROJECTS.map(function (p) { return { slug: p.slug, real: true, queries: p.queries || [] }; });
    rows.forEach(function (p) { known[p.slug] = true; });
    projectSummaries().forEach(function (p) {
      if (!known[p.slug]) { known[p.slug] = true; rows.push({ slug: p.slug, real: false, queries: [] }); }
    });
    TRIAGES.forEach(function (t) {
      if (t.project && !known[t.project]) { known[t.project] = true; rows.push({ slug: t.project, real: false, queries: [] }); }
    });
    rows.sort(function (a, b) { return a.slug < b.slug ? -1 : a.slug > b.slug ? 1 : 0; });
    return rows;
  }

  function renderProjectsSidebar() {
    var wrap = document.getElementById("side-projects-list");
    clear(wrap);
    var rows = projectTreeRows();
    rows.forEach(function (p) {
      var expanded = nav.item.projects === p.slug;
      var undecided = p.queries.reduce(function (a, q) { return a + (q.undecided || 0); }, 0);
      var li = el("li", {}, [el("button", {
        attrs: { type: "button", "aria-expanded": String(expanded), "aria-current": String(expanded) },
        on: { click: function () { selectProject(p.slug); } },
      }, [
        el("span", { className: "lbl", text: p.slug }),
        el("span", { className: "n", text: undecided ? String(undecided) : "" }),
      ])]);
      if (expanded) {
        if (p.queries.length) {
          var tree = el("ul", { className: "side-tree" });
          p.queries.forEach(function (q) {
            tree.appendChild(el("li", {}, [el("button", {
              attrs: { type: "button", "aria-current": String(nav.section === "projects" && nav.sub === "queries" && tri.slug === q.slug) },
              on: { click: function () { openProjectQuery(p.slug, q.slug); } },
            }, [
              el("span", { className: "lbl", text: q.slug }),
              el("span", { className: "n", text: q.undecided ? String(q.undecided) : "" }),
            ])]));
          });
          li.appendChild(tree);
        } else {
          li.appendChild(el("div", { className: "side-tree" }, [el("div", { className: "none", text: "no linked queries" })]));
        }
      }
      wrap.appendChild(li);
    });
  }

  // Phase 3 §3.2/§3.3: selecting a project row switches the main pane from
  // the plain card grid to that project's folder (Summary subtab first).
  // Clicking the same row again collapses it back to the grid.
  function selectProject(slug) {
    nav.item.projects = (nav.item.projects === slug) ? null : slug;
    nav.sub = nav.item.projects ? (nav.sub || "summary") : null;
    renderProjectsSidebar();
    renderProjectsMain();
    pushNavState();
    syncUrl();
  }

  function openProjectQuery(projectSlug, querySlug) {
    tri.slug = querySlug;
    if (nav.section !== "projects" || nav.item.projects !== projectSlug) {
      nav.item.projects = projectSlug;
      showSection("projects", { push: true });
    }
    nav.sub = "queries";
    renderProjectsSidebar();
    renderProjectsMain();
    pushNavState();
    syncUrl();
  }

  function currentProject() {
    var slug = nav.item.projects;
    if (!slug) return null;
    var found = PROJECTS.filter(function (p) { return p.slug === slug; });
    return found[0] || null;
  }

  // D7: every query, grouped -- "Not in a project" first, then one group
  // per project (never a project that only has unlinked queries omitted --
  // groups come from TRIAGES itself, not from PROJECTS). A linked query's
  // row re-parents #p-triage into its project folder (↗) instead of
  // rendering it here.
  function renderQueriesList() {
    var wrap = document.getElementById("q-grouped-list");
    if (!wrap) return;
    clear(wrap);
    var byProject = {};
    var unlinked = [];
    TRIAGES.forEach(function (t) {
      if (t.project) { (byProject[t.project] = byProject[t.project] || []).push(t); } else unlinked.push(t);
    });
    function group(label, items, projectSlug) {
      if (!items.length) return;
      wrap.appendChild(el("li", { className: "side-group" }, [el("span", { text: label })]));
      items.forEach(function (t) {
        wrap.appendChild(el("li", {}, [
          el("span", { className: "qid", text: t.slug }),
          el("span", {}, [document.createTextNode((t.query || "") + (projectSlug ? " ↗" : ""))]),
          el("button", {
            className: "cmdbtn", text: "Open", attrs: { type: "button" },
            on: {
              click: function () {
                if (projectSlug) { openProjectQuery(projectSlug, t.slug); return; }
                tri.slug = t.slug;
                mountTriageInto("triage-home", "queries-section");
                loadTriageView();
                renderQueriesSidebar();
              },
            },
          }),
          el("small", { text: (t.found || 0) + " found · " + (t.pending || 0) + " pending" }),
        ]));
      });
    }
    group("Not in a project", unlinked, null);
    Object.keys(byProject).sort().forEach(function (slug) { group(slug, byProject[slug], slug); });
  }

  function renderQueriesSidebar() {
    var wrap = document.getElementById("side-queries-list");
    clear(wrap);
    TRIAGES.forEach(function (t) {
      wrap.appendChild(el("li", {}, [el("button", {
        attrs: { type: "button", "aria-current": String(tri.slug === t.slug && nav.section === "queries") },
        on: { click: function () { tri.slug = t.slug; mountTriageInto("triage-home", "queries-section"); loadTriageView(); renderQueriesSidebar(); } },
      }, [
        el("span", { className: "lbl", text: t.slug }),
        el("span", { className: "n", text: t.pending ? String(t.pending) : "" }),
      ])]));
    });
    document.getElementById("side-count").textContent = nav.section === "queries" ? String(TRIAGES.length) : document.getElementById("side-count").textContent;
    var pendingTotal = TRIAGES.reduce(function (a, t) { return a + (t.pending || 0); }, 0);
    var dot = document.getElementById("rail-dot-queries");
    if (dot) dot.hidden = !pendingTotal;
    renderQueriesList();
  }

  // Phase 2: Insights' own pill row (#ins-nav) moved here; insights.js
  // calls this back (via ctx.renderInsightsSidebar) whenever `ins.view`
  // changes from any trigger, not just a sidebar click, so the highlight
  // never drifts out of sync.
  function renderInsightsSidebar() {
    var wrap = document.getElementById("side-insights-list");
    if (!wrap || typeof INSIGHTS === "undefined" || !INSIGHTS) return;
    clear(wrap);
    INSIGHTS.INSIGHT_VIEWS.forEach(function (v) {
      wrap.appendChild(el("li", {}, [el("button", {
        attrs: { type: "button", "aria-current": String(INSIGHTS.ins.view === v.id) },
        on: { click: function () { INSIGHTS.setView(v.id); } },
      }, [el("span", { className: "lbl", text: v.label })])]));
    });
  }

  var SIDE_TITLES = { library: "Library", overview: "Overview", projects: "Projects", queries: "Queries", insights: "Insights" };
  function renderSidebar() {
    document.querySelectorAll(".side-panel").forEach(function (p) { p.hidden = p.dataset.sec !== nav.section; });
    document.getElementById("side-title").textContent = SIDE_TITLES[nav.section] || "";
    if (nav.section === "library") { document.getElementById("side-count").textContent = String(ROWS.length); renderLibrarySidebar(); }
    else if (nav.section === "overview") { document.getElementById("side-count").textContent = ""; renderOverviewSidebar(); }
    else if (nav.section === "projects") { document.getElementById("side-count").textContent = String(projectTreeRows().length); renderProjectsSidebar(); }
    else if (nav.section === "queries") { renderQueriesSidebar(); }
    else if (nav.section === "insights") { document.getElementById("side-count").textContent = ""; renderInsightsSidebar(); }
  }

  // ------------------------------------------------------------- papers

  var state = {
    query: "",
    project: "all",
    chips: [], // {id, label, pred}
    sort: null, // {field, dir}
    missing: null, // a coverage-matrix column name: show only papers lacking it
    selected: new Set(),
  };

  function setMissingFilter(col) {
    state.missing = (col && MATRIX_COLUMNS_LIVE.indexOf(col) >= 0) ? col : null;
    currentPage = 0;
    renderChips();
    renderTable();
  }

  // Toolbar quick filters: one-click `missing:` toggles for the columns
  // people chase most (pdf, fulltext). Same state as the coverage header.
  var quickFilterBtns = Array.prototype.slice.call(document.querySelectorAll(".quick button[data-missing]"));
  quickFilterBtns.forEach(function (b) {
    var col = b.getAttribute("data-missing");
    b.addEventListener("click", function () { setMissingFilter(state.missing === col ? null : col); });
  });
  function syncQuickFilters() {
    quickFilterBtns.forEach(function (b) {
      var col = b.getAttribute("data-missing");
      b.hidden = MATRIX_COLUMNS_LIVE.indexOf(col) < 0;
      b.setAttribute("aria-pressed", String(state.missing === col));
    });
  }

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
    syncQuickFilters();
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
    var quickCovers = quickFilterBtns.some(function (b) { return b.getAttribute("data-missing") === state.missing; });
    if (state.missing && !quickCovers) {
      wrap.appendChild(el("span", { className: "fchip" }, [
        el("span", { text: "missing: " + state.missing }),
        el("button", {
          className: "x", text: "×", attrs: { type: "button", "aria-label": "remove filter missing " + state.missing },
          on: { click: function () { setMissingFilter(null); } },
        }),
      ]));
    }
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
      if (state.missing) {
        var m = MATRIX_BY_PMID[r.pmid];
        if (m && m[state.missing]) return false;
      }
      if (q) {
        var hay = [r.title, r.citekey, r.journal, r.pmid, r.authors_short, r.last_author].filter(Boolean).join(" ").toLowerCase();
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
      else if (field === "coverage") { av = coverageCount(a); bv = coverageCount(b); }
      else if (field === "has_pdf") { av = a.has_pdf ? 1 : 0; bv = b.has_pdf ? 1 : 0; }
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
    renderCoverageHeader();
    renderTableRows();
    if (nav.section === "library") renderLibrarySidebar();
    syncUrl();
    if (document.getElementById("next-scope").checked) scheduleNextActions();
  }

  // The coverage matrix (list.py --matrix) lives in the Papers table as one
  // strip per row; the header shows each column's short label, the share
  // of the whole library that has it, and toggles the `missing:` filter.
  function renderCoverageHeader() {
    var head = document.getElementById("covhead");
    if (!head) return;
    clear(head);
    var total = MATRIX_ROWS_LIVE.length || 1;
    MATRIX_COLUMNS_LIVE.forEach(function (c) {
      var n = 0;
      MATRIX_ROWS_LIVE.forEach(function (m) { if (m[c]) n++; });
      var pct = Math.round(n / total * 100);
      var btn = el("button", {
        text: MATRIX_SHORT[c] || c.slice(0, 2),
        attrs: { type: "button", "aria-pressed": String(state.missing === c), title: c + ": " + pct + "% of papers -- click to show papers missing it" },
        on: { click: function () { setMissingFilter(state.missing === c ? null : c); } },
      });
      head.appendChild(el("div", {}, [btn, el("small", { text: String(pct) })]));
    });
    var legend = document.getElementById("covlegend-cols");
    if (legend) legend.textContent = MATRIX_COLUMNS_LIVE.map(function (c) { return (MATRIX_SHORT[c] || c) + "=" + c; }).join(" · ");
  }

  // The matrix's `retraction` cell means "retraction status checked"; the
  // red variant is reserved for a status that actually flags the paper.
  var RETRACTION_OK = ["unknown", "none", "active", "no_pmcid", "check_failed"];
  function retractionFlagged(r) {
    return !!(r && r.retraction_status && RETRACTION_OK.indexOf(r.retraction_status) < 0);
  }

  function coverageStrip(r) {
    var m = MATRIX_BY_PMID[r.pmid];
    return el("div", { className: "covstrip" }, MATRIX_COLUMNS_LIVE.map(function (c) {
      var on = !!(m && m[c]);
      var cls = on ? (c === "retraction" && retractionFlagged(r) ? "ret" : "on") : "";
      return el("i", { className: cls, attrs: { title: c + ": " + (on ? "yes" : "no") } });
    }));
  }

  function isToRead(r) {
    return (r.projects || []).some(function (p) { return p.reading_status === "to_read"; });
  }

  function markOpenRow() {
    var tbody = document.getElementById("rows");
    Array.prototype.forEach.call(tbody.children, function (tr) {
      tr.classList.toggle("open", !!drawerState.pmid && tr.dataset.pmid === drawerState.pmid);
    });
  }

  function renderTableRows() {
    keyboardActiveIndex = -1;
    var start = currentPage * PAGE_SIZE;
    currentPageRows = currentVisible.slice(start, start + PAGE_SIZE);

    var tbody = document.getElementById("rows");
    clear(tbody);
    currentPageRows.forEach(function (r) {
      var tr = el("tr", { attrs: { "data-pmid": r.pmid } });
      function syncRowClass() {
        tr.className = [
          state.selected.has(r.pmid) ? "sel" : "",
          isToRead(r) ? "toread" : "",
          drawerState.pmid === r.pmid ? "open" : "",
        ].filter(Boolean).join(" ");
      }
      syncRowClass();

      var cb = el("input", { attrs: { type: "checkbox", "aria-label": "Select " + (r.title || r.pmid) } });
      cb.checked = state.selected.has(r.pmid);
      cb.addEventListener("click", function (e) { e.stopPropagation(); });
      cb.addEventListener("change", function () {
        if (cb.checked) state.selected.add(r.pmid); else state.selected.delete(r.pmid);
        renderActionBar();
        syncRowClass();
      });
      tr.appendChild(el("td", { className: "sel", attrs: { "data-label": "Select" } }, [cb]));

      var clip = el("td", { className: "clip" + (r.has_pdf ? " has" : ""), attrs: { "data-label": "PDF" } });
      if (r.has_pdf) {
        var icon = svgEl("svg", { width: "14", height: "14", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": "2", "aria-label": "PDF attached" });
        icon.appendChild(svgEl("path", { d: "M21 12l-8.5 8.5a5 5 0 0 1-7-7L14 5a3.5 3.5 0 0 1 5 5l-8.5 8.5a2 2 0 0 1-3-3L15 8" }));
        clip.appendChild(icon);
      }
      tr.appendChild(clip);

      tr.appendChild(el("td", { className: "au", attrs: { "data-label": "Authors", title: r.authors_short || "" }, text: r.authors_short || "" }));
      tr.appendChild(el("td", { className: "la", attrs: { "data-label": "Last author", title: r.last_author || "" }, text: r.last_author || "" }));
      tr.appendChild(el("td", { className: "title", attrs: { "data-label": "Title", title: (r.title || "") + (r.citekey ? " · " + r.citekey : "") }, text: r.title || "(untitled)" }));
      tr.appendChild(el("td", { className: "journal", attrs: { "data-label": "Journal", title: r.journal || "" }, text: r.journal || "" }));
      tr.appendChild(el("td", { className: "num", attrs: { "data-label": "Year" }, text: r.year || "" }));
      tr.appendChild(el("td", { className: "cov", attrs: { "data-label": "Coverage" } }, [coverageStrip(r)]));
      tr.appendChild(el("td", { className: "num" + (r.notes_count ? "" : " zero"), attrs: { "data-label": "Notes" }, text: r.notes_count ? String(r.notes_count) : "" }));
      tr.appendChild(el("td", { className: "num" + (r.claims_active ? "" : " zero"), attrs: { "data-label": "Claims" }, text: r.claims_active ? String(r.claims_active) : "" }));

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

    // O4: `[` toggles the sidebar, `/` jumps to Library and focuses its
    // search -- both disabled while typing or while screening keys are live
    // (handled above, which returns before reaching here for "triage").
    if (!typing && !e.metaKey && !e.ctrlKey && !e.altKey) {
      if (e.key === "[") { e.preventDefault(); toggleSidebar(); return; }
      if (e.key === "/") {
        e.preventDefault();
        if (nav.section !== "library") showSection("library", { push: true });
        document.getElementById("q").focus();
        return;
      }
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

  // Restore a filter/sort/project combination (decoded from the URL).
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
    state.missing = (v.missing && MATRIX_COLUMNS_LIVE.indexOf(v.missing) >= 0) ? v.missing : null;
    renderSourceCoverage();
    renderChips();
    renderTable();
  }


  // ---------------------------------------------- shareable URL state (FR-01)
  //
  // The core view state (tab, search, project, issue chips, source filter,
  // sort, insight view) lives in the query string and is kept current with
  // history.replaceState. Precedence: the URL is read once on load; after
  // that the page state is the truth and the URL follows it -- applying a
  // saved view just changes page state, which rewrites the URL. Other params
  // (the live token, a ?paper= deep link) and the #triage/ hash are kept.
  // Set-of-PMIDs chips from the Insights tab are deliberately not encoded.

  var VIEW_PARAM_KEYS = ["tab", "q", "project", "issue", "source", "missing", "sort", "insight", "center", "hops", "sec", "item", "sub"];
  var SORT_FIELDS = ["source_badge", "title", "year", "journal", "project", "claims_active", "days_since_check",
    "has_pdf", "authors_short", "last_author", "coverage", "notes_count"];
  var urlSyncEnabled = false;

  function encodeViewState() {
    var p = new URLSearchParams();
    if (nav.section !== "library") p.set("sec", nav.section);
    var item = nav.item[nav.section];
    if (item) p.set("item", item);
    if (nav.sub) p.set("sub", nav.sub);
    if (state.query) p.set("q", state.query);
    if (state.project !== "all") p.set("project", state.project);
    state.chips.forEach(function (c) { if (c.id.indexOf("issue:") === 0) p.append("issue", c.id.slice(6)); });
    if (sourceFilterSet) p.set("source", Array.from(sourceFilterSet).join(","));
    if (state.missing) p.set("missing", state.missing);
    if (state.sort) p.set("sort", state.sort.field + ":" + state.sort.dir);
    var ins = INSIGHTS.ins;
    if (nav.section === "insights" && ins.view !== "evidence") p.set("insight", ins.view);
    if (nav.section === "insights" && ins.view === "graph" && ins.graphMode === "neighborhood" && ins.center) {
      p.set("center", ins.center);
      if (ins.hops !== 1) p.set("hops", String(ins.hops));
    }
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
    // sec/item/sub is the current scheme; a bare legacy `tab=` (a link
    // copied before this redesign) maps onto it so old links keep landing
    // in the right place (D12).
    var sec = p.get("sec");
    var legacyTab = p.get("tab");
    if (!sec && legacyTab) sec = LEGACY_TAB_TO_SECTION.hasOwnProperty(legacyTab) ? LEGACY_TAB_TO_SECTION[legacyTab] : null;
    if (sec && SECTIONS.indexOf(sec) < 0) sec = null;
    var item = p.get("item") || (legacyTab === "maint" ? "lint" : null);
    return {
      sec: sec,
      item: item,
      sub: p.get("sub") || null,
      insight: p.get("insight"),
      center: /^[pc]:\S+$/.test(p.get("center") || "") ? p.get("center") : null,
      hops: p.get("hops") === "2" ? 2 : 1,
      query: p.get("q") || "",
      project: p.get("project") || "all",
      sort: sort,
      source: source.length ? source : null,
      missing: /^[a-z_]+$/.test(p.get("missing") || "") ? p.get("missing") : null,
      issues: p.getAll("issue").filter(function (b) { return LINT_BUCKET_LABELS.hasOwnProperty(b); })
        .map(function (b) { return { bucket: b, label: LINT_BUCKET_LABELS[b] }; }),
    };
  }

  function applyViewState(v) {
    if (!v) return;
    if (v.project !== "all" && !Array.prototype.some.call(document.getElementById("proj").options, function (o) { return o.value === v.project; })) {
      document.getElementById("proj").appendChild(el("option", { attrs: { value: v.project }, text: v.project + " (no papers)" }));
    }
    var ins = INSIGHTS.ins;
    if (v.insight && INSIGHTS.INSIGHT_VIEWS.some(function (x) { return x.id === v.insight; })) ins.view = v.insight;
    if (v.center) {
      ins.view = "graph";
      ins.graphMode = "neighborhood";
      ins.center = v.center;
      ins.hops = v.hops;
    }
    applyView(v);
    if (v.sec) {
      if (v.item) nav.item[v.sec] = v.item;
      if (v.sub) nav.sub = v.sub;
      showSection(v.sec, { silent: true });
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
            on: { click: function () { openProjectQuery(p.slug, t.slug); } },
          })]));
          triList.appendChild(el("span", { text: t.found + " found · " + t.loaded + " loaded · " + t.decided + " decided" }));
        });
      }
      wrap.appendChild(el("article", { className: "panel" }, [
        el("h2", { text: p.slug }),
        pbar, plegend, kv, triList, cmds,
      ]));
    });
    document.getElementById("c-projects").textContent = String(projects.length);
    if (nav.section === "projects") renderProjectsSidebar();
  }

  // ------------------------------------------------- project folder (D6)
  //
  // No project selected -> the existing card grid. A project selected ->
  // the folder: fixed Summary/Papers/Queries/Reports/Screening-log subtabs.
  // `p` may be undefined for a project known only from paper `.projects`
  // tags or a triage link (no `projects/<slug>/project.yaml` yet) -- the
  // folder still opens, with an explanatory Summary and the other subtabs
  // empty, rather than refusing to expand it.
  function renderProjectsMain() {
    var slug = nav.item.projects;
    var grid = document.getElementById("p-projects");
    var folder = document.getElementById("proj-folder");
    var heading = document.getElementById("proj-heading");
    if (!slug) {
      folder.hidden = true;
      grid.hidden = false;
      heading.textContent = "Projects";
      renderProjects();
      return;
    }
    grid.hidden = true;
    folder.hidden = false;
    heading.textContent = slug;
    applyProjectSub(nav.sub || "summary", currentProject());
  }

  document.getElementById("proj-subtabs").addEventListener("click", function (e) {
    var b = e.target.closest("button[data-psub]");
    if (!b) return;
    nav.sub = b.dataset.psub;
    pushNavState();
    syncUrl();
    applyProjectSub(nav.sub, currentProject());
  });

  function applyProjectSub(sub, p) {
    nav.sub = sub;
    document.querySelectorAll("#proj-subtabs button[data-psub]").forEach(function (b) {
      b.setAttribute("aria-selected", String(b.dataset.psub === sub));
    });
    document.querySelectorAll("#proj-folder .psubpage").forEach(function (n) { n.hidden = n.dataset.psub !== sub; });
    document.title = (p ? p.slug : nav.item.projects) + " · " + sub + " — Projects · Paper library";
    if (sub === "summary") renderProjectSummary(p);
    else if (sub === "papers") renderProjectPapers(p);
    else if (sub === "queries") { mountTriageInto("proj-queries-mount", "project:" + nav.item.projects); renderTriageTab(); }
    else if (sub === "reports") renderProjectReports(p);
    else if (sub === "screening") renderProjectScreeningLog(p);
  }

  function renderProjectSummary(p) {
    var wrap = document.getElementById("proj-summary");
    clear(wrap);
    if (!p) {
      wrap.appendChild(el("div", { className: "empty", text: "no projects/" + nav.item.projects + "/project.yaml yet -- see /ref:project create" }));
      return;
    }
    var s = p.summary || {};
    var kv = el("dl", { className: "kv" }, [
      el("span", { text: "scope" }), el("span", { text: p.scope || "(none)" }),
      el("span", { text: "template" }), el("span", { text: p.template || "(none)" }),
      el("span", { text: "papers" }), el("span", { text: String(s.paper_count || 0) }),
    ]);
    wrap.appendChild(el("h3", { text: "Questions" }));
    // D8/phase 5: real per-question paper counts, from the question<->paper
    // link (`project.py dashboard_summary()`'s `paper_count` per question).
    if (p.questions && p.questions.length) {
      var qlist = el("ul", { className: "qlist" });
      p.questions.forEach(function (q) {
        qlist.appendChild(el("li", {}, [
          el("span", { className: "qid", text: q.id }),
          el("span", { text: q.text }),
          el("small", { text: (q.paper_count || 0) + " paper" + (q.paper_count === 1 ? "" : "s") }),
        ]));
      });
      wrap.appendChild(qlist);
      if (p.unassigned_papers) {
        wrap.appendChild(el("small", { text: p.unassigned_papers + " paper(s) not linked to any question" }));
      }
    } else {
      wrap.appendChild(el("div", { className: "empty", text: "no questions yet -- /ref:project add-question" }));
    }
    wrap.appendChild(kv);
    if (p.queries && p.queries.length) {
      wrap.appendChild(el("h3", { text: "Queries" }));
      var qcards = el("div", { className: "repgrid" });
      p.queries.forEach(function (q) {
        qcards.appendChild(el("button", {
          className: "repcard", attrs: { type: "button" },
          on: { click: function () { openProjectQuery(p.slug, q.slug); } },
        }, [
          el("b", { text: q.slug }),
          el("small", { text: q.total + " total · " + q.included + " included · " + q.pending + " pending · " + q.undecided + " undecided" }),
        ]));
      });
      wrap.appendChild(qcards);
    }
    if (p.reading_queue && p.reading_queue.length) {
      wrap.appendChild(el("h3", { text: "Reading queue" }));
      var rq = el("dl", { className: "kv" });
      p.reading_queue.slice(0, 10).forEach(function (m) {
        rq.appendChild(el("span", { text: m.pmid }));
        rq.appendChild(el("span", { text: (m.why_saved || m.reading_status || "") }));
      });
      wrap.appendChild(rq);
    }
    if (p.next_steps && p.next_steps.length) {
      wrap.appendChild(el("h3", { text: "Workflow" }));
      var steps = el("dl", { className: "kv" });
      p.next_steps.forEach(function (cmd) {
        steps.appendChild(el("button", {
          className: "cmdbtn", text: "Copy", attrs: { type: "button" },
          on: { click: function () { copyText(cmd.replace("<slug>", p.slug)); } },
        }));
        steps.appendChild(el("code", { text: cmd }));
      });
      wrap.appendChild(steps);
    }
  }

  // Papers subtab reuses the Library table component with `state.project`
  // pinned (phase 3 §3.4); full renderTable() mount-point refactor is a
  // larger change than this pass makes -- for now this is a focused
  // pmid/status list rather than the full sortable table. Phase 5 §5/§6
  // adds a Question chip per row plus bulk "Assign to question".
  var projPapersSelected = new Set();

  function renderProjectPapers(p) {
    var wrap = document.getElementById("proj-papers");
    clear(wrap);
    if (!p) { wrap.appendChild(el("div", { className: "empty", text: "no project.yaml yet" })); return; }
    projPapersSelected = new Set();
    var jump = el("button", {
      className: "cmdbtn", text: "Open in Library (filtered)", attrs: { type: "button" },
      on: { click: function () { state.project = p.slug; selectTab("papers"); renderTable(); } },
    });
    wrap.appendChild(jump);

    var qOptions = p.questions || [];
    var bulkBar = el("div", { className: "tri-bulk" });
    bulkBar.hidden = true;
    var assignSelect = el("select", { attrs: { "aria-label": "Assign to question" } }, [
      el("option", { text: "Assign to question…", attrs: { value: "" } }),
    ].concat(qOptions.map(function (q) { return el("option", { text: q.id + ": " + q.text, attrs: { value: q.id } }); })));
    var assignBtn = el("button", {
      className: "cmdbtn", text: "Assign", attrs: { type: "button" },
      on: {
        click: function () {
          var qid = assignSelect.value;
          if (!qid || !projPapersSelected.size) return;
          postJSON("/api/project/" + encodeURIComponent(p.slug) + "/papers", {
            pmids: Array.from(projPapersSelected), add: [qid],
          }).then(function () { loadProjects().then(function () { renderProjectPapers(currentProject()); }); })
            .catch(function (err) { showError("bulk assign failed: " + describeFetchError(err)); });
        },
      },
    });
    bulkBar.appendChild(el("span", { text: "0 selected" }));
    bulkBar.appendChild(assignSelect);
    bulkBar.appendChild(assignBtn);
    wrap.appendChild(bulkBar);

    var table = el("table", { className: "reading-queue" }, [
      el("thead", {}, [el("tr", {}, [
        el("th", {}), el("th", { text: "pmid" }), el("th", { text: "priority" }),
        el("th", { text: "reading status" }), el("th", { text: "questions" }),
      ])]),
    ]);
    var tbody = el("tbody");
    (p.papers || []).forEach(function (m) {
      var cb = el("input", { attrs: { type: "checkbox", "aria-label": "select " + m.pmid } });
      cb.addEventListener("change", function () {
        if (cb.checked) projPapersSelected.add(m.pmid); else projPapersSelected.delete(m.pmid);
        bulkBar.hidden = !projPapersSelected.size;
        bulkBar.firstChild.textContent = projPapersSelected.size + " selected";
      });
      tbody.appendChild(el("tr", {}, [
        el("td", {}, [cb]), el("td", { text: m.pmid }), el("td", { text: m.priority == null ? "" : String(m.priority) }),
        el("td", { text: m.reading_status || "" }),
        el("td", { text: (m.questions || []).join(", ") }),
      ]));
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    if (!(p.papers || []).length) wrap.appendChild(el("div", { className: "empty", text: "no papers in this project yet" }));
  }

  // Phase 4 §2: card grid grouped Narrative/Analysis/Review; click -> a
  // full-width reader replaces the grid with a "‹ Reports" crumb back.
  // `projReportOpen` is a light in-memory reader flag rather than a full
  // `reports/<id>` nav.sub entry (D14 asks for the latter so Back also
  // walks the reader) -- Back from a report currently lands on the grid,
  // not a step further out; flagged as a scope cut, not a silent gap.
  var projReportOpen = null; // {project, kind, id} while a reader is open
  var REPORT_GROUPS = ["Narrative", "Analysis", "Review"];

  function renderProjectReports(p) {
    var wrap = document.getElementById("proj-reports");
    clear(wrap);
    if (!p) { wrap.appendChild(el("div", { className: "empty", text: "no project.yaml yet" })); return; }
    if (projReportOpen && projReportOpen.project === p.slug) {
      renderReportReader(p, projReportOpen.kind, projReportOpen.id);
      return;
    }
    wrap.appendChild(el("div", { className: "empty", text: "loading…" }));
    fetchJSON("/api/project/" + encodeURIComponent(p.slug) + "/reports").then(function (cards) {
      clear(wrap);
      var groups = {};
      cards.forEach(function (c) { (groups[c.group] = groups[c.group] || []).push(c); });
      REPORT_GROUPS.forEach(function (g) {
        if (!groups[g]) return;
        wrap.appendChild(el("div", { className: "side-group" }, [el("span", { text: g })]));
        var grid = el("div", { className: "repgrid" });
        groups[g].forEach(function (c) {
          var cssState = c.state === "live" ? "fresh" : (c.state || "none");
          grid.appendChild(el("button", {
            className: "repcard" + (c.state === "none" ? " off" : ""), attrs: { type: "button" },
            on: {
              click: function () {
                if (c.state === "none") { copyText(c.command); return; }
                projReportOpen = { project: p.slug, kind: c.kind, id: c.id };
                renderReportReader(p, c.kind, c.id);
              },
            },
          }, [
            el("b", { text: c.title }),
            el("span", { className: "repstate " + cssState, text: c.state === "none" ? "not yet run" : (c.state === "live" ? "live" : c.state) }),
            el("small", { text: c.why || c.command || (c.generated_at || "") }),
          ]));
        });
        wrap.appendChild(grid);
      });
      if (!cards.length) wrap.appendChild(el("div", { className: "empty", text: "no reports yet" }));
    }).catch(function (err) {
      clear(wrap);
      wrap.appendChild(el("div", { className: "empty", text: "could not load reports: " + describeFetchError(err) }));
    });
  }

  function renderReportReader(p, kind, id) {
    var wrap = document.getElementById("proj-reports");
    clear(wrap);
    var crumb = el("button", {
      className: "cmdbtn", text: "‹ Reports", attrs: { type: "button" },
      on: { click: function () { projReportOpen = null; renderProjectReports(p); } },
    });
    wrap.appendChild(crumb);
    wrap.appendChild(el("div", { className: "empty", text: "loading…" }));
    fetchJSON("/api/project/" + encodeURIComponent(p.slug) + "/report/" + kind + "/" + encodeURIComponent(id)).then(function (data) {
      clear(wrap);
      wrap.appendChild(crumb);
      var view = el("div", { className: "panel repview" }, [
        el("div", { className: "rephead" }, [el("h3", { text: kind + " · " + id })]),
      ]);
      if (data.body) view.appendChild(el("div", { className: "prose", text: data.body }));
      if (data.answer) view.appendChild(el("div", { className: "prose", text: data.answer }));
      if (data.rows) view.appendChild(el("pre", { text: JSON.stringify(data.rows, null, 2) }));
      if (data.grade) view.appendChild(el("pre", { text: JSON.stringify(data.grade, null, 2) }));
      if (data.single_study_fragile) {
        view.appendChild(el("h4", { text: "Single-study fragile claims (" + data.single_study_fragile.length + ")" }));
        view.appendChild(el("pre", { text: JSON.stringify(data.single_study_fragile, null, 2) }));
      }
      if (data.unresolved_conflicts) {
        view.appendChild(el("h4", { text: "Unresolved conflicts (" + data.unresolved_conflicts.length + ")" }));
        view.appendChild(el("pre", { text: JSON.stringify(data.unresolved_conflicts, null, 2) }));
      }
      wrap.appendChild(view);
    }).catch(function (err) {
      clear(wrap);
      wrap.appendChild(crumb);
      wrap.appendChild(el("div", { className: "empty", text: "could not load report: " + describeFetchError(err) }));
    });
  }

  function renderProjectScreeningLog(p) {
    var wrap = document.getElementById("proj-screening");
    clear(wrap);
    if (!p) { wrap.appendChild(el("div", { className: "empty", text: "no project.yaml yet" })); return; }
    wrap.appendChild(el("div", { className: "empty", text: "loading…" }));
    fetchJSON("/api/project/" + encodeURIComponent(p.slug) + "/screening?limit=100").then(function (page) {
      clear(wrap);
      if (!page.records.length) { wrap.appendChild(el("div", { className: "empty", text: "no screening decisions yet" })); return; }
      var table = el("table", { className: "reading-queue" }, [
        el("thead", {}, [el("tr", {}, [el("th", { text: "pmid" }), el("th", { text: "decision" }), el("th", { text: "reason" }), el("th", { text: "when" })])]),
      ]);
      var tbody = el("tbody");
      page.records.forEach(function (r) {
        tbody.appendChild(el("tr", {}, [
          el("td", { text: r.pmid }), el("td", { text: r.decision }), el("td", { text: r.reason || "" }), el("td", { text: r.timestamp || "" }),
        ]));
      });
      table.appendChild(tbody);
      wrap.appendChild(table);
    }).catch(function (err) {
      clear(wrap);
      wrap.appendChild(el("div", { className: "empty", text: "could not load screening log: " + describeFetchError(err) }));
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
    var panel = list.closest(".nextpanel");
    var summaryEl = document.getElementById("next-summary");
    clear(summaryEl);
    if (!SUMMARY) {
      caption.textContent = "";
      panel.setAttribute("data-empty", "true");
      summaryEl.textContent = LIVE ? "summary not loaded yet" : "rebuild the dashboard to rank next actions";
      return;
    }
    var scoped = document.getElementById("next-scope").checked;
    var visible = scoped ? new Set(currentVisible.map(function (r) { return r.pmid; })) : null;
    var actions = (SUMMARY.top_actions || []).map(function (a) { return actionForScope(a, visible); }).filter(Boolean);
    actions.sort(function (a, b) { return b.score - a.score || (a.id < b.id ? -1 : 1); });
    actions = actions.slice(0, 8);
    caption.textContent = "ranked " + String(SUMMARY.generated_at || "").slice(11, 16);
    caption.title = SUMMARY.paper_count + " papers · " + SUMMARY.issues_total + " open issues · score = weight × papers × project boost";
    if (!actions.length) {
      panel.setAttribute("data-empty", "true");
      var check = svgEl("svg", { viewBox: "0 0 24 24", "aria-hidden": "true" });
      check.appendChild(svgEl("circle", { cx: 12, cy: 12, r: 9 }));
      check.appendChild(svgEl("path", { d: "m8.5 12.5 2.5 2.5 4.5-5" }));
      summaryEl.appendChild(check);
      summaryEl.appendChild(el("span", { text: scoped ? "Nothing to do for the papers in the current filters." : "Nothing to do. Library is healthy." }));
      return;
    }
    panel.setAttribute("data-empty", "false");
    summaryEl.textContent = actions.length + " action" + (actions.length === 1 ? "" : "s") + " · " + SUMMARY.issues_total + " open issues";
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
  document.getElementById("next-toggle").addEventListener("click", function () {
    var panel = document.querySelector(".nextpanel");
    var collapsed = panel.getAttribute("data-collapsed") !== "true";
    panel.setAttribute("data-collapsed", String(collapsed));
    this.setAttribute("aria-expanded", String(!collapsed));
    this.setAttribute("aria-label", (collapsed ? "Expand" : "Collapse") + " next actions");
  });
  document.querySelector(".nextpanel").setAttribute("data-collapsed", "false");
  document.getElementById("next-toggle").setAttribute("aria-expanded", "true");

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

  // `mode` is the panel's sub-view (the icon tablist): overview, notes,
  // claims, figures, files, or the pdf.js viewer.
  var DRAWER_VIEWS = ["overview", "notes", "claims", "figures", "files", "pdf"];
  var drawerState = { pmid: null, mode: "overview", wide: false, autoWide: false, cmds: false };
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

  // The panel is docked (not modal): clicking another table row swaps its
  // content in place, the page shrinks to make room (body.pane-open), and
  // focus moves into it only when it was closed before -- a row click while
  // it is already open keeps focus on the table so j/k browsing continues.
  function openDrawer(pmid) {
    var wasOpen = !document.getElementById("drawer").hidden;
    if (!wasOpen) lastFocusedBeforeDrawer = document.activeElement;
    var samePaper = drawerState.pmid === pmid;
    drawerState.pmid = pmid;
    if (!samePaper && drawerState.mode === "pdf") drawerState.mode = "overview";
    document.getElementById("drawer").hidden = false;
    document.body.classList.add("pane-open");
    autoCollapseForDrawer(true);
    setDrawerMode(drawerState.mode);
    renderDrawerHeader();
    loadDetail(pmid, function (detail) { if (drawerState.pmid === pmid) renderDrawerBody(detail); });
    markOpenRow();
    if (!wasOpen) {
      var focusables = drawerFocusables();
      if (focusables.length) focusables[0].focus();
    }
  }

  function closeDrawer() {
    document.getElementById("drawer").hidden = true;
    document.body.classList.remove("pane-open");
    autoCollapseForDrawer(false);
    drawerState.pmid = null;
    markOpenRow();
    if (lastFocusedBeforeDrawer && document.contains(lastFocusedBeforeDrawer)) lastFocusedBeforeDrawer.focus();
    lastFocusedBeforeDrawer = null;
  }

  function setDrawerWide(wide) {
    drawerState.wide = !!wide;
    document.getElementById("drawer").classList.toggle("wide", drawerState.wide);
    document.body.classList.toggle("pane-wide", drawerState.wide);
    document.getElementById("d-wide").setAttribute("aria-pressed", String(drawerState.wide));
  }

  document.getElementById("d-close").addEventListener("click", closeDrawer);
  document.getElementById("d-wide").addEventListener("click", function () { setDrawerWide(!drawerState.wide); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !document.getElementById("drawer").hidden) closeDrawer(); });

  document.getElementById("d-prev").addEventListener("click", function () { stepDrawer(-1); });
  document.getElementById("d-next").addEventListener("click", function () { stepDrawer(1); });

  function stepDrawer(delta) {
    var idx = currentVisible.findIndex(function (r) { return r.pmid === drawerState.pmid; });
    if (idx < 0) return;
    var next = idx + delta;
    if (next < 0 || next >= currentVisible.length) return;
    openDrawer(currentVisible[next].pmid);
  }

  document.getElementById("d-views").addEventListener("click", function (e) {
    var btn = e.target.closest("button[data-view]");
    if (btn) setDrawerMode(btn.dataset.view);
  });
  document.getElementById("d-cmds").addEventListener("click", function () {
    drawerState.cmds = !drawerState.cmds;
    document.getElementById("d-cmds").setAttribute("aria-pressed", String(drawerState.cmds));
    document.getElementById("d-foot").hidden = !drawerState.cmds;
  });

  function setDrawerMode(mode) {
    if (DRAWER_VIEWS.indexOf(mode) < 0) mode = "overview";
    var changed = drawerState.mode !== mode;
    drawerState.mode = mode;
    document.querySelectorAll("#d-views button[data-view]").forEach(function (b) {
      b.setAttribute("aria-selected", String(b.dataset.view === mode));
    });
    document.getElementById("d-body").hidden = mode === "pdf";
    document.getElementById("d-pdf").hidden = mode !== "pdf";
    if (changed && mode !== "pdf" && drawerState.pmid && loadedDetails[drawerState.pmid]) {
      renderDrawerBody(loadedDetails[drawerState.pmid]);
    }
    // The pdf.js viewer needs room: widen the panel for it and give the
    // space back when the user returns to details (unless they widened it
    // themselves).
    if (mode === "pdf") { drawerState.autoWide = !drawerState.wide; setDrawerWide(true); }
    else if (drawerState.autoWide) { drawerState.autoWide = false; setDrawerWide(false); }
    if (mode === "pdf") renderPdfTab();
  }

  function renderDrawerHeader() {
    var row = BY_PMID[drawerState.pmid];
    if (!row) return;
    var idx = currentVisible.findIndex(function (r) { return r.pmid === drawerState.pmid; });
    document.getElementById("d-pos").textContent = (idx >= 0 ? (idx + 1) + " / " + currentVisible.length : "");
    document.getElementById("d-prev").disabled = idx <= 0;
    document.getElementById("d-next").disabled = idx < 0 || idx >= currentVisible.length - 1;

    var eyebrow = document.getElementById("d-eyebrow");
    clear(eyebrow);
    var eb = [row.journal, row.year].filter(Boolean).join(" ");
    if (eb) eyebrow.appendChild(el("span", { text: eb }));
    eyebrow.appendChild(el("span", { className: "ck", text: row.citekey || row.pmid }));

    var badges = document.getElementById("d-badges");
    clear(badges);
    var badge = row.source_badge || "none";
    badges.appendChild(el("span", { className: "badge", attrs: { style: "--c:" + SOURCE_COLOR[badge] } }, [
      el("i"), el("span", { text: badge === "none" ? "no meta" : badge }),
    ]));
    if (retractionFlagged(row)) {
      badges.appendChild(el("span", { className: "flag crit", text: row.retraction_status }));
    }
    if (row.stale_check) badges.appendChild(el("span", { className: "flag", text: "stale check" }));

    document.getElementById("d-title").textContent = row.title || "(untitled)";
  }

  // One sub-view at a time (the header tablist); the commands footer is
  // rebuilt on every render and shown by the terminal button.
  function renderDrawerBody(detail) {
    var body = document.getElementById("d-body");
    clear(body);
    var footWrap = document.getElementById("d-foot");
    clear(footWrap);
    var row = BY_PMID[drawerState.pmid];

    if (!detail) {
      body.appendChild(el("div", { className: "empty", text: "could not load details for this paper." }));
      return;
    }

    var view = drawerState.mode === "pdf" ? "overview" : drawerState.mode;
    if (view === "overview") body.appendChild(sectionOverview(row, detail));
    else if (view === "notes") body.appendChild(sectionNotes(row, detail));
    else if (view === "claims") body.appendChild(sectionClaims(detail));
    else if (view === "figures") body.appendChild(sectionFigures(detail));
    else if (view === "files") body.appendChild(sectionFiles(detail));
    body.scrollTop = 0;

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
    footWrap.appendChild(el("button", {
      className: "cmdbtn", text: "Show in graph",
      on: { click: function () { var pmid = row.pmid; closeDrawer(); INSIGHTS.showInGraph("p:" + pmid); } },
    }));
  }

  function sec(id, title, kids) {
    return el("div", { className: "d-sec", attrs: { id: "sec-" + id } }, [
      el("h3", { text: title }),
    ].concat(kids));
  }

  function idChip(label, value) {
    var chip = el("button", {
      className: "idchip", attrs: { type: "button", title: "Copy " + value },
      on: { click: function () { copyText(value); } },
    }, [el("span", { text: label + ": " + value }), el("span", { text: "⧉", attrs: { "aria-hidden": "true" } })]);
    return chip;
  }

  var READING_STATES = ["to_screen", "to_read", "reading", "read"];

  // Overview (the ⓘ view): authors line with a full-list toggle, clamped
  // abstract, the paper's coverage-matrix row as a checklist (same cells as
  // the table strip), a key/value block (projects, reading status, claims,
  // copyable identifiers), the PDF card (page-1 thumbnail in live mode --
  // clicking it opens the viewer), and funding tucked away at the bottom.
  function sectionOverview(row, detail) {
    var kids = [];

    // authors: "Smith, Jones, Patel … Weber, Anna" + more -> every author
    var authorsFull = (detail.authors || []).map(function (a) {
      return [a.last, a.first].filter(Boolean).join(", ") || a.raw || "";
    }).filter(Boolean);
    var short = row.authors_short || "";
    if (row.last_author && short.indexOf("…") >= 0) short = short.replace(/, …$/, "") + " … " + row.last_author;
    var byline = el("div", { className: "d-byline" });
    var bylineText = el("span", { text: short || (authorsFull.length ? authorsFull.join("; ") : "no author list yet") });
    byline.appendChild(bylineText);
    if (authorsFull.length > 1 && short) {
      var open = false;
      var toggle = el("button", { className: "d-more", text: "more", attrs: { type: "button", "aria-expanded": "false" } });
      toggle.addEventListener("click", function () {
        open = !open;
        bylineText.textContent = open ? authorsFull.join("; ") : short;
        toggle.textContent = open ? "less" : "more";
        toggle.setAttribute("aria-expanded", String(open));
      });
      byline.appendChild(toggle);
    }
    kids.push(byline);

    if (detail.abstract) {
      var p = el("p", { className: "prose d-abstract", text: detail.abstract });
      var more = el("button", { className: "d-more", text: "more", attrs: { type: "button", "aria-expanded": "false" } });
      more.addEventListener("click", function () {
        var isOpen = p.classList.toggle("open");
        more.textContent = isOpen ? "less" : "more";
        more.setAttribute("aria-expanded", String(isOpen));
      });
      kids.push(el("div", { className: "d-abswrap" }, [p, detail.abstract.length < 320 ? null : more]));
    } else {
      kids.push(el("div", { className: "empty", text: "no abstract on file" }));
    }

    var m = MATRIX_BY_PMID[row.pmid] || {};
    kids.push(el("div", { className: "covgrid" }, MATRIX_COLUMNS_LIVE.map(function (c) {
      var on = !!m[c];
      return el("span", { className: (on ? "on" : "") + (on && c === "retraction" && retractionFlagged(row) ? " ret" : ""), attrs: { title: c + ": " + (on ? "yes" : "no") } }, [el("i"), el("span", { text: c })]);
    })));

    // key/value block
    var kv = el("div", { className: "kv" });
    var projChips = el("div", { className: "idchips" }, (row.projects || []).map(function (pr) {
      return el("span", { className: "idchip static", attrs: { title: pr.reading_status ? "reading: " + pr.reading_status.replace("_", " ") : "" } }, [el("span", { text: pr.slug })]);
    }));
    projChips.appendChild(el("button", {
      className: "idchip", text: "+", attrs: { type: "button", title: "Copy a /ref:project add-paper command for this paper" },
      on: { click: function () { copyText("/ref:project add-paper <slug> " + row.pmid); flash("command copied -- replace <slug>", 2600); } },
    }));
    kv.appendChild(el("span", { className: "k", text: "Projects" }));
    kv.appendChild(projChips);

    var reading = el("select", { attrs: { "aria-label": "Reading status" } });
    var cur = (row.projects || []).map(function (pr) { return pr.reading_status; }).filter(Boolean)[0] || "";
    reading.appendChild(el("option", { attrs: { value: "" }, text: cur ? cur.replace("_", " ") : "(unset)" }));
    READING_STATES.forEach(function (s) { if (s !== cur) reading.appendChild(el("option", { attrs: { value: s }, text: s.replace("_", " ") })); });
    var slug = (row.projects || []).length === 1 ? row.projects[0].slug : "<slug>";
    reading.addEventListener("change", function () {
      if (!reading.value) return;
      copyText("/ref:project add-paper " + slug + " " + row.pmid + " --reading-status " + reading.value);
      flash(slug === "<slug>" ? "command copied -- replace <slug>" : "command copied -- run it to change the status", 2600);
      reading.value = "";
    });
    kv.appendChild(el("span", { className: "k", text: "Reading" }));
    kv.appendChild(el("span", {}, [reading]));

    // phase 5 §5: a question multi-select, live (unlike the copy-command
    // controls above) -- only offered when the paper belongs to exactly
    // one project, same "<slug>" ambiguity guard as Reading.
    if ((row.projects || []).length === 1) {
      var pr = row.projects[0];
      var proj = PROJECTS.filter(function (x) { return x.slug === pr.slug; })[0];
      if (proj && proj.questions && proj.questions.length) {
        var qsel = el("select", { attrs: { multiple: "multiple", "aria-label": "Questions", size: String(Math.min(4, proj.questions.length)) } });
        proj.questions.forEach(function (q) {
          qsel.appendChild(el("option", {
            text: q.id + ": " + q.text, attrs: { value: q.id, selected: (pr.questions || []).indexOf(q.id) >= 0 ? "selected" : undefined },
          }));
        });
        qsel.addEventListener("change", function () {
          var selected = Array.prototype.filter.call(qsel.options, function (o) { return o.selected; }).map(function (o) { return o.value; });
          var current = pr.questions || [];
          var add = selected.filter(function (q) { return current.indexOf(q) < 0; });
          var remove = current.filter(function (q) { return selected.indexOf(q) < 0; });
          if (!add.length && !remove.length) return;
          postJSON("/api/project/" + encodeURIComponent(pr.slug) + "/paper/" + encodeURIComponent(row.pmid), { add: add, remove: remove })
            .then(function (m) { pr.questions = m.questions; flash("questions updated", 1800); })
            .catch(function (err) { showError("could not update questions: " + describeFetchError(err)); });
        });
        kv.appendChild(el("span", { className: "k", text: "Questions" }));
        kv.appendChild(el("span", {}, [qsel]));
      }
    }

    kv.appendChild(el("span", { className: "k", text: "Claims" }));
    kv.appendChild(el("span", { className: "mono", text: (row.claims_active || 0) + " active" + (row.extraction_tier ? " · tier " + row.extraction_tier : "") }));

    var ids = el("div", { className: "idchips" });
    if (row.doi) ids.appendChild(idChip("doi", row.doi));
    ids.appendChild(idChip("pmid", row.pmid));
    if (row.pmcid) ids.appendChild(idChip("pmcid", row.pmcid));
    kv.appendChild(el("span", { className: "k", text: "Identifiers" }));
    kv.appendChild(ids);

    kv.appendChild(el("span", { className: "k", text: "Checked" }));
    kv.appendChild(el("span", { className: "mono", text: [row.checked_at ? row.checked_at.slice(0, 10) : "never", row.stale_check ? "(stale)" : null].filter(Boolean).join(" ") }));
    kids.push(kv);

    kids.push(pdfCard(row));

    var funding = detail.funding || {};
    if ((funding.observations || []).length || funding.state) {
      kids.push(el("details", { className: "d-fold" }, [
        el("summary", { text: "Funding & acknowledgements" + (funding.state ? " · " + funding.state : "") }),
        sectionFunding(detail),
      ]));
    }
    return el("div", { className: "d-overview" }, kids);
  }

  function pdfCard(row) {
    var paths = row.pdf_paths || [];
    var thumb = el("div", { className: "pdfthumb", attrs: { role: "button", tabindex: "0", "aria-label": paths.length ? "Open PDF" : "No PDF attached" } });
    function openPdf() { setDrawerMode("pdf"); }
    thumb.addEventListener("click", openPdf);
    thumb.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openPdf(); } });
    var btns = el("div", { className: "btns" });
    if (paths.length) {
      thumb.textContent = "PDF";
      if (LIVE) renderPdfThumb(row, paths[0], thumb);
      btns.appendChild(el("button", { className: "cmdbtn primary", text: "View PDF", attrs: { type: "button" }, on: { click: openPdf } }));
    } else {
      thumb.textContent = "no PDF";
      if (LIVE) btns.appendChild(pdfDropZone(row));
      else btns.appendChild(el("button", { className: "cmdbtn", text: "/ref:fetch-pdf " + row.pmid, attrs: { type: "button" }, on: { click: function () { copyText("/ref:fetch-pdf " + row.pmid); } } }));
    }
    return el("div", { className: "pdfcard" }, [thumb, btns]);
  }

  var thumbCache = {}; // pmid/path -> data URL of page 1, so re-opening a paper is instant
  function renderPdfThumb(row, path, thumb) {
    var key = row.pmid + "/" + path;
    function show(url) {
      clear(thumb);
      var img = el("img", { attrs: { src: url, alt: "First page of the PDF" } });
      img.style.width = "100%";
      img.style.display = "block";
      thumb.appendChild(img);
    }
    if (thumbCache[key]) { show(thumbCache[key]); return; }
    loadPdfJs().then(function (pdfjsLib) {
      return apiFetch("/files/" + encodeURIComponent(row.pmid) + "/" + path.split("/").map(encodeURIComponent).join("/"))
        .then(function (r) { if (!r.ok) throw new Error("http " + r.status); return r.arrayBuffer(); })
        .then(function (buf) { return pdfjsLib.getDocument({ data: buf }).promise; })
        .then(function (doc) { return doc.getPage(1); })
        .then(function (page) {
          var vp = page.getViewport({ scale: 1 });
          var scale = 300 / vp.width; // 2x the 150px card for crisp text on retina screens
          var viewport = page.getViewport({ scale: scale });
          var canvas = document.createElement("canvas");
          canvas.width = viewport.width;
          canvas.height = viewport.height;
          return page.render({ canvasContext: canvas.getContext("2d"), viewport: viewport }).promise.then(function () { return canvas.toDataURL("image/png"); });
        })
        .then(function (url) { thumbCache[key] = url; if (thumb.isConnected) show(url); });
    }).catch(function () { /* the card's "PDF" label stays; the viewer still opens on click */ });
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
    var noteFilter = "", noteOrder = "newest";
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
      var q = noteFilter.trim().toLowerCase();
      var shown = (notes || []).filter(function (n) { return !q || ((n.text || "") + " " + (n.at || "")).toLowerCase().indexOf(q) >= 0; });
      if (noteOrder === "newest") shown = shown.slice().reverse();
      shown.forEach(function (n) { list.appendChild(noteListItem(n)); });
      if (!(notes || []).length) list.appendChild(el("li", { className: "empty", text: "no committed notes yet" }));
      else if (!shown.length) list.appendChild(el("li", { className: "empty", text: "no notes match the filter" }));
    }
    renderNoteList(detail.notes);

    var filterInput = el("input", { attrs: { type: "search", placeholder: "Filter notes…", "aria-label": "Filter notes" } });
    filterInput.addEventListener("input", function () { noteFilter = filterInput.value; renderNoteList(detail.notes); });
    var orderSel = el("select", { attrs: { "aria-label": "Order notes" } }, [
      el("option", { attrs: { value: "newest" }, text: "Newest first" }),
      el("option", { attrs: { value: "oldest" }, text: "Oldest first" }),
    ]);
    orderSel.addEventListener("change", function () { noteOrder = orderSel.value; renderNoteList(detail.notes); });
    var noteTools = el("div", { className: "notetools" }, [filterInput, orderSel]);

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

    textarea.setAttribute("placeholder", LIVE ? "Write your note here…" : "Write your note here… (kept only in this browser until you run /ref:note)");
    var composer = el("div", { className: "composer" }, [textarea, el("div", { className: "row" }, rowKids)]);
    wrap.appendChild(composer);
    wrap.appendChild(noteTools);
    wrap.appendChild(list);
    return wrap;
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

  // D3: intake is global -- the rail "Add" button opens a popover, and
  // dropping anywhere on the window (not just the popover's own zone or a
  // table row) opens a full-window overlay that names the target before
  // anything uploads.
  function intakeTargetContext() {
    if (nav.section === "library" && state.project !== "all" && state.project !== "none") return state.project;
    if (nav.section === "queries" && tri.slug) {
      var t = TRIAGES.filter(function (x) { return x.slug === tri.slug; })[0];
      if (t && t.project) return t.project;
    }
    return null;
  }
  function updateDropTargetLabel() {
    var sel = document.getElementById("intake-target");
    var label = document.getElementById("drop-target-label");
    if (!sel || !label) return;
    label.textContent = sel.value ? ("project: " + sel.value) : "All papers";
  }
  function fillIntakeTargets() {
    var sel = document.getElementById("intake-target");
    if (!sel) return;
    var current = sel.value;
    clear(sel);
    sel.appendChild(el("option", { attrs: { value: "" }, text: "All papers (library only)" }));
    projectSummaries().forEach(function (p) {
      sel.appendChild(el("option", { attrs: { value: p.slug }, text: "project: " + p.slug } ));
    });
    var known = Array.prototype.some.call(sel.options, function (o) { return o.value === current; });
    sel.value = known ? current : (intakeTargetContext() || "");
    updateDropTargetLabel();
  }
  function openIntakePop() {
    var pop = document.getElementById("intake");
    if (!pop || !LIVE) return;
    fillIntakeTargets();
    pop.hidden = false;
    var addBtn = document.getElementById("btn-add");
    if (addBtn) addBtn.setAttribute("aria-expanded", "true");
    var txt = document.getElementById("intake-text");
    if (txt) txt.focus();
  }
  function closeIntakePop() {
    var pop = document.getElementById("intake");
    if (!pop) return;
    pop.hidden = true;
    var addBtn = document.getElementById("btn-add");
    if (addBtn) addBtn.setAttribute("aria-expanded", "false");
  }
  if (LIVE) {
    var addBtn = document.getElementById("btn-add");
    if (addBtn) addBtn.addEventListener("click", function () {
      if (document.getElementById("intake").hidden) openIntakePop(); else closeIntakePop();
    });
    var intakeCloseBtn = document.getElementById("intake-close");
    if (intakeCloseBtn) intakeCloseBtn.addEventListener("click", closeIntakePop);
    var intakeTargetSel = document.getElementById("intake-target");
    if (intakeTargetSel) intakeTargetSel.addEventListener("change", updateDropTargetLabel);
    document.addEventListener("keydown", function (e) {
      var pop = document.getElementById("intake");
      if (e.key === "Escape" && pop && !pop.hidden) closeIntakePop();
    });

    var overlay = document.getElementById("drop-overlay");
    var overlayDepth = 0;
    window.addEventListener("dragenter", function (e) {
      if (!hasFiles(e)) return;
      e.preventDefault();
      if (++overlayDepth === 1 && overlay) { fillIntakeTargets(); overlay.hidden = false; }
    });
    // A file dropped anywhere else must not navigate the tab away from the dashboard.
    window.addEventListener("dragover", function (e) { if (hasFiles(e)) e.preventDefault(); });
    window.addEventListener("dragleave", function (e) {
      if (!hasFiles(e)) return;
      if (--overlayDepth <= 0) { overlayDepth = 0; if (overlay) overlay.hidden = true; }
    });
    window.addEventListener("drop", function (e) {
      overlayDepth = 0;
      if (overlay) overlay.hidden = true;
      if (!hasFiles(e)) return;
      if (e.defaultPrevented) return; // a more specific drop zone (a table row, the PDF pane) already handled it
      e.preventDefault();
      openIntakePop();
      var dt = e.dataTransfer;
      if (dt.files && dt.files.length) submitIntakeFiles(dt.files);
    });
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

  // Phase 3 §3.1: re-fetched whenever the library changes (manual refresh,
  // change banner) so the folder tree and Queries grouping stay live.
  function loadProjects() {
    if (!LIVE) return Promise.resolve();
    return fetchJSON("/api/projects").then(function (list) {
      PROJECTS = list || [];
      if (nav.section === "projects") { renderProjectsSidebar(); renderProjectsMain(); }
      if (nav.section === "queries") renderQueriesSidebar();
    }).catch(function (err) {
      showError("could not load projects: " + describeFetchError(err));
    });
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
      renderQueriesSidebar();
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
  // The Insights tab lives in insights.js (loaded before this file) and
  // reads the page through this context.

  function filtersActive() {
    return !!(state.query || state.project !== "all" || state.chips.length || sourceFilterSet || state.missing);
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

  var INSIGHTS = window.RefDashInsights({
    DATA: DATA, LIVE: LIVE, state: state,
    rows: function () { return ROWS; },
    byPmid: function () { return BY_PMID; },
    activeTab: function () { return activeTab; },
    el: el, svgEl: svgEl, clear: clear, copyText: copyText, downloadText: downloadText,
    fetchJSON: fetchJSON, describeFetchError: describeFetchError,
    filteredRows: filteredRows, filtersActive: filtersActive, applyPmidFilter: applyPmidFilter,
    openDrawer: openDrawer, selectTab: selectTab, syncUrl: syncUrl,
    renderInsightsSidebar: function () { renderInsightsSidebar(); },
  });

  // --------------------------------------------------------------- init

  function renderAll() {
    renderHealth();
    renderProjectSelect();
    renderSourceCoverage();
    renderFunnel();
    renderTrendChart();
    renderTable();
    renderActionBar();
    renderChips();
    renderNextActions();
    renderSidebar();
  }

  // P0.2: a refresh fetches all four live endpoints independently
  // (allSettled, not all-or-nothing) -- one endpoint returning non-2xx
  // must not blank out the others. Whatever succeeded replaces its slice
  // of state; whatever failed keeps its last known-good value and is
  // named in the error banner.
  // ------------------------------------------------------------- intake
  //
  // "Add papers" panel (live only). One drop zone takes PDFs (files) and
  // text (PMIDs, DOIs, PubMed/PMC/DOI links). Text items go as one batch
  // to POST /api/intake and come back through /api/jobs/<id>; each PDF is
  // one POST /api/intake/pdf. intake_pipeline.py checks the library first:
  // a paper that already exists is never re-added, only topped up (PDF,
  // full text). Server answers that need a decision (needs_pmid,
  // needs_replace, needs_force) render inline controls, never a dialog.

  var intake = { items: [], seq: 0, jobs: 0 };

  function intakeCaption() {
    var cap = document.getElementById("intake-caption");
    var panel = document.getElementById("intake");
    var running = intake.items.filter(function (i) { return i.state === "running" || i.state === "queued"; }).length;
    var finished = intake.items.length - running;
    panel.setAttribute("data-busy", String(running > 0));
    cap.className = running ? "busy" : "";
    if (!intake.items.length) cap.textContent = LIVE ? "PDFs · PMIDs · PubMed links" : "";
    else if (running) cap.textContent = finished + " of " + intake.items.length + " done · " + running + " running";
    else cap.textContent = intake.items.length + " processed";
    document.getElementById("intake-clear").hidden = !intake.items.some(function (i) { return i.state === "done" || i.state === "exists"; });
  }

  function intakeIcon(state) {
    var icon = svgEl("svg", { viewBox: "0 0 24 24", "aria-hidden": "true" });
    var cls = { done: "done", exists: "exists", running: "running", queued: "running", failed: "fail" }[state] || "warn";
    icon.setAttribute("class", "ico " + cls);
    if (cls === "done" || cls === "exists") {
      icon.appendChild(svgEl("circle", { cx: 12, cy: 12, r: 9 }));
      icon.appendChild(svgEl("path", { d: "m8.5 12.5 2.5 2.5 4.5-5" }));
    } else if (cls === "running") {
      icon.appendChild(svgEl("path", { d: "M21 12a9 9 0 1 1-3-6.7" }));
    } else if (cls === "fail") {
      icon.appendChild(svgEl("circle", { cx: 12, cy: 12, r: 9 }));
      icon.appendChild(svgEl("path", { d: "m9 9 6 6M15 9l-6 6" }));
    } else {
      icon.appendChild(svgEl("circle", { cx: 12, cy: 12, r: 9 }));
      icon.appendChild(svgEl("path", { d: "M12 8v4M12 16h.01" }));
    }
    return icon;
  }

  function renderIntake() {
    var list = document.getElementById("intake-list");
    clear(list);
    intake.items.forEach(function (it) {
      var trailCls = "trail" + (it.state === "failed" ? " fail" : (/^needs_/.test(it.state) ? " warn" : ""));
      var trail = (it.steps || []).join(" → ");
      if (it.state === "queued") trail = "waiting…";
      if (it.state === "running" && !trail) trail = "identifying…";
      if (it.error && it.state === "failed") trail = (trail ? trail + " → " : "") + it.error;
      var body = el("div", { className: "intakebody" }, [
        el("span", { className: "name", text: it.title ? it.title : it.label, attrs: { title: it.label } }),
        el("span", { className: trailCls, text: trail, attrs: { title: trail } }),
      ]);
      if (it.state === "running") body.appendChild(el("div", { className: "bar" }, [el("i")]));
      var act = el("div", { className: "intakeact" });
      if (it.pmid && (it.state === "done" || it.state === "exists")) {
        act.appendChild(el("a", { text: "open", attrs: { href: "#" + it.pmid } , on: { click: function (e) { e.preventDefault(); openDrawer(it.pmid); } } }));
      }
      if (it.state === "needs_pmid") {
        var inp = el("input", { attrs: { type: "text", placeholder: "PMID", "aria-label": "PMID for " + it.label, inputmode: "numeric" } });
        inp.addEventListener("keydown", function (e) {
          if (e.key === "Enter") { e.preventDefault(); var v = inp.value.trim(); if (/^\d{5,10}$/.test(v)) uploadIntakePdf(it, { pmid: v }); }
        });
        act.appendChild(inp);
      }
      if (it.state === "needs_replace") {
        act.appendChild(el("button", { className: "cmdbtn", text: "Replace PDF", attrs: { type: "button" }, on: { click: function () { uploadIntakePdf(it, { replace: true, pmid: it.pmid }); } } }));
        act.appendChild(el("a", { text: "open", attrs: { href: "#" + it.pmid }, on: { click: function (e) { e.preventDefault(); openDrawer(it.pmid); } } }));
      }
      if (it.state === "needs_force") {
        act.appendChild(el("button", { className: "cmdbtn", text: "Attach anyway", attrs: { type: "button" }, on: { click: function () { uploadIntakePdf(it, { force: true, pmid: it.pmid, replace: true }); } } }));
      }
      list.appendChild(el("li", { attrs: { "data-state": it.state } }, [intakeIcon(it.state), body, act]));
    });
    intakeCaption();
  }

  function intakeAddItem(label, kind, extra) {
    var it = { id: ++intake.seq, label: label, kind: kind, state: "queued", steps: [] };
    for (var k in (extra || {})) it[k] = extra[k];
    intake.items.push(it);
    return it;
  }

  function intakeApply(it, res) {
    it.state = res.status || "failed";
    it.steps = res.steps || [];
    it.pmid = res.pmid || it.pmid || null;
    it.title = res.title || null;
    it.error = res.error || null;
    it.kind = res.kind || it.kind;
  }

  function intakeFinishedBatch() {
    renderIntake();
    if (intake.items.some(function (i) { return i.touched; })) {
      intake.items.forEach(function (i) { i.touched = false; });
      refreshRows();
    }
  }

  function splitIntakeText(text) {
    return text.split(/[\s,;]+/).map(function (t) { return t.trim(); }).filter(Boolean);
  }

  function submitIntakeText(tokens) {
    if (!LIVE || !tokens.length) return;
    var seen = {};
    var fresh = tokens.filter(function (t) { if (seen[t]) return false; seen[t] = true; return true; });
    var items = fresh.map(function (t) { return intakeAddItem(t, "text"); });
    renderIntake();
    var fulltext = document.getElementById("intake-fulltext").checked;
    items.forEach(function (i) { i.state = "running"; });
    renderIntake();
    apiFetch("/api/intake", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items: fresh, fulltext: fulltext }),
    }).then(function (r) { return r.json().then(function (b) { return { ok: r.ok, body: b }; }); })
      .then(function (out) {
        if (!out.ok) throw new Error(out.body && out.body.error || "intake refused");
        pollIntakeJob(out.body.job_id, items);
      })
      .catch(function (err) {
        items.forEach(function (i) { i.state = "failed"; i.error = String(err.message || err); });
        renderIntake();
      });
  }

  function pollIntakeJob(jobId, items) {
    var byInput = {};
    items.forEach(function (i) { byInput[i.label] = i; });
    var tick = function () {
      fetchJSON("/api/jobs/" + jobId).then(function (job) {
        (job.results || []).forEach(function (res) {
          var it = byInput[res.input];
          if (!it || it.state !== "running") return;
          intakeApply(it, res);
          it.touched = res.status === "done";
        });
        if (job.state === "running") { renderIntake(); setTimeout(tick, 900); return; }
        if (job.state === "failed") items.forEach(function (i) { if (i.state === "running") { i.state = "failed"; i.error = job.error || "job failed"; } });
        intakeFinishedBatch();
      }).catch(function (err) {
        items.forEach(function (i) { if (i.state === "running") { i.state = "failed"; i.error = describeFetchError(err); } });
        renderIntake();
      });
    };
    setTimeout(tick, 500);
  }

  var intakePdfQueue = [];
  var intakePdfBusy = false;

  function submitIntakeFiles(files) {
    if (!LIVE) return;
    Array.prototype.forEach.call(files, function (f) {
      var it = intakeAddItem(f.name || "upload.pdf", "pdf", { file: f });
      intakePdfQueue.push(it);
    });
    renderIntake();
    drainIntakePdfs();
  }

  function drainIntakePdfs() {
    if (intakePdfBusy) return;
    var it = intakePdfQueue.shift();
    if (!it) { intakeFinishedBatch(); return; }
    intakePdfBusy = true;
    uploadIntakePdf(it, {}, function () { intakePdfBusy = false; drainIntakePdfs(); });
  }

  function uploadIntakePdf(it, opts, done) {
    opts = opts || {};
    it.state = "running";
    it.steps = [];
    it.error = null;
    renderIntake();
    var finish = function () { renderIntake(); if (done) done(); else intakeFinishedBatch(); };
    validatePdfFile(it.file).then(function (problem) {
      if (problem) { it.state = "failed"; it.error = problem; finish(); return; }
      var qs = [];
      if (opts.pmid) qs.push("pmid=" + encodeURIComponent(opts.pmid));
      if (opts.replace) qs.push("replace=1");
      if (opts.force) qs.push("force=1");
      var xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/intake/pdf" + (qs.length ? "?" + qs.join("&") : ""));
      xhr.setRequestHeader("X-Ref-Token", TOKEN);
      xhr.setRequestHeader("Content-Type", "application/pdf");
      xhr.setRequestHeader("X-Filename", encodeURIComponent(it.file.name || "upload.pdf"));
      xhr.upload.onprogress = function (e) {
        if (e.lengthComputable) { it.steps = ["uploading " + Math.round(e.loaded / e.total * 100) + "%"]; renderIntake(); }
      };
      xhr.upload.onload = function () { it.steps = ["identifying…"]; renderIntake(); };
      xhr.onerror = function () { it.state = "failed"; it.error = "upload failed -- is the dashboard server still running?"; finish(); };
      xhr.onload = function () {
        var body = {};
        try { body = JSON.parse(xhr.responseText || "{}"); } catch (e) { /* keep {} */ }
        if (!body.status) { it.state = "failed"; it.error = body.error || ("http " + xhr.status); finish(); return; }
        intakeApply(it, body);
        it.touched = body.status === "done";
        finish();
      };
      xhr.send(it.file);
    });
  }

  (function initIntake() {
    var panel = document.getElementById("intake");
    var zone = document.getElementById("intake-zone");
    var form = document.getElementById("intake-form");
    var text = document.getElementById("intake-text");
    if (!LIVE) {
      panel.setAttribute("data-static", "true");
      document.getElementById("intake-static").hidden = false;
      intakeCaption();
      return;
    }
    intakeCaption();
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var tokens = splitIntakeText(text.value);
      if (!tokens.length) return;
      text.value = "";
      submitIntakeText(tokens);
    });
    zone.addEventListener("click", function () {
      var input = el("input", { attrs: { type: "file", accept: "application/pdf,.pdf", multiple: "multiple", hidden: "hidden" } });
      input.addEventListener("change", function () { if (input.files && input.files.length) submitIntakeFiles(input.files); input.remove(); });
      document.body.appendChild(input);
      input.click();
    });
    zone.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); zone.click(); } });
    var dragDepth = 0;
    panel.addEventListener("dragenter", function (e) { e.preventDefault(); dragDepth++; panel.classList.add("dragging"); });
    panel.addEventListener("dragover", function (e) { e.preventDefault(); });
    panel.addEventListener("dragleave", function () { if (--dragDepth <= 0) { dragDepth = 0; panel.classList.remove("dragging"); } });
    panel.addEventListener("drop", function (e) {
      e.preventDefault();
      dragDepth = 0;
      panel.classList.remove("dragging");
      var dt = e.dataTransfer;
      if (!dt) return;
      if (dt.files && dt.files.length) { submitIntakeFiles(dt.files); return; }
      var dropped = dt.getData("text/uri-list") || dt.getData("text/plain") || "";
      var tokens = splitIntakeText(dropped).filter(function (t) { return !/^#/.test(t); });
      if (tokens.length) submitIntakeText(tokens);
    });
    document.getElementById("intake-clear").addEventListener("click", function () {
      intake.items = intake.items.filter(function (i) { return i.state !== "done" && i.state !== "exists"; });
      renderIntake();
    });
  })();

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
            else if (key === "matrix" && res.value) setMatrix(res.value);
          } else {
            failed.push(describeFetchError(res.reason));
          }
        });
        loadedDetails = {};
        maintRendered = false;
        INSIGHTS.invalidate();
        renderAll();
        loadHealth();
        loadTriages().then(function () { if (activeTab === "triage") loadTriageView(); });
        loadProjects();
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
      if (results[3]) setMatrix(results[3]);
      SUMMARY = results[4];
      clearError();
      renderAll();
      showSection("library", { silent: true });
      applyViewState(decodeViewState(location.search));
      urlSyncEnabled = true;
      syncUrl();
      loadHealth();
      var addBtn = document.getElementById("btn-add");
      if (addBtn) addBtn.hidden = false; // D3: intake is hidden in static mode, shown once live data confirms we're serving
      var wantTriage = triageFromHash();
      loadTriages(wantTriage).then(function () {
        // §5 risk / plan §3.5: a legacy `#triage/<slug>` link (or --view)
        // resolves to the query's project folder when it's linked, the
        // flat Queries section otherwise -- same query, same single mount.
        if (wantTriage && tri.slug === wantTriage) {
          var found = TRIAGES.filter(function (t) { return t.slug === wantTriage; })[0];
          if (found && found.project) openProjectQuery(found.project, wantTriage);
          else { selectTab("triage"); renderTriageTab(); }
        }
      });
      loadProjects();
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
    showSection("library", { silent: true });
    applyViewState(decodeViewState(location.search));
    urlSyncEnabled = true;
    syncUrl();
  }
})();
