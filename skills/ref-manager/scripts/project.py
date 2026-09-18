#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""`/ref:project` — projects/<slug>/{project.yaml,papers.yaml} (§3b, D20).

No YAML dependency (D: minimize deps) — these are JSON files with a .yaml
extension per PLAN.md's naming, written/read as JSON. Simple enough not to
need a real YAML lib; revisit if PLAN.md later requires hand-editing.

Membership references a paper once per project; relevance/priority/reading
state live on that membership record, independently of every other
project's membership for the same paper (§3b — this is the phase-1 gate's
"one paper belongs to two projects with independent state" requirement).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lib_atomic import atomic_write_json, now_iso, read_json
from lib_ids import allocate_slug, check_question_id, SlugError
from lib_selector import source_badge
from lib_schema import validate_project, SchemaError

READING_STATES = ("to_screen", "to_read", "reading", "read")

# Reason chips the Triage tab offers per decision (PUBMED_TRIAGE_IMPLEMENTATION_PLAN.md
# P3). A project overrides a decision's list with `screening_reasons` in
# project.yaml; decisions it doesn't mention keep these defaults. The
# excluded list follows common PRISMA 2020 full-text exclusion categories.
DEFAULT_SCREENING_REASONS = {
    "excluded": [
        "wrong population", "wrong intervention or exposure", "wrong comparator", "wrong outcome",
        "wrong study design", "not primary research", "not peer reviewed", "duplicate",
    ],
    "pending": ["needs full text", "unclear eligibility"],
    "included": [],
}
MAX_REASON_CHARS = 120
MAX_REASONS_PER_DECISION = 20

# Starter templates (UX_BACKLOG.md "Project starter templates") -- each
# `next_steps` entry is copied verbatim from that command's own doc
# (docs/tutorials/systematic-review.html, docs/tutorials/thesis-chapter.html),
# not invented here. A template only stamps which workflow this project
# follows and prints its proven command sequence after `create`; it never
# pre-fills scope/questions with placeholder research content -- that's
# always the user's own topic, not the tool's to guess.
TEMPLATES = {
    "systematic-review": {
        "description": "saved search -> screen -> full text -> PRISMA flow -> appraised review",
        "next_steps": [
            '/ref:search-pubmed "<question>" --slug <query-slug> --create',
            "/ref:add <pmid...>",
            "/ref:project add-paper <slug> <pmid>",
            '/ref:screen --project <slug> --pmid <pmid> --decision included|excluded --reason "<text>"',
            "/ref:fetch <pmid...>",
            "/ref:review --prisma --project <slug> --query <query-slug>",
            "/ref:review --project <slug> --screened included --batch <label>",
        ],
    },
    "thesis-chapter": {
        "description": "one research question, ~20 papers, extracted claims verified into a defensible paragraph",
        "next_steps": [
            '/ref:project add-question <slug> --id q1 --text "<your research question>"',
            "/ref:add <pmid...>",
            "/ref:project add-paper <slug> <pmid>",
            "/ref:extract <pmid...>",
            "/ref:verify claim <pmid> <claim_id> accept|edit|reject",
            "/ref:compare --project <slug> --batch <label>",
            '/ref:ask "<question>" --project <slug>',
        ],
    },
}


def _project_dir(library_root: Path, slug: str) -> Path:
    return library_root / "projects" / slug


def _paper_source_badge(library_root: Path, pmid: str) -> str:
    paper_dir = library_root / "papers" / pmid
    meta = read_json(paper_dir / "meta.json")
    return source_badge(paper_dir, meta) if meta else "metadata-only"


def _paper_source_counts(library_root: Path, papers: list[dict]) -> dict[str, int]:
    counts = {
        "metadata_only": 0,
        "abstract_only": 0,
        "full_text": 0,
        "pdf_backed": 0,
        "oa_pending": 0,
    }
    for paper in papers:
        badge = _paper_source_badge(library_root, str(paper["pmid"]))
        counts[badge.replace("-", "_")] += 1
    return counts


