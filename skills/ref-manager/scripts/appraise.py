#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Advanced `/ref:review` -- GRADE certainty + risk-of-bias appraisal (§5a,
D15, PLAN.md phase 10). A sibling mode to prisma.py's `--prisma`; this
module never touches prisma.py.

**Gate check first, always** (§8 phase-10 row): before generating anything,
inspect the resolved selector's `by_extraction_tier` report. Wholly
abstract-tier -> refuse outright, no appraisal content generated (RoB2/NOS/
AMSTAR-2/GRADE all need full-text detail this library doesn't have for an
abstract-only paper). Mixed -> appraise the full-tier papers, flag each
abstract-tier paper's appraisal as `insufficient_information` rather than
silently skipping or silently appraising it.

**Checklist selection by study_type** (the claim schema's own field, set by
phase 4 extraction): rct -> RoB 2 (5 domains), cohort/case_control ->
Newcastle-Ottawa (3 star-rated categories), meta_analysis -> AMSTAR-2 (a
representative subset of items, not all 16 -- see AMSTAR2_ITEMS). Other
study types get a general note, never a forced-fit rating.

**Honesty constraint that shapes most of this module**: the phase-4 claim
schema (population/intervention/comparator/outcome/timepoint/direction/
effect_value/effect_measure/uncertainty_interval/study_design/
cohort_identity/adjustment_context) captures PICO+ outcome data, NOT
methodological-quality signals like randomization concealment, blinding, or
protocol registration. Most RoB2/AMSTAR-2 domains therefore legitimately
land on `insufficient_information` -- that is the honest, correct output
given what this schema captures, not a shortfall of this module. A handful
of domains DO map onto real claim fields (RoB2 measurement-of-outcome onto
outcome+effect_measure; NOS comparability onto adjustment_context) and use
them; everything else states plainly that the claim schema doesn't capture
that signal.

**Model draft vs. human-reviewed** (§3b, same pattern as claims/identity/
grants/authorship): every domain this module generates is a DRAFT. Review
happens through verify.py's existing per-PMID corrections.json mechanism
with a new "appraisal" target_type (target_id = "<pmid>:<domain_key>") --
an appraisal judges ONE paper's risk of bias, so it fits corrections.json's
per-PMID shape even when that paper is part of a multi-paper GRADE rating.
The cross-paper GRADE certainty rating itself is NOT per-PMID and has no
corrections.json home -- it's part of the persisted review artifact
directly, the same way phase 8's cross-paper relation review lives on the
relation record itself rather than in any one paper's corrections.json.

Freeze contract: projects/<slug>/reviews/<batch>/ or a library-root
reviews/<batch>/ fallback (project-less selector), same reused-unless-
refresh idiom as compare.py/summarize.py.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from lib_atomic import atomic_write_json, atomic_write_text, now_iso
from okf_emit import _fm
from lib_selector import resolve_from_args, add_selector_args, SelectorError, paper_meta
from lib_verify_link import load_corrections, active_claims
from lib_schema import clean_claim_value
from relation import list_relations


def _study_type(claims: list[dict]) -> str:
    if not claims:
        return "unknown"
    types = [c.get("study_type", "unknown") for c in claims]
    return max(set(types), key=types.count)


# --------------------------------------------------------------- RoB 2 (RCT)

ROB2_DOMAINS = (
    "randomization_process", "deviations_from_intended_interventions",
    "missing_outcome_data", "measurement_of_outcome", "selection_of_reported_result",
)


def _domain(rating: str, claim_ids: list[str], note: str) -> dict:
    return {"rating": rating, "claim_ids": claim_ids, "note": note, "review_status": "model_draft"}


# Signals that can push a RoB 2 domain to "high" (a draft must be able to say
# high, or an RCT could never trigger GRADE's risk-of-bias downgrade).
NON_RANDOM = r"quasi[- ]?random|non[- ]?randomi[sz]|not randomi[sz]|alternat(e|ing) allocation|allocated by (date|birth|record|day)"
ATTRITION = r"drop(ped|s)?[\s-]?outs?|attrition|lost to follow|loss to follow|withdrew|discontinued"
HIGH_ATTRITION_PCT = 20.0  # RoB 2 fixes no threshold; 20% is the common rule of thumb


