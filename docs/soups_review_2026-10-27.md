# SOUPS inventory and review — 27 October 2026

Baseline: GitHub main `9422994515c40e91a9b878a1a4d5445db3d781cd`; 3,598 records in both the verified repository corpus and live JSON. No public data, taxonomy, pipeline schedules or deployments changed.

Proposed collection label: **SOUPS — Symposium on Usable Privacy and Security**. Venue and publisher remain separate bibliographic fields.

## Discovery coverage

503 provisionally identified research-paper links; 249 separately typed program or ancillary document links. The latter are not a complete poster/workshop inventory. All 22 annual program/proceedings pages were retrieved. A retrieved page is not proof of a complete proceedings inventory.

| Year | Paper links | Abstracts available | Other documents |
|---|---:|---:|---:|
| 2005 | 10 | 0 | 25 |
| 2006 | 14 | 0 | 24 |
| 2007 | 13 | 0 | 16 |
| 2008 | 12 | 0 | 24 |
| 2009 | 15 | 0 | 23 |
| 2010 | 16 | 0 | 20 |
| 2011 | 15 | 0 | 15 |
| 2012 | 14 | 0 | 24 |
| 2013 | 15 | 0 | 30 |
| 2014 | 21 | 21 | 0 |
| 2015 | 22 | 22 | 0 |
| 2016 | 22 | 22 | 4 |
| 2017 | 26 | 26 | 8 |
| 2018 | 28 | 28 | 3 |
| 2019 | 27 | 27 | 4 |
| 2020 | 26 | 26 | 8 |
| 2021 | 36 | 36 | 6 |
| 2022 | 37 | 37 | 6 |
| 2023 | 33 | 33 | 9 |
| 2024 | 33 | 33 | 0 |
| 2025 | 30 | 30 | 0 |
| 2026 | 38 | 38 | 0 |

## Gaps and controls

- soups.page historical year links returned 404. Original CUPS/CMU pages recovered 2005–2013. The advertised soups.bib also returned 404.
- ACM 2012 and 2013 links returned 403. No challenges or paywalls were bypassed; other ACM annual endpoints have not been individually tested.
- 2007 has 13 linked program papers versus 12 accepted in the historical homepage tally; 2008 has 12 versus 13. These differences remain unresolved, not silently corrected.
- 2012 contains two extensionless official paper links. Preserve their printed URLs; individual document verification remains pending.
- Early program author bylines are retained as raw evidence; structured authors, abstracts and original publication metadata still need verification.
- Poster, workshop, lightning-talk and tutorial sources are tracked separately in `soups_ancillary_sources.json`; ancillary coverage remains partial for every year.
- Batch 1: all 20 author lists, conference years, venues, publishers and paper landing pages verified against individual USENIX citation metadata. All 20 have official abstracts. None supplies a DOI in that metadata; DOI discovery and PDF link verification remain pending.
- No exact normalized-title or official-URL match, or title similarity >=0.90 hold, was found for batch 1 in the baseline ALEX corpus. Missing DOIs and alternate-title versions remain limitations.
- Only the first 20 candidates have had substantive abstract review. The rest remain not assessed. No full-text findings are inferred.
- Review numbers are stable. User selection decisions are distinct from recommendations and publication approval. Changed reviewed content invalidates the decision; disappearing sources retain their identity and decision.
- Existing APWG release checks require APWG-specific identities and DOI metadata. Do not run SOUPS rows through that release code or invent identifiers to satisfy it. Reuse its content-bound approval approach when implementing a SOUPS release after editorial review.

## Run and validate

```sh
node scripts/soups_fetch.mjs .cache/soups
python -m alex.pipelines.soups_review --snapshots .cache/soups --base-commit VERIFIED_MAIN_SHA
python -m pytest -q tests/test_soups_review.py
```

Acquisition is serial, paced and bounded to official HTML hosts. Raw snapshots stay in the local cache; PDFs are not downloaded. Receipts record source hashes and access outcomes. The Python program writes only the review manifest and cannot import or publish. A refresh preserves stable numbers and decisions, and requires reassessment if reviewed content changes.

Validation: six focused regression tests passed; Node module syntax and acquisition replay validated (cached annual sources plus two successful fresh requests). The public corpus and public index retain their verified baseline hashes. No site build is needed for these review-only files; release work must run the repository’s normal classification, quality, schema and build checks.

## Batch 1

All decisions are pending. Recommendations: 18 include, 2 discuss. Selection approval does not grant merge or deployment permission.

### 1. “I didn’t know I would be this excited not to be scammed.” Exploring Emotional and Behavioral Responses During Phishing Attacks (2026)

Authors: Raphael Weidhaas; Alexandra von Preuschen; Verena Distler

Official paper: https://www.usenix.org/conference/soups2026/presentation/weidhaas

**Include · direct relevance.** Observed emotional and behavioural responses during simulated phishing attacks; informs prevention and victim engagement.

ALEX match: none found. DOI not supplied; DOI discovery and PDF link checks pending.

