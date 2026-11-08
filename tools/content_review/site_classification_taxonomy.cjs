'use strict';
// Independently fixed vocabulary; CI compares this policy with ALEX's Python
// classification constants. A writer must bind the policy to immutable code.
const categories=['OSINT Methodology','Social Media & SOCMINT','Dark Web & Underground','Cyber Threat Intelligence',
 'Digital Forensics & Evidence','Malware & Exploits','Vulnerability Research','Disinformation & Influence','Cybercrime & Fraud',
 'Network & Infrastructure Security','IoT & CPS Security','Privacy & Surveillance','AI/ML for Security','Foundations & Surveys','Other'];
const investigation_types=['Network Investigation','Social Media Analysis','Dark Web Analysis','Malware Analysis','Attribution',
 'Phishing Analysis','Forensic Investigation','Threat Hunting','Vulnerability Assessment','Incident Response','Other'];
const source_types=['Social Media','Public Records','Dark Web','DNS/WHOIS','Satellite Imagery','Government Data','News Media',
 'Forums & Communities','Code Repositories','Corporate Records','Court Records','Academic Literature','Leaked Data','Other'];
module.exports={categories,investigation_types,source_types};