def _attrition_pct(text: str) -> float | None:
    """Largest attrition proportion stated near an attrition phrase:
    "15%" or "9 of 60". None when no number is given."""
    best = None
    for m in re.finditer(ATTRITION, text, re.I):
        window = text[max(0, m.start() - 60):m.end() + 60]
        for pct in re.findall(r"(\d+(?:\.\d+)?)\s*%", window):
            best = max(best or 0.0, float(pct))
        for num, den in re.findall(r"(\d+)\s*(?:of|/|out of)\s*(\d+)", window):
            if int(den) > 0 and int(num) <= int(den):
                best = max(best or 0.0, 100.0 * int(num) / int(den))
    return best


def rob2_appraisal(claims: list[dict]) -> dict:
    domains = {}

    def design_text(c):
        return (c.get("study_design") or "") + " " + (c.get("evidence_span") or "")

    non_random = [c for c in claims if re.search(NON_RANDOM, design_text(c), re.I)]
    rand = [c for c in claims if re.search(r"randomi[sz]", design_text(c), re.I)]
    if non_random:
        domains["randomization_process"] = _domain(
            "high", [c["claim_id"] for c in non_random],
            "study_design/evidence_span describes non-random or quasi-random allocation")
    elif rand:
        domains["randomization_process"] = _domain(
            "low", [c["claim_id"] for c in rand],
            "study_design/evidence_span mentions randomization")
    else:
        domains["randomization_process"] = _domain(
            "insufficient_information", [],
            "no claim's study_design/evidence_span mentions randomization")

    domains["deviations_from_intended_interventions"] = _domain(
        "insufficient_information", [],
        "claim schema does not capture protocol adherence/deviations")

    attrition = [c for c in claims if re.search(ATTRITION, c.get("evidence_span") or "", re.I)]
    if attrition:
        pcts = [p for p in (_attrition_pct(c.get("evidence_span") or "") for c in attrition) if p is not None]
        worst = max(pcts) if pcts else None
        if worst is not None and worst >= HIGH_ATTRITION_PCT:
            domains["missing_outcome_data"] = _domain(
                "high", [c["claim_id"] for c in attrition],
                f"evidence_span reports {worst:.0f}% attrition (>= {HIGH_ATTRITION_PCT:.0f}%)")
        else:
            detail = f"{worst:.0f}% attrition" if worst is not None else "attrition, no proportion stated"
            domains["missing_outcome_data"] = _domain(
                "some_concerns", [c["claim_id"] for c in attrition],
                f"evidence_span mentions dropout/attrition/loss to follow-up ({detail})")
    else:
        domains["missing_outcome_data"] = _domain(
            "insufficient_information", [],
            "no claim's evidence_span mentions dropout/attrition")

    measured = [c for c in claims if c.get("outcome", "unknown") != "unknown" and c.get("effect_measure", "unknown") != "unknown"]
    if measured:
        domains["measurement_of_outcome"] = _domain(
            "low", [c["claim_id"] for c in measured],
            "outcome and effect_measure are both defined")
    else:
        domains["measurement_of_outcome"] = _domain(
            "insufficient_information", [],
            "outcome and/or effect_measure are unknown for every active claim")

    domains["selection_of_reported_result"] = _domain(
        "insufficient_information", [],
        "claim schema does not capture pre-registration/selective-reporting signals")

    return {"checklist": "RoB2", "domains": domains}


# --------------------------------------------------- Newcastle-Ottawa (cohort/case-control)

UNADJUSTED = r"^(none|no adjustment|not adjusted|unadjusted|crude)\b"


def _known(c: dict, field: str) -> bool:
    return clean_claim_value(c.get(field)) is not None


