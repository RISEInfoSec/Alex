# Pending APWG quality audit — October 27, 2026

## Evidence and reproducibility

Input: [completed run 40481008085](https://github.com/RISEInfoSec/Alex/actions/runs/40481008085),
[review artifact 12724075056](https://github.com/RISEInfoSec/Alex/actions/runs/40481008085/artifacts/12724075056).
This is an offline replay against editorial manifest commit
761d5b301b07e19cad45dec98db58224b28a2f32, including the subsequent acceptance
of 50 and rejection of 90. It is not a newly completed CI artifact. The
machine-readable companion records input, manifest, policy and correction
hashes, paper identities, scores, exact term matches, overlapping blockers,
source provenance and per-paper actions. Citation observations retain their
provider/date; unknown citations are lower-bound zero contributions, not
verified zero citation counts. No OpenAlex, other provider or model requests
were made by the replay.

Reproduce from the repository root after downloading the artifact:

```sh
PYTHONPATH=. python scripts/audit_apwg_pending_quality.py \
  --input /path/to/artifact/apwg_bibliography_with_abstracts.csv \
  --source-run 40481008085 --source-artifact 12724075056 \
  --output /tmp/apwg_pending_quality_audit.json
```

All 66 pending identities and abstract digests match their recorded approvals.
No pending paper lacks an abstract. The artifact's aggregate 126 abstracts
must not be compared directly with pre-release totals: 91 records are now
existing/suppressed (90 released additions plus the original exact match),
and checkpoint restoration intentionally skips existing records. Their live
abstracts are unchanged. The pending collection has not lost approved text.

## Results under unchanged policy

| Primary disposition | Before venue repair | After venue repair |
|---|---:|---:|
| Eligible for controlled release recommendation | 1 | 2 |
| Core-term hold | 19 | 19 |
| Relevance-floor hold | 29 | 29 |
| Below review threshold | 17 | 16 |
| Total pending | 66 | 66 |

Eligible records are **50** (55.27) and **163** (53.24). They remain unpublished,
with publication_approved=false. Both are in the human-quality-review score
band, not automatic admission. Editorial approval is recorded; a controlled
release still requires explicit authorization.

Primary statuses hide additional failures. After venue repair, **35** fail
the relevance floor, **19** fail core terms, and **45** are below their review
threshold; these counts overlap. Four citation counts remain unknown
(163, 165, 166, 167). Only 165 lacks a mandatory metadata field (DOI) and
retains its bibliographic-review flag. No original year was changed.

## Evidence-backed metadata repair

The importer already carried exact URL/title bibliographic corrections for
these four papers, but did not propagate independently verified venue fields.
The repair fills absent venues only after exact source-link, DOI, title and
original-year checks. It preserves available venues and existing/ambiguous
corpus matches. Publisher and APWG collection attribution remain separate.
No APWG-only score bonus or threshold change was introduced.

| Paper | Verified venue evidence | Score after repair | Remaining result |
|---|---|---:|---|
| 163 Quantum-Enabled Cybercrime | [Author's institutional publications list](https://people.se.cmich.edu/liao1q/publications.htm), eCrime 2025 | 53.24 | Eligible for release recommendation; citations unknown |
| 165 Checkout Checkup | [Author's publications list](https://christinahyeung.github.io/), eCrime 2020 | 43.82 | Core term, score and DOI/bibliographic holds |
| 166 Resilient Domain Whitelist | [Research group's publication list](https://drakkar.imag.fr/publications/), eCrime 2023, matching DOI | 43.82 | Score hold; citations unknown |
| 167 Anti-Phishing Phil | [Official SOUPS 2007 program](https://cups.cs.cmu.edu/soups/2007/program.html), matching authors/title | 18.41 | Core-term and score holds; citations unknown |

Paper 167 is SOUPS research published by ACM, not an eCrime publication merely
because APWG links it. Its existing original 2007 year and DOI are preserved. Its actual venue does
not match the current whitelist, so it receives 40% venue credit, without
appending a publisher name to obtain extra points.
Paper 166's publisher uses *Blacklist* while APWG uses *Blocklist*; the
matching DOI and authors support identity, but neither title nor approved
abstract text was silently rewritten. Paper 165's DOI remains unknown.

## Narrow scoring issue for approval before implementation

The relevance gate derives its vocabulary from the 12 discovery queries.
Those queries omit phishing, ransomware, botnet and several investigation
subjects already present in ALEX's categories/core vocabulary. Consequently,
paper 104 (ransomware taxonomy), 141 (passive DNS botnet monitoring) and 155
(malware URL detection) pass the core gate but score zero relevance. This is
a vocabulary-coverage failure, not evidence that the papers lack scientific
quality. The core vocabulary separately omits such clear subjects as online
carding (110), pet scams (100) and pig-butchering scams (109).

Recommended next development step: evaluate a separate, carefully bounded
quality-topic vocabulary against these reviewed positives AND off-topic
negative examples. Keep discovery queries, weights, thresholds and the
requirement for substantive topic evidence unchanged. Do not use generic
words such as fraud, trust, security, intelligence or cryptocurrency alone as
automatic topic approval, and do not introduce an APWG collection exemption.
Present before/after effects on APWG and the regular review/rejection queues
before enabling any vocabulary change. No such policy change is implemented
in this PR update.

At least seven primary relevance holds already exceed the numeric review
threshold (93, 98, 104, 105, 111, 112, 113), but they remain held until the
vocabulary issue is resolved. Most other records have overlapping score
holds, so fixing one gate does not imply readiness. Paper 114 scores 44.98;
it remains below 45.0 rather than being rounded into admission. Verified
2025 papers fall outside the configured one-year recent-paper tier in 2026;
this rule was not changed to improve their results.

## Individual audit

Each row below uses all current gates. See the JSON companion for secondary
blockers and source details. No PDF is retained or republished.

| Paper | Title | Score | Disposition |
|---|---|---:|---|
| 50 | Identifying Unintended Harms of Cybersecurity Countermeasures | 55.27 | editorially_approved_pending_release |
| 93 | An inquiry into money laundering tools in the Bitcoin ecosystem | 64.1 | hold_relevance_floor |
| 94 | Investigative response modeling and predictive data collection | 57.62 | hold_core_term_gate |
| 97 | Building and Testing a Network of Social Trust in an Underground Forum: Robust Connections and Overlapping Criminal Domains | 56.25 | hold_core_term_gate |
| 98 | $1.00 per RT #BostonMarathon #PrayForBoston: Analyzing fake content on Twitter | 56.01 | hold_relevance_floor |
| 99 | Authorship attribution of web forum posts | 55.18 | hold_core_term_gate |
| 100 | Resource Networks of Pet Scam Websites | 54.24 | hold_core_term_gate |
| 101 | THREAT/crawl: a Trainable, Highly-Reusable, and Extensible Automated Method and Tool to Crawl Criminal Underground Forums | 52.75 | hold_core_term_gate |
| 102 | Taking down websites to prevent crime | 51.02 | hold_core_term_gate |
| 103 | “Effects of Peer Feedback on Password Strength | 50.13 | hold_core_term_gate |
| 104 | A Key-Management-Based Taxonomy for Ransomware | 49.86 | hold_relevance_floor |
| 105 | From Lamborghinis to Ladas: Empirical Analysis of LockBit’s Business Operations | 48.51 | hold_relevance_floor |
| 106 | Large Scale Detection of IDN Domain Name Masquerading | 47.91 | hold_core_term_gate |
| 107 | Security and Privacy Risks of Number Recycling at Mobile Carriers in the United States | 47.91 | hold_core_term_gate |
| 108 | Characterizing key stakeholders in an online black-hat marketplace | 47.02 | hold_core_term_gate |
| 109 | A Sinister Fattening Dissecting the Tales of Pig Butchering and other Cryptocurrency Scams | 46.26 | hold_core_term_gate |
| 110 | All your cards are belong to us: Understanding online carding forums | 46.1 | hold_core_term_gate |
| 111 | Contextual Classification of Cybercriminal Posts Using Large Language Models: A Comprehensive Study on Tech Support Scam Marketplaces | 46.01 | hold_relevance_floor |
| 112 | “Smells Phishy?”: An educational game about online phishing scams | 45.74 | hold_relevance_floor |
| 113 | From playing games to committing crimes: A multi-technique approach to predicting key actors on an online gaming forum | 45.22 | hold_relevance_floor |
| 114 | A notation for describing the steps in indicator expansion | 44.98 | hold_below_review_threshold |
| 116 | Using URL Shorteners to Compare Phishing and Malware Attacks | 44.52 | hold_relevance_floor |
| 117 | Infrastructure Patterns in Toll Scam Domains: A Comprehensive Analysis of Cybercriminal Registration and Hosting Strategies | 44.41 | hold_below_review_threshold |
| 118 | Unicorns in the Wild West: Empirical Analysis of Cybercrime Facilitated by Cryptocurrencies | 44.41 | hold_below_review_threshold |
| 119 | “Invest in crypto!”: An analysis of investment scam advertisements found in Bitcointalk | 43.92 | hold_core_term_gate |
| 120 | Burn Before Reading: A stealthy framework for combating live forensics examinations | 43.82 | hold_below_review_threshold |
| 121 | Spammer success through customization and randomization of URLs | 43.82 | hold_core_term_gate |
| 122 | Hey Google Remind me to be Phished Exploiting the Notifications of the Google AI Assistant on Android for Social Engineering Attacks | 43.82 | hold_below_review_threshold |
| 124 | Beaver: Estimating Future Risks at Scale in Real-World Deployments | 43.82 | hold_below_review_threshold |
| 125 | Detecting Malicious Domain Registration Batches: Patterns, Prevalence, and Security Implications | 43.82 | hold_below_review_threshold |
| 126 | Just in Plain Sight: Unveiling CSAM Distribution Campaigns on the Clear Web | 43.82 | hold_below_review_threshold |
| 127 | “Send to which account?” Evaluation of an LLM-based Scambaiting System | 43.82 | hold_below_review_threshold |
| 128 | Why do users trust the wrong messages? A behavioural model of phishing | 43.55 | hold_below_review_threshold |
| 129 | Ten years of attacks on companies using visual impersonation of domain names | 42.69 | hold_relevance_floor |
| 130 | Discovery, infiltration, and denial of service in a process control system wireless network | 42.34 | hold_relevance_floor |
| 131 | Cryptocurrency Exchange Closure Revisited (Again) | 42.33 | hold_below_review_threshold |
| 132 | Folex: An analysis of an herbal and counterfeit luxury goods affiliate program | 42.06 | hold_core_term_gate |
| 133 | Pump, Dump, and then What? The Long-Term Impact of Cryptocurrency Pump-and-Dump Schemes | 42.03 | hold_core_term_gate |
| 134 | “I don’t really give them piece of mind”: User Perceptions of Social Engineering Attacks | 41.83 | hold_relevance_floor |
| 135 | Evaluating randomness in cyber attack textual artifacts | 41.45 | hold_relevance_floor |
| 136 | Analysis of content copyright infringement in mobile application markets | 41.35 | hold_below_review_threshold |
| 137 | Which malware lures work best? Measurements from a large instant messaging worm | 41.35 | hold_below_review_threshold |
| 139 | ModZoo: A Large-Scale Study of Modded Android Apps and Their Markets | 41.01 | hold_relevance_floor |
| 140 | Inside LockBit: Technical, Behavioral, and Financial Anatomy of a Ransomware Empire | 41.01 | hold_relevance_floor |
| 141 | Monitoring a fast flux botnet using recursive and passive DNS: A case study | 40.69 | hold_relevance_floor |
| 142 | Profiling underground merchants based on network behavior | 40.6 | hold_relevance_floor |
| 143 | SemanticPhish: A Semantic-based Scanning System for Early Detection of Phishing Attacks | 40.37 | hold_relevance_floor |
| 144 | An expanding reference library for Peer-to-Peer content | 39.94 | hold_below_review_threshold |
| 145 | Family Ties: A Close Look at the Influence of Static Features on the Precision of Malware Family Clustering | 39.41 | hold_below_review_threshold |
| 146 | The smuggling theory approach to organized digital crime | 39.21 | hold_relevance_floor |
| 147 | Global adversarial capability modeling | 38.98 | hold_relevance_floor |
| 148 | Beneath the radar: Exploring the economics of business fraud via underground markets | 38.92 | hold_relevance_floor |
| 149 | Characterizing the impact of malware infections and remediation attempts through support forum analysis | 38.51 | hold_relevance_floor |
| 150 | Geo-Phisher: the design and evaluation of information visualizations about internet phishing trends | 38.25 | hold_relevance_floor |
| 151 | Averages Don’t Characterise the Heavy Tails of Ransoms | 38.09 | hold_relevance_floor |
| 152 | Empirical analysis of losses from business-email compromise | 38.09 | hold_core_term_gate |
| 153 | Dual canonicalization: An answer to the homograph attack | 37.05 | hold_relevance_floor |
| 154 | A Layered Approach to Defending Against List- Linking Email Bombs | 36.74 | hold_relevance_floor |
| 155 | Empirical analysis of factors affecting malware URL detection | 36.68 | hold_relevance_floor |
| 157 | Breaking and fixing content-based filtering | 35.83 | hold_relevance_floor |
| 158 | Spare the rod, spoil the network security? Economic analysis of sanctions online | 35.69 | hold_relevance_floor |
| 161 | Controlling spam and spear phishing via peered network overlays and non-repudiable traceback | 35.53 | hold_relevance_floor |
| 163 | Quantum-Enabled Cybercrime: A Portfolio Analysis of Cryptocurrency Theft and Double-Spending | 53.24 | editorially_approved_pending_release |
| 165 | Checkout Checkup: Misuse of Payment Data from Web Skimming | 43.82 | hold_core_term_gate |
| 166 | Building a Resilient Domain Whitelist to Enhance Phishing Blocklist Accuracy | 43.82 | hold_below_review_threshold |
| 167 | Anti-Phishing Phil: The Design and Evaluation of a Game That Teaches People Not to Fall for Phish | 18.41 | hold_core_term_gate |

Validation: 390 local tests passed, including 148 focused importer/pipeline/editorial/recommendation tests,
including identity mismatches, preservation of existing metadata, and the
archive-to-quality venue path. Seventeen existing pandas warnings remain.
GitHub checks on the new report/metadata commit must be verified separately.
No accepted corpus, public asset, release bundle, scoring policy or deployment
configuration was changed.