### 2. Anxious and Aware: Examining the Effects of Social Anxiety on Social Engineering Resilience and Vulnerability (2026)

Authors: Martin Dechant; Victoria Woo; Florence Tomlin; Bettina Moltrecht; Mark Warner

Official paper: https://www.usenix.org/conference/soups2026/presentation/dechant

**Include · direct relevance.** Studies social-anxiety traits and susceptibility or resilience to social-engineering tactics.

ALEX match: none found. DOI not supplied; DOI discovery and PDF link checks pending.

### 3. Quantifying Risk Perception and Scam Response Among International and Domestic US University Students (2026)

Authors: Alexandra Xinran Li; Elijah Bouma-Sims; Lily Klucinec; Ray Liu; Ayesha Binte Mostofa; Arjun Arunasalam; Lorrie Faith Cranor; Pubali Datta; Lucy Simko; Karen Sowon

Official paper: https://www.usenix.org/conference/soups2026/presentation/li

**Include · direct relevance.** Compares scam encounters, losses, disengagement and reporting among international and domestic students.

ALEX match: none found. DOI not supplied; DOI discovery and PDF link checks pending.

### 4. Experiences with Digital Scams Post-Incarceration in the U.S. (2026)

Authors: Yael Eiger; Candice Baughman; Rory Andes; Bryan Glant; Franziska Roesner

Official paper: https://www.usenix.org/conference/soups2026/presentation/eiger

**Include · direct relevance.** Documents scam victimization, coercive tactics and reporting barriers after incarceration.

ALEX match: none found. DOI not supplied; DOI discovery and PDF link checks pending.

### 5. Usability Determines Safety for At-Risk Users: Evaluating Hidden Device Detectors for Intimate Partner Surveillance (2026)

Authors: Akhil Polamarasetty; Leonie Maria Tanczer; Enrico Costanza; Kevin Chetty

Official paper: https://www.usenix.org/conference/soups2026/presentation/polamarasetty

**Include · direct relevance.** Evaluates tools for finding hidden surveillance devices in intimate-partner abuse contexts.

ALEX match: none found. DOI not supplied; DOI discovery and PDF link checks pending.

### 6. "Don't Let Them Get To You": Understanding the Role of TikTok as a Source of Support for Cyberbullying Victims (2026)

Authors: Saba Iqbal; Warda Usman; Daniel Zappala

Official paper: https://www.usenix.org/conference/soups2026/presentation/iqbal

**Include · direct relevance.** Assesses support and advice offered to cyberbullying victims on TikTok.

ALEX match: none found. DOI not supplied; DOI discovery and PDF link checks pending.

### 7. "You Have Been Selected as the Winner": Characterizing User-Reported Scams on TikTok (2026)

Authors: Smirity Kaushik; Kyle Beadle; Gauri Nayak; Madelyn Rose Sanfilippo; Mainack Mondal; Yang Wang; Sai Teja Peddinti; Jingjie Li; Yixin Zou

Official paper: https://www.usenix.org/conference/soups2026/presentation/kaushik

**Include · direct relevance.** Analyzes user reports of TikTok scams, including impersonation and verification-badge fraud; not a direct sample of scam operations.

ALEX match: none found. DOI not supplied; DOI discovery and PDF link checks pending.

### 8. SoK: Mapping Threats to Defenses in Online Survey Fraud (2026)

Authors: Shiza Ali; Wellington Esposito Barbosa; Matthias Fassl; Aditi Ganapathi; Jaron Mink; Adam J. Aviv

Official paper: https://www.usenix.org/conference/soups2026/presentation/ali

**Include · direct relevance.** Maps deliberate human and automated online survey fraud to detection and mitigation methods.

ALEX match: none found. DOI not supplied; DOI discovery and PDF link checks pending.

### 9. "Hello, is this Anna?": Unpacking the Lifecycle of Pig-Butchering Scams (2025)

Authors: Rajvardhan Oak; Zubair Shafiq

Official paper: https://www.usenix.org/conference/soups2025/presentation/oak-butchering

**Include · direct relevance.** Victim interviews reconstruct pig-butchering scam stages, manipulation and repeat victimization.

ALEX match: none found. DOI not supplied; DOI discovery and PDF link checks pending.

### 10. Can You Walk Me Through It? Explainable SMS Phishing Detection using LLM-based Agents (2025)

Authors: Yizhu Wang; Haoyu Zhai; Chenkai Wang; Qingying Hao; Nick A. Cohen; Roopa Foulger; Jonathan A. Handler; Gang Wang

Official paper: https://www.usenix.org/conference/soups2025/presentation/wang

**Include · direct relevance.** Evaluates evidence-based explanations for SMS phishing detection using external domain and URL context.

ALEX match: none found. DOI not supplied; DOI discovery and PDF link checks pending.

### 11. Between Court Orders and Platform Policies: Understanding Law Enforcement and Meta Interactions in Addressing Non-Consensual Image Disclosure Abuse (2025)

Authors: Amna Batool; Kentaro Toyama