def nos_appraisal(claims: list[dict]) -> dict:
    """Each category carries `assessable`: False when its stars are 0 only
    because the claims don't record the signal. Only an assessable 0-star
    category (e.g. an explicitly unadjusted analysis) is a real finding --
    appraisal_signal() reads just those as high risk."""
    domains = {}

    defined_pop = [c for c in claims if _known(c, "population")]
    defined_cohort = [c for c in claims if _known(c, "cohort_identity")]
    sel_ids = [c["claim_id"] for c in (defined_pop or defined_cohort)]
    stars = (1 if defined_pop else 0) + (1 if defined_cohort else 0)
    domains["selection"] = {
        "stars_awarded": stars, "stars_max": 4, "claim_ids": sel_ids, "assessable": stars > 0,
        "note": ("population and/or cohort_identity are defined (partial signal only -- "
                 "remaining selection sub-items, e.g. non-exposed cohort selection/ascertainment "
                 "of exposure, are not captured by the claim schema)" if stars
                 else "population and cohort_identity unknown for every active claim -- not assessable"),
        "review_status": "model_draft",
    }

    # The extractor writes the literal "unknown" when a field isn't stated, so
    # "none" here means the paper says it didn't adjust -- read the raw value
    # before clean_claim_value() folds "none" into the placeholders.
    unadjusted = [c for c in claims
                  if isinstance(c.get("adjustment_context"), str)
                  and re.search(UNADJUSTED, c["adjustment_context"].strip(), re.I)]
    adjusted = [c for c in claims if _known(c, "adjustment_context") and c not in unadjusted]
    if adjusted:
        comparability = {"stars_awarded": 2, "claim_ids": [c["claim_id"] for c in adjusted], "assessable": True,
                         "note": "adjustment_context names confounders adjusted for"}
    elif unadjusted:
        comparability = {"stars_awarded": 0, "claim_ids": [c["claim_id"] for c in unadjusted], "assessable": True,
                         "note": "adjustment_context states the analysis was unadjusted"}
    else:
        comparability = {"stars_awarded": 0, "claim_ids": [], "assessable": False,
                         "note": "adjustment_context is unknown for every active claim -- comparability not assessable"}
    domains["comparability"] = {**comparability, "stars_max": 2, "review_status": "model_draft"}

    outcome_defined = [c for c in claims if _known(c, "outcome") and _known(c, "effect_measure")]
    domains["outcome_exposure"] = {
        "stars_awarded": 1 if outcome_defined else 0, "stars_max": 3,
        "claim_ids": [c["claim_id"] for c in outcome_defined], "assessable": bool(outcome_defined),
        "note": ("outcome and effect_measure are defined (partial signal only -- assessment of "
                 "outcome/adequacy of follow-up length and completeness are not captured)"
                 if outcome_defined else "outcome/effect_measure unknown -- not assessable"),
        "review_status": "model_draft",
    }

    return {"checklist": "Newcastle-Ottawa", "domains": domains}


# ------------------------------------------------------- AMSTAR-2 (meta-analysis)

# (key, critical, "yes" pattern, "no" pattern). The "no" pattern is checked
# first: a stated shortcoming beats a passing mention of the same topic.
AMSTAR2_ITEMS = (
    ("protocol_registered_prior", True, r"PROSPERO|protocol.{0,20}regist",
     r"(no|without( a)?) (a priori |prior |pre-?registered )?protocol|not (prospectively )?registered|unregistered"),
    ("adequate_literature_search", True, r"systematic search|PRISMA|search strategy",
     r"single (electronic )?database|only one database|no grey literature|English[- ]language (studies |articles )?only"),
    ("study_selection_duplicate", False, r"independent(ly)?.{0,20}(screen|select)|duplicate.{0,20}(screen|select)",
     r"(single|one) (reviewer|author) (screened|selected)|screened by (a single|one) (reviewer|author)"),
    ("list_of_excluded_studies", False, r"excluded stud",
     r"(no|without( a)?) list of excluded|excluded studies (were )?not (listed|reported)"),
    ("risk_of_bias_assessment_included_studies", True, r"risk of bias|quality assess",
     r"(risk of bias|quality) (was |were )?not (formally )?assessed|did not assess (the )?(risk of bias|quality)|no (risk of bias|quality) assessment"),
    ("risk_of_bias_accounted_in_results", True, r"risk of bias.{0,40}(interpret|discuss|result)",
     r"(did not|without) (consider|account for|discuss)(ing)? (the )?risk of bias"),
    ("publication_bias_assessed", False, r"funnel plot|publication bias|Egger",
     r"publication bias (was |were )?not (formally )?assessed|did not assess publication bias|too few studies (to|for) (assess|funnel)"),
)


