# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Funding/acknowledgement extraction from JATS (PLAN.md §3c):

"Extract structured PubMed grants at ingest; inspect JATS funding elements
and funding/acknowledgement passages during conversion, independently of
scientific-claim promotion."

Produces funding.json observations using the same evidence-kind vocabulary
Phase 1's add.py already writes (indexed_funding_association for PubMed
GrantList entries): explicit_acknowledgement_verified when a <funding-group>
/<award-group> names funder+award explicitly, possible_match for acknowledgement-
section prose that mentions funding without structured markup, unknown when
nothing was found (never a false "not funded" negative, §3c).
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

_FUNDING_WORDS = re.compile(
    r"\b(fund(ed|ing)?|grant|support(ed)?|award(ed)?)\b", re.IGNORECASE
)


def _funder_fields(funder_el: ET.Element | None) -> tuple[str | None, str | None]:
    """Read `<funding-source>`'s `<institution>` (the funder name) and
    `<institution-id>` (the FundRef DOI etc.) as separate children instead of
    flattening all descendant text together, which used to concatenate the
    id straight onto the name (§9.1, e.g. "EU-Project STIPED (Horizon2020)
    10.13039/501100000780"). A plain `<funding-source>Name</funding-source>`
    (no `<institution>` wrapper) still works via the `.text` fallback."""
    if funder_el is None:
        return None, None
    institution_el = funder_el.find(".//institution")
    if institution_el is not None:
        funder = "".join(institution_el.itertext()).strip() or None
    else:
        funder = (funder_el.text or "").strip() or None
    id_el = funder_el.find(".//institution-id")
    fundref_id = "".join(id_el.itertext()).strip() or None if id_el is not None else None
    return funder, fundref_id


def extract_funding_observations(xml_text: str) -> tuple[list[dict], str]:
    """Returns (observations, state) where state is one of
    explicit_acknowledgement_verified / possible_match / unknown, taking the
    strongest evidence found across the whole document."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return [], "unknown"

    observations: list[dict] = []

    for fg in root.iter("funding-group"):
        for ag in fg.iter("award-group"):
            funder_el = ag.find(".//funding-source")
            award_el = ag.find(".//award-id")
            funder, fundref_id = _funder_fields(funder_el)
            award = "".join(award_el.itertext()).strip() if award_el is not None else None
            if funder or fundref_id or award:
                observations.append({
                    "kind": "explicit_acknowledgement_verified",
                    "source": "jats_funding_group",
                    "funder": funder,
                    "fundref_id": fundref_id,
                    "award_number": award,
                    "locator": "funding-group/award-group",
                })
        # a <funding-statement> with no structured award-group still counts as explicit
        stmt_el = fg.find("funding-statement")
        if stmt_el is not None and not fg.findall("award-group"):
            text = "".join(stmt_el.itertext()).strip()
            if text:
                observations.append({
                    "kind": "explicit_acknowledgement_verified",
                    "source": "jats_funding_statement",
                    "funder": None,
                    "fundref_id": None,
                    "award_number": None,
                    "text": text,
                    "locator": "funding-group/funding-statement",
                })

    if not observations:
        # fall back to prose scan of an acknowledgements section
        for sec in root.iter("sec"):
            sec_type = (sec.get("sec-type") or "").lower()
            title_el = sec.find("title")
            title = (title_el.text or "") if title_el is not None else ""
            if sec_type == "funding" or "acknowledg" in title.lower() or "acknowledg" in sec_type:
                text = "".join(sec.itertext()).strip()
                if text and _FUNDING_WORDS.search(text):
                    observations.append({
                        "kind": "possible_match",
                        "source": "jats_acknowledgement_prose",
                        "funder": None,
                        "fundref_id": None,
                        "award_number": None,
                        "text": text[:1000],
                        "locator": f"sec[sec-type={sec_type or 'acknowledgements'}]",
                    })

    if any(o["kind"] == "explicit_acknowledgement_verified" for o in observations):
        state = "explicit_acknowledgement_verified"
    elif observations:
        state = "possible_match"
    else:
        state = "unknown"
    return observations, state
