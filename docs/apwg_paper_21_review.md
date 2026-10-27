# Paper 21: abstract-completeness review

Checked October 26, 2026. DOI: 10.1109/ecrime.2009.5342609.

The reviewed OpenAlex abstract in run 40427031598, artifact 12701110589,
contains only the background paragraph. The author's companion page
identifies the exact title, authors, DOI and 2009 IEEE proceedings and shows
two additional abstract paragraphs describing the proposed banking
framework and automated decoy users (phoneybots). This confirms incomplete
coverage in the reviewed OpenAlex snapshot, not merely a short abstract.

Evidence:
- Author page: https://www.hooklee.com/honeypots4anti-phishing.asp
- Author PDF: https://www.hooklee.com/papers/apwg-ecrs2009.pdf
- Publisher record: https://ieeexplore.ieee.org/document/5342609/
- APWG listing: https://ecrimeresearch.org/2009-accepted-research-papers

The indexed first-page author PDF text independently includes the omitted
contribution paragraphs. Direct PDF retrieval timed out; no PDF was retained.
No new OpenAlex API request was made in this check. This finding concerns the
reviewed snapshot, not a claim that OpenAlex has never corrected its record.

Recommended next correction: use the complete original author abstract for
this specific record, explicitly identify its source, preserve the reviewed
OpenAlex version/hash as audit evidence, and rerun unchanged quality scoring.
Do not concatenate separately sourced text or manufacture a summary.
Proposed classification: Cybercrime & Fraud / Phishing Analysis, replacing
the provisional Malware & Exploits category. This is a framework proposal;
do not describe it as empirically validated on the basis of its abstract.

The global OpenAlex preference remains unchanged. A source-specific exception
and editorial selection have not yet been approved; paper 21 stays held.
The 27 approved selections, live corpus and publication gate are unchanged.

This update records evidence and a recommendation only. JSON was parsed and
approval/hold invariants checked; no pipeline execution or score validation
was possible because the execution environment became unavailable.


## Approved correction and unchanged-policy rescore

The user agreed to the author-source exception, rescoring and proposed
classification. The manifest now stores the complete original author abstract,
its source URL and SHA-256, and the reviewed incomplete OpenAlex source/hash.
Review enrichment replaces only that exact identity/source/content combination;
changed upstream text is not overwritten. Existing records and possible
duplicates retain precedence. No PDF request is needed for this correction.
Both bibliography enrichment and direct classification review apply the same
idempotent correction before scoring. Global OpenAlex preference is unchanged.

Replay against artifact 12701110589 changes the score from **61.55 to 65.96**;
core-term and relevance gates pass with unchanged thresholds and weights.
The contribution is a banking anti-phishing framework using honeytokens and
automated decoy users; classification is approved as **Cybercrime & Fraud /
Phishing Analysis**, replacing Malware & Exploits. The source page describes a
proposal; this is not a claim of demonstrated deployment effectiveness.

Editorial selection remains pending explicit review of this corrected record;
27 previous selections remain approved. Publication remains unauthorized.
The earlier execution limitation above describes the evidence-only commit;
the correction was subsequently tested and scored in the restored environment.
