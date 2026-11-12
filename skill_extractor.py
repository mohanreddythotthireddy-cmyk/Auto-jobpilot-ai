"""Phase 1 - Skill extraction and synonym normalisation.

How it avoids a fixed personal skill list
-----------------------------------------
1. Anything the resume itself *lists* (skills section, 'Technologies:' lines in
   projects, items inside parentheses) is captured even if the tool is unknown
   to the alias catalogue below.
2. The catalogue is only a *dictionary of synonyms and categories*. A skill is
   reported only if its text actually appears in the resume. Nothing is added
   because it is in the catalogue.
3. Every skill keeps its original wording and the section/project/line where
   it was found.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Optional

from resume_parser import ParsedResume, TECH_LINE_RE, BULLET_RE, strip_md, parse_resume_text

EXTRACTOR_VERSION = "1.1"

PL, CLOUD, AWS = "Programming Languages", "Cloud Platforms", "AWS Services"
DEVOPS, OS, DB = "DevOps Tools", "Operating Systems", "Databases"
NET, FW, LIB = "Networking", "Frameworks", "Libraries"
TOOL, PLAT, CON = "Development Tools", "Software Platforms", "Concepts"
DATA, OTHER = "Data & Big Data", "Other"

# (canonical name, category, extra aliases). Dictionary only - never a skill list.
CATALOG = [
    # languages
    ("Python", PL, []), ("Java", PL, []), ("C", PL, []), ("C++", PL, ["CPP"]),
    ("C#", PL, ["C Sharp", "CSharp"]), ("JavaScript", PL, ["Javascript", "JS", "ECMAScript"]),
    ("TypeScript", PL, ["Typescript", "TS"]), ("Kotlin", PL, []), ("Swift", PL, []),
    ("Go", PL, ["Golang"]), ("Rust", PL, []), ("Ruby", PL, []), ("PHP", PL, []),
    ("R", PL, []), ("Scala", PL, []), ("Dart", PL, []), ("MATLAB", PL, ["Matlab"]),
    ("SQL", PL, ["Structured Query Language"]), ("PL/SQL", PL, ["PLSQL"]), ("T-SQL", PL, ["TSQL"]),
    ("Bash", PL, ["Bash Scripting"]), ("Shell Scripting", PL, ["Shell Script", "Shell"]),
    ("PowerShell", PL, []), ("HTML", PL, ["HTML5"]), ("CSS", PL, ["CSS3"]),
    # cloud + AWS
    ("AWS", CLOUD, ["Amazon Web Services"]), ("Microsoft Azure", CLOUD, ["Azure"]),
    ("Google Cloud Platform", CLOUD, ["GCP", "Google Cloud"]),
    ("AWS EC2", AWS, ["EC2", "Amazon EC2", "Amazon Elastic Compute Cloud", "Elastic Compute Cloud"]),
    ("AWS S3", AWS, ["S3", "Amazon S3", "Amazon Simple Storage Service", "Simple Storage Service"]),
    ("AWS IAM", AWS, ["IAM", "Identity and Access Management", "AWS Identity and Access Management"]),
    ("AWS VPC", AWS, ["VPC", "Amazon VPC", "Virtual Private Cloud"]),
    ("AWS RDS", AWS, ["RDS", "Amazon RDS", "Relational Database Service"]),
    ("AWS Lambda", AWS, ["Amazon Lambda"]), ("AWS CloudWatch", AWS, ["CloudWatch", "Amazon CloudWatch"]),
    ("AWS CloudFormation", AWS, ["CloudFormation"]), ("AWS DynamoDB", AWS, ["DynamoDB", "Amazon DynamoDB"]),
    ("AWS EBS", AWS, ["EBS", "Elastic Block Store"]), ("AWS ELB", AWS, ["ELB", "Elastic Load Balancer", "Elastic Load Balancing"]),
    ("AWS Route 53", AWS, ["Route 53", "Route53"]), ("AWS SNS", AWS, ["SNS"]), ("AWS SQS", AWS, ["SQS"]),
    ("AWS ECS", AWS, ["ECS"]), ("AWS EKS", AWS, ["EKS"]), ("AWS Glue", AWS, []),
    ("AWS Redshift", AWS, ["Redshift", "Amazon Redshift"]), ("AWS Athena", AWS, ["Athena"]),
    ("AWS EMR", AWS, ["EMR"]), ("AWS Auto Scaling", AWS, ["Auto Scaling"]),
    ("AWS Internet Gateway", AWS, ["Internet Gateway", "Internet Gateways", "IGW", "AWS IGW"]),
    ("AWS NAT Gateway", AWS, ["NAT Gateway", "NAT Gateways", "AWS NAT Gateway", "NAT GW"]),
    ("AWS Security Groups", AWS, ["Security Groups", "Security Group", "AWS Security Group"]),
    ("AWS Subnets", AWS, ["Subnets", "Subnet", "Public Subnet", "Public Subnets",
                          "Private Subnet", "Private Subnets", "AWS Subnet"]),
    ("AWS ALB", AWS, ["ALB", "Application Load Balancer", "Application Load Balancers", "Amazon ALB"]),
    ("AWS NLB", AWS, ["NLB", "Network Load Balancer", "Network Load Balancers"]),
    ("AWS Network ACL", AWS, ["NACL", "NACLs", "Network ACL", "Network ACLs", "Network Access Control List"]),
    ("AWS Route Tables", AWS, ["Route Table", "Route Tables"]),
    # devops
    ("Docker", DEVOPS, []), ("Kubernetes", DEVOPS, ["K8s"]), ("Jenkins", DEVOPS, []),
    ("Git", DEVOPS, []), ("GitHub", DEVOPS, ["Github"]), ("GitLab", DEVOPS, ["Gitlab"]),
    ("Bitbucket", DEVOPS, []), ("GitHub Actions", DEVOPS, ["Github Actions"]),
    ("Terraform", DEVOPS, []), ("Ansible", DEVOPS, []), ("Helm", DEVOPS, []),
    ("Argo CD", DEVOPS, ["ArgoCD"]), ("Prometheus", DEVOPS, []), ("Grafana", DEVOPS, []),
    ("Maven", DEVOPS, []), ("Gradle", DEVOPS, []), ("Nginx", DEVOPS, ["NGINX"]),
    ("CI/CD", CON, ["Continuous Integration and Continuous Deployment",
                    "Continuous Integration and Continuous Delivery",
                    "Continuous Integration/Continuous Deployment",
                    "Continuous Integration / Continuous Deployment", "CICD", "CI CD"]),
    ("Infrastructure as Code", CON, ["IaC", "Infrastructure-as-Code"]),
    # OS
    ("Linux", OS, ["GNU/Linux"]), ("Ubuntu", OS, []), ("Kali Linux", OS, []),
    ("Windows", OS, ["Microsoft Windows"]), ("macOS", OS, ["Mac OS"]), ("Android", PLAT, []),
    # databases
    ("MySQL", DB, []), ("PostgreSQL", DB, ["Postgres"]), ("SQLite", DB, []), ("MongoDB", DB, ["Mongo DB"]),
    ("Oracle Database", DB, ["Oracle DB"]), ("Redis", DB, []), ("NoSQL", DB, []),
    ("Microsoft SQL Server", DB, ["MS SQL Server", "SQL Server", "MSSQL"]), ("Firebase", PLAT, []),
    ("Cassandra", DB, []),
    # big data / data
    ("Apache Spark", DATA, ["Spark"]), ("PySpark", DATA, []), ("Hadoop", DATA, []),
    ("Apache Kafka", DATA, ["Kafka"]), ("Apache Airflow", DATA, ["Airflow"]), ("Hive", DATA, ["Apache Hive"]),
    ("Tableau", DATA, []), ("Power BI", DATA, ["PowerBI"]), ("Microsoft Excel", DATA, ["MS Excel", "Excel"]),
    # libraries
    ("Pandas", LIB, []), ("NumPy", LIB, ["Numpy"]), ("Matplotlib", LIB, []), ("Seaborn", LIB, []),
    ("scikit-learn", LIB, ["Scikit-learn", "sklearn", "Scikit Learn"]), ("TensorFlow", LIB, ["Tensorflow"]),
    ("PyTorch", LIB, ["Pytorch"]), ("Keras", LIB, []), ("OpenCV", LIB, []), ("NLTK", LIB, []),
    ("Requests", LIB, []), ("BeautifulSoup", LIB, ["Beautiful Soup", "bs4"]), ("Selenium", LIB, []),
    ("Plotly", LIB, []), ("Jetpack Compose", LIB, []), ("Retrofit", LIB, []),
    # frameworks
    ("Django", FW, []), ("Flask", FW, []), ("FastAPI", FW, ["Fast API"]), ("Streamlit", FW, []),
    ("Spring Boot", FW, ["SpringBoot"]), ("Spring", FW, ["Spring Framework"]), ("Hibernate", FW, []),
    ("React", FW, ["React.js", "ReactJS", "React JS"]), ("React Native", FW, []),
    ("Angular", FW, ["AngularJS"]), ("Vue.js", FW, ["Vue", "VueJS"]), ("Next.js", FW, ["NextJS"]),
    ("Node.js", FW, ["NodeJS", "Node JS"]), ("Express.js", FW, ["Express", "ExpressJS"]),
    ("Bootstrap", FW, []), ("Tailwind CSS", FW, ["Tailwind", "TailwindCSS"]), ("Flutter", FW, []),
    ("jQuery", LIB, ["JQuery"]), ("Pytest", TOOL, ["PyTest"]), ("JUnit", TOOL, []),
    # tools
    ("VS Code", TOOL, ["Visual Studio Code", "VSCode"]), ("Android Studio", TOOL, []),
    ("IntelliJ IDEA", TOOL, ["IntelliJ"]), ("PyCharm", TOOL, []), ("Eclipse", TOOL, []),
    ("Postman", TOOL, []), ("Jira", TOOL, ["JIRA"]), ("Figma", TOOL, []), ("Jupyter Notebook", TOOL, ["Jupyter"]),
    ("Google Colab", TOOL, ["Colab"]), ("Wireshark", NET, []), ("Cisco Packet Tracer", NET, ["Packet Tracer"]),
    # networking
    ("TCP/IP", NET, ["TCP IP"]), ("DNS", NET, []), ("DHCP", NET, []), ("HTTP", NET, ["HTTPS", "HTTP/HTTPS"]),
    ("OSI Model", NET, ["OSI"]), ("Subnetting", NET, []), ("VPN", NET, []), ("Firewall", NET, ["Firewalls"]),
    ("Computer Networks", NET, ["Computer Networking", "Networking"]), ("Load Balancing", NET, ["Load Balancer"]),
    # concepts
    ("REST API", CON, ["REST APIs", "RESTful API", "RESTful APIs", "RESTful Web Services", "REST"]),
    ("Object-Oriented Programming", CON, ["OOP", "OOPs", "Object Oriented Programming"]),
    ("Data Structures", CON, ["Data Structures and Algorithms", "DSA"]), ("Algorithms", CON, []),
    ("Machine Learning", CON, ["ML"]), ("Deep Learning", CON, []),
    ("Natural Language Processing", CON, ["NLP"]), ("Computer Vision", CON, []),
    ("DBMS", CON, ["Database Management System", "Database Management Systems"]),
    ("Agile", CON, ["Agile Methodology"]), ("Scrum", CON, []), ("SDLC", CON, ["Software Development Life Cycle"]),
    ("Microservices", CON, ["Microservice"]), ("Web Scraping", CON, []), ("Data Analysis", CON, []),
    ("ETL", CON, []), ("Cloud Computing", CON, []), ("Version Control", CON, []),
    ("Operating Systems", CON, []), ("Cybersecurity", CON, ["Cyber Security"]),
]

# Short/ambiguous words: only trust them in explicit skill lists, or with exact capitalisation.
LIST_ONLY = {"C", "R", "Go"}
CASE_SENSITIVE = {"React", "Spark", "Swift", "Express", "Rust", "Ruby", "Dart", "Excel",
                  "Flask", "Vue", "Hive", "Spring", "Requests", "Shell", "Athena", "Helm",
                  "REST", "ML", "OSI", "TS", "JS", "Networking", "Eclipse", "Colab", "Tailwind"}


def _ws(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


ALIAS_MAP: dict = {}    # lowercase alias -> canonical
ALIAS_ORIG: dict = {}   # lowercase alias -> alias as written (for case checks)
CATEGORY: dict = {}     # canonical -> category
for _canon, _cat, _aliases in CATALOG:
    CATEGORY[_canon] = _cat
    for _a in [_canon, *_aliases]:
        k = _a.lower()
        if k in ALIAS_MAP and ALIAS_MAP[k] != _canon:
            raise ValueError(f"Alias collision: {_a!r} -> {ALIAS_MAP[k]!r} and {_canon!r}")
        ALIAS_MAP[k] = _canon
        ALIAS_ORIG[k] = _a

_alts = sorted(ALIAS_ORIG.values(), key=len, reverse=True)
_PATTERN = re.compile(
    r"(?<![\w+#.])(?:" + "|".join(re.escape(a).replace("\\ ", r"\s+") for a in _alts) + r")(?![\w+#]|\.\w)",
    re.I,
)
_URL_OR_MAIL = re.compile(r"(?:https?://|www\.)\S+|\S+@\S+|(?:github|linkedin)\.com/\S*", re.I)

LABEL_RE = re.compile(r"^\s*(?:[-*+\u2022]\s*)?([A-Za-z][A-Za-z0-9 &/+.\-]{1,40}?)\s*:\s*(.+)$")
LABEL_CATEGORY = [
    ("language", PL), ("cloud", CLOUD), ("aws", AWS), ("devops", DEVOPS), ("operating", OS),
    ("database", DB), ("network", NET), ("framework", FW), ("librar", LIB),
    ("tool", TOOL), ("platform", PLAT), ("concept", CON), ("big data", DATA),
]
# Section-style labels ("Networking: ...") are headings, not skills the candidate listed.
GENERIC_LABELS = {"networking", "databases", "database", "cloud", "devops", "tools", "frameworks",
                  "libraries", "languages", "programming languages", "operating systems",
                  "platforms", "concepts", "big data", "tools & technologies", "technologies"}
STOP = {"basic", "basics", "advanced", "intermediate", "beginner", "expert", "proficient",
        "familiar", "knowledge", "hands", "experience", "good", "strong", "excellent", "etc",
        "others", "other", "including", "like", "such", "various", "level", "years", "year",
        "core", "working", "familiarity", "exposure", "skills", "skill"}


@dataclass
class Evidence:
    section: str
    section_kind: Optional[str]
    project: Optional[str]
    line: str
    original: str


@dataclass
class Skill:
    name: str
    category: str
    in_catalog: bool
    original_forms: list = field(default_factory=list)
    evidence: list = field(default_factory=list)

    @property
    def found_in(self) -> list:
        return sorted({e.section_kind or "other" for e in self.evidence})

    @property
    def projects(self) -> list:
        return sorted({e.project for e in self.evidence if e.section_kind == "projects" and e.project})

    def to_dict(self) -> dict:
        d = asdict(self)
        d["found_in"] = self.found_in
        d["projects"] = self.projects
        return d


def _split_top(text: str) -> list:
    """Split on , ; | bullets - but not inside brackets."""
    parts, depth, buf = [], 0, []
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if depth == 0 and ch in ",;|\u2022\u00b7":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def _scan(text: str, list_mode: bool) -> list:
    """Return [(canonical, matched_text)] for catalogue terms present in text."""
    found = []
    text = _URL_OR_MAIL.sub(" ", text)
    for m in _PATTERN.finditer(text):
        matched = _ws(m.group(0))
        key = matched.lower()
        orig = ALIAS_ORIG[key]
        if orig in LIST_ONLY and not list_mode:
            continue
        if orig in CASE_SENSITIVE and matched != orig and not list_mode:
            continue
        if orig in CASE_SENSITIVE and matched != orig and list_mode and len(orig) <= 3:
            continue
        found.append((ALIAS_MAP[key], matched))
    return found


def _plausible_unknown(t: str) -> bool:
    if not (2 <= len(t) <= 40) or not re.search(r"[A-Za-z]{2}", t):
        return False
    words = t.split()
    if len(words) > 4 or (t.endswith(".") and len(words) > 1):
        return False
    if any(w in STOP for w in re.findall(r"[a-z]+", t.lower())):
        return False
    return not re.match(r"^(and|or|with|using|etc|of|in|for|the|a)\b", t.lower())


def _label_category(label: str) -> Optional[str]:
    low = label.lower()
    for needle, cat in LABEL_CATEGORY:
        if needle in low:
            return cat
    return None


def dedupe_key(name: str) -> str:
    """Key for spotting duplicates such as 'Security Group' / 'security-groups'.
    Keeps + and # so C and C++ (or C#) are never merged."""
    k = re.sub(r"[\s\-_.]", "", name.lower())
    if len(k) > 4 and k.endswith("s") and not k.endswith("ss"):
        k = k[:-1]
    return k