def create(library_root: Path, slug: str, scope: str | None, *, template: str | None = None) -> dict:
    if template is not None and template not in TEMPLATES:
        raise SchemaError(f"template must be one of {sorted(TEMPLATES)}, got {template!r}")
    allocate_slug(library_root, "project", slug)  # validates + refuses collision
    pdir = _project_dir(library_root, slug)
    pdir.mkdir(parents=True)
    project = {"slug": slug, "scope": scope, "questions": []}
    if template is not None:
        project["template"] = template
    validate_project(project)
    atomic_write_json(pdir / "project.yaml", project)
    atomic_write_json(pdir / "papers.yaml", {"papers": []})
    return project


def add_question(library_root: Path, slug: str, qid: str, text: str) -> dict:
    pdir = _project_dir(library_root, slug)
    project_path = pdir / "project.yaml"
    if not project_path.exists():
        raise SlugError(f"project {slug!r} does not exist")
    project = json.loads(project_path.read_text())
    check_question_id(project, qid)  # scoped per-project (§3d)
    project["questions"].append({"id": qid, "text": text})
    validate_project(project)
    atomic_write_json(project_path, project)
    return project


def _question_ids(library_root: Path, slug: str) -> set[str]:
    project_path = _project_dir(library_root, slug) / "project.yaml"
    if not project_path.exists():
        raise SlugError(f"project {slug!r} does not exist")
    return {q["id"] for q in json.loads(project_path.read_text()).get("questions", [])}


def _validate_question_ids(library_root: Path, slug: str, qids: list[str]) -> None:
    """phase 5 §1: every `questions` entry on a membership record (or a
    brief's `question_id`) must name a question that actually exists on
    this project -- `lib_ids.check_question_id()` checks the opposite
    direction (a *new* id doesn't collide), so this is its own small
    lookup rather than a reuse."""
    known = _question_ids(library_root, slug)
    bad = sorted(set(qids) - known)
    if bad:
        raise SchemaError(f"unknown question id(s) for project {slug!r}: {', '.join(bad)}")


def add_paper(
    library_root: Path, slug: str, pmid: str, relevance: str | None,
    priority: int | None, reading_status: str | None,
    questions: list[str] | None = None,
) -> dict:
    pdir = _project_dir(library_root, slug)
    papers_path = pdir / "papers.yaml"
    if not papers_path.exists():
        raise SlugError(f"project {slug!r} does not exist")
    if reading_status is not None and reading_status not in READING_STATES:
        raise SchemaError(f"reading_status must be one of {READING_STATES}")
    if questions:
        _validate_question_ids(library_root, slug, questions)

    doc = read_json(papers_path, {"papers": []})
    for m in doc["papers"]:
        if m["pmid"] == pmid:
            return m  # already a member; membership references a paper once (§3b)

    membership = {
        "pmid": pmid,
        "relevance": relevance,
        "priority": priority,
        "reading_status": reading_status,
        "why_saved": None,
        "screening": None,
        "added_at": now_iso(),
        # phase 5 §1: which of the project's questions this paper answers;
        "questions": list(dict.fromkeys(questions or [])),
    }
    doc["papers"].append(membership)
    atomic_write_json(papers_path, doc)
    return membership


def set_paper_questions(
    library_root: Path, slug: str, pmid: str,
    add: list[str] | None = None, remove: list[str] | None = None,
) -> dict:
    """phase 5 §2/§6: `/ref:queue set --question/--no-question` and the
    dashboard's single + bulk question-assign POSTs all go through this --
    same add/remove-by-list shape either way."""
    papers_path = _project_dir(library_root, slug) / "papers.yaml"
    if not papers_path.exists():
        raise SlugError(f"project {slug!r} does not exist")
    add = add or []
    remove = remove or []
    if add:
        _validate_question_ids(library_root, slug, add)

    doc = read_json(papers_path, {"papers": []})
    for m in doc["papers"]:
        if m["pmid"] == pmid:
            current = list(m.get("questions") or [])
            for q in add:
                if q not in current:
                    current.append(q)
            current = [q for q in current if q not in remove]
            m["questions"] = current
            atomic_write_json(papers_path, doc)
            return m
    raise SchemaError(f"pmid {pmid!r} is not a member of project {slug!r} (add it first via /ref:project)")


def screening_reasons(library_root: Path, slug: str | None) -> dict[str, list[str]]:
    """Effective reason chips: the project's overrides on top of the defaults.
    `slug=None` (a triage with no project) or a missing project gives the
    defaults."""
    out = {k: list(v) for k, v in DEFAULT_SCREENING_REASONS.items()}
    if slug:
        project_path = _project_dir(library_root, slug) / "project.yaml"
        if project_path.exists():
            custom = json.loads(project_path.read_text()).get("screening_reasons") or {}
            for decision, items in custom.items():
                if decision in out and isinstance(items, list):
                    out[decision] = [i for i in items if isinstance(i, str)]
    return out