def amstar2_appraisal(claims: list[dict]) -> dict:
    items = {}
    for key, critical, yes_pattern, no_pattern in AMSTAR2_ITEMS:
        spans = [(c["claim_id"], c.get("evidence_span") or "") for c in claims]
        no_hits = [cid for cid, s in spans if re.search(no_pattern, s, re.I)]
        yes_hits = [cid for cid, s in spans if re.search(yes_pattern, s, re.I)]
        if no_hits:
            items[key] = {"rating": "no", "critical": critical, "claim_ids": no_hits,
                          "note": f"evidence_span states a shortcoming for {key}", "review_status": "model_draft"}
        elif yes_hits:
            items[key] = {"rating": "yes", "critical": critical, "claim_ids": yes_hits,
                          "note": f"evidence_span matches expected signal for {key}", "review_status": "model_draft"}
        else:
            items[key] = {"rating": "insufficient_information", "critical": critical, "claim_ids": [],
                          "note": "no claim's evidence_span matches the expected signal; claim schema "
                                  "does not otherwise capture this AMSTAR-2 item", "review_status": "model_draft"}

    assessed = [i for i in items.values() if i["rating"] != "insufficient_information"]
    critical_no = [k for k, i in items.items() if i["critical"] and i["rating"] == "no"]
    critical_unknown = [k for k, i in items.items() if i["critical"] and i["rating"] == "insufficient_information"]
    noncritical_no = [k for k, i in items.items() if not i["critical"] and i["rating"] == "no"]
    if not assessed:
        overall = "insufficient_information"
        overall_note = "every item is insufficient_information -- overall confidence not assessable from library data"
    elif critical_no:
        overall = "critically_low"
        overall_note = f"critical item(s) rated no: {critical_no}"
    elif critical_unknown:
        # Standard AMSTAR-2 can't rate above critically_low without knowing
        # every critical item, so a missing one leaves the rating open rather
        # than letting it default to high.
        overall = "insufficient_information"
        overall_note = (f"critical item(s) not confirmed: {critical_unknown} -- overall confidence "
                        "not assessable until they are reviewed")
    else:
        if len(noncritical_no) > 1:
            overall = "low"
        elif len(noncritical_no) == 1:
            overall = "moderate"
        else:
            overall = "high"
        overall_note = "every critical item confirmed; standard AMSTAR-2 logic over the non-critical items"

    return {"checklist": "AMSTAR-2", "items": items, "overall_confidence": overall, "overall_note": overall_note}


CHECKLIST_BY_STUDY_TYPE = {
    "rct": rob2_appraisal,
    "cohort": nos_appraisal,
    "case_control": nos_appraisal,
    "meta_analysis": amstar2_appraisal,
}