class _Collector:
    def __init__(self):
        self.skills: dict = {}
        self._seen: set = set()

    def add(self, name, category, in_catalog, original, ctx, line):
        sk = self.skills.get(name.lower())
        if sk is None:
            sk = Skill(name=name, category=category, in_catalog=in_catalog)
            self.skills[name.lower()] = sk
        if original and original not in sk.original_forms:
            sk.original_forms.append(original)
        ev = Evidence(section=ctx[0], section_kind=ctx[1], project=ctx[2],
                      line=_ws(line)[:200], original=original)
        key = (ev.section, ev.project, ev.line, ev.original)
        if (name.lower(), key) not in self._seen:
            self._seen.add((name.lower(), key))
            sk.evidence.append(ev)


def _process_atom(text, prefix, hint, ctx, line, out: _Collector) -> list:
    """Resolve one list item. Returns canonical names added."""
    t = text.strip().strip(".:;-\u2013 ")
    t = BULLET_RE.sub("", t).strip()
    if not t:
        return []
    added = []
    if prefix:
        c = ALIAS_MAP.get(_ws(prefix + t).lower())
        if c:
            out.add(c, CATEGORY[c], True, t, ctx, line)   # keep the resume's own wording
            return [c]
    c = ALIAS_MAP.get(_ws(t).lower())
    if c:
        out.add(c, CATEGORY[c], True, t, ctx, line)
        return [c]
    for c, matched in _scan(t, list_mode=True):
        out.add(c, CATEGORY[c], True, matched, ctx, line)
        added.append(c)
    if added:
        return added
    if _plausible_unknown(t):
        out.add(t, hint or OTHER, False, t, ctx, line)
        return [t]
    return []