Official paper: https://www.usenix.org/conference/soups2025/presentation/batool

**Include · direct relevance.** Examines Pakistani law-enforcement requests to Meta about non-consensual image disclosure, including extortion and cultural policy gaps.

ALEX match: none found. DOI not supplied; DOI discovery and PDF link checks pending.

### 12. Spy-oT: Understanding How Users Learn to Use Internet of Things Devices For Abusive Purposes (2025)

Authors: Kieron Ivy Turk; Alice Hutchings

Official paper: https://www.usenix.org/conference/soups2025/presentation/turk

**Include · direct relevance.** Investigates how abusers discover and exploit IoT functionality for domestic abuse.

ALEX match: none found. DOI not supplied; DOI discovery and PDF link checks pending.

### 13. Integrating Large Language Models into Security Incident Response (2025)

Authors: Diana Kramer; Lambert Rosique; Ajay Narotam; Elie Bursztein; Patrick Gage Kelley; Kurt Thomas; Allison Woodruff

Official paper: https://www.usenix.org/conference/soups2025/presentation/kramer

**Include · supporting relevance.** Tests LLM-assisted incident-investigation summaries; directly relevant to accuracy and reliability in investigative reporting.

ALEX match: none found. DOI not supplied; DOI discovery and PDF link checks pending.

### 14. Language as Lure: A Naturalistic Study on Pasifika Phishing Susceptibility (2025)

Authors: Eric Spero; Isa Seow; Lucas Betts; Eddie Fuatimau; Robert Biddle; Danielle Lottridge; Giovanni Russello

Official paper: https://www.usenix.org/conference/soups2025/presentation/spero

**Include · direct relevance.** Field phishing simulations examine how language and cultural context influence susceptibility in a Melanesian government workforce.

ALEX match: none found. DOI not supplied; DOI discovery and PDF link checks pending.

### 15. Youth-Centered GAI Risks (YAIR): A Taxonomy of Generative AI Risks from Empirical Data (2025)

Authors: Yaman Yu; Yiren Liu; Jacky Zhang; Yun Huang; Yang Wang

Official paper: https://www.usenix.org/conference/soups2025/presentation/yu

**Discuss · uncertain relevance.** Broad youth generative-AI risk taxonomy includes misuse and exploitation, but the abstract does not establish how much content concerns cybercrime or abuse. Full-text review needed before inclusion.

ALEX match: none found. DOI not supplied; DOI discovery and PDF link checks pending.

### 16. Victims, Vigilantes, and Advice Givers: An Analysis of Scam-Related Discourse on Reddit (2025)

Authors: Rajvardhan Oak; Zubair Shafiq

Official paper: https://www.usenix.org/conference/soups2025/presentation/oak-discourse

**Include · direct relevance.** Studies scam tactics, victim support, reporting discourse and scambaiting communities on Reddit.

ALEX match: none found. DOI not supplied; DOI discovery and PDF link checks pending.

### 17. “TikTok, Do Your Thing”: User Reactions to Social Surveillance in the Public Sphere (2025)

Authors: Meira Gilbert; Miranda Wei; Lindah Kotut

Official paper: https://www.usenix.org/conference/soups2025/presentation/gilbert

**Discuss · supporting relevance.** Crowdsourced identification of strangers has clear OSINT, stalking and consent implications; much of the observed activity is framed as romantic rather than criminal.

ALEX match: none found. DOI not supplied; DOI discovery and PDF link checks pending.

### 18. What Drives SMiShing Susceptibility? A U.S. Interview Study of How and Why Mobile Phone Users Judge Text Messages to be Real or Fake (2024)

Authors: Sarah Tabassum; Cori Faklaris; Heather Richter Lipford

Official paper: https://www.usenix.org/conference/soups2024/presentation/tabassum-sarah

**Include · direct relevance.** Interviews examine how users assess, verify and report suspicious SMS messages.

ALEX match: none found. DOI not supplied; DOI discovery and PDF link checks pending.

### 19. Comparing Malware Evasion Theory with Practice: Results from Interviews with Expert Analysts (2024)

Authors: Miuyin Yong Wong; Matthew Landen; Frank Li; Fabian Monrose; Mustaque Ahamad

Official paper: https://www.usenix.org/conference/soups2024/presentation/yong-wong

**Include · direct relevance.** Expert malware analysts describe evasion challenges and practical countermeasures; supports technical investigations.

ALEX match: none found. DOI not supplied; DOI discovery and PDF link checks pending.

### 20. "Violation of my body:" Perceptions of AI-generated non-consensual (intimate) imagery (2024)

Authors: Natalie Grace Brigham; Miranda Wei; Tadayoshi Kohno; Elissa M. Redmiles

Official paper: https://www.usenix.org/conference/soups2024/presentation/brigham

**Include · direct relevance.** Studies attitudes to non-consensual synthetic intimate imagery, relevant to image-based abuse and victimization.

ALEX match: none found. DOI not supplied; DOI discovery and PDF link checks pending.

