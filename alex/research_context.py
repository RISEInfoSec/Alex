"""Presentation context, independent of relevance scores and inclusion gates."""
from datetime import date
from html import escape

NOTICE = ("This work reflects the evidence and technical environment at the time of publication. "
          "Its methods and insights may remain valuable, while some findings or practical guidance "
          "may have been refined or superseded by subsequent research and developments. "
          "Please consult more recent sources before applying it to current research or investigations.")


def historical_only(paper: dict) -> bool:
    # Explicit editorial metadata only. Never infer this from age or a score.
    return str(paper.get("historical_only", "")).strip().lower() == "true"


def earlier_research(paper: dict, as_of: date) -> bool:
    try:
        published = date.fromisoformat(str(paper.get("publication_date", "")))
        # February 29 reaches its anniversary on February 28 in non-leap years.
        try:
            anniversary = published.replace(year=published.year + 5)
        except ValueError:
            anniversary = published.replace(year=published.year + 5, day=28)
        return as_of >= anniversary
    except (TypeError, ValueError):
        try:
            year = float(paper.get("year", 0))
            return year.is_integer() and 0 < year <= as_of.year - 5
        except (TypeError, ValueError):
            return False


def marker(paper: dict, as_of: date) -> str:
    if historical_only(paper):
        return '<span class="context-marker context-historical" title="Historical reference" aria-label="Historical reference">H</span>'
    if earlier_research(paper, as_of):
        return '<span class="context-marker context-earlier" title="Earlier research: five years or older" aria-label="Earlier research: five years or older">5+</span>'
    return ""


def notice(paper: dict, as_of: date) -> str:
    if not earlier_research(paper, as_of) and not historical_only(paper):
        return ""
    historical = '<p><strong>Historical reference.</strong> Included for its historical contribution. Technical details and recommendations should be read in the context of the period in which the work was published.</p>' if historical_only(paper) else ""
    return f'<aside class="research-context" aria-label="Research context"><strong>Research context</strong>{historical}<p>{escape(NOTICE)}</p></aside>'


LEGEND = ('<div class="context-legend" aria-label="Research context legend">'
          '<span><span class="context-marker context-earlier" aria-hidden="true">5+</span> Earlier research · five years or older</span>'
          '<span><span class="context-marker context-historical" aria-hidden="true">H</span> Historical reference</span></div>')