def _process_list(text, hint, label_prefix, ctx, line, out: _Collector):
    for item in _split_top(text):
        m = re.match(r"^(.*?)\s*[(\[](.*)[)\]]\s*(.*)$", item)
        if m and m.group(1).strip():
            parent, inner, tail = m.group(1), m.group(2), m.group(3)
            names = _process_atom(parent, label_prefix, hint, ctx, line, out)
            prefix = "AWS " if ("AWS" in names or label_prefix) else ""
            for sub in _split_top(inner):
                _process_atom(sub, prefix, hint, ctx, line, out)
            if tail.strip():
                _process_atom(tail, label_prefix, hint, ctx, line, out)
        else:
            _process_atom(item, label_prefix, hint, ctx, line, out)


def extract_skills(resume: ParsedResume) -> list:
    """Extract every skill that appears in the resume, with source references."""
    out = _Collector()
    for b in resume.blocks:
        if b.kind is None:           # header/contact lines are not skill evidence
            continue
        section = b.parent or b.title
        project = b.title if b.is_item else None
        ctx = (section, b.kind, project)
        lines = list(b.lines)
        if b.is_item:
            lines.insert(0, b.title)
        for raw in lines:
            plain = strip_md(raw)
            if not plain.strip():
                continue
            hint, prefix, body = None, "", None
            lm = LABEL_RE.match(plain)
            tm = TECH_LINE_RE.match(plain)
            if b.kind == "skills":
                if lm:
                    label, body = lm.group(1), lm.group(2)
                    hint = _label_category(label)
                    if "aws" in label.lower() or "amazon" in label.lower():
                        prefix = "AWS "
                    lc = ALIAS_MAP.get(_ws(label).lower())
                    if lc and _ws(label).lower() not in GENERIC_LABELS:
                        out.add(lc, CATEGORY[lc], True, label.strip(), ctx, plain)
                else:
                    body = BULLET_RE.sub("", plain)
                _process_list(body, hint, prefix, ctx, plain, out)
            else:
                if tm:
                    _process_list(tm.group(2), None, "", ctx, plain, out)
                for c, matched in _scan(plain, list_mode=False):
                    out.add(c, CATEGORY[c], True, matched, ctx, plain)
    merged: dict = {}
    for sk in out.skills.values():
        key = dedupe_key(sk.name)
        base = merged.get(key)
        if base is None:
            merged[key] = sk
            continue
        keep, drop = (base, sk) if base.in_catalog or not sk.in_catalog else (sk, base)
        for f in drop.original_forms:
            if f not in keep.original_forms:
                keep.original_forms.append(f)
        keep.evidence.extend(e for e in drop.evidence if e not in keep.evidence)
        merged[key] = keep
    return sorted(merged.values(), key=lambda s: (s.category, s.name.lower()))


def extract_skills_from_text(text: str) -> list:
    return extract_skills(parse_resume_text(text))


def group_by_category(skills: list) -> dict:
    groups: dict = {}
    for s in skills:
        groups.setdefault(s.category, []).append(s)
    return groups