def merge_appraisal_review(library_root: Path, pmid: str, draft: dict) -> dict:
    """Overlay verify.py's per-PMID "appraisal" corrections onto a freshly
    generated draft: any domain/item with a recorded review decision shows
    human_confirmed/human_edited/human_rejected instead of model_draft."""
    corrections = load_corrections(library_root, pmid)
    by_target = {}
    for c in corrections:
        if c.get("target_type") != "appraisal":
            continue
        by_target.setdefault(c["target_id"], []).append(c)

    def _apply(container: dict, checklist_key: str):
        for key, entry in container.items():
            target_id = f"{pmid}:{checklist_key}:{key}"
            decisions = by_target.get(target_id)
            if not decisions:
                continue
            latest = decisions[-1]
            if latest["decision"] == "accept":
                entry["review_status"] = "human_confirmed"
            elif latest["decision"] == "edit":
                entry["review_status"] = "human_edited"
                replacement = latest.get("replacement_value") or {}
                if "note" not in replacement:
                    # the machine note explained the draft rating, which the
                    # edit has replaced -- keep it, but out of the `note` slot
                    entry["draft_note"] = entry.get("note")
                    entry["note"] = latest.get("rationale") or entry.get("note")
                entry.update(replacement)
                if "stars_awarded" in replacement:
                    entry["assessable"] = True  # a human scored it
            elif latest["decision"] == "reject":
                entry["review_status"] = "human_rejected"
            entry["review_rationale"] = latest.get("rationale")
            entry["reviewer"] = latest.get("reviewer")

    if "domains" in draft:
        _apply(draft["domains"], draft.get("checklist", ""))
    if "items" in draft:
        _apply(draft["items"], draft.get("checklist", ""))
    return draft


def draft_appraisal_for_pmid(library_root: Path, pmid: str) -> dict:
    meta = paper_meta(library_root, pmid) or {}
    if meta.get("extraction_tier") != "full":
        return {
            "pmid": pmid, "checklist": None, "insufficient_information": True,
            "reason": f"extraction_tier={meta.get('extraction_tier')!r} -- full text required for appraisal",
        }
    claims = active_claims(library_root, pmid)
    study_type = _study_type(claims)
    fn = CHECKLIST_BY_STUDY_TYPE.get(study_type)
    if fn is None:
        return {
            "pmid": pmid, "checklist": None, "study_type": study_type,
            "note": f"no standard checklist (RoB2/NOS/AMSTAR-2) applies to study_type={study_type!r} "
                    "(§5a division of labour maps checklists to rct/cohort/case_control/meta_analysis only)",
        }
    draft = fn(claims)
    draft["pmid"] = pmid
    draft["study_type"] = study_type
    return merge_appraisal_review(library_root, pmid, draft)


# --------------------------------------------------------------- GRADE (set-level)

def _relevant_relations(library_root: Path, pmids: set[str]) -> list[dict]:
    out = []
    for r in list_relations(library_root):
        rel_pmids = {sc["pmid"] for sc in r.get("supporting_claims", [])}
        if rel_pmids & pmids:
            out.append(r)
    return out


def appraisal_signal(a: dict) -> dict:
    """One paper's appraisal read as GRADE's risk-of-bias factor reads it:
    `assessed` when any domain/item carries a real rating, `high_risk` when
    one is high (RoB2), zero stars (NOS) or critically_low (AMSTAR-2).
    Each checklist shape needs its own reading: RoB2/NOS use "domains"
    (RoB2 domains carry "rating", NOS domains carry "stars_awarded"/
    "stars_max" instead -- no "rating" key at all), AMSTAR-2 uses "items"
    plus a top-level "overall_confidence"."""
    if a.get("insufficient_information") or a.get("checklist") is None:
        return {"assessed": False, "high_risk": False}
    high = False
    assessed = False
    for d in a.get("domains", {}).values():
        if "stars_awarded" in d:  # NOS star-rated domain
            # 0 stars is high risk only when assessable -- a 0 that just means
            # "the claims don't record this" is not evidence of bias. Records
            # written before `assessable` existed read as assessable.
            if d["stars_max"] > 0 and d.get("assessable", True):
                assessed = True
                if d["stars_awarded"] == 0:
                    high = True
        else:  # RoB2 rating domain
            rating = d.get("rating")
            if rating and rating != "insufficient_information":
                assessed = True
                if rating in ("high",):
                    high = True
    for it in a.get("items", {}).values():  # AMSTAR-2 items
        rating = it.get("rating")
        if rating and rating != "insufficient_information":
            assessed = True
    if a.get("overall_confidence") not in (None, "insufficient_information"):
        assessed = True
        if a["overall_confidence"] == "critically_low":
            high = True
    return {"assessed": assessed, "high_risk": high}