def set_reasons(library_root: Path, slug: str, decision: str, reasons: list[str] | None) -> dict:
    """Replace one decision's reason chips for a project; `reasons=None`
    drops the override so the defaults apply again."""
    project_path = _project_dir(library_root, slug) / "project.yaml"
    if not project_path.exists():
        raise SlugError(f"project {slug!r} does not exist")
    if decision not in DEFAULT_SCREENING_REASONS:
        raise SchemaError(f"decision must be one of {sorted(DEFAULT_SCREENING_REASONS)}")
    project = json.loads(project_path.read_text())
    custom = dict(project.get("screening_reasons") or {})
    if reasons is None:
        custom.pop(decision, None)
    else:
        clean = list(dict.fromkeys(" ".join(r.split()) for r in reasons if r and r.strip()))
        if len(clean) > MAX_REASONS_PER_DECISION:
            raise SchemaError(f"at most {MAX_REASONS_PER_DECISION} reasons per decision")
        too_long = [r for r in clean if len(r) > MAX_REASON_CHARS]
        if too_long:
            raise SchemaError(f"reason longer than {MAX_REASON_CHARS} characters: {too_long[0]!r}")
        custom[decision] = clean
    if custom:
        project["screening_reasons"] = custom
    else:
        project.pop("screening_reasons", None)
    validate_project(project)
    atomic_write_json(project_path, project)
    return {"slug": slug, "screening_reasons": screening_reasons(library_root, slug)}


def linked_triages(library_root: Path, slug: str) -> list[str]:
    """Saved-search triages linked to this project. Derived from
    triage/*/triage.json -- project.yaml has no triage field
    (PUBMED_TRIAGE_IMPLEMENTATION_PLAN.md §4.1)."""
    base = library_root / "triage"
    if not base.is_dir():
        return []
    out = []
    for p in sorted(base.glob("*/triage.json")):
        try:
            if json.loads(p.read_text()).get("project") == slug:
                out.append(p.parent.name)
        except ValueError:
            continue
    return out


def show(library_root: Path, slug: str) -> dict:
    pdir = _project_dir(library_root, slug)
    project_path = pdir / "project.yaml"
    if not project_path.exists():
        raise SlugError(f"project {slug!r} does not exist")
    papers_doc = read_json(pdir / "papers.yaml", {"papers": []})
    papers = papers_doc.get("papers", [])
    reading = {"to_screen": 0, "to_read": 0, "reading": 0, "read": 0}
    for paper in papers:
        status = paper.get("reading_status")
        if status in reading:
            reading[status] += 1
    source = _paper_source_counts(library_root, papers)
    return {
        "project": json.loads(project_path.read_text()),
        "papers": papers_doc,
        "triages": linked_triages(library_root, slug),
        "screening_reasons": screening_reasons(library_root, slug),
        "summary": {
            "paper_count": len(papers),
            "reading": reading,
            "source": source,
            "question_count": len(json.loads(project_path.read_text()).get("questions", [])),
        },
    }


