/* /ref:dashboard Insights tab (DASHBOARD_FEATURE_REQUESTS.md FR-09..FR-17,
 * GRAPH_VISUALIZATION_IMPLEMENTATION_PLAN.md Phases 1-5).
 *
 * Split out of app.js, which loads this file first and calls
 * window.RefDashInsights(ctx) once. Everything the tab needs from the rest
 * of the page comes through ctx; rows, the pmid index and the active tab
 * are getters because refresh and tab switches reassign them in app.js.
 * Same rules as app.js: read-only, and untrusted text only ever goes
 * through el()/textContent, never raw HTML injection.
 */
window.RefDashInsights = function (ctx) {
  "use strict";

  var DATA = ctx.DATA, LIVE = ctx.LIVE, state = ctx.state;
  var el = ctx.el, svgEl = ctx.svgEl, clear = ctx.clear, copyText = ctx.copyText, downloadText = ctx.downloadText;
  var fetchJSON = ctx.fetchJSON, describeFetchError = ctx.describeFetchError;
  var filteredRows = ctx.filteredRows, filtersActive = ctx.filtersActive, applyPmidFilter = ctx.applyPmidFilter;
  var openDrawer = ctx.openDrawer, selectTab = ctx.selectTab, syncUrl = ctx.syncUrl;

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
  var knowForce = false; // the refresh button asks the server to bypass its knowledge() memo

  function loadKnowledge() {
    if (KNOW || !LIVE) return Promise.resolve(KNOW);
    if (!knowPromise) {
      knowPromise = fetchJSON("/api/knowledge" + (knowForce ? "?refresh=1" : "")).then(
        function (k) { KNOW = k; knowForce = false; knowPromise = null; return k; },
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
    { id: "maturity", label: "Maturity" },
    { id: "synthesis", label: "Synthesis draft" },
  ];
  var ins = {
    view: "evidence", rowDim: "population", colDim: "outcome", fixDim: "", fixVal: "", color: "direction",
    gapMax: 0, topics: null, metric: "papers", graphMode: "concepts", graphN: 60, zoom: 1, selected: null,
    yfrom: null, yto: null, follow: true, clusterQuery: "", graphCache: null, detail: null,
    center: null, hops: 1, graphView: "graph", tableSort: { key: "degree", dir: "desc" }, focusId: null,
    relHidden: {}, reviewedOnly: false, tierFull: false, selectedRel: null, nbIndex: null, cardCache: null,
    gapView: "grid", gapConcept: "", pan: null, clusterView: "cards", maturitySort: "volume",
    clusterMap: { zoom: 1, pan: null, selected: null, cache: null, focusId: null, sort: { key: "papers", dir: "desc" } },
  };
  var CLAIM_DIMS = {
    population: "Population", intervention: "Intervention", comparator: "Comparator",
    outcome: "Outcome", study_type: "Study design", tier: "Evidence tier",
  };
  var DIR_KEYS = ["up", "down", "null", "other"];
  var DIR_LABEL = { up: "increase", down: "decrease", "null": "no difference", other: "other", mixed: "mixed direction" };
  var DIR_COLOR = { up: "var(--accent)", down: "var(--s-oa)", "null": "var(--faint)", other: "var(--muted)", mixed: "var(--c7)" };
  var PALETTE = ["var(--c1)", "var(--c2)", "var(--c3)", "var(--c4)", "var(--c5)", "var(--c6)", "var(--c7)", "var(--c8)"];
  var MESH_NOISE = new Set([
    "humans", "animals", "male", "female", "adult", "aged", "aged, 80 and over", "middle aged", "young adult",
    "adolescent", "child", "child, preschool", "infant", "infant, newborn", "mice", "rats", "pregnancy",
    "retrospective studies", "prospective studies", "cross-sectional studies", "cohort studies",
    "case-control studies", "follow-up studies", "longitudinal studies", "surveys and questionnaires",
    "treatment outcome", "risk factors", "time factors", "reproducibility of results",
    "sensitivity and specificity", "severity of illness index", "disease models, animal", "cells, cultured",
  ]);


  function insightScope() {
    var base = ins.follow ? filteredRows() : ctx.rows();
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


  function paperButton(pmid) {
    var row = ctx.byPmid()[pmid];
    return el("button", {
      className: "plink", attrs: { type: "button", title: row ? row.title || pmid : pmid },
      text: row ? (row.citekey || pmid) : pmid,
      on: { click: function () { if (ctx.byPmid()[pmid]) openDrawer(pmid); } },
    });
  }

  function paperList(pmids, limit) {
    var ul = el("ul", { className: "ins-papers" });
    var list = Array.from(pmids).sort(function (a, b) {
      var ya = parseInt((ctx.byPmid()[a] || {}).year, 10) || 0, yb = parseInt((ctx.byPmid()[b] || {}).year, 10) || 0;
      return yb - ya || (a < b ? -1 : 1);
    });
    list.slice(0, limit || 25).forEach(function (pmid) {
      var row = ctx.byPmid()[pmid] || {};
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
      var key = rv + "\u0000" + cv;
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
      loadKnowledge().then(function () { if (KNOW && ctx.activeTab() === "insights") renderInsights(); }, function (err) {
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
    renderInsightCards(body, scope);
    ({
      evidence: renderEvidenceMap, gaps: renderGaps, timeline: renderTimeline,
      graph: renderGraph, clusters: renderClusters, maturity: renderMaturity, synthesis: renderSynthesis,
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
        className: "cmdbtn", text: "Copy /ref:query-pubmed", attrs: { type: "button" },
        on: { click: function () { copyText("/ref:query-pubmed '" + q + "' --slug " + slug + " --create"); } },
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
        var cell = m.cells[r.value + "\u0000" + c.value];
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
      var key = c.intervention + "\u0000" + c.outcome;
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
        var cell = m.cells[r.value + "\u0000" + c.value];
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

  function gapsCommand(scope) {
    var pmids = Array.from(scope.pmids);
    return state.project !== "all" && state.project !== "none" && ins.follow
      ? "/ref:gaps --project " + state.project
      : pmids.length <= 50 ? "/ref:gaps " + pmids.join(" ") : "/ref:gaps --project <slug>";
  }

  // Port of gaps.population_outcome_gap(): an intervention concept's own
  // claims are those whose intervention equals its name or an alias
  // (case-insensitive); rows and columns are those claims' populations and
  // outcomes; every uncovered cell is a gap. Claim fields arrive already
  // cleaned by lib_schema.clean_claim_value(), which gaps.py also applies,
  // so placeholders ("not reported", ...) are null on both sides. A
  // population/outcome that exactly matches any concept's name or alias
  // (`concepts`, the registry) is folded onto that concept's name; other
  // values stay as written. Self-contained on purpose --
  // tests/test_phase9_gaps.py runs this function under node against the
  // Python original. popOf/outOf give a claim's folded values.
  function populationOutcomeGaps(claims, concept, concepts) {
    var names = {}, canonical = {};
    [concept.name].concat(concept.aliases || []).forEach(function (n) { names[String(n).toLowerCase()] = true; });
    (concepts || []).forEach(function (c) {
      [c.name].concat(c.aliases || []).forEach(function (t) {
        var k = String(t).toLowerCase();
        if (!Object.prototype.hasOwnProperty.call(canonical, k)) canonical[k] = c.name;
      });
    });
    function fold(v) {
      if (!v) return null;
      var k = String(v).toLowerCase();
      return Object.prototype.hasOwnProperty.call(canonical, k) ? canonical[k] : v;
    }
    function popOf(c) { return fold(c.population); }
    function outOf(c) { return fold(c.outcome); }
    var own = claims.filter(function (c) { return names.hasOwnProperty(String(c.intervention || "").trim().toLowerCase()); });
    var pops = {}, outs = {}, covered = {};
    own.forEach(function (c) {
      if (popOf(c)) pops[popOf(c)] = true;
      if (outOf(c)) outs[outOf(c)] = true;
      covered[JSON.stringify([popOf(c), outOf(c)])] = true;
    });
    var populations = Object.keys(pops).sort(), outcomes = Object.keys(outs).sort();
    var gaps = [];
    populations.forEach(function (p) {
      outcomes.forEach(function (o) {
        if (covered[JSON.stringify([p, o])]) return;
        gaps.push({
          gap_type: "population_outcome_gap", intervention_concept_id: concept.id,
          missing_population: p, missing_outcome: o,
          population_evidenced_by: own.filter(function (c) { return popOf(c) === p; }).map(function (c) { return c.claim_id; }),
          outcome_evidenced_by: own.filter(function (c) { return outOf(c) === o; }).map(function (c) { return c.claim_id; }),
        });
      });
    });
    return { populations: populations, outcomes: outcomes, own: own, gaps: gaps, popOf: popOf, outOf: outOf, fold: fold };
  }

  var GAP_VIEWS = [["grid", "Population × outcome"], ["sparse", "Sparse pairs (heuristic)"]];

  function renderGaps(body, scope) {
    body.appendChild(el("div", { className: "ins-controls" }, [el("div", { className: "d-mode", attrs: { role: "group", "aria-label": "Gap view" } }, GAP_VIEWS.map(function (v) {
      return el("button", {
        text: v[1], attrs: { type: "button", "aria-pressed": String(ins.gapView === v[0]) },
        on: { click: function () { ins.gapView = v[0]; ins.detail = null; renderInsights(); } },
      });
    }))]));
    if (ins.gapView === "grid") renderGapGrid(body, scope); else renderSparsePairs(body, scope);
    renderGapLists(body, scope);
  }

  function renderGapGrid(body, scope) {
    var concepts = (KNOW && KNOW.concepts) || [];
    if (!concepts.length) {
      body.appendChild(el("div", { className: "empty", text: "no concepts in graph/concepts.jsonl yet -- /ref:weave maps claim interventions to concepts, which this grid needs" }));
      return;
    }
    if (!scope.claims.length) { noClaimsNotice(body); return; }
    var options = concepts.map(function (c) { return { c: c, r: populationOutcomeGaps(scope.claims, c, concepts) }; })
      .filter(function (x) { return x.r.own.length; })
      .sort(function (a, b) { return b.r.own.length - a.r.own.length || (a.c.name < b.c.name ? -1 : 1); });
    if (!options.length) {
      body.appendChild(el("div", { className: "empty", text: "no claim's intervention matches a concept name or alias in scope -- map them with /ref:weave or /ref:concept add-alias" }));
      return;
    }
    var chosen = options.filter(function (x) { return x.c.id === ins.gapConcept; })[0] || options[0];
    ins.gapConcept = chosen.c.id;
    var res = chosen.r;
    body.appendChild(el("div", { className: "ins-controls" }, [
      selectControl("Intervention concept", chosen.c.id, options.map(function (x) {
        return [x.c.id, x.c.name + " (" + x.r.own.length + " claims · " + x.r.gaps.length + " gaps)"];
      }), function (v) { ins.gapConcept = v; ins.detail = null; renderInsights(); }),
      el("span", { className: "sub", text: res.populations.length + " populations × " + res.outcomes.length + " outcomes from this intervention's own claims · " +
        res.gaps.length + " uncovered — the same rule as /ref:gaps population_outcome_gap. Values that are a concept's name or alias are shown under that concept." }),
    ]));
    if (!res.populations.length || !res.outcomes.length) {
      body.appendChild(el("div", { className: "empty", text: "these claims don't record both a population and an outcome -- nothing to cross" }));
      return;
    }
    var gapAt = {};
    res.gaps.forEach(function (g) { gapAt[JSON.stringify([g.missing_population, g.missing_outcome])] = g; });
    var table = el("table", { className: "evmap" });
    table.appendChild(el("tr", {}, [el("th", { className: "corner", text: "Population ↓ · Outcome →" })]
      .concat(res.outcomes.map(function (o) { return el("th", { className: "col", attrs: { title: o } }, [el("span", { text: o })]); }))));
    res.populations.forEach(function (p) {
      var tr = el("tr", {}, [el("th", { className: "rowlbl", attrs: { title: p } }, [el("span", { text: p })])]);
      res.outcomes.forEach(function (o) {
        var key = JSON.stringify([p, o]);
        var gap = gapAt[key];
        var cell = null;
        if (!gap) {
          cell = newCell();
          res.own.forEach(function (c) { if (res.popOf(c) === p && res.outOf(c) === o) addToCell(cell, c); });
        }
        var label = p + " × " + o + ": " + (gap ? "gap, no claims" : cell.pmids.size + " papers, " + cell.claims.length + " claims, " + DIR_LABEL[dominantDir(cell.dir)]);
        tr.appendChild(el("td", {}, [el("button", {
          className: "evcell" + (gap ? " hatch" : ""),
          attrs: { type: "button", title: label, "aria-label": label, "aria-pressed": String(!!(ins.detail && ins.detail.po === key)),
            style: gap ? null : "background:color-mix(in srgb," + DIR_COLOR[dominantDir(cell.dir)] + " 55%,transparent)" },
          on: { click: function () { ins.detail = ins.detail && ins.detail.po === key ? null : { po: key }; renderInsights(); } },
        }, [el("span", { className: "ct", text: gap ? "gap" : String(cell.pmids.size) })])]));
      });
      table.appendChild(tr);
    });
    body.appendChild(el("div", { className: "evwrap" }, [table]));
    var legend = el("div", { className: "tri-legend" });
    ["up", "down", "null", "mixed"].forEach(function (k) { legend.appendChild(el("span", {}, [el("i", { attrs: { style: "background:" + DIR_COLOR[k] } }), document.createTextNode(DIR_LABEL[k])])); });
    legend.appendChild(el("span", {}, [el("i", { className: "hatchsw" }), document.createTextNode("gap: population and outcome each studied for this intervention, never together")]));
    body.appendChild(legend);

    if (!ins.detail || !ins.detail.po) return;
    var po = JSON.parse(ins.detail.po), g = gapAt[ins.detail.po];
    var panel = el("div", { className: "panel ins-detail" }, [el("h2", { text: chosen.c.name + ": " + po[0] + " × " + po[1] })]);
    if (g) {
      var byId = {};
      res.own.forEach(function (c) { byId[c.claim_id] = c; });
      panel.appendChild(el("p", { className: "prose", text: "Gap: no claim on " + chosen.c.name + " reports “" + po[1] + "” in “" + po[0] + "”." }));
      panel.appendChild(el("div", { className: "sub", text: "population_evidenced_by: " + g.population_evidenced_by.join(", ") }));
      panel.appendChild(claimTable(g.population_evidenced_by.map(function (id) { return byId[id]; })));
      panel.appendChild(el("div", { className: "sub", text: "outcome_evidenced_by: " + g.outcome_evidenced_by.join(", ") }));
      panel.appendChild(claimTable(g.outcome_evidenced_by.map(function (id) { return byId[id]; })));
      var candidates = new Set(g.population_evidenced_by.concat(g.outcome_evidenced_by).map(function (id) { return byId[id].pmid; }));
      panel.appendChild(gapActions([chosen.c.name, po[0], po[1]], candidates));
      var cmd = gapsCommand(scope) + " --intervention-concept " + chosen.c.id + " --types population_outcome_gap";
      panel.appendChild(el("div", { className: "pcmds" }, [
        el("code", { text: cmd }),
        el("button", { className: "cmdbtn", text: "Copy", attrs: { type: "button" }, on: { click: function () { copyText(cmd); } } }),
      ]));
    } else {
      var claims = res.own.filter(function (c) { return res.popOf(c) === po[0] && res.outOf(c) === po[1]; });
      panel.appendChild(claimTable(claims));
    }
    body.appendChild(panel);
  }

  function renderSparsePairs(body, scope) {
    body.appendChild(matrixControls(scope, [
      selectControl("Show combinations with", String(ins.gapMax), [["0", "no claims"], ["1", "at most one paper"]],
        function (v) { ins.gapMax = parseInt(v, 10); renderInsights(); }),
    ]));
    var claims = fixedClaims(scope);
    if (!claims.length) { noClaimsNotice(body); return; }

    var gaps = findGaps(claims, ins.rowDim, ins.colDim, ins.gapMax).slice(0, 30);
    var sec1 = el("div", { className: "panel" }, [el("h2", {}, [
      document.createTextNode("Sparse " + CLAIM_DIMS[ins.rowDim].toLowerCase() + " × " + CLAIM_DIMS[ins.colDim].toLowerCase() + " combinations (heuristic)"),
      el("span", { text: "score = papers on each side ÷ (1 + papers together); not a /ref:gaps finding" }),
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
  }

  function renderGapLists(body, scope) {
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
        el("span", { className: "dirtag", attrs: { style: "--c:" + relStyle(x.r).stroke }, text: relLabel(x.r) }),
        el("button", {
          className: "plink", text: x.subject + " ↔ " + x.object, attrs: { type: "button", title: "Show in the claim network" },
          on: { click: function () {
            ins.view = "graph"; ins.graphMode = "claims"; ins.selected = null; ins.selectedRel = x.r.id;
            ins.relHidden = {}; ins.reviewedOnly = false; renderInsights(); syncUrl();
          } },
        }),
      ].concat(x.r.pmids.slice(0, 6).map(paperButton))));
    });
    sec3.appendChild(ul3);

    var gapsCmd = gapsCommand(scope);
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
        var y = parseInt((ctx.byPmid()[p] || {}).year, 10);
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
        return { a: e.a, b: e.b, w: e.cell.pmids.size, kind: e.kind, cell: e.cell, mixed: e.kind === "io" && e.cell.dir.up > 0 && e.cell.dir.down > 0 };
      });
      // A relation joins the claim-value nodes its concepts name, through
      // the concept's name or any alias (intervention first, then outcome,
      // then population).
      var terms = {};
      ((KNOW && KNOW.concepts) || []).forEach(function (c) {
        terms[c.id] = [c.name].concat(c.aliases || []).map(function (a) { return String(a).toLowerCase(); });
      });
      var find = function (cid) {
        var names = terms[cid] || [];
        var prefixes = ["i:", "o:", "p:"];
        for (var pi = 0; pi < prefixes.length; pi++) {
          for (var ni = 0; ni < names.length; ni++) if (have[prefixes[pi] + names[ni]]) return prefixes[pi] + names[ni];
        }
        return null;
      };
      relationsInScope(scope).filter(relationVisible).forEach(function (r) {
        var a = find(r.subject), b = find(r.object);
        if (a && b && a !== b) edges.push({ a: a, b: b, w: r.pmids.length || 1, kind: "rel", rel: r });
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
        var row = ctx.byPmid()[p] || {};
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

  // ------------------------------------ neighborhood (graph plan Phase 1)
  //
  // One paper or concept and what it touches, 1 or 2 hops out. Concept
  // nodes are registry concepts only (graph/concepts.jsonl), matched
  // through their names and aliases exactly as topicIndex() folds terms;
  // unmapped MeSH terms and claim values stay in the Concepts mode.
  // Relation edges are the recorded concept <-> concept relations, never
  // re-derived here.

  var NB_CAP = 100;
  var KIND_RANK = { concept: 0, paper: 1, author: 2, claim: 3 };
  var DIR_GLYPH = { up: "↑", down: "↓", "null": "→", other: "·" };

  function conceptAliasIndex() {
    var idx = {};
    ((KNOW && KNOW.concepts) || []).forEach(function (c) {
      [c.name].concat(c.aliases || []).forEach(function (a) {
        var k = normWords(a).trim();
        if (k.length >= 3) idx[k] = c;
      });
    });
    return idx;
  }

  function conceptNames() {
    var names = {};
    ((KNOW && KNOW.concepts) || []).forEach(function (c) { names[c.id] = c.name; });
    return names;
  }

  function relationsInScope(scope) {
    return ((KNOW && KNOW.relations) || []).filter(function (r) {
      return !r.pmids.length || r.pmids.some(function (p) { return scope.pmids.has(p); });
    });
  }

  function relationVisible(r) {
    return !ins.relHidden[r.type] && (!ins.reviewedOnly || r.review_state === "reviewed");
  }

  function claimLabel(c) {
    return (c.intervention || "?") + " → " + (c.outcome || "?") + " " + (DIR_GLYPH[c.dir] || DIR_GLYPH.other);
  }

  function supportingClaims(rel) {
    var want = new Set((rel.supporting || []).map(function (sc) { return sc.pmid + "/" + sc.claim_id; }));
    return ((KNOW && KNOW.claims) || []).filter(function (c) { return want.has(c.pmid + "/" + c.claim_id); });
  }

  function scopeKey(scope) {
    return scope.claims.length + "|" + Array.from(scope.pmids).join(",");
  }

  // The whole paper / concept / author / claim graph for the scope, built
  // once per scope and reused by every neighborhood and the insight cards.
  function neighborhoodIndex(scope) {
    var key = scopeKey(scope);
    if (ins.nbIndex && ins.nbIndex.key === key && ins.nbIndex.know === KNOW) return ins.nbIndex;
    var aliases = conceptAliasIndex(), aliasKeys = Object.keys(aliases);
    var info = {}, adj = {}, rels = {}, via = {};
    function node(id, props) {
      if (!info[id]) { props.pmids = props.pmids || new Set(); info[id] = props; adj[id] = {}; }
      return id;
    }
    function link(a, b, kind) {
      if (adj[a][b] === "relation") return;
      adj[a][b] = kind;
      adj[b][a] = kind;
    }
    // a claim <-> concept link that exists only because a relation lists
    // the claim; kept with its relations so hiding them hides the link
    function relLink(k, cid, r) {
      if (adj[k][cid] && adj[k][cid] !== "supports-claim") return;
      link(k, cid, "supports-claim");
      var key = pairKey(k, cid);
      (via[key] = via[key] || []).push(r);
    }
    function concept(label) {
      var c = label && aliases[normWords(label).trim()];
      return c ? node("c:" + c.id, { kind: "concept", label: c.name }) : null;
    }
    scope.rows.forEach(function (r) {
      var p = node("p:" + r.pmid, { kind: "paper", label: r.citekey || r.pmid, title: r.title, pmids: new Set([r.pmid]) });
      var paper = scope.papers[r.pmid] || {};
      function mention(cid) {
        if (!cid) return;
        link(p, cid, "mentions");
        info[cid].pmids.add(r.pmid);
      }
      (paper.mesh || []).forEach(function (m) { mention(concept(m)); });
      var title = normWords(r.title);
      aliasKeys.forEach(function (a) { if (title.indexOf(" " + a + " ") >= 0) mention(concept(a)); });
      (paper.authors || []).forEach(function (name) {
        var a = node("a:" + name, { kind: "author", label: name });
        info[a].pmids.add(r.pmid);
        link(p, a, "authored");
      });
    });
    scope.claims.forEach(function (c) {
      var p = "p:" + c.pmid;
      if (!info[p]) return;
      var k = node("k:" + c.pmid + "/" + c.claim_id, { kind: "claim", label: claimLabel(c), claim: c, pmids: new Set([c.pmid]) });
      link(p, k, "reports");
      ["intervention", "outcome", "population"].forEach(function (f) {
        var cid = concept(c[f]);
        if (!cid) return;
        link(k, cid, "about");
        link(p, cid, "mentions");
        info[cid].pmids.add(c.pmid);
      });
    });
    var names = conceptNames();
    relationsInScope(scope).forEach(function (r) {
      if (!r.subject || !r.object || r.subject === r.object) return;
      var a = node("c:" + r.subject, { kind: "concept", label: names[r.subject] || r.subject });
      var b = node("c:" + r.object, { kind: "concept", label: names[r.object] || r.object });
      adj[a][b] = adj[b][a] = "relation";
      var pair = pairKey(a, b);
      (rels[pair] = rels[pair] || []).push(r);
      supportingClaims(r).forEach(function (c) {
        var k = "k:" + c.pmid + "/" + c.claim_id;
        if (!info[k]) return;
        relLink(k, a, r);
        relLink(k, b, r);
      });
    });
    ins.nbIndex = { key: key, know: KNOW, info: info, adj: adj, rels: rels, via: via };
    return ins.nbIndex;
  }

  // A paper's connectivity: registry concepts it mentions and other papers
  // sharing at least one author. Claims are left out so heavily extracted
  // papers don't win by claim count alone.
  function paperLinks(idx, pid) {
    // memoised on the index: the centre picker sorts every paper by this
    var memo = idx.links || (idx.links = {});
    if (memo[pid]) return memo[pid];
    var concepts = 0, coauthored = new Set();
    Object.keys(idx.adj[pid] || {}).forEach(function (n) {
      var kind = idx.info[n].kind;
      if (kind === "concept") concepts++;
      if (kind === "author") Object.keys(idx.adj[n]).forEach(function (q) { if (q !== pid) coauthored.add(q); });
    });
    return (memo[pid] = { concepts: concepts, coauthored: coauthored.size, total: concepts + coauthored.size });
  }

  function pairKey(a, b) {
    return a < b ? a + "\u0000" + b : b + "\u0000" + a;
  }

  // The visible link kind between two index nodes, or null when every
  // relation behind it is hidden by the legend toggles / "reviewed only".
  function visibleLink(idx, a, b) {
    var kind = idx.adj[a][b];
    if (kind === "relation") return (idx.rels[pairKey(a, b)] || []).some(relationVisible) ? kind : null;
    if (kind === "supports-claim") return (idx.via[pairKey(a, b)] || []).some(relationVisible) ? kind : null;
    return kind || null;
  }

  function buildNeighborhood(scope, centerId, hops) {
    return neighborhoodGraph(neighborhoodIndex(scope), centerId, hops);
  }

  function neighborhoodGraph(idx, centerId, hops) {
    if (!idx.info[centerId]) return { nodes: [], edges: [], adj: {}, missing: true };
    var hop = {};
    hop[centerId] = 0;
    var order = [centerId], frontier = [centerId], dropped = 0;
    for (var h = 1; h <= hops; h++) {
      var cand = {};
      frontier.forEach(function (id) {
        Object.keys(idx.adj[id]).forEach(function (n) { if (!hop.hasOwnProperty(n) && visibleLink(idx, id, n)) cand[n] = (cand[n] || 0) + 1; });
      });
      var ids = Object.keys(cand).sort(function (a, b) {
        return cand[b] - cand[a] || KIND_RANK[idx.info[a].kind] - KIND_RANK[idx.info[b].kind] ||
          idx.info[b].pmids.size - idx.info[a].pmids.size || (a < b ? -1 : 1);
      });
      var room = NB_CAP - order.length;
      if (ids.length > room) { dropped += ids.length - room; ids = ids.slice(0, room); }
      ids.forEach(function (n) { hop[n] = h; order.push(n); });
      frontier = ids;
    }
    var nodes = order.map(function (id) {
      var x = idx.info[id];
      return { id: id, label: x.label, title: x.title, kind: x.kind, size: Math.max(1, x.pmids.size), pmids: x.pmids, hop: hop[id], claim: x.claim };
    });
    var edges = [];
    for (var i = 0; i < order.length; i++) {
      for (var j = i + 1; j < order.length; j++) {
        var a = order[i], b = order[j], kind = visibleLink(idx, a, b);
        if (!kind) continue;
        if (kind === "relation") {
          idx.rels[pairKey(a, b)].filter(relationVisible).forEach(function (r) {
            edges.push({ a: "c:" + r.subject, b: "c:" + r.object, w: 1, kind: "rel", rel: r });
          });
        } else {
          edges.push({ a: a, b: b, w: 1, kind: kind });
        }
      }
    }
    var adj = {};
    nodes.forEach(function (n) { adj[n.id] = {}; });
    edges.forEach(function (e) {
      adj[e.a][e.b] = (adj[e.a][e.b] || 0) + e.w;
      adj[e.b][e.a] = (adj[e.b][e.a] || 0) + e.w;
    });
    return { nodes: nodes, edges: edges, adj: adj, capped: dropped > 0, dropped: dropped };
  }

  // Centre, hop-1 ring, hop-2 ring. Hop-2 nodes sit at the mean angle of
  // their hop-1 parents so spokes don't cross; O(n log n), no iteration.
  function radialLayout(nodes, edges, centerId, W, H) {
    var pos = {}, rings = [], hopOf = {}, angle = {}, nb = {};
    nodes.forEach(function (n) { hopOf[n.id] = n.hop; (rings[n.hop] = rings[n.hop] || []).push(n); });
    edges.forEach(function (e) { (nb[e.a] = nb[e.a] || []).push(e.b); (nb[e.b] = nb[e.b] || []).push(e.a); });
    pos[centerId] = { x: W / 2, y: H / 2 };
    angle[centerId] = 0;
    var maxHop = rings.length - 1;
    for (var h = 1; h <= maxHop; h++) {
      var ring = rings[h] || [];
      ring.forEach(function (n) {
        var sx = 0, sy = 0;
        (nb[n.id] || []).forEach(function (m) { if (hopOf[m] === h - 1) { sx += Math.cos(angle[m]); sy += Math.sin(angle[m]); } });
        n._a = h === 1 ? KIND_RANK[n.kind] : Math.atan2(sy, sx);
      });
      ring.sort(function (a, b) { return a._a - b._a || (a.label < b.label ? -1 : a.label > b.label ? 1 : 0); });
      var rx = (W / 2 - 70) * h / maxHop, ry = (H / 2 - 30) * h / maxHop;
      ring.forEach(function (n, i) {
        var a = -Math.PI / 2 + 2 * Math.PI * (i + (h % 2 ? 0 : 0.5)) / ring.length;
        angle[n.id] = a;
        pos[n.id] = { x: W / 2 + rx * Math.cos(a), y: H / 2 + ry * Math.sin(a) };
        delete n._a;
      });
    }
    return pos;
  }

  // The neighborhood id a graph node can be centred on, or null.
  function centerIdFor(n) {
    if (n.kind === "paper") return "p:" + Array.from(n.pmids)[0];
    if (n.kind === "claim") return "p:" + n.claim.pmid;
    if (n.id.indexOf("c:") === 0 && n.kind === "concept") return n.id;
    var c = conceptAliasIndex()[normWords(n.label).trim()];
    return c ? "c:" + c.id : null;
  }

  function showInGraph(centerId) {
    ins.view = "graph";
    ins.graphMode = "neighborhood";
    ins.center = centerId;
    ins.selected = null;
    ins.selectedRel = null;
    ins.zoom = 1;
    ins.pan = null;
    selectTab("insights");
    renderInsights();
    syncUrl();
  }

  // ------------------------------------------ graph encoding (Phases 1-2)

  var KIND_COLOR = {
    paper: "var(--s-abs)", author: "var(--s-oa)", concept: "var(--accent)", mesh: "var(--s-full)",
    intervention: "var(--accent)", outcome: "var(--s-oa)", population: "var(--c5)", claim: "var(--c3)",
  };
  var KIND_LEGEND = [["concept", "concept (size = papers)"], ["paper", "paper"], ["author", "author (ring)"], ["claim", "claim (diamond)"]];
  var REL_TYPES = ["supports", "replicates", "extends", "potential_conflict", "contradicts"];
  var REL_STYLE = {
    supports: { stroke: "var(--good)", width: 2 },
    replicates: { stroke: "var(--good)", width: 1.4, double: true },
    extends: { stroke: "var(--c5)", width: 2 },
    potential_conflict: { stroke: "var(--warn)", width: 2.2, dash: "6 4" },
    contradicts: { stroke: "var(--crit)", width: 2.8 },
  };
  var REL_GLYPH = { supports: "+", replicates: "=", extends: "»", potential_conflict: "?", contradicts: "✕" };
  var EDGE_KIND_LABEL = {
    co: "co-occurs", pt: "mentions", pa: "authored", pi: "population → intervention",
    mentions: "mentions", authored: "authored", reports: "reports", about: "claim about", "supports-claim": "supporting claim",
    shared: "shared papers",
  };

  function relLabel(r) {
    return String(r.type).replace(/_/g, " ") + " — " + (r.review_state === "reviewed" ? "reviewed" : "unreviewed") + (r.stale ? " · stale" : "");
  }

  function relStyle(r) {
    var st = REL_STYLE[r.type] || { stroke: "var(--muted)", width: 1.6 };
    return { stroke: st.stroke, width: st.width, dash: st.dash, double: st.double, opacity: r.stale ? 0.35 : 0.9 };
  }

  function edgeLabel(e) {
    if (e.kind === "rel") return relLabel(e.rel);
    if (e.kind === "io") return "intervention → outcome · " + (e.mixed ? "mixed direction" : DIR_LABEL[dominantDir(e.cell.dir)]);
    return EDGE_KIND_LABEL[e.kind] || e.kind;
  }

  function edgePapers(e) {
    return e.cell ? e.cell.pmids.size : e.rel ? e.rel.pmids.length : e.w;
  }

  function nodeColor(n) {
    if (ins.graphMode === "concepts") return n.cluster >= 0 ? PALETTE[n.cluster % PALETTE.length] : "var(--faint)";
    return KIND_COLOR[n.kind] || "var(--muted)";
  }

  function edgeStyle(e) {
    if (e.kind === "rel") return relStyle(e.rel);
    if (e.kind === "io") {
      if (e.mixed) return { stroke: DIR_COLOR.mixed, width: 1 + Math.min(4, e.w), dash: "1 4", opacity: 0.9 };
      return { stroke: DIR_COLOR[dominantDir(e.cell.dir)], width: 1 + Math.min(4, e.w), opacity: 0.7 };
    }
    if (e.kind === "pi" || e.kind === "reports" || e.kind === "authored" || e.kind === "about") return { stroke: "var(--line)", width: 1, opacity: 0.9 };
    if (e.kind === "supports-claim") return { stroke: "var(--good)", width: 1, dash: "2 3", opacity: 0.7 };
    return { stroke: "var(--faint)", width: Math.min(4, 0.6 + Math.log(1 + e.w)), opacity: 0.45 };
  }

  function legendLine(st) {
    var s = svgEl("svg", { viewBox: "0 0 26 10", class: "lsw", "aria-hidden": "true" });
    (st.double ? [3, 7] : [5]).forEach(function (y) {
      s.appendChild(svgEl("line", { x1: 1, x2: 25, y1: y, y2: y, stroke: st.stroke, "stroke-width": Math.min(st.width, 2.4), "stroke-dasharray": st.dash || "none", "stroke-opacity": st.opacity || 1 }));
    });
    return s;
  }

  // Legend with per-relation-type toggles and the "reviewed only" filter.
  function relationLegend(counts) {
    var wrap = el("div", { className: "tri-legend rel-legend", attrs: { role: "group", "aria-label": "Relation types" } });
    REL_TYPES.forEach(function (t) {
      var shown = !ins.relHidden[t];
      wrap.appendChild(el("button", {
        className: "reltoggle", attrs: { type: "button", "aria-pressed": String(shown), title: (shown ? "Hide " : "Show ") + t.replace(/_/g, " ") + " relations" },
        on: { click: function () { ins.relHidden[t] = shown; ins.selectedRel = null; renderInsights(); } },
      }, [legendLine(relStyle({ type: t })), document.createTextNode(REL_GLYPH[t] + " " + (t === "potential_conflict" ? "potential conflict — unreviewed" : t === "contradicts" ? "contradicts — reviewed" : t) + " (" + (counts[t] || 0) + ")")]));
    });
    wrap.appendChild(el("span", {}, [legendLine({ stroke: "var(--muted)", width: 2, opacity: 0.35 }), document.createTextNode("faded = stale")]));
    var cb = el("input", { attrs: { type: "checkbox" } });
    cb.checked = ins.reviewedOnly;
    cb.addEventListener("change", function () { ins.reviewedOnly = cb.checked; ins.selectedRel = null; renderInsights(); });
    wrap.appendChild(el("label", {}, [cb, document.createTextNode(" reviewed only")]));
    return wrap;
  }

  function relationDetail(rel) {
    var names = conceptNames();
    var subj = names[rel.subject] || rel.subject, obj = names[rel.object] || rel.object;
    var wrap = el("div", { className: "reldetail" });
    wrap.appendChild(el("h2", {}, [document.createTextNode("Relation"), el("button", {
      className: "cmdbtn", text: "Clear", attrs: { type: "button" }, on: { click: function () { ins.selectedRel = null; renderInsights(); } },
    })]));
    wrap.appendChild(el("b", { className: "gtitle", text: subj + "  " + (REL_GLYPH[rel.type] || "–") + "  " + obj }));
    wrap.appendChild(el("div", {}, [
      el("span", { className: "dirtag", attrs: { style: "--c:" + relStyle(rel).stroke }, text: relLabel(rel) }),
    ]));
    var facts = el("ul", { className: "ins-list" }, [
      el("li", {}, [el("small", { text: "id" }), el("code", { text: rel.id })]),
      el("li", {}, [el("small", { text: "review" }), el("span", { text: rel.review_state === "reviewed" ? "reviewed" + (rel.reviewed_at ? " " + String(rel.reviewed_at).slice(0, 10) : "") : "unreviewed" })]),
      el("li", {}, [el("small", { text: "rationale" }), el("span", { text: rel.rationale || "none recorded" })]),
    ]);
    if (rel.stale) facts.appendChild(el("li", {}, [el("small", { text: "stale" }), el("span", { text: "a supporting claim is no longer active -- the review needs reconfirming" })]));
    wrap.appendChild(facts);
    if (rel.type === "potential_conflict") {
      wrap.appendChild(el("p", { className: "sub", text: "Opposite directions under matching comparator, effect measure, timepoint and population. Only a review with a rationale turns this into a contradiction." }));
    }
    wrap.appendChild(el("div", { className: "pcmds" }, [
      el("button", { className: "cmdbtn", text: "Center on " + subj, attrs: { type: "button" }, on: { click: function () { showInGraph("c:" + rel.subject); } } }),
      el("button", { className: "cmdbtn", text: "Center on " + obj, attrs: { type: "button" }, on: { click: function () { showInGraph("c:" + rel.object); } } }),
    ]));

    var claims = supportingClaims(rel);
    wrap.appendChild(el("h2", { text: "Supporting claims (" + claims.length + (rel.claim_ids && rel.claim_ids.length !== claims.length ? " of " + rel.claim_ids.length + " still active" : "") + ")" }));
    if (claims.length) wrap.appendChild(comparabilityList(claims));
    wrap.appendChild(el("div", { className: "pcmds" }, rel.pmids.slice(0, 8).map(paperButton).concat(rel.pmids.length ? [el("button", {
      className: "cmdbtn", text: "Papers (" + rel.pmids.length + ")", attrs: { type: "button" },
      on: { click: function () { applyPmidFilter("relation: " + subj + " – " + obj, rel.pmids); } },
    })] : [])));

    if (rel.review_state !== "reviewed" || rel.stale) {
      var cmd = "/ref:weave review " + rel.id + " <type> --rationale \"…\"";
      wrap.appendChild(el("h2", { text: rel.stale ? "Reconfirm" : "Review" }));
      wrap.appendChild(el("div", { className: "pcmds" }, [
        el("code", { text: cmd }),
        el("button", { className: "cmdbtn", text: "Copy", attrs: { type: "button" }, on: { click: function () { copyText(cmd); } } }),
      ]));
      wrap.appendChild(el("p", { className: "sub", text: "<type>: " + REL_TYPES.join(" / ") + ". contradicts requires a rationale." }));
    }
    return wrap;
  }

  // Supporting claims on the fields relation.comparable() checks, one block
  // per claim so it fits the side panel; a value that differs across the
  // claims (or is missing on any) is marked ≠.
  function comparabilityList(claims) {
    var fields = [["direction", "direction"], ["population", "population"], ["comparator", "comparator"], ["timepoint", "timepoint"], ["effect", "effect measure"]];
    var differs = {};
    fields.forEach(function (f) {
      var vals = new Set(claims.map(function (c) { return String(c[f[0]] || "").toLowerCase(); }));
      differs[f[0]] = vals.size > 1 || vals.has("");
    });
    return el("div", { className: "complist" }, claims.map(function (c) {
      return el("div", { className: "conflict" }, [
        el("div", {}, [paperButton(c.pmid), el("small", { text: " " + claimLabel(c) })]),
        el("dl", { className: "compfields" }, [].concat.apply([], fields.map(function (f) {
          return [
            el("dt", { text: f[1] }),
            el("dd", { className: differs[f[0]] ? "differs" : "", attrs: { title: differs[f[0]] ? "differs across the supporting claims" : "same in every supporting claim" },
              text: (c[f[0]] || "not reported") + (differs[f[0]] ? " ≠" : "") }),
          ];
        }))),
      ]);
    }));
  }

  // Graph / Table toggle: the same nodes and edges as text (Phase 1). o:
  // selected, showHop, sort ({key, dir}), onSort(sort), onSelect(id), onRel(id).
  function renderGraphTable(graph, byId, o) {
    var wrap = el("div", { className: "panel gtable" });
    var deg = {};
    graph.nodes.forEach(function (n) { deg[n.id] = Object.keys(graph.adj[n.id] || {}).length; });
    var s = o.sort;
    var cols = [["label", "Node"], ["kind", "Type"], ["papers", "Papers"], ["degree", "Degree"]];
    if (o.showHop) cols.push(["hop", "Hop"]);
    var val = {
      label: function (n) { return n.label.toLowerCase(); }, kind: function (n) { return n.kind; },
      papers: function (n) { return n.size; }, degree: function (n) { return deg[n.id]; }, hop: function (n) { return n.hop; },
    };
    var rows = graph.nodes.slice().sort(function (a, b) {
      var va = val[s.key](a), vb = val[s.key](b);
      var c = va < vb ? -1 : va > vb ? 1 : 0;
      return (s.dir === "asc" ? c : -c) || (a.label < b.label ? -1 : 1);
    });
    var head = el("tr", {}, cols.map(function (c) {
      var num = c[0] !== "label" && c[0] !== "kind";
      return el("th", { className: num ? "num" : "", attrs: { "aria-sort": s.key === c[0] ? (s.dir === "asc" ? "ascending" : "descending") : "none" } }, [el("button", {
        className: "plink", text: c[1] + (s.key === c[0] ? (s.dir === "asc" ? " ▲" : " ▼") : ""), attrs: { type: "button" },
        on: { click: function () { o.onSort({ key: c[0], dir: s.key === c[0] && s.dir === "desc" ? "asc" : num ? "desc" : "asc" }); } },
      })]);
    }));
    var nodeTable = el("table", { className: "ins-table", attrs: { "aria-label": "Graph nodes" } }, [head]);
    rows.forEach(function (n) {
      nodeTable.appendChild(el("tr", { className: o.selected === n.id ? "sel" : "" }, [
        el("td", {}, [el("button", {
          className: "plink", text: n.label, attrs: { type: "button", title: n.title || n.label, "aria-pressed": String(o.selected === n.id) },
          on: { click: function () { o.onSelect(n.id); } },
        })]),
        el("td", { text: n.kind }),
        el("td", { className: "num", text: String(n.size) }),
        el("td", { className: "num", text: String(deg[n.id]) }),
      ].concat(o.showHop ? [el("td", { className: "num", text: String(n.hop) })] : [])));
    });
    wrap.appendChild(el("h2", {}, [document.createTextNode("Nodes"), el("span", { text: graph.nodes.length + "" })]));
    wrap.appendChild(el("div", { className: "tablewrap ins-tablewrap" }, [nodeTable]));

    var edgeTable = el("table", { className: "ins-table", attrs: { "aria-label": "Graph edges" } }, [el("tr", {}, [
      el("th", { text: "From" }), el("th", { text: "To" }), el("th", { text: "Kind" }), el("th", { className: "num", text: "Papers" }),
    ])]);
    graph.edges.slice().sort(function (a, b) { return edgePapers(b) - edgePapers(a); }).forEach(function (e) {
      edgeTable.appendChild(el("tr", {}, [
        el("td", { text: byId[e.a].label }), el("td", { text: byId[e.b].label }),
        el("td", {}, e.rel && o.onRel ? [el("button", {
          className: "plink", text: edgeLabel(e), attrs: { type: "button" },
          on: { click: function () { o.onRel(e.rel.id); } },
        })] : [document.createTextNode(edgeLabel(e))]),
        el("td", { className: "num", text: String(edgePapers(e)) }),
      ]));
    });
    wrap.appendChild(el("h2", {}, [document.createTextNode("Edges"), el("span", { text: graph.edges.length + "" })]));
    wrap.appendChild(el("div", { className: "tablewrap ins-tablewrap" }, [edgeTable]));
    return wrap;
  }

  // ------------------------------------------------ interactive SVG graph
  //
  // Shared by the knowledge graph and the cluster map. Nodes drag with the
  // mouse, pen or a finger; positions are written back into the cached
  // layout, so they survive re-renders until the layout is rebuilt
  // ("Re-layout"). The background pans with a mouse, ⌘/Ctrl + wheel (or a
  // trackpad pinch) zooms around the pointer, and Shift + arrow keys move a
  // focused node. A press that moves less than DRAG_SLOP px is a click.

  var DRAG_SLOP = 4, NUDGE = 12;

  function setAttrs(node, attrs) {
    Object.keys(attrs).forEach(function (k) { node.setAttribute(k, attrs[k]); });
  }

  function makeShape(n, color, r) {
    if (n.kind === "author") {
      return svgEl("circle", { class: "shape", r: Math.max(5, r - 1), fill: "var(--panel)", stroke: color, "stroke-width": 2.5 });
    }
    if (n.kind === "claim") return svgEl("polygon", { class: "shape", fill: color, stroke: "var(--panel)", "stroke-width": 1.5 });
    return svgEl("circle", { class: "shape", r: r, fill: color, stroke: "var(--panel)", "stroke-width": 1.5 });
  }

  function placeShape(shape, n, p, r) {
    if (n.kind === "claim") {
      var d = Math.max(6, r);
      shape.setAttribute("points", [p.x + "," + (p.y - d), (p.x + d) + "," + p.y, p.x + "," + (p.y + d), (p.x - d) + "," + p.y].join(" "));
    } else {
      setAttrs(shape, { cx: p.x, cy: p.y });
    }
  }

  function placeEdge(rec, pos) {
    var a = pos[rec.e.a], b = pos[rec.e.b];
    var dx = b.x - a.x, dy = b.y - a.y, len = Math.sqrt(dx * dx + dy * dy) || 1;
    rec.lines.forEach(function (line, i) {
      var o = rec.offsets[i], ox = -dy / len * o, oy = dx / len * o;
      setAttrs(line, { x1: a.x + ox, y1: a.y + oy, x2: b.x + ox, y2: b.y + oy });
    });
    if (rec.hit) setAttrs(rec.hit, { x1: a.x, y1: a.y, x2: b.x, y2: b.y });
    if (rec.badge) {
      var off = (rec.offsets[0] + rec.offsets[rec.offsets.length - 1]) / 2;
      var mx = (a.x + b.x) / 2 - dy / len * off, my = (a.y + b.y) / 2 + dx / len * off;
      setAttrs(rec.badge, { cx: mx, cy: my });
      setAttrs(rec.glyph, { x: mx, y: my + 3.8 });
      if (rec.staleTag) setAttrs(rec.staleTag, { x: mx + 10, y: my + 3.5 });
    }
  }

  // o: W, H, view ({zoom, pan} state, mutated), sel, nbrs, selRel, labelled
  // (Set), anchorCenter (labels point away from this node, or null),
  // relShiftStart, ariaLabel, color(n), radius(n, maxSize), classFor(n),
  // ariaExtra(n), onPick(n), onPickRel(rel), focusId.
  function drawGraph(graph, pos, o) {
    var W = o.W, H = o.H, v = o.view, sel = o.sel, nbrs = o.nbrs;
    var byId = {};
    graph.nodes.forEach(function (n) { byId[n.id] = n; });
    var svg = svgEl("svg", { class: "graph", role: "group", "aria-label": o.ariaLabel });
    var box = {};
    function setView(cx, cy) {
      box.w = W / v.zoom;
      box.h = H / v.zoom;
      box.x = Math.max(Math.min(0, W - box.w), Math.min(Math.max(0, W - box.w), cx - box.w / 2));
      box.y = Math.max(Math.min(0, H - box.h), Math.min(Math.max(0, H - box.h), cy - box.h / 2));
      svg.setAttribute("viewBox", box.x + " " + box.y + " " + box.w + " " + box.h);
    }
    var start = v.pan || (sel && pos[sel.id]) || { x: W / 2, y: H / 2 };
    setView(start.x, start.y);
    function toSvg(ev) {
      var m = svg.getScreenCTM();
      if (!m) return null;
      var pt = svg.createSVGPoint();
      pt.x = ev.clientX;
      pt.y = ev.clientY;
      return pt.matrixTransform(m.inverse());
    }

    var byNode = {}, relCount = {};
    graph.edges.forEach(function (e) {
      if (!pos[e.a] || !pos[e.b]) return;
      var st = edgeStyle(e);
      var on = o.selRel ? e.rel === o.selRel : !sel || e.a === sel.id || e.b === sel.id;
      var gEdge = svgEl("g", { class: "gedge" + (e.rel ? " rel" : "") });
      var offsets = st.double ? [-1.8, 1.8] : [0];
      if (e.rel) {
        // parallel relations between one pair fan out instead of overlapping;
        // in the claim network they also clear the intervention -> outcome
        // line drawn on the same pair, so dashes never merge with it
        var pk = e.a < e.b ? e.a + "|" + e.b : e.b + "|" + e.a;
        var nth = relCount[pk] = (relCount[pk] || 0) + 1;
        var shift = (nth - 1 + (o.relShiftStart || 0)) * 6;
        offsets = offsets.map(function (x) { return x + shift; });
      }
      var rec = { e: e, offsets: offsets, lines: offsets.map(function () {
        return gEdge.appendChild(svgEl("line", {
          stroke: st.stroke, "stroke-width": st.width, "stroke-opacity": on ? st.opacity : 0.08, "stroke-dasharray": st.dash || "none",
        }));
      }) };
      if (e.kind === "io" || e.kind === "rel" || e.kind === "shared") {
        var t = svgEl("title", {});
        t.textContent = byId[e.a].label + (e.kind === "shared" ? " – " : " → ") + byId[e.b].label + ": " + (e.cell
          ? DIR_KEYS.filter(function (k) { return e.cell.dir[k]; }).map(function (k) { return DIR_GLYPH[k] + " " + DIR_LABEL[k] + " " + e.cell.dir[k]; }).join(", ") + (e.mixed ? " · mixed direction" : "")
          : e.rel ? relLabel(e.rel) : e.w + " shared papers");
        gEdge.appendChild(t);
      }
      if (e.rel) {
        rec.hit = gEdge.appendChild(svgEl("line", { class: "hit", stroke: "transparent", "stroke-width": 10 }));
        // glyph badge on the line: the type stays readable without colour
        var badgeG = gEdge.appendChild(svgEl("g", { class: "ebadge", opacity: on ? 1 : 0.15 }));
        rec.badge = badgeG.appendChild(svgEl("circle", { r: 7.5, fill: "var(--panel)", stroke: st.stroke, "stroke-width": 1.4, "stroke-dasharray": st.dash ? "2 1.5" : "none" }));
        rec.glyph = badgeG.appendChild(svgEl("text", { class: "eglyph", "text-anchor": "middle" }));
        rec.glyph.textContent = REL_GLYPH[e.rel.type] || "·";
        if (e.rel.stale) {
          rec.staleTag = badgeG.appendChild(svgEl("text", { class: "estale" }));
          rec.staleTag.textContent = "stale";
        }
        gEdge.addEventListener("click", function () { o.onPickRel(e.rel); });
      }
      placeEdge(rec, pos);
      (byNode[e.a] = byNode[e.a] || []).push(rec);
      (byNode[e.b] = byNode[e.b] || []).push(rec);
      svg.appendChild(gEdge);
    });

    var maxSize = 1;
    graph.nodes.forEach(function (n) { maxSize = Math.max(maxSize, n.size); });
    var nodeEls = {}, nodeRecs = {};
    function placeNode(rec) {
      var p = pos[rec.n.id];
      placeShape(rec.shape, rec.n, p, rec.r);
      if (!rec.text) return;
      var c = o.anchorCenter && pos[o.anchorCenter];
      var left = c && rec.n.id !== o.anchorCenter && p.x < c.x - 1;
      setAttrs(rec.text, { x: left ? p.x - rec.r - 3 : p.x + rec.r + 3, y: p.y + 4, "text-anchor": left ? "end" : "start" });
    }
    function moveNode(id, x, y) {
      pos[id].x = Math.max(8, Math.min(W - 8, x));
      pos[id].y = Math.max(8, Math.min(H - 8, y));
      placeNode(nodeRecs[id]);
      (byNode[id] || []).forEach(function (rec) { placeEdge(rec, pos); });
    }

    var drag = null, suppressClick = false;
    graph.nodes.forEach(function (n) {
      var on = !sel || n.id === sel.id || (nbrs && nbrs[n.id]);
      var r = o.radius(n, maxSize);
      var gEl = svgEl("g", { class: "gnode" + (sel && n.id === sel.id ? " sel" : "") + (o.classFor ? o.classFor(n) : ""), tabindex: "0", role: "button", opacity: on ? 1 : 0.18,
        "aria-label": n.kind + " " + n.label + ", " + n.size + " paper" + (n.size === 1 ? "" : "s") + (o.ariaExtra ? o.ariaExtra(n) : "") + ". Shift + arrow keys move it." });
      var rec = nodeRecs[n.id] = { n: n, r: r, shape: gEl.appendChild(makeShape(n, o.color(n), r)) };
      nodeEls[n.id] = gEl;
      var title = svgEl("title", {});
      title.textContent = (n.title || n.label) + " · " + n.kind + " · " + n.size + " paper" + (n.size === 1 ? "" : "s");
      gEl.appendChild(title);
      if (o.labelled.has(n.id) || (sel && on)) {
        rec.text = gEl.appendChild(svgEl("text", {}));
        rec.text.textContent = n.label.length > 28 ? n.label.slice(0, 27) + "…" : n.label;
      }
      placeNode(rec);

      gEl.addEventListener("pointerdown", function (ev) {
        if (ev.button !== 0) return;
        ev.stopPropagation();
        // keep the grab point under the pointer instead of snapping the centre to it
        var grab = toSvg(ev);
        drag = { id: n.id, x0: ev.clientX, y0: ev.clientY, moved: false,
          dx: grab ? pos[n.id].x - grab.x : 0, dy: grab ? pos[n.id].y - grab.y : 0 };
        try { gEl.setPointerCapture(ev.pointerId); } catch (err) { /* synthetic events have no active pointer */ }
      });
      gEl.addEventListener("pointermove", function (ev) {
        if (!drag || drag.id !== n.id) return;
        if (!drag.moved && Math.abs(ev.clientX - drag.x0) + Math.abs(ev.clientY - drag.y0) < DRAG_SLOP) return;
        drag.moved = true;
        svg.classList.add("dragging");
        var pt = toSvg(ev);
        if (pt) moveNode(n.id, pt.x + drag.dx, pt.y + drag.dy);
      });
      function endDrag() {
        if (!drag || drag.id !== n.id) return;
        if (drag.moved) {
          // the click that follows a drag must not toggle the selection
          suppressClick = true;
          setTimeout(function () { suppressClick = false; }, 0);
          svg.classList.remove("dragging");
        }
        drag = null;
      }
      gEl.addEventListener("pointerup", endDrag);
      gEl.addEventListener("pointercancel", endDrag);
      gEl.addEventListener("click", function () { if (!suppressClick) o.onPick(n); });
      gEl.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); o.onPick(n); return; }
        var delta = { ArrowRight: [1, 0], ArrowDown: [0, 1], ArrowLeft: [-1, 0], ArrowUp: [0, -1] }[e.key];
        if (!delta) return;
        if (e.shiftKey) {
          e.preventDefault();
          moveNode(n.id, pos[n.id].x + delta[0] * NUDGE, pos[n.id].y + delta[1] * NUDGE);
          return;
        }
        if (!sel) return;
        // arrows walk the selected node and its neighbours
        e.preventDefault();
        var step = delta[0] + delta[1];
        var ring = [sel.id].concat(Object.keys(nbrs || {}).sort(function (x, y) { return nbrs[y] - nbrs[x] || (x < y ? -1 : 1); }));
        var at = ring.indexOf(n.id);
        var next = ring[((at < 0 ? 0 : at) + step + ring.length) % ring.length];
        if (nodeEls[next]) nodeEls[next].focus();
      });
      svg.appendChild(gEl);
    });

    // background pan (mouse / pen; touch keeps scrolling the page)
    var pan = null;
    svg.addEventListener("pointerdown", function (ev) {
      if (ev.button !== 0 || ev.pointerType === "touch" || (ev.target.closest && ev.target.closest(".gnode, .gedge.rel"))) return;
      pan = { x0: ev.clientX, y0: ev.clientY, bx: box.x, by: box.y, scale: box.w / (svg.clientWidth || W) };
      try { svg.setPointerCapture(ev.pointerId); } catch (err) { /* synthetic events have no active pointer */ }
      svg.classList.add("panning");
    });
    svg.addEventListener("pointermove", function (ev) {
      if (!pan) return;
      setView(pan.bx - (ev.clientX - pan.x0) * pan.scale + box.w / 2, pan.by - (ev.clientY - pan.y0) * pan.scale + box.h / 2);
      v.pan = { x: box.x + box.w / 2, y: box.y + box.h / 2 };
    });
    function endPan() { pan = null; svg.classList.remove("panning"); }
    svg.addEventListener("pointerup", endPan);
    svg.addEventListener("pointercancel", endPan);
    svg.addEventListener("wheel", function (ev) {
      if (!(ev.ctrlKey || ev.metaKey)) return;
      ev.preventDefault();
      var pt = toSvg(ev) || { x: box.x + box.w / 2, y: box.y + box.h / 2 };
      var old = box.w;
      v.zoom = Math.max(0.5, Math.min(5, v.zoom * (ev.deltaY < 0 ? 1.15 : 1 / 1.15)));
      var k = (W / v.zoom) / old;
      // keep the point under the cursor fixed
      setView(pt.x - (pt.x - box.x) * k + (W / v.zoom) / 2, pt.y - (pt.y - box.y) * k + (H / v.zoom) / 2);
      v.pan = { x: box.x + box.w / 2, y: box.y + box.h / 2 };
    }, { passive: false });

    if (o.focusId && nodeEls[o.focusId]) {
      var target = nodeEls[o.focusId];
      setTimeout(function () { if (document.contains(target)) target.focus({ preventScroll: true }); }, 0);
    }
    return { svg: svg, nodeEls: nodeEls };
  }

  function zoomControls(view, relayout) {
    function rerender() { renderInsights(); }
    return el("span", { className: "zoom" }, [
      el("button", { className: "iconbtn", text: "−", attrs: { type: "button", "aria-label": "Zoom out" }, on: { click: function () { view.zoom = Math.max(0.5, view.zoom / 1.3); rerender(); } } }),
      el("button", { className: "iconbtn", text: "+", attrs: { type: "button", "aria-label": "Zoom in" }, on: { click: function () { view.zoom = Math.min(5, view.zoom * 1.3); rerender(); } } }),
      el("button", { className: "iconbtn", text: "⤢", attrs: { type: "button", "aria-label": "Reset zoom and pan" }, on: { click: function () { view.zoom = 1; view.pan = null; rerender(); } } }),
      el("button", { className: "cmdbtn", text: "Re-layout", attrs: { type: "button", title: "Discard dragged positions and lay the graph out again" },
        on: { click: function () { relayout(); view.pan = null; rerender(); } } }),
    ]);
  }

  var DRAG_HINT = "drag nodes to rearrange · drag the background to pan · ⌘/Ctrl + scroll to zoom · Shift + arrows move a focused node";

  function centerPicker(scope) {
    var idx = neighborhoodIndex(scope);
    var ids = Object.keys(idx.info);
    var degree = function (id) { return paperLinks(idx, id).total; };
    var concepts = ids.filter(function (id) { return idx.info[id].kind === "concept"; })
      .sort(function (a, b) { return idx.info[b].pmids.size - idx.info[a].pmids.size || (idx.info[a].label < idx.info[b].label ? -1 : 1); });
    var papers = ids.filter(function (id) { return idx.info[id].kind === "paper"; })
      .sort(function (a, b) { return degree(b) - degree(a) || (a < b ? -1 : 1); }).slice(0, 150);
    var sel = el("select", { attrs: { "aria-label": "Center on" } }, [el("option", { attrs: { value: "" }, text: "Center on…" })]);
    function group(label, list, text) {
      if (!list.length) return;
      var g = el("optgroup", { attrs: { label: label } });
      list.forEach(function (id) {
        var o = el("option", { attrs: { value: id }, text: text(idx.info[id], id) });
        if (id === ins.center) o.selected = true;
        g.appendChild(o);
      });
      sel.appendChild(g);
    }
    group("Concepts", concepts, function (x) { return x.label + " (" + x.pmids.size + ")"; });
    group("Papers (most connected)", papers, function (x, id) { var l = paperLinks(idx, id); return x.label + " · " + l.concepts + " concepts, " + l.coauthored + " co-author papers"; });
    sel.addEventListener("change", function () { if (sel.value) showInGraph(sel.value); });
    return el("label", {}, [sel]);
  }

  // Always-on labels. Global modes: the 22 largest nodes. Neighborhood: the
  // centre and its first ring -- when the ring is crowded, 12 nodes evenly
  // spaced in radialLayout()'s ring order, so labels never sit side by
  // side; the outer ring is labelled only around the selection.
  var NB_RING_LABELS = 12;
  function graphLabels(graph, nbMode) {
    if (!nbMode) {
      return new Set(graph.nodes.slice().sort(function (a, b) { return b.size - a.size; }).slice(0, 22).map(function (n) { return n.id; }));
    }
    var ring = graph.nodes.filter(function (n) { return n.hop === 1; });
    if (ring.length > NB_RING_LABELS) {
      ring.sort(function (a, b) { return KIND_RANK[a.kind] - KIND_RANK[b.kind] || (a.label < b.label ? -1 : a.label > b.label ? 1 : 0); });
      var step = ring.length / NB_RING_LABELS;
      var picked = [];
      for (var i = 0; i < NB_RING_LABELS; i++) picked.push(ring[Math.floor(i * step)]);
      ring = picked;
    }
    return new Set([ins.center].concat(ring.map(function (n) { return n.id; })));
  }

  var GRAPH_MODES = [["concepts", "Concepts"], ["papers", "Papers & authors"], ["claims", "Claim network"], ["neighborhood", "Neighborhood"]];

  function renderGraph(body, scope) {
    var nbMode = ins.graphMode === "neighborhood";
    var relMode = nbMode || ins.graphMode === "claims";
    var seg = el("div", { className: "d-mode", attrs: { role: "group", "aria-label": "Graph mode" } }, GRAPH_MODES.map(function (m) {
      return el("button", {
        text: m[1], attrs: { type: "button", "aria-pressed": String(ins.graphMode === m[0]) },
        on: { click: function () { ins.graphMode = m[0]; ins.selected = null; ins.selectedRel = null; ins.zoom = 1; ins.pan = null; renderInsights(); syncUrl(); } },
      });
    }));
    var controls = [seg];
    if (nbMode) {
      controls.push(el("div", { className: "d-mode", attrs: { role: "group", "aria-label": "Hops" } }, [1, 2].map(function (h) {
        return el("button", {
          text: h + " hop" + (h === 1 ? "" : "s"), attrs: { type: "button", "aria-pressed": String(ins.hops === h) },
          on: { click: function () { ins.hops = h; ins.selected = null; renderInsights(); syncUrl(); } },
        });
      })));
      controls.push(centerPicker(scope));
    } else {
      var range = el("input", { attrs: { type: "range", min: "20", max: "200", step: "10", value: String(ins.graphN), "aria-label": "Maximum nodes" } });
      range.addEventListener("change", function () { ins.graphN = parseInt(range.value, 10); renderInsights(); });
      controls.push(el("label", {}, [document.createTextNode("Nodes ≤ " + ins.graphN + " "), range]));
    }
    if (relMode) {
      controls.push(selectControl("Extraction", ins.tierFull ? "full" : "all", [["all", "abstract + full text"], ["full", "full text only"]],
        function (v) { ins.tierFull = v === "full"; ins.selected = null; renderInsights(); }));
    }
    controls.push(el("div", { className: "d-mode", attrs: { role: "group", "aria-label": "Graph or table" } }, [["graph", "Graph"], ["table", "Table"]].map(function (v) {
      return el("button", {
        text: v[1], attrs: { type: "button", "aria-pressed": String(ins.graphView === v[0]) },
        on: { click: function () { ins.graphView = v[0]; renderInsights(); } },
      });
    })));
    if (ins.graphView === "graph") controls.push(zoomControls(ins, function () { ins.graphCache = null; }));
    body.appendChild(el("div", { className: "ins-controls" }, controls));

    var gscope = relMode && ins.tierFull
      ? { rows: scope.rows, pmids: scope.pmids, papers: scope.papers, claims: scope.claims.filter(function (c) { return c.tier === "full"; }) }
      : scope;
    if (ins.graphMode === "claims" && !gscope.claims.length) { noClaimsNotice(body); return; }
    if (nbMode && !ins.center) {
      body.appendChild(el("div", { className: "empty", text: "pick a paper or concept above -- or use “Center here” on any graph node, or “Show in graph” in a paper's drawer" }));
      return;
    }

    var W = 900, H = 600;
    var relKey = REL_TYPES.filter(function (t) { return ins.relHidden[t]; }).join(",") + (ins.reviewedOnly ? "|r" : "");
    var key = [ins.graphMode, nbMode ? ins.center + "/" + ins.hops : ins.graphN, ins.tierFull, relKey, scopeKey(gscope)].join("|");
    if (!ins.graphCache || ins.graphCache.key !== key || ins.graphCache.know !== KNOW) {
      var g = nbMode ? buildNeighborhood(gscope, ins.center, ins.hops) : buildGraph(gscope);
      ins.graphCache = { key: key, know: KNOW, graph: g, pos: nbMode ? radialLayout(g.nodes, g.edges, ins.center, W, H) : forceLayout(g.nodes, g.edges, W, H) };
    }
    var graph = ins.graphCache.graph, pos = ins.graphCache.pos;
    if (nbMode && graph.missing) {
      var pm = ins.center.indexOf("p:") === 0 ? ins.center.slice(2) : null;
      body.appendChild(el("div", { className: "empty", text: pm && ctx.byPmid()[pm]
        ? "PMID " + pm + " is outside the current scope -- untick “follow the Papers filters” or widen the year range"
        : "nothing to center on: " + ins.center + " is not a paper or registry concept in scope" }));
      return;
    }
    if (!graph.nodes.length) {
      body.appendChild(el("div", { className: "empty", text: "nothing to draw -- no topic terms or claims in scope" }));
      return;
    }
    if (nbMode && graph.nodes.length === 1) {
      var only = graph.nodes[0];
      var fix = only.kind === "paper"
        ? ["/ref:extract " + Array.from(only.pmids)[0], "/ref:weave"]
        : ["/ref:weave"];
      body.appendChild(el("div", { className: "empty" }, [
        document.createTextNode(only.label + " has no concept, author or claim links in scope yet -- extract claims, then map them to concepts: "),
      ].concat(fix.map(function (c) {
        return el("button", { className: "cmdbtn", text: c, attrs: { type: "button" }, on: { click: function () { copyText(c); } } });
      }))));
      return;
    }
    var byId = {};
    graph.nodes.forEach(function (n) { byId[n.id] = n; });
    var sel = ins.selected && byId[ins.selected] ? byId[ins.selected] : null;
    var nbrs = sel ? graph.adj[sel.id] : null;
    // a relation can be selected from the Gaps view even when its concepts
    // aren't drawn at this node limit -- the detail panel still shows it
    var selRel = ins.selectedRel ? ((KNOW && KNOW.relations) || []).filter(function (r) { return r.id === ins.selectedRel; })[0] || null : null;

    var main;
    if (ins.graphView === "table") {
      main = renderGraphTable(graph, byId, {
        selected: ins.selected, showHop: nbMode, sort: ins.tableSort,
        onSort: function (s) { ins.tableSort = s; renderInsights(); },
        onSelect: function (id) { ins.selected = ins.selected === id ? null : id; ins.selectedRel = null; renderInsights(); },
        onRel: function (id) { ins.selectedRel = id; renderInsights(); },
      });
    } else {
      var drawn = drawGraph(graph, pos, {
        W: W, H: H, view: ins, sel: sel, nbrs: nbrs, selRel: selRel,
        labelled: graphLabels(graph, nbMode), anchorCenter: nbMode ? ins.center : null, relShiftStart: nbMode ? 0 : 1,
        ariaLabel: (nbMode ? "Neighborhood of " + byId[ins.center].label + ", " : "Knowledge graph, ") + graph.nodes.length + " nodes",
        color: nodeColor,
        radius: function (n, maxSize) { return nbMode && n.kind === "paper" ? 6 : 4 + 11 * Math.sqrt(n.size / maxSize); },
        classFor: function (n) { return nbMode && n.id === ins.center ? " center" : ""; },
        ariaExtra: function (n) { return nbMode ? ", hop " + n.hop : ""; },
        onPick: function (n) { ins.selected = sel && sel.id === n.id ? null : n.id; ins.selectedRel = null; ins.focusId = n.id; ins.pan = null; renderInsights(); },
        onPickRel: function (rel) { ins.selectedRel = ins.selectedRel === rel.id ? null : rel.id; renderInsights(); },
        focusId: ins.focusId,
      });
      ins.focusId = null;
      main = el("div", { className: "panel" }, [drawn.svg]);
    }

    var legend = el("div", { className: "tri-legend" });
    if (ins.graphMode === "concepts") {
      legend.appendChild(el("span", { text: "colour = cluster · size = papers · line = papers sharing both terms" }));
    } else if (ins.graphMode === "papers") {
      [["paper", "paper"], ["concept", "concept / claim term"], ["mesh", "MeSH term"], ["author", "shared author (ring)"]].forEach(function (k) {
        legend.appendChild(el("span", {}, [el("i", { attrs: { style: "background:" + KIND_COLOR[k[0]] } }), document.createTextNode(k[1])]));
      });
    } else if (nbMode) {
      KIND_LEGEND.forEach(function (k) {
        legend.appendChild(el("span", {}, [el("i", { className: "k-" + k[0], attrs: { style: "--c:" + KIND_COLOR[k[0]] } }), document.createTextNode(k[1])]));
      });
      legend.appendChild(el("span", { text: "rings = hops from the centre" }));
    } else {
      [["intervention", "intervention"], ["outcome", "outcome"], ["population", "population"]].forEach(function (k) {
        legend.appendChild(el("span", {}, [el("i", { attrs: { style: "background:" + KIND_COLOR[k[0]] } }), document.createTextNode(k[1])]));
      });
      ["up", "down", "null"].forEach(function (k) {
        legend.appendChild(el("span", {}, [legendLine({ stroke: DIR_COLOR[k], width: 2 }), document.createTextNode(DIR_GLYPH[k] + " " + DIR_LABEL[k])]));
      });
      legend.appendChild(el("span", {}, [legendLine({ stroke: DIR_COLOR.mixed, width: 2, dash: "1 4" }), document.createTextNode("↑↓ mixed direction (inferred from claims, not a recorded relation)")]));
    }
    if (ins.graphView === "graph") legend.appendChild(el("span", { className: "sub", text: DRAG_HINT }));
    main.appendChild(legend);
    if (relMode) {
      var counts = {};
      relationsInScope(gscope).forEach(function (r) { counts[r.type] = (counts[r.type] || 0) + 1; });
      main.appendChild(relationLegend(counts));
    }
    if (graph.capped) main.appendChild(el("div", { className: "sub", text: "showing " + NB_CAP + " nodes -- " + graph.dropped + " more at this hop count were left out (most-linked kept)" }));

    var side = el("div", { className: "panel gside" });
    var relEdges = graph.edges.filter(function (e) { return e.rel; });
    function relList(edges) {
      var ul = el("ul", { className: "ins-list" });
      edges.slice(0, 20).forEach(function (e) {
        ul.appendChild(el("li", {}, [
          el("button", {
            className: "plink", attrs: { type: "button", "aria-pressed": String(ins.selectedRel === e.rel.id) },
            text: byId[e.a].label + " " + (REL_GLYPH[e.rel.type] || "–") + " " + byId[e.b].label,
            on: { click: function () { ins.selectedRel = e.rel.id; renderInsights(); } },
          }),
          el("small", { text: relLabel(e.rel) }),
        ]));
      });
      if (edges.length > 20) ul.appendChild(el("li", { className: "more", text: "+" + (edges.length - 20) + " more in the table view" }));
      return ul;
    }
    function openFirst(edges) {
      return edges.slice().sort(function (a, b) {
        var oa = (a.rel.review_state !== "reviewed" || a.rel.stale) ? 0 : 1, ob = (b.rel.review_state !== "reviewed" || b.rel.stale) ? 0 : 1;
        return oa - ob || (a.rel.type < b.rel.type ? -1 : 1);
      });
    }

    if (selRel) {
      side.appendChild(relationDetail(selRel));
    } else if (!sel) {
      if (nbMode) {
        var centre = byId[ins.center];
        var kinds = {};
        graph.nodes.forEach(function (n) { if (n.id !== ins.center) kinds[n.kind] = (kinds[n.kind] || 0) + 1; });
        side.appendChild(el("h2", { text: "Centre · " + centre.kind }));
        side.appendChild(el("b", { className: "gtitle", text: centre.title || centre.label }));
        side.appendChild(el("div", { className: "sub", text: Object.keys(kinds).sort().map(function (k) { return kinds[k] + " " + k + (kinds[k] === 1 ? "" : "s"); }).join(" · ") + " within " + ins.hops + " hop" + (ins.hops === 1 ? "" : "s") }));
        side.appendChild(el("div", { className: "pcmds" }, [
          el("button", { className: "cmdbtn primary", text: "Select centre", attrs: { type: "button" }, on: { click: function () { ins.selected = ins.center; renderInsights(); } } }),
        ].concat(centre.kind === "paper" ? [el("button", {
          className: "cmdbtn", text: "Open paper", attrs: { type: "button" }, on: { click: function () { openDrawer(Array.from(centre.pmids)[0]); } },
        })] : [])));
        side.appendChild(el("h2", { text: "Relations (" + relEdges.length + ")" }));
        if (!relEdges.length) side.appendChild(el("div", { className: "empty", text: "no recorded relations touch this neighbourhood -- /ref:weave proposes them" }));
        side.appendChild(relList(openFirst(relEdges)));
      } else if (ins.graphMode === "claims") {
        side.appendChild(el("h2", { text: "Explore" }));
        side.appendChild(el("p", { className: "sub", text: "Click a node or a relation line. Relations are recorded concept edges; mixed direction is inferred from claims on one intervention → outcome pair." }));
        side.appendChild(el("h2", { text: "Recorded relations (" + relEdges.length + ")" }));
        if (!relEdges.length) side.appendChild(el("div", { className: "empty", text: "no relations between the concepts drawn here -- /ref:weave proposes them" }));
        side.appendChild(relList(openFirst(relEdges)));
        var mixed = graph.edges.filter(function (e) { return e.mixed; });
        side.appendChild(el("h2", { text: "Mixed direction (" + mixed.length + ")" }));
        if (!mixed.length) side.appendChild(el("div", { className: "empty", text: "no intervention → outcome pair has both increases and decreases in scope" }));
        mixed.slice(0, 20).forEach(function (e) {
          var pm = Array.from(e.cell.pmids);
          side.appendChild(el("div", { className: "conflict" }, [
            el("b", { text: byId[e.a].label + " → " + byId[e.b].label }),
            el("span", { className: "sub", text: "↑ " + e.cell.dir.up + " · ↓ " + e.cell.dir.down + " · → " + e.cell.dir["null"] + " · mixed direction, not a reviewed contradiction" }),
            el("div", { className: "pcmds" }, pm.slice(0, 8).map(paperButton).concat([el("button", {
              className: "cmdbtn", text: "Papers (" + pm.length + ")", attrs: { type: "button" },
              on: { click: function () { applyPmidFilter("mixed direction: " + byId[e.a].label + " → " + byId[e.b].label, pm); } },
            })])),
          ]));
        });
      } else {
        side.appendChild(el("h2", { text: "Explore" }));
        side.appendChild(el("p", { className: "sub", text: "Click or press Enter on a node to see its neighbourhood and papers. Raise the node limit for more detail; lower it on large libraries." }));
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
      side.appendChild(el("h2", {}, [document.createTextNode(sel.kind + (nbMode ? " · hop " + sel.hop : "")), el("button", {
        className: "cmdbtn", text: "Clear", attrs: { type: "button" }, on: { click: function () { ins.selected = null; renderInsights(); } },
      })]));
      side.appendChild(el("b", { className: "gtitle", text: sel.title || sel.label }));
      var centerId = centerIdFor(sel);
      side.appendChild(el("div", { className: "pcmds" }, [el("button", {
        className: "cmdbtn primary", text: "Show " + sel.pmids.size + " papers", attrs: { type: "button" },
        on: { click: function () { applyPmidFilter(sel.kind + ": " + sel.label, Array.from(sel.pmids)); } },
      })].concat(sel.kind === "paper" || sel.kind === "claim" ? [el("button", {
        className: "cmdbtn", text: "Open paper", attrs: { type: "button" },
        on: { click: function () { openDrawer(Array.from(sel.pmids)[0]); } },
      })] : []).concat(centerId && !(nbMode && centerId === ins.center) ? [el("button", {
        className: "cmdbtn", text: sel.kind === "claim" ? "Center on paper" : "Center here", attrs: { type: "button" },
        on: { click: function () { showInGraph(centerId); } },
      })] : [])));
      if (sel.claim) side.appendChild(claimTable([sel.claim]));
      if (sel.kind === "paper") {
        var overlay = appraisalOverlay(Array.from(sel.pmids)[0]);
        if (overlay) { side.appendChild(el("h2", { text: "Appraisal" })); side.appendChild(overlay); }
      }
      var outgoing = graph.edges.filter(function (e) { return (e.a === sel.id || e.b === sel.id) && e.cell && e.kind === "io"; });
      if (outgoing.length) {
        side.appendChild(el("h2", { text: "Findings" }));
        outgoing.sort(function (a, b) { return b.w - a.w; }).slice(0, 15).forEach(function (e) {
          var other = byId[e.a === sel.id ? e.b : e.a];
          side.appendChild(el("div", { className: "conflict" + (e.mixed ? " is" : "") }, [
            el("b", { text: (e.a === sel.id ? "→ " : "← ") + other.label }),
            el("span", { className: "sub", text: "↑ " + e.cell.dir.up + " · ↓ " + e.cell.dir.down + " · → " + e.cell.dir["null"] + " · " + e.cell.pmids.size + " papers" + (e.mixed ? " · mixed direction" : "") }),
            el("div", { className: "pcmds" }, Array.from(e.cell.pmids).slice(0, 6).map(paperButton)),
          ]));
        });
      }
      var touching = relEdges.filter(function (e) { return e.a === sel.id || e.b === sel.id; });
      if (touching.length) {
        side.appendChild(el("h2", { text: "Relations (" + touching.length + ")" }));
        side.appendChild(relList(openFirst(touching)));
      }
      side.appendChild(el("h2", { text: "Connected" }));
      var ul2 = el("ul", { className: "ins-list" });
      Object.keys(nbrs || {}).sort(function (a, b) { return nbrs[b] - nbrs[a] || (a < b ? -1 : 1); }).slice(0, 20).forEach(function (id) {
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
    if (ins.selected && !sel) side.appendChild(el("div", { className: "empty", text: nbMode ? "the selected node isn't in this neighbourhood" : "the selected node isn't among the top " + ins.graphN + " -- raise the node limit" }));
    body.appendChild(el("div", { className: "gwrap" }, [main, side]));
  }

  // ------------------------------------ insight cards (graph plan Phase 1)
  //
  // A "what is notable" row above every Insights view, computed only from
  // the knowledge payload already loaded. Each card either centres the
  // graph on a node or applies a Papers-tab chip.

  function insightCards(scope) {
    var key = scopeKey(scope);
    if (ins.cardCache && ins.cardCache.key === key && ins.cardCache.know === KNOW) return ins.cardCache.cards;
    var cards = [];
    var idx = neighborhoodIndex(scope);
    var best = null, bestLinks = null;
    scope.rows.forEach(function (r) {
      var l = paperLinks(idx, "p:" + r.pmid);
      if (l.total && (!bestLinks || l.total > bestLinks.total || (l.total === bestLinks.total && r.pmid < best))) { best = r.pmid; bestLinks = l; }
    });
    if (best) {
      var row = ctx.byPmid()[best] || {};
      cards.push({ n: String(bestLinks.total), label: "links on the best-connected paper",
        detail: (row.citekey || best) + " · " + bestLinks.concepts + " concepts + " + bestLinks.coauthored + " co-author papers",
        title: row.title, go: function () { showInGraph("p:" + best); } });
    }
    var conflicts = unresolvedConflicts(scope);
    var conflictPmids = new Set();
    conflicts.forEach(function (x) { x.r.pmids.forEach(function (p) { if (scope.pmids.has(p)) conflictPmids.add(p); }); });
    cards.push({ n: String(conflicts.length), label: "open conflicts", detail: "unreviewed or stale relations",
      go: conflictPmids.size ? function () { applyPmidFilter("open conflicts", Array.from(conflictPmids)); } : null });
    var singles = ioPairs(scope.claims).filter(function (p) { return p.pmids.size === 1; });
    var singlePmids = new Set();
    singles.forEach(function (p) { p.pmids.forEach(function (x) { singlePmids.add(x); }); });
    cards.push({ n: String(singles.length), label: "single-study findings", detail: "intervention → outcome on one paper",
      go: singlePmids.size ? function () { applyPmidFilter("single-study findings", Array.from(singlePmids)); } : null });
    var withClaims = new Set(scope.claims.map(function (c) { return c.pmid; }));
    var noClaims = scope.rows.filter(function (r) { return !withClaims.has(r.pmid); }).map(function (r) { return r.pmid; });
    cards.push({ n: String(noClaims.length), label: "papers with no active claims", detail: noClaims.length ? "/ref:extract to include them" : "all papers extracted",
      go: noClaims.length ? function () { applyPmidFilter("no active claims", noClaims); } : null });

    var trends = computeClusters(scope, topicIndex(scope)).map(function (c) { return { c: c, t: clusterTrend(c) }; })
      .filter(function (x) { return x.t.label; });
    var growing = trends.filter(function (x) { return x.t.label === "growing"; }).sort(function (a, b) { return b.t.ratio - a.t.ratio; })[0];
    var fading = trends.filter(function (x) { return x.t.label === "fading"; }).sort(function (a, b) { return a.t.ratio - b.t.ratio; })[0];
    [[growing, "growing topic"], [fading, "fading topic"]].forEach(function (g) {
      if (!g[0]) return;
      var x = g[0];
      cards.push({ n: "×" + x.t.ratio.toFixed(2), label: g[1], detail: x.c.name,
        title: x.t.last + " papers " + x.t.lastSpan + " vs " + x.t.prev + " in " + x.t.prevSpan,
        go: function () { ins.view = "clusters"; ins.clusterQuery = x.c.terms[0].label; renderInsights(); syncUrl(); } });
    });
    ins.cardCache = { key: key, know: KNOW, cards: cards };
    return cards;
  }

  function renderInsightCards(body, scope) {
    var row = el("div", { className: "ins-cards", attrs: { role: "list", "aria-label": "Notable in scope" } });
    insightCards(scope).forEach(function (c) {
      var kids = [el("b", { text: c.n }), el("span", { text: c.label }), el("small", { text: c.detail })];
      row.appendChild(el("div", { attrs: { role: "listitem" } }, [c.go
        ? el("button", { className: "ins-card", attrs: { type: "button", title: c.title || c.detail }, on: { click: c.go } }, kids)
        : el("div", { className: "ins-card off" }, kids)]));
    });
    body.appendChild(row);
  }

  // ------------------------------------ cluster trends (graph plan Phase 4)
  //
  // Papers in the last five years vs the five before, ending at the newest
  // publication year in the library (not today's date, so a static build
  // reads the same next year). growing >= 1.25x, fading <= 0.8x; no label
  // unless both windows hold >= 3 papers.

  var TREND_MIN = 3, TREND_UP = 1.25, TREND_DOWN = 0.8;

  function libraryLastYear() {
    var y = 0;
    ctx.rows().forEach(function (r) { y = Math.max(y, parseInt(r.year, 10) || 0); });
    return y;
  }

  function clusterTrend(c) {
    var Y = libraryLastYear();
    var perYear = {}, last = 0, prev = 0;
    c.pmids.forEach(function (p) {
      var y = parseInt((ctx.byPmid()[p] || {}).year, 10);
      if (!y) return;
      perYear[y] = (perYear[y] || 0) + 1;
      if (y > Y - 5) last++;
      else if (y > Y - 10) prev++;
    });
    var ratio = prev ? last / prev : null;
    var label = last >= TREND_MIN && prev >= TREND_MIN ? (ratio >= TREND_UP ? "growing" : ratio <= TREND_DOWN ? "fading" : "stable") : null;
    return { perYear: perYear, last: last, prev: prev, ratio: ratio, label: label,
      lastSpan: (Y - 4) + "–" + Y, prevSpan: (Y - 9) + "–" + (Y - 5), y1: Y };
  }

  function sparkline(t, y0) {
    var from = Math.max(y0 || t.y1, t.y1 - 29), W = 120, H = 26;
    var max = 1, pts = [];
    for (var y = from; y <= t.y1; y++) max = Math.max(max, t.perYear[y] || 0);
    for (var yy = from; yy <= t.y1; yy++) {
      var x = t.y1 === from ? W / 2 : (yy - from) / (t.y1 - from) * (W - 4) + 2;
      pts.push(x.toFixed(1) + "," + (H - 2 - (t.perYear[yy] || 0) / max * (H - 4)).toFixed(1));
    }
    var s = svgEl("svg", { viewBox: "0 0 " + W + " " + H, class: "spark", role: "img",
      "aria-label": "papers per year " + from + "–" + t.y1 + ", peak " + max });
    var bandX = t.y1 === from ? 0 : Math.max(0, (t.y1 - 4 - from) / (t.y1 - from) * (W - 4) + 2);
    s.appendChild(svgEl("rect", { x: bandX, y: 0, width: W - bandX, height: H, fill: "var(--hover)" }));
    s.appendChild(svgEl("polyline", { points: pts.join(" "), fill: "none", stroke: "var(--accent)", "stroke-width": 1.5 }));
    return s;
  }

  // ------------------------------------------------- clusters (FR-14)

  // Two terms are linked for clustering only when they share papers at
  // least CLUSTER_LIFT times as often as chance (|A|·|B| / papers) would
  // give. Terms found in most papers co-occur with everything at about
  // chance level and would otherwise merge every topic into one cluster.
  // Scopes under CLUSTER_LIFT_MIN_PAPERS are too small for a stable
  // expectation and keep the plain co-occurrence count.
  var CLUSTER_LIFT = 1.5, CLUSTER_LIFT_MIN_PAPERS = 20;

  function computeClusters(scope, terms) {
    var co = cooccurrence(terms, 400, 2);
    var n = scope.rows.length, useLift = n >= CLUSTER_LIFT_MIN_PAPERS;
    var minW = n > 60 ? 2 : 1;
    var size = {};
    co.chosen.forEach(function (t) { size[t.key] = t.pmids.size; });
    var adj = {};
    co.chosen.forEach(function (t) {
      adj[t.key] = {};
      Object.keys(co.adj[t.key]).forEach(function (m) {
        var w = co.adj[t.key][m];
        if (w < minW || (useLift && w < CLUSTER_LIFT * size[t.key] * size[m] / n)) return;
        adj[t.key][m] = w;
      });
    });
    var labels = labelPropagation(co.chosen.map(function (t) { return t.key; }), adj);
    var groups = {};
    co.chosen.forEach(function (t) { (groups[labels[t.key]] = groups[labels[t.key]] || []).push(t); });
    return Object.keys(groups).map(function (g) { return groups[g]; }).filter(function (ts) { return ts.length >= 2; }).map(function (ts) {
      ts.sort(function (a, b) { return b.pmids.size - a.pmids.size || (a.label < b.label ? -1 : 1); });
      var pmids = new Set();
      ts.forEach(function (t) { t.pmids.forEach(function (p) { pmids.add(p); }); });
      var years = Array.from(pmids).map(function (p) { return parseInt((ctx.byPmid()[p] || {}).year, 10); }).filter(Boolean);
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
      el("div", { className: "d-mode", attrs: { role: "group", "aria-label": "Cluster view" } }, [["cards", "Cards"], ["map", "Map"], ["table", "Table"]].map(function (v) {
        return el("button", {
          text: v[1], attrs: { type: "button", "aria-pressed": String(ins.clusterView === v[0]) },
          on: { click: function () { ins.clusterView = v[0]; renderInsights(); } },
        });
      })),
      q, ins.clusterView === "map" ? zoomControls(ins.clusterMap, function () { ins.clusterMap.cache = null; }) : null,
      el("span", { className: "sub", text: "Terms (MeSH, concepts, claim population/intervention/outcome) that appear in at least two papers, grouped by how often they co-occur" +
        (scope.rows.length >= CLUSTER_LIFT_MIN_PAPERS ? " — at least " + CLUSTER_LIFT + "× as often as chance." : ".") }),
    ]));
    var clusters = computeClusters(scope, topicIndex(scope));
    var needle = ins.clusterQuery.trim().toLowerCase();
    if (needle) clusters = clusters.filter(function (c) { return c.terms.some(function (t) { return t.label.toLowerCase().indexOf(needle) >= 0; }); });
    if (!clusters.length) {
      body.appendChild(el("div", { className: "empty", text: needle ? "no cluster contains “" + needle + "”" : "not enough shared terms to form clusters in scope" }));
      return;
    }
    if (ins.clusterView !== "cards") { renderClusterMap(body, clusters); return; }
    var max = clusters[0].pmids.size;
    clusters.forEach(function (c) { max = Math.max(max, c.pmids.size); });
    var grid = el("div", { className: "clgrid" });
    var TREND_TAG = { growing: ["↑ growing", "var(--good)"], fading: ["↓ fading", "var(--warn)"], stable: ["→ stable", "var(--muted)"] };
    clusters.slice(0, 40).forEach(function (c, i) {
      var trend = clusterTrend(c);
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
        el("div", { className: "cltrend" }, [
          sparkline(trend, c.y0),
          trend.label ? el("span", { className: "dirtag", attrs: { style: "--c:" + TREND_TAG[trend.label][1] }, text: TREND_TAG[trend.label][0] }) : null,
          el("small", { text: trend.lastSpan + ": " + trend.last + " · " + trend.prevSpan + ": " + trend.prev +
            (trend.label ? " · ratio " + trend.ratio.toFixed(2) : " · too few papers for a trend (needs " + TREND_MIN + "+ in each window)") }),
        ]),
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

  // ------------------------------------------ cluster map (graph plan Phase 4)
  //
  // Clusters as nodes (size = papers, colour = the card's colour), joined
  // when they share at least CLUSTER_MAP_MIN_SHARED papers.

  var CLUSTER_MAP_MIN_SHARED = 2, CLUSTER_MAP_MAX = 40;

  function buildClusterMap(clusters) {
    var list = clusters.slice(0, CLUSTER_MAP_MAX);
    var nodes = list.map(function (c, i) {
      return { id: "cl:" + i, label: c.terms.slice(0, 2).map(function (t) { return t.label; }).join(" · "), title: c.name,
        kind: "cluster", size: c.pmids.size, pmids: c.pmids, cluster: i, c: c };
    });
    var edges = [];
    for (var i = 0; i < nodes.length; i++) {
      for (var j = i + 1; j < nodes.length; j++) {
        var shared = 0;
        nodes[i].pmids.forEach(function (p) { if (nodes[j].pmids.has(p)) shared++; });
        if (shared >= CLUSTER_MAP_MIN_SHARED) edges.push({ a: nodes[i].id, b: nodes[j].id, w: shared, kind: "shared" });
      }
    }
    var adj = {};
    nodes.forEach(function (n) { adj[n.id] = {}; });
    edges.forEach(function (e) { adj[e.a][e.b] = e.w; adj[e.b][e.a] = e.w; });
    return { nodes: nodes, edges: edges, adj: adj };
  }

  function renderClusterMap(body, clusters) {
    var cm = ins.clusterMap, W = 900, H = 560;
    var key = clusters.slice(0, CLUSTER_MAP_MAX).map(function (c) { return c.name + ":" + c.pmids.size; }).join("|");
    if (!cm.cache || cm.cache.key !== key) {
      var g = buildClusterMap(clusters);
      cm.cache = { key: key, graph: g, pos: forceLayout(g.nodes, g.edges, W, H) };
      cm.selected = null;
    }
    var graph = cm.cache.graph, pos = cm.cache.pos;
    var byId = {};
    graph.nodes.forEach(function (n) { byId[n.id] = n; });
    var sel = cm.selected && byId[cm.selected] ? byId[cm.selected] : null;
    var nbrs = sel ? graph.adj[sel.id] : null;
    function pick(id) { cm.selected = cm.selected === id ? null : id; cm.focusId = id; cm.pan = null; renderInsights(); }

    var main;
    if (ins.clusterView === "table") {
      main = renderGraphTable(graph, byId, {
        selected: cm.selected, showHop: false, sort: cm.sort,
        onSort: function (s) { cm.sort = s; renderInsights(); }, onSelect: pick,
      });
    } else {
      var drawn = drawGraph(graph, pos, {
        W: W, H: H, view: cm, sel: sel, nbrs: nbrs, selRel: null,
        labelled: new Set(graph.nodes.slice().sort(function (a, b) { return b.size - a.size; }).slice(0, 22).map(function (n) { return n.id; })),
        ariaLabel: "Cluster map, " + graph.nodes.length + " clusters",
        color: function (n) { return PALETTE[n.cluster % PALETTE.length]; },
        radius: function (n, max) { return 8 + 20 * Math.sqrt(n.size / max); },
        onPick: function (n) { pick(n.id); }, onPickRel: function () {}, focusId: cm.focusId,
      });
      cm.focusId = null;
      main = el("div", { className: "panel" }, [drawn.svg, el("div", { className: "tri-legend" }, [
        el("span", { text: "size = papers · colour = the cluster's card · line = papers two clusters share (≥ " + CLUSTER_MAP_MIN_SHARED + ")" }),
        el("span", { className: "sub", text: DRAG_HINT }),
      ])]);
    }

    var side = el("div", { className: "panel gside" });
    if (!sel) {
      side.appendChild(el("h2", { text: "Cluster map" }));
      side.appendChild(el("p", { className: "sub", text: graph.nodes.length + " clusters · " + graph.edges.length + " overlaps. Click a cluster to see its trend, papers and the clusters it shares papers with." }));
      var ul = el("ul", { className: "ins-list" });
      graph.edges.slice().sort(function (a, b) { return b.w - a.w; }).slice(0, 10).forEach(function (e) {
        ul.appendChild(el("li", {}, [
          el("button", { className: "plink", text: byId[e.a].label, attrs: { type: "button" }, on: { click: function () { pick(e.a); } } }),
          el("span", { text: "–" }),
          el("button", { className: "plink", text: byId[e.b].label, attrs: { type: "button" }, on: { click: function () { pick(e.b); } } }),
          el("small", { text: e.w + " shared" }),
        ]));
      });
      if (!graph.edges.length) ul.appendChild(el("li", { className: "more", text: "no two clusters share " + CLUSTER_MAP_MIN_SHARED + "+ papers" }));
      side.appendChild(ul);
    } else {
      var c = sel.c, trend = clusterTrend(c);
      side.appendChild(el("h2", {}, [document.createTextNode("cluster"), el("button", {
        className: "cmdbtn", text: "Clear", attrs: { type: "button" }, on: { click: function () { pick(sel.id); } },
      })]));
      side.appendChild(el("b", { className: "gtitle", text: c.name }));
      side.appendChild(el("div", { className: "cltrend" }, [
        sparkline(trend, c.y0),
        el("small", { text: trend.lastSpan + ": " + trend.last + " · " + trend.prevSpan + ": " + trend.prev + (trend.label ? " · " + trend.label + " ×" + trend.ratio.toFixed(2) : "") }),
      ]));
      side.appendChild(el("div", { className: "pcmds" }, [
        el("button", { className: "cmdbtn primary", text: "Papers (" + c.pmids.size + ")", attrs: { type: "button" },
          on: { click: function () { applyPmidFilter("cluster: " + c.name, Array.from(c.pmids)); } } }),
        el("button", { className: "cmdbtn", text: "Open in graph", attrs: { type: "button" }, on: { click: function () {
          ins.view = "graph"; ins.graphMode = "concepts"; ins.selected = c.terms[0].key; ins.zoom = 1; ins.pan = null;
          renderInsights(); syncUrl();
        } } }),
      ]));
      side.appendChild(el("h2", { text: "Shares papers with" }));
      var ul2 = el("ul", { className: "ins-list" });
      Object.keys(nbrs).sort(function (a, b) { return nbrs[b] - nbrs[a]; }).forEach(function (id) {
        ul2.appendChild(el("li", {}, [
          el("button", { className: "plink", text: byId[id].label, attrs: { type: "button" }, on: { click: function () { pick(id); } } }),
          el("small", { text: nbrs[id] + " papers" }),
        ]));
      });
      if (!ul2.children.length) ul2.appendChild(el("li", { className: "more", text: "no overlap of " + CLUSTER_MAP_MIN_SHARED + "+ papers" }));
      side.appendChild(ul2);
      side.appendChild(el("h2", { text: "Terms" }));
      side.appendChild(el("div", { className: "clterms" }, c.terms.slice(0, 16).map(function (t) {
        return el("button", { className: "fchip", attrs: { type: "button" }, on: { click: function () { applyPmidFilter("topic: " + t.label, Array.from(t.pmids)); } } },
          [document.createTextNode(t.label), el("span", { className: "x", text: String(t.pmids.size) })]);
      })));
    }
    body.appendChild(el("div", { className: "gwrap" }, [main, side]));
  }

  // --------------------------- maturity + appraisal overlay (graph plan Phase 5)
  //
  // Components per intervention concept, shown side by side and never
  // blended into one score. The appraisal overlay reads /ref:review's frozen
  // batches: GRADE certainty there is one rating for a batch's whole paper
  // set (appraise.grade_certainty), so it is shown per batch -- never
  // relabelled as a per-outcome rating.

  // Needs only populationOutcomeGaps(); tests run it under node. Outcomes
  // are folded through the concept registry the same way as in the grid.
  function maturityComponents(claims, concept, relations, concepts) {
    var res = populationOutcomeGaps(claims, concept, concepts);
    var papers = {}, outcomesInScope = {};
    res.own.forEach(function (c) { papers[c.pmid] = true; });
    claims.forEach(function (c) { if (c.intervention && c.outcome) outcomesInScope[res.outOf(c)] = true; });
    var cells = res.populations.length * res.outcomes.length;
    return {
      concept: concept.id,
      pmids: Object.keys(papers).sort(),
      volume: Object.keys(papers).length,
      claims: res.own.length,
      outcomes: res.outcomes.length,
      outcomesInScope: Object.keys(outcomesInScope).length,
      cells: cells,
      covered: cells - res.gaps.length,
      fullText: res.own.filter(function (c) { return c.tier === "full"; }).length,
      openConflicts: relations.filter(function (r) {
        return (r.subject === concept.id || r.object === concept.id) &&
          ((r.type === "potential_conflict" && r.review_state !== "reviewed") || (r.type === "contradicts" && r.stale));
      }).map(function (r) { return r.id; }),
    };
  }

  var CERT_COLOR = { high: "var(--good)", moderate: "var(--c5)", low: "var(--warn)", very_low: "var(--crit)" };
  var MATURITY_SORTS = [
    ["volume", "papers"], ["breadth", "outcome breadth"], ["coverage", "coverage"], ["fulltext", "full-text share"], ["conflicts", "open conflicts"],
  ];

  function ratio(n, d) { return d ? n / d : 0; }

  function meter(n, d, label) {
    var pct = d ? Math.round(100 * n / d) : 0;
    return el("div", { className: "meter", attrs: { title: label + ": " + n + " of " + d } }, [
      el("span", { className: "mtext", text: d ? n + "/" + d + " · " + pct + "%" : "–" }),
      el("span", { className: "mbar", attrs: { "aria-hidden": "true" } }, [el("i", { attrs: { style: "width:" + pct + "%" } })]),
    ]);
  }

  function reviewsTouching(pmids) {
    var set = new Set(pmids);
    return ((KNOW && KNOW.reviews) || []).map(function (rv) {
      return { rv: rv, hit: rv.pmids.filter(function (p) { return set.has(p); }) };
    }).filter(function (x) { return x.hit.length; });
  }

  function certChip(rv) {
    var cert = (rv.grade && rv.grade.certainty) || "unknown";
    return el("span", { className: "dirtag", attrs: { style: "--c:" + (CERT_COLOR[cert] || "var(--muted)"), title: "GRADE certainty for batch " + rv.batch },
      text: "GRADE " + cert.replace(/_/g, " ") });
  }

  function appraisalState(a) {
    if (!a) return "not in batch";
    if (a.insufficient_information) return "insufficient information";
    if (!a.checklist) return "no checklist for " + (a.study_type || "this design");
    return a.high_risk ? "high risk" : a.assessed ? "assessed, no high-risk domain" : "not assessable";
  }

  var CHECKLIST_LABEL = { RoB2: "RoB 2", "Newcastle-Ottawa": "Newcastle-Ottawa", "AMSTAR-2": "AMSTAR 2" };

  // One line per review batch that appraised this paper (graph side panel).
  function appraisalOverlay(pmid) {
    var hits = reviewsTouching([pmid]);
    if (!hits.length) return null;
    return el("div", { className: "apprlist" }, hits.map(function (x) {
      var a = x.rv.appraisals[pmid];
      return el("div", { className: "conflict" }, [
        el("div", {}, [certChip(x.rv), el("small", { text: " batch " + x.rv.batch + (x.rv.project ? " · " + x.rv.project : "") })]),
        el("span", { className: "sub", text: (a && a.checklist ? (CHECKLIST_LABEL[a.checklist] || a.checklist) + " · " : "") + appraisalState(a) }),
      ]);
    }));
  }

  function renderMaturity(body, scope) {
    var concepts = (KNOW && KNOW.concepts) || [];
    var relations = relationsInScope(scope);
    var rows = concepts.map(function (c) { return { c: c, m: maturityComponents(scope.claims, c, relations, concepts) }; })
      .filter(function (x) { return x.m.claims; });
    var key = {
      volume: function (m) { return m.volume; }, breadth: function (m) { return ratio(m.outcomes, m.outcomesInScope); },
      coverage: function (m) { return ratio(m.covered, m.cells); }, fulltext: function (m) { return ratio(m.fullText, m.claims); },
      conflicts: function (m) { return m.openConflicts.length; },
    }[ins.maturitySort] || function (m) { return m.volume; };
    rows.sort(function (a, b) { return key(b.m) - key(a.m) || b.m.volume - a.m.volume || (a.c.name < b.c.name ? -1 : 1); });

    body.appendChild(el("div", { className: "ins-controls" }, [
      selectControl("Sort by", ins.maturitySort, MATURITY_SORTS, function (v) { ins.maturitySort = v; renderInsights(); }),
      el("span", { className: "sub", text: "Each column is its own measure; there is no combined score." }),
    ]));

    var panel = el("div", { className: "panel" }, [el("h2", {}, [
      document.createTextNode("Evidence maturity by intervention concept"), el("span", { text: rows.length + " concepts with claims in scope" }),
    ])]);
    if (!concepts.length) {
      panel.appendChild(el("div", { className: "empty", text: "no concepts in graph/concepts.jsonl yet -- /ref:weave maps claim interventions to concepts" }));
    } else if (!rows.length) {
      panel.appendChild(el("div", { className: "empty", text: "no claim's intervention matches a concept name or alias in scope -- map them with /ref:weave or /ref:concept add-alias" }));
    } else {
      var table = el("table", { className: "ins-table maturity" }, [el("tr", {}, [
        el("th", { text: "Concept" }), el("th", { className: "num", text: "Papers" }), el("th", { text: "Outcome breadth" }),
        el("th", { text: "Coverage" }), el("th", { text: "Full-text share" }), el("th", { className: "num", text: "Open conflicts" }),
        el("th", { text: "Appraisal" }), el("th", { text: "" }),
      ])]);
      rows.forEach(function (x) {
        var m = x.m;
        var reviews = reviewsTouching(m.pmids);
        table.appendChild(el("tr", {}, [
          el("td", {}, [el("b", { text: x.c.name }), el("small", { text: " " + m.claims + " claims" })]),
          el("td", { className: "num", text: String(m.volume) }),
          el("td", {}, [meter(m.outcomes, m.outcomesInScope, "distinct outcomes for this intervention / outcomes studied for any intervention in scope")]),
          el("td", {}, [meter(m.covered, m.cells, "covered population × outcome cells / all cells (the Gaps grid)")]),
          el("td", {}, [meter(m.fullText, m.claims, "claims extracted from full text / all its claims")]),
          el("td", { className: "num" }, [m.openConflicts.length ? el("button", {
            className: "plink", text: String(m.openConflicts.length), attrs: { type: "button", title: "Open the first in the claim network" },
            on: { click: function () {
              ins.view = "graph"; ins.graphMode = "claims"; ins.selectedRel = m.openConflicts[0]; ins.selected = null;
              ins.relHidden = {}; ins.reviewedOnly = false; renderInsights(); syncUrl();
            } },
          }) : document.createTextNode("0")]),
          el("td", {}, reviews.length ? reviews.map(function (r) {
            return el("div", {}, [certChip(r.rv), el("small", { text: " " + r.rv.batch + " · " + r.hit.length + "/" + m.volume + " papers" })]);
          }) : [el("small", { text: "no review batch" })]),
          el("td", {}, [el("div", { className: "pcmds" }, [
            el("button", { className: "cmdbtn", text: "Gap grid", attrs: { type: "button" }, on: { click: function () {
              ins.view = "gaps"; ins.gapView = "grid"; ins.gapConcept = x.c.id; ins.detail = null; renderInsights(); syncUrl();
            } } }),
            el("button", { className: "cmdbtn", text: "Neighborhood", attrs: { type: "button" }, on: { click: function () { showInGraph("c:" + x.c.id); } } }),
          ])]),
        ]));
      });
      panel.appendChild(el("div", { className: "tablewrap ins-tablewrap" }, [table]));
      panel.appendChild(el("ul", { className: "ins-list formula" }, [
        el("li", { text: "Papers: papers with an active claim whose intervention is this concept (name or alias)." }),
        el("li", { text: "Outcome breadth: its distinct outcomes ÷ outcomes studied for any intervention in scope." }),
        el("li", { text: "Coverage: population × outcome cells with a claim ÷ all cells — the Gaps grid, same rule as /ref:gaps." }),
        el("li", { text: "Full-text share: its claims extracted from full text ÷ all its claims." }),
        el("li", { text: "Open conflicts: unreviewed potential conflicts plus stale contradictions on relations touching the concept." }),
      ]));
    }
    body.appendChild(panel);

    var batches = ((KNOW && KNOW.reviews) || []).map(function (rv) {
      return { rv: rv, inScope: rv.pmids.filter(function (p) { return scope.pmids.has(p); }) };
    }).filter(function (x) { return x.inScope.length; });
    var apanel = el("div", { className: "panel" }, [el("h2", {}, [
      document.createTextNode("Appraisal (/ref:review batches)"), el("span", { text: batches.length + " batch" + (batches.length === 1 ? "" : "es") + " with papers in scope" }),
    ])]);
    apanel.appendChild(el("p", { className: "sub", text: "GRADE certainty is recorded once per review batch for its whole paper set, not per outcome. Domain ratings come from claim fields; most read “insufficient information” by design." }));
    if (!batches.length) {
      var cmd = "/ref:review " + (state.project !== "all" && state.project !== "none" ? "--project " + state.project : "<selector>") + " --batch <label>";
      apanel.appendChild(el("div", { className: "empty" }, [
        document.createTextNode("no appraised review batch covers these papers -- "),
        el("button", { className: "cmdbtn", text: cmd, attrs: { type: "button" }, on: { click: function () { copyText(cmd); } } }),
      ]));
    }
    batches.forEach(function (x) {
      var rv = x.rv, g = rv.grade || {};
      var card = el("div", { className: "conflict review" }, [
        el("div", {}, [certChip(rv), el("b", { text: " " + rv.batch }), el("small", { text: (rv.project ? " · " + rv.project : "") + (rv.resolved_at ? " · " + String(rv.resolved_at).slice(0, 10) : "") })]),
        el("span", { className: "sub", text: "baseline " + String(g.baseline || "?").replace(/_/g, " ") + (g.baseline_reason ? " (" + g.baseline_reason + ")" : "") +
          " · " + (g.downgrades_applied || 0) + " downgrade" + (g.downgrades_applied === 1 ? "" : "s") + " · " + x.inScope.length + "/" + rv.pmids.length + " papers in scope" }),
      ]);
      var factors = el("ul", { className: "ins-list factors" });
      Object.keys(g.factors || {}).forEach(function (f) {
        var fx = g.factors[f];
        var state_ = fx.not_assessed ? "not assessed" : fx.downgrade ? "downgraded" : "no downgrade";
        factors.appendChild(el("li", {}, [
          el("span", { className: "dirtag", attrs: { style: "--c:" + (fx.downgrade ? "var(--warn)" : fx.not_assessed ? "var(--faint)" : "var(--good)") }, text: f.replace(/_/g, " ") + ": " + state_ }),
          el("small", { text: fx.reason || "" }),
        ]));
      });
      card.appendChild(factors);
      var papers = el("ul", { className: "ins-list" });
      x.inScope.forEach(function (pmid) {
        var a = rv.appraisals[pmid];
        var reviewed = a ? Object.keys(a.review_status || {}).filter(function (k) { return k !== "model_draft"; }).reduce(function (s, k) { return s + a.review_status[k]; }, 0) : 0;
        papers.appendChild(el("li", {}, [
          paperButton(pmid),
          el("span", { text: (a && a.checklist ? (CHECKLIST_LABEL[a.checklist] || a.checklist) + " · " : "") + appraisalState(a) }),
          el("small", { text: reviewed ? reviewed + " domain(s) human-reviewed" : "model draft" }),
        ]));
      });
      card.appendChild(papers);
      card.appendChild(el("div", { className: "pcmds" }, [el("button", {
        className: "cmdbtn", text: "Papers (" + x.inScope.length + ")", attrs: { type: "button" },
        on: { click: function () { applyPmidFilter("review " + rv.batch, x.inScope); } },
      })]));
      apanel.appendChild(card);
    });
    body.appendChild(apanel);
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
      L.push("- **" + mdEscape(p.i) + " → " + mdEscape(p.o) + "**: " + DIR_LABEL[dom] +
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

  return {
    ins: ins,
    INSIGHT_VIEWS: INSIGHT_VIEWS,
    render: renderInsights,
    showInGraph: showInGraph,
    // a live refresh: refetch /api/knowledge bypassing the server memo and
    // drop every structure derived from the old payload
    invalidate: function () {
      KNOW = null;
      knowForce = true;
      ins.graphCache = null;
      ins.nbIndex = null;
      ins.cardCache = null;
      ins.clusterMap.cache = null;
    },
  };
};
