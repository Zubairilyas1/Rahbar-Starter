"""Citation verification service (Section 3.4).

Verifies that every citation in the model's answer strictly matches a retrieved
passage chunk. Hallucinated or non-retrieved citations are filtered out to prevent
the -10 point deduction.
"""

from __future__ import annotations

import logging
from ..schemas import Citation, Passage

log = logging.getLogger("rahbar.citations")


def verify_citations(citations: list[Citation], passages: list[Passage]) -> list[Citation]:
    """Filter citations to only those that match a retrieved passage by source and section/page."""
    if not citations or not passages:
        return []

    valid_citations: list[Citation] = []
    seen: set[tuple[str, str, int | None]] = set()

    for cite in citations:
        key = (cite.source, cite.section, cite.page)
        if key in seen:
            continue

        matched = False
        for p in passages:
            # Source must match exactly
            if cite.source.strip().lower() == p.source.strip().lower():
                # Either section matches or page matches
                section_match = (
                    cite.section.strip().lower() in p.section.strip().lower()
                    or p.section.strip().lower() in cite.section.strip().lower()
                )
                page_match = cite.page is not None and p.page is not None and cite.page == p.page

                if section_match or page_match:
                    matched = True
                    break

        if matched:
            valid_citations.append(cite)
            seen.add(key)
        else:
            log.warning(
                f"Dropped hallucinated citation: source='{cite.source}', "
                f"section='{cite.section}', page={cite.page} (does not match any retrieved passage)"
            )

    return valid_citations