def dashboard_summary(library_root: Path, slug: str) -> dict:
    """Everything the dashboard's Projects folder tree/Summary needs for one
    project (DASHBOARD_NAV_IMPLEMENTATION_PLAN.md phase 3 §3.1) -- `show()`
    plus the template's `next_steps` and a reading-queue slice. Linked-query
    counts are attached by `dashboard.py` (needs `triage.py`, which already
    imports `project`, so it can't be reused the other way round)."""
    info = show(library_root, slug)
    proj = info["project"]
    template = proj.get("template")
    members = info["papers"].get("papers", [])
    papers = sorted(members, key=lambda m: (m.get("priority") is None, m.get("priority")))
    # phase 5 §5: per-question paper counts (D8) -- "unassigned" is members
    # with no `questions` at all, not a question id of its own.
    question_counts = {q["id"]: 0 for q in proj.get("questions", [])}
    unassigned = 0
    for m in members:
        qids = m.get("questions") or []
        if not qids:
            unassigned += 1
        for qid in qids:
            if qid in question_counts:
                question_counts[qid] += 1
    questions = [dict(q, paper_count=question_counts.get(q["id"], 0)) for q in proj.get("questions", [])]
    return {
        "slug": proj["slug"],
        "scope": proj.get("scope"),
        "template": template,
        "next_steps": TEMPLATES[template]["next_steps"] if template in TEMPLATES else [],
        "questions": questions,
        "unassigned_papers": unassigned,
        "summary": info["summary"],
        "screening_reasons": info["screening_reasons"],
        "reading_queue": [
            {"pmid": m["pmid"], "priority": m.get("priority"), "why_saved": m.get("why_saved"),
             "reading_status": m.get("reading_status")}
            for m in papers[:20]
        ],
        # phase 5 §5: full membership (Papers subtab, D8's question chip row)
        # -- `reading_queue` above stays a short "what to read next" slice.
        "papers": [
            {"pmid": m["pmid"], "priority": m.get("priority"), "why_saved": m.get("why_saved"),
             "reading_status": m.get("reading_status"), "questions": m.get("questions") or []}
            for m in papers
        ],
        "triage_slugs": info["triages"],
    }


def list_projects(library_root: Path) -> list[dict]:
    projects_dir = library_root / "projects"
    out = []
    if projects_dir.is_dir():
        for pdir in sorted(projects_dir.iterdir()):
            p = pdir / "project.yaml"
            if p.exists():
                proj = json.loads(p.read_text())
                papers_path = pdir / "papers.yaml"
                papers_doc = read_json(papers_path, {"papers": []}) if papers_path.exists() else {"papers": []}
                papers = papers_doc.get("papers", [])
                reading = {"to_screen": 0, "to_read": 0, "reading": 0, "read": 0}
                for paper in papers:
                    status = paper.get("reading_status")
                    if status in reading:
                        reading[status] += 1
                source = _paper_source_counts(library_root, papers)
                out.append({
                    "slug": proj["slug"],
                    "scope": proj.get("scope"),
                    "questions": len(proj["questions"]),
                    "papers": len(papers),
                    "reading": reading,
                    "source": source,
                })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["create", "add-question", "add-paper", "show", "list", "templates", "set-reasons"])
    ap.add_argument("--repo")
    ap.add_argument("--slug")
    ap.add_argument("--scope")
    ap.add_argument("--template", choices=sorted(TEMPLATES))
    ap.add_argument("--question-id")
    ap.add_argument("--text")
    ap.add_argument("--pmid")
    ap.add_argument("--relevance")
    ap.add_argument("--priority", type=int)
    ap.add_argument("--reading-status")
    ap.add_argument("--question", action="append", help="add-paper: link the paper to this project question; repeatable (phase 5 §2)")
    ap.add_argument("--decision", choices=sorted(DEFAULT_SCREENING_REASONS), help="set-reasons: which decision's chips")
    ap.add_argument("--reason", action="append", help="set-reasons: one chip; repeatable, in display order")
    ap.add_argument("--reset", action="store_true", help="set-reasons: go back to the default chips")
    args = ap.parse_args()

    if args.action == "templates":
        print(json.dumps(
            {name: t["description"] for name, t in TEMPLATES.items()}, indent=2,
        ))
        return 0

    if not args.repo:
        print("error: --repo is required", file=sys.stderr)
        return 1
    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    try:
        if args.action == "create":
            result = create(library_root, args.slug, args.scope, template=args.template)
            if args.template:
                result = {
                    **result,
                    "next_steps": [
                        step.replace("<slug>", args.slug) for step in TEMPLATES[args.template]["next_steps"]
                    ],
                }
        elif args.action == "add-question":
            result = add_question(library_root, args.slug, args.question_id, args.text)
        elif args.action == "add-paper":
            result = add_paper(library_root, args.slug, args.pmid, args.relevance, args.priority, args.reading_status, questions=args.question)
        elif args.action == "show":
            result = show(library_root, args.slug)
        elif args.action == "set-reasons":
            if not args.decision or (args.reset == bool(args.reason)):
                print("error: set-reasons needs --decision and either --reason ... or --reset", file=sys.stderr)
                return 1
            result = set_reasons(library_root, args.slug, args.decision, None if args.reset else args.reason)
        else:
            result = list_projects(library_root)
    except (SlugError, SchemaError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