def grade_certainty(library_root: Path, pmids: list[str], appraisals: dict[str, dict]) -> dict:
    all_claims = []
    for pmid in pmids:
        all_claims.extend(active_claims(library_root, pmid))

    study_types = {c.get("study_type", "unknown") for c in all_claims}
    baseline = "high" if study_types and study_types <= {"rct"} else "low"

    factors = {}

    # 1. risk of bias: an explicit "high"/"critically_low" signal downgrades;
    # if every paper's appraisal is unassessable, this factor is not_assessed
    # (per-paper reading: appraisal_signal()).
    high_risk_pmids = []
    any_assessed = False
    for pmid, a in appraisals.items():
        signal = appraisal_signal(a)
        if signal["high_risk"]:
            high_risk_pmids.append(pmid)
        if signal["assessed"]:
            any_assessed = True
    if not any_assessed:
        factors["risk_of_bias"] = {"downgrade": False, "not_assessed": True,
                                     "reason": "no paper's appraisal produced an assessable (non-insufficient) domain"}
    elif high_risk_pmids:
        factors["risk_of_bias"] = {"downgrade": True, "not_assessed": False,
                                     "reason": f"high/critically_low rated domain(s) in {sorted(high_risk_pmids)}"}
    else:
        factors["risk_of_bias"] = {"downgrade": False, "not_assessed": False,
                                     "reason": "assessed domains show no high/critically_low rating"}

    # 2. inconsistency: potential_conflict/contradicts relation among the appraised papers
    relevant = _relevant_relations(library_root, set(pmids))
    conflicts = [r for r in relevant if r["type"] in ("potential_conflict", "contradicts") and not r.get("stale")]
    if relevant:
        factors["inconsistency"] = {
            "downgrade": bool(conflicts), "not_assessed": False,
            "reason": (f"conflicting relation(s): {[r['relation_id'] for r in conflicts]}" if conflicts
                       else "relation graph checked, no unresolved conflict among these papers"),
        }
    else:
        factors["inconsistency"] = {"downgrade": False, "not_assessed": True,
                                      "reason": "no relation-graph data available for these papers"}

    # 3. imprecision: every claim reports an uncertainty interval?
    with_ui = [c for c in all_claims if c.get("uncertainty_interval", "unknown") != "unknown"]
    if not all_claims:
        factors["imprecision"] = {"downgrade": False, "not_assessed": True, "reason": "no active claims to assess"}
    elif not with_ui:
        factors["imprecision"] = {"downgrade": True, "not_assessed": False,
                                    "reason": "no active claim reports an uncertainty interval (CI/SE/p-value)"}
    else:
        factors["imprecision"] = {"downgrade": False, "not_assessed": False,
                                    "reason": f"{len(with_ui)}/{len(all_claims)} claims report an uncertainty interval"}

    # 4. indirectness: population/intervention/outcome/comparator consistency across claims
    fields = ("population", "intervention", "outcome", "comparator")
    mismatches = []
    for f in fields:
        values = {c.get(f, "unknown") for c in all_claims if c.get(f, "unknown") != "unknown"}
        if len(values) > 1:
            mismatches.append(f)
    if not all_claims:
        factors["indirectness"] = {"downgrade": False, "not_assessed": True, "reason": "no active claims to assess"}
    elif mismatches:
        factors["indirectness"] = {"downgrade": True, "not_assessed": False,
                                     "reason": f"claims disagree on: {mismatches}"}
    else:
        factors["indirectness"] = {"downgrade": False, "not_assessed": False,
                                     "reason": "population/intervention/outcome/comparator consistent across claims"}

    # 5. publication bias: not assessable from a curated single-library snapshot
    factors["publication_bias"] = {"downgrade": False, "not_assessed": True,
                                     "reason": "not assessable from a curated single-library snapshot (no funnel-plot/search-completeness data)"}

    levels = ["very_low", "low", "moderate", "high"]
    downgrades = sum(1 for f in factors.values() if f["downgrade"])
    start_idx = levels.index(baseline) if baseline in levels else levels.index("high")
    final_idx = max(0, start_idx - downgrades)

    return {
        "baseline": baseline, "baseline_reason": f"study_types={sorted(study_types)}",
        "factors": factors, "downgrades_applied": downgrades, "certainty": levels[final_idx],
    }


