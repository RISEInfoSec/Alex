# Public record links and deletion requests

The searchable public library offers **Open record**, **Copy link**, and **Flag for deletion**. Static bibliographies link to the corresponding ALEX record through **Open ALEX record**.

Record URLs use the public homepage with one `record` query parameter. Identity uses normalized DOI first, then public source URL, then title/year/author. Numeric display IDs, row order, search filters, private console URLs, and review metadata are never included. Source and bibliographic aliases continue to resolve if a DOI is subsequently added. Duplicate identities fail closed rather than choosing an arbitrary record.

Opening a link loads the public corpus and expands the exact record, including explicit historical references. Missing, removed, or ambiguous records show an unavailable message. Links require JavaScript and retain ALEX's generic social preview. Corrections to all identifying metadata can invalidate an old link; there is no persistent identifier/redirect registry yet.

Copy link uses the Clipboard API and provides a selected, read-only URL when clipboard access fails.

Flag for deletion opens a prefilled GitHub issue form. The visitor must sign in to GitHub, supply a reason, confirm the review request, and submit it there. Opening the form alone does not save a flag. Requests are public, as stated beside the action and on the form. They contain only the public record URL/title and the visitor's explanation.

GitHub persists the request and governs who can edit/close it. A flag has no authority to change the corpus. Maintainers assess the request using the existing editorial removal process, record approved removals in `config/corpus_exclusions.json`, and publish through the established release workflow. Do not treat a submitted flag or a closed issue as automatic deletion authorization.

Validation: `node tests/test_record_actions.cjs`, `python -m pytest tests/test_record_links.py tests/test_collections.py tests/test_research_context.py -q`, `python scripts/stage_site.py`, and `python scripts/check_record_actions.py`.
