"""Offline copy of ALEX's closed paper-classification vocabulary.

The compatibility test compares these lists with the literal policy in
alex/pipelines/classify.py. A future writer must also bind both implementations
to immutable source and independently validate decisions under its fence.
"""
CATEGORIES=['OSINT Methodology','Social Media & SOCMINT','Dark Web & Underground','Cyber Threat Intelligence',
 'Digital Forensics & Evidence','Malware & Exploits','Vulnerability Research','Disinformation & Influence',
 'Cybercrime & Fraud','Network & Infrastructure Security','IoT & CPS Security','Privacy & Surveillance',
 'AI/ML for Security','Foundations & Surveys','Other']
INVESTIGATION_TYPES=['Network Investigation','Social Media Analysis','Dark Web Analysis','Malware Analysis','Attribution',
 'Phishing Analysis','Forensic Investigation','Threat Hunting','Vulnerability Assessment','Incident Response','Other']
OSINT_SOURCE_TYPES=['Social Media','Public Records','Dark Web','DNS/WHOIS','Satellite Imagery','Government Data','News Media',
 'Forums & Communities','Code Repositories','Corporate Records','Court Records','Academic Literature','Leaked Data','Other']
POLICY={'categories':CATEGORIES,'investigation_types':INVESTIGATION_TYPES,'source_types':OSINT_SOURCE_TYPES}