# --------------------------------------------------------------- markdown render

def _cell(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


# JSON is stored with sorted keys, so render in each checklist's own order
# (a fresh and a reloaded review then produce the same review.md).
RENDER_ORDER = (
    *ROB2_DOMAINS, "selection", "comparability", "outcome_exposure",
    *(item[0] for item in AMSTAR2_ITEMS),
    "risk_of_bias", "inconsistency", "imprecision", "indirectness", "publication_bias",
)


def _ordered(d: dict) -> list[tuple[str, dict]]:
    rank = {k: i for i, k in enumerate(RENDER_ORDER)}
    return sorted(d.items(), key=lambda kv: (rank.get(kv[0], len(rank)), kv[0]))


def _appraisal_markdown(pmid: str, a: dict) -> list[str]:
    lines = [f"### PMID {pmid}", ""]
    if a.get("checklist") is None:
        why = a.get("reason") or a.get("note") or "no checklist applied"
        label = "Insufficient information" if a.get("insufficient_information") else "Not appraised"
        return lines + [f"**{label}:** {why}", ""]
    lines.append(f"Checklist: **{a['checklist']}** · study type: {a.get('study_type', 'unknown')}")
    lines += ["", "| Domain | Rating | Claims | Status | Note |", "|---|---|---|---|---|"]
    for key, d in _ordered({**a.get("domains", {}), **a.get("items", {})}):
        rating = f"{d['stars_awarded']}/{d['stars_max']} ★" if "stars_awarded" in d else d.get("rating", "—")
        if "stars_awarded" in d and not d.get("assessable", True):
            rating += " (not assessable)"
        if d.get("critical"):
            rating += " (critical)"
        claims = ", ".join(f"`{c}`" for c in d.get("claim_ids", [])) or "—"
        status = d.get("review_status", "—")
        if d.get("reviewer"):
            status += f" ({d['reviewer']})"
        note = d.get("note", "")
        if d.get("review_rationale") and d.get("review_rationale") != note:
            note = f"{note} — reviewer: {d['review_rationale']}" if note else f"reviewer: {d['review_rationale']}"
        lines.append(f"| {_cell(key)} | {_cell(rating)} | {claims} | {_cell(status)} | {_cell(note)} |")
    if "overall_confidence" in a:
        lines += ["", f"Overall confidence: **{a['overall_confidence']}** — {a.get('overall_note', '')}"]
    return lines + [""]


def render_markdown(manifest: dict, appraisals: dict, grade: dict) -> str:
    """Human-readable review.md, derived from manifest.json, appraisals/*.json
    and grade.json (which stay the source of truth)."""
    fm = _fm({
        "type": "review", "batch": manifest["batch"], "project": manifest["project"],
        "resolved_at": manifest["resolved_at"], "selector": manifest["selector_expression"],
        "certainty": grade["certainty"], "pmids": manifest["pmids"],
    })
    lines = [f"# Review `{manifest['batch']}`", "", f"Selector: `{manifest['selector_expression']}`", "",
             "> All ratings are machine-derived drafts unless marked human_confirmed/human_edited/"
             "human_rejected (see `/ref:verify review-appraisal`).", "",
             "## GRADE certainty", "",
             f"**{grade['certainty']}** (baseline {grade['baseline']}, {grade['downgrades_applied']} downgrade(s); "
             f"{grade['baseline_reason']})", "",
             "| Factor | Downgrade | Assessed | Reason |", "|---|---|---|---|"]
    for name, f in _ordered(grade["factors"]):
        lines.append(f"| {_cell(name)} | {'yes' if f['downgrade'] else 'no'} | "
                     f"{'no' if f['not_assessed'] else 'yes'} | {_cell(f['reason'])} |")
    lines += ["", "## Per-paper appraisals", ""]
    for pmid in manifest["pmids"]:
        lines += _appraisal_markdown(pmid, appraisals[pmid])
    return fm + "\n" + "\n".join(lines)


# --------------------------------------------------------------- freeze/persist

def _batch_dir(library_root: Path, batch: str, project: str | None) -> Path:
    if project:
        return library_root / "projects" / project / "reviews" / batch
    return library_root / "reviews" / batch


def run_review(library_root: Path, batch: str, project: str | None,
                resolution: dict | None, refresh: bool) -> dict:
    bdir = _batch_dir(library_root, batch, project)
    manifest_path = bdir / "manifest.json"

    if manifest_path.exists() and not refresh:
        manifest = json.loads(manifest_path.read_text())
        appraisals = {p: json.loads((bdir / "appraisals" / f"{p}.json").read_text()) for p in manifest["pmids"]}
        grade = json.loads((bdir / "grade.json").read_text())
        if not (bdir / "review.md").exists():  # backfill reviews frozen before review.md existed
            atomic_write_text(bdir / "review.md", render_markdown(manifest, appraisals, grade))
        return {"status": "reused_frozen_review", "batch": batch, "manifest": manifest,
                "appraisals": appraisals, "grade": grade, "markdown": str(bdir / "review.md")}

    if resolution is None:
        raise SelectorError("no selector resolution available for a new/refreshed review")

    tier_counts = resolution["report"]["by_extraction_tier"]
    if tier_counts.get("full", 0) == 0:
        return {
            "status": "refused", "batch": batch,
            "reason": "selected set is wholly abstract-tier -- appraisal needs full-text detail; "
                      "not proceeding (§8 phase-10 gate)",
            "by_extraction_tier": tier_counts,
        }

    pmids = resolution["pmids"]
    prior_pmids = []
    if manifest_path.exists():
        prior_pmids = json.loads(manifest_path.read_text())["pmids"]

    appraisals = {pmid: draft_appraisal_for_pmid(library_root, pmid) for pmid in pmids}
    grade = grade_certainty(library_root, pmids, appraisals)

    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / "appraisals").mkdir(exist_ok=True)
    for pmid, a in appraisals.items():
        atomic_write_json(bdir / "appraisals" / f"{pmid}.json", a)
    atomic_write_json(bdir / "grade.json", grade)

    manifest = {
        "batch": batch, "project": project,
        "selector_expression": resolution["selector_expression"],
        "pmids": pmids, "resolved_at": now_iso(),
        "report": resolution["report"],
    }
    atomic_write_json(manifest_path, manifest)
    atomic_write_text(bdir / "review.md", render_markdown(manifest, appraisals, grade))

    status = "created" if not prior_pmids else "refreshed"
    result = {"status": status, "batch": batch, "manifest": manifest, "appraisals": appraisals, "grade": grade,
              "markdown": str(bdir / "review.md")}
    if prior_pmids:
        result["added_pmids"] = sorted(set(pmids) - set(prior_pmids))
        result["removed_pmids"] = sorted(set(prior_pmids) - set(pmids))
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    add_selector_args(ap)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--batch", required=True)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    library_root = Path(args.repo).expanduser().resolve()
    if not library_root.is_dir():
        print(f"error: no library at {library_root}", file=sys.stderr)
        return 1

    try:
        manifest_exists = (_batch_dir(library_root, args.batch, args.project) / "manifest.json").exists()
        resolution = None
        if not manifest_exists or args.refresh:
            resolution = resolve_from_args(library_root, args)
        result = run_review(library_root, args.batch, args.project, resolution, args.refresh)
    except SelectorError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
