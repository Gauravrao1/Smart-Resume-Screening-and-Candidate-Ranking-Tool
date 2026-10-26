"""Skill taxonomy and matching.

Every skill has a canonical name plus aliases. Matching uses custom word
boundaries so that "C++", "C#", ".NET" and "Node.js" work, and so that
"Java" never matches inside "JavaScript".
"""
from __future__ import annotations

import re
from functools import lru_cache

SKILLS: dict[str, list[str]] = {
    # --- Languages ---
    "Python": ["python", "python3"],
    "Java": ["java", "core java"],
    "JavaScript": ["javascript", "js", "ecmascript", "es6"],
    "TypeScript": ["typescript"],
    "C++": ["c++"],
    "C#": ["c#"],
    "C": ["c programming", "c language"],
    "Go": ["golang"],
    "R": ["r programming", "r language", "rstudio"],
    "Rust": ["rust"],
    "PHP": ["php"],
    "Ruby": ["ruby"],
    "Swift": ["swift"],
    "Kotlin": ["kotlin"],
    "Scala": ["scala"],
    "MATLAB": ["matlab"],
    "SQL": ["sql", "t-sql", "pl/sql"],
    # --- Web / backend ---
    "HTML": ["html", "html5"],
    "CSS": ["css", "css3"],
    "React": ["react", "reactjs", "react.js"],
    "Angular": ["angular", "angularjs"],
    "Vue": ["vue", "vuejs", "vue.js"],
    "Node.js": ["node.js", "nodejs"],
    "Express": ["express.js", "expressjs"],
    "Django": ["django"],
    "Flask": ["flask"],
    "FastAPI": ["fastapi"],
    "Spring Boot": ["spring boot", "springboot", "spring framework"],
    ".NET": [".net", "dotnet", "asp.net"],
    "Laravel": ["laravel"],
    "Ruby on Rails": ["ruby on rails", "rails"],
    "REST APIs": ["rest api", "rest apis", "restful", "restful api", "restful apis", "rest"],
    "GraphQL": ["graphql"],
    "Microservices": ["microservices", "microservice"],
    "Android": ["android"],
    "iOS": ["ios"],
    "Flutter": ["flutter"],
    "React Native": ["react native"],
    # --- Data / AI ---
    "Machine Learning": ["machine learning", "ml"],
    "Deep Learning": ["deep learning"],
    "NLP": ["nlp", "natural language processing"],
    "Computer Vision": ["computer vision", "image processing"],
    "LLMs": ["llm", "llms", "large language model", "large language models", "generative ai"],
    "Data Analysis": ["data analysis", "data analytics", "data analyst"],
    "Data Science": ["data science", "data scientist"],
    "Statistics": ["statistics", "statistical analysis", "statistical modeling"],
    "Pandas": ["pandas"],
    "NumPy": ["numpy"],
    "scikit-learn": ["scikit-learn", "sklearn", "scikit learn"],
    "TensorFlow": ["tensorflow"],
    "Keras": ["keras"],
    "PyTorch": ["pytorch"],
    "OpenCV": ["opencv"],
    "spaCy": ["spacy"],
    "NLTK": ["nltk"],
    "Hugging Face": ["hugging face", "huggingface", "transformers"],
    "Data Visualization": ["data visualization", "data visualisation", "matplotlib", "seaborn", "plotly"],
    "Tableau": ["tableau"],
    "Power BI": ["power bi", "powerbi"],
    "Excel": ["excel", "ms excel", "microsoft excel"],
    "ETL": ["etl", "data pipeline", "data pipelines"],
    "Apache Spark": ["spark", "pyspark", "apache spark"],
    "Hadoop": ["hadoop"],
    "Kafka": ["kafka"],
    "Airflow": ["airflow"],
    # --- Databases ---
    "MySQL": ["mysql"],
    "PostgreSQL": ["postgresql", "postgres"],
    "MongoDB": ["mongodb", "mongo"],
    "SQLite": ["sqlite"],
    "Redis": ["redis"],
    "Oracle DB": ["oracle db", "oracle database"],
    "NoSQL": ["nosql"],
    "Elasticsearch": ["elasticsearch"],
    # --- Cloud / DevOps ---
    "AWS": ["aws", "amazon web services"],
    "Azure": ["azure", "microsoft azure"],
    "GCP": ["gcp", "google cloud", "google cloud platform"],
    "Docker": ["docker"],
    "Kubernetes": ["kubernetes", "k8s"],
    "Terraform": ["terraform"],
    "Ansible": ["ansible"],
    "Jenkins": ["jenkins"],
    "CI/CD": ["ci/cd", "cicd", "continuous integration", "continuous delivery"],
    "Git": ["git", "github", "gitlab", "bitbucket"],
    "Linux": ["linux", "unix"],
    "Bash": ["bash", "shell scripting", "shell script"],
    # --- Engineering practice ---
    "Agile": ["agile", "scrum", "kanban"],
    "JIRA": ["jira"],
    "OOP": ["oop", "object-oriented", "object oriented"],
    "Data Structures & Algorithms": ["data structures", "algorithms", "dsa"],
    "System Design": ["system design", "software architecture"],
    "Unit Testing": ["unit testing", "pytest", "junit", "test automation", "unittest"],
    "Selenium": ["selenium"],
    "Cybersecurity": ["cybersecurity", "cyber security", "information security", "network security"],
    "Networking": ["networking", "tcp/ip"],
    # --- Soft skills ---
    "Communication": ["communication", "communication skills"],
    "Leadership": ["leadership", "team lead", "led a team", "team leadership"],
    "Problem Solving": ["problem solving", "problem-solving"],
    "Teamwork": ["teamwork", "collaboration", "team player"],
    "Project Management": ["project management", "project manager"],
}

_BEFORE = r"(?<![\w+#.])"   # not preceded by a word char, +, # or .
_AFTER = r"(?![\w+#])"      # not followed by a word char, + or #


@lru_cache(maxsize=None)
def pattern_for(name: str) -> re.Pattern:
    """Compiled regex matching a canonical skill (any alias) or a custom phrase."""
    aliases = SKILLS.get(name, [name.lower()])
    aliases = sorted(set(aliases + [name.lower()]), key=len, reverse=True)
    body = "|".join(re.escape(a).replace(r"\ ", r"\s+") for a in aliases)
    return re.compile(f"{_BEFORE}(?:{body}){_AFTER}", re.IGNORECASE)


def has_skill(name: str, text: str) -> bool:
    return bool(pattern_for(name).search(text))


def find_skills(text: str) -> list[str]:
    """All taxonomy skills mentioned in ``text`` (taxonomy order)."""
    return [s for s in SKILLS if has_skill(s, text)]


def canonicalize(token: str) -> str:
    """Map a user-typed skill to its canonical name, or keep it as a custom skill."""
    t = token.strip()
    low = t.lower()
    for canonical, aliases in SKILLS.items():
        if low == canonical.lower() or low in aliases:
            return canonical
    return t
