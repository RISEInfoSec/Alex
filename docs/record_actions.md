# Public record links and private deletion review

The public library offers **Open record**, **Copy link**, and **Flag for deletion**. Static bibliographies link to the same public record view.

Public record URLs use normalized DOI, source URL, or title/year/author identity rather than sequential export IDs. Direct links open the exact record, including historical references. Ambiguous or missing records show an unavailable message. Copy link retains its clipboard-denial fallback.

Flag for deletion navigates to the owner-private ALEX Research Review site at `/records?identity=...`. The URL contains only the public bibliographic identity. Opening it does not create a flag. The private site requires sign-in and separately authorizes administrator IDs before displaying or changing deletion flags.

The private sidebar labels the existing controls **Review** with an H2, and places a separate **Deletion** H2 beneath them. Administrators can find a record, save a flag with an optional reason, update the reason, view flagged records, and remove a flag. Flags, reasons, and change history remain in the private site's database. No public GitHub removal issue is created.

A flag preserves the record and its publication state. Actual removal remains a separate explicit editorial decision using the existing corpus-exclusion and release process. Shared public record links and clipboard behavior are independent of deletion management.

Validation: `node tests/test_record_actions.cjs`, `python -m pytest tests/test_record_links.py tests/test_collections.py tests/test_research_context.py -q`, `python scripts/stage_site.py`, and `python scripts/check_record_actions.py`. Private-site authorization, persistence, concurrency, and rollback tests are maintained with that site's source.
