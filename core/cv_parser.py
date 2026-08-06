import os
import re
import json
import logging
from pydantic import BaseModel, Field

def extract_text_from_file(file_path):
    """Extract raw text from PDF, DOCX, or TXT resumes."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    
    ext = os.path.splitext(file_path)[1].lower()
    text = ""
    
    if ext == '.pdf':
        try:
            import pypdf
            reader = pypdf.PdfReader(file_path)
            pages_text = [page.extract_text() or "" for page in reader.pages]
            text = "\n".join(pages_text)
        except Exception as e:
            logging.error(f"Error reading PDF with pypdf: {e}")
            raise RuntimeError("Could not extract text from PDF. Please ensure pypdf is installed and file is valid.")
            
    elif ext == '.docx':
        try:
            import docx
            doc = docx.Document(file_path)
            text = "\n".join([p.text for p in doc.paragraphs if p.text])
        except Exception:
            try:
                import zipfile
                import xml.etree.ElementTree as ET
                with zipfile.ZipFile(file_path, 'r') as docx_zip:
                    xml_content = docx_zip.read('word/document.xml')
                    tree = ET.fromstring(xml_content)
                    texts = [node.text for node in tree.iter() if node.text]
                    text = " ".join(texts)
            except Exception as e:
                logging.error(f"Error reading DOCX: {e}")
                raise RuntimeError("Could not extract text from DOCX file.")
                
    elif ext in ['.txt', '.md']:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read()
    else:
        raise ValueError(f"Unsupported file format: {ext}. Supported formats: .pdf, .docx, .txt, .md")
        
    return text.strip()

import uuid

class RoleSuggestionSchema(BaseModel):
    title: str = Field(description="Title of the recommended job role, e.g., Data Scientist or AI Engineer.")
    english_terms: list[str] = Field(description="List of English search keywords for this role.")
    arabic_terms: list[str] = Field(description="List of Arabic translations or search terms for this role.")

class CVExtractionSchema(BaseModel):
    resume_keywords: list[str] = Field(description="List of core technical skills, programming languages, frameworks, and methodologies found in the CV (in lowercase, e.g., python, sql, machine learning, pytorch, aws).")
    suggested_removals: list[str] = Field(default=[], description="List of irrelevant skills, outdated technologies, or conflicting keywords currently in config that should be removed.")
    target_roles: list[RoleSuggestionSchema] = Field(description="Recommended target job roles based on the candidate's CV experience.")
    roles_to_remove: list[str] = Field(default=[], description="Titles of current target roles that do not fit the candidate's background.")
    target_levels: list[str] = Field(description="Inferred target seniority levels, e.g., junior, fresh, intern, mid-level, senior.")
    levels_to_remove: list[str] = Field(default=[], description="Seniority levels that conflict with candidate's actual experience (e.g. senior/manager if candidate is fresh).")
    user_brief: str = Field(description="A clear, professional 3-4 sentence first-person profile summary describing the user's background, core expertise, experience level, and what kind of roles they are seeking.")
    location: str = Field(default="Egypt", description="The country or primary residency mentioned in the CV if found.")

def generate_cv_proposals(parsed_cv, current_config):
    """
    Compares AI/heuristic CV extraction results with current config to generate structured ADD and REMOVE proposal items.
    Returns a list of dict proposals.
    """
    proposals = []
    
    # 1. Resume Keywords / Skills Additions
    existing_skills = set([str(x).lower().strip() for x in current_config.get("RESUME_KEYWORDS", []) + current_config.get("MUST_HAVE_SKILLS", [])])
    for skill in parsed_cv.get("resume_keywords", []):
        s_clean = str(skill).lower().strip()
        if s_clean and s_clean not in existing_skills:
            proposals.append({
                "id": f"cv_prop_{uuid.uuid4().hex[:8]}",
                "source": "CV Import",
                "field": "RESUME_KEYWORDS",
                "type": "add",
                "value": s_clean,
                "display_name": f"Skill: {s_clean.title()}",
                "reason": "Extracted from CV as key competency"
            })
            existing_skills.add(s_clean)

    # Resume Keywords Removals
    for s_rem in parsed_cv.get("suggested_removals", []):
        s_clean = str(s_rem).lower().strip()
        if s_clean in existing_skills:
            proposals.append({
                "id": f"cv_prop_{uuid.uuid4().hex[:8]}",
                "source": "CV Import",
                "field": "RESUME_KEYWORDS",
                "type": "remove",
                "value": s_clean,
                "display_name": f"Skill: {s_clean.title()}",
                "reason": "AI identified as irrelevant or outdated for CV profile"
            })

    # 2. Target Roles Additions & Removals
    existing_roles = current_config.get("ROLES", [])
    existing_role_titles = set([r.get("title", "").lower().strip() for r in existing_roles if isinstance(r, dict)])
    
    for r in parsed_cv.get("target_roles", []):
        title = r.get("title", "").strip() if isinstance(r, dict) else str(r).strip()
        if title and title.lower() not in existing_role_titles:
            role_obj = r if isinstance(r, dict) else {"title": title, "english_terms": [title], "arabic_terms": []}
            proposals.append({
                "id": f"cv_prop_{uuid.uuid4().hex[:8]}",
                "source": "CV Import",
                "field": "ROLES",
                "type": "add",
                "value": role_obj,
                "display_name": f"Role: {title}",
                "reason": "Recommended target role based on CV experience"
            })
            existing_role_titles.add(title.lower())

    for r_rem in parsed_cv.get("roles_to_remove", []):
        title_rem = str(r_rem).strip().lower()
        for r_exist in existing_roles:
            r_title = r_exist.get("title", "").strip()
            if r_title.lower() == title_rem:
                proposals.append({
                    "id": f"cv_prop_{uuid.uuid4().hex[:8]}",
                    "source": "CV Import",
                    "field": "ROLES",
                    "type": "remove",
                    "value": r_exist,
                    "display_name": f"Role: {r_title}",
                    "reason": "Does not align with CV career direction"
                })

    # 3. Target Levels Additions & Removals
    existing_levels = set([str(l).lower().strip() for l in current_config.get("TARGET_LEVELS", [])])
    for level in parsed_cv.get("target_levels", []):
        l_clean = str(level).lower().strip()
        if l_clean and l_clean not in existing_levels:
            proposals.append({
                "id": f"cv_prop_{uuid.uuid4().hex[:8]}",
                "source": "CV Import",
                "field": "TARGET_LEVELS",
                "type": "add",
                "value": l_clean,
                "display_name": f"Experience Level: {l_clean.title()}",
                "reason": "Inferred experience level from CV"
            })
            existing_levels.add(l_clean)

    for l_rem in parsed_cv.get("levels_to_remove", []):
        l_clean = str(l_rem).lower().strip()
        if l_clean in existing_levels:
            proposals.append({
                "id": f"cv_prop_{uuid.uuid4().hex[:8]}",
                "source": "CV Import",
                "field": "TARGET_LEVELS",
                "type": "remove",
                "value": l_clean,
                "display_name": f"Experience Level: {l_clean.title()}",
                "reason": "Conflicts with actual experience level in CV"
            })

    # 4. Location Additions
    cv_loc = parsed_cv.get("location")
    if cv_loc:
        existing_locs = set([str(x).lower().strip() for x in current_config.get("LOCATION", [])])
        if cv_loc.lower().strip() not in existing_locs:
            proposals.append({
                "id": f"cv_prop_{uuid.uuid4().hex[:8]}",
                "source": "CV Import",
                "field": "LOCATION",
                "type": "add",
                "value": cv_loc,
                "display_name": f"Location: {cv_loc}",
                "reason": "Residency/Country extracted from CV"
            })

    # 5. User Brief Proposal
    if parsed_cv.get("user_brief"):
        proposals.append({
            "id": f"cv_prop_{uuid.uuid4().hex[:8]}",
            "source": "CV Import",
            "field": "USER_BRIEF",
            "type": "add",
            "value": parsed_cv["user_brief"],
            "display_name": "Profile Brief: Tailored Summary",
            "reason": "Updated profile summary generated from CV"
        })

    return proposals

def parse_cv_with_ai(file_path, api_key=None):
    """
    Parses a CV/Resume file using Gemini AI and returns structured AI matching configurations.
    Falls back to intelligent local keyword matching if no AI key or if API calls fail.
    """
    raw_text = extract_text_from_file(file_path)
    if not raw_text:
        return {"error": "Extracted text is empty. Could not read CV contents."}
        
    # Attempt AI parsing if key exists
    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key:
        try:
            from core.config import decrypt_value
            key = decrypt_value(os.getenv("GEMINI_API_KEY"))
        except Exception:
            pass

    if key and key != "Your_GEMINI_API_KEY_Here":
        try:
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=key)
            
            prompt = f"""
            You are an expert technical recruiter and AI career profiling assistant.
            Analyze the following resume text and generate optimal configuration settings for an AI-powered job matching agent.
            Extract core technical skills as `resume_keywords`, infer appropriate `target_roles` with search terms in English and Arabic, determine `target_levels` (e.g., junior, fresh, intern, mid, senior), extract residency country `location`, and craft an authoritative 3-4 sentence `user_brief` in first person summarizing the candidate's profile for LLM job scoring.
            Also identify any `suggested_removals` (skills/keywords currently unsuited), `roles_to_remove`, or `levels_to_remove`.
            
            RESUME TEXT:
            {raw_text[:8000]}
            """
            
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=CVExtractionSchema,
                )
            )
            parsed = json.loads(response.text)
            parsed["status"] = "success"
            parsed["engine"] = "gemini"
            return parsed
            
        except Exception as e:
            logging.warning(f"Gemini AI CV parsing failed ({e}). Falling back to intelligent heuristic parser.")

    # Intelligent Heuristic Fallback Engine
    return parse_cv_heuristic(raw_text)

def parse_cv_heuristic(text):
    """Heuristic offline taxonomy matcher for CV text."""
    text_lower = text.lower()
    
    # Common skill taxonomy
    common_skills = [
        "python", "sql", "mysql", "postgresql", "mongodb", "nosql", "java", "c++", "c#", "javascript", "typescript",
        "react", "angular", "vue", "html", "css", "node.js", "express", "django", "flask", "fastapi", "spring", "dotnet",
        "artificial intelligence", "ai", "machine learning", "ml", "deep learning", "dl", "nlp", "computer vision",
        "tensorflow", "keras", "pytorch", "scikit-learn", "pandas", "numpy", "matplotlib", "seaborn", "scipy",
        "power bi", "tableau", "excel", "dax", "bi", "data engineering", "etl", "spark", "hadoop", "airflow", "snowflake",
        "docker", "kubernetes", "aws", "azure", "gcp", "linux", "git", "github", "mlops", "ci/cd", "restful api",
        "genai", "llm", "transformers", "huggingface", "langchain", "llamaindex", "rag", "opencv", "yolo", "cnn", "rnn",
        "lstm", "statistics", "a/b testing", "feature engineering", "eda", "data analyst", "data scientist", "data engineer"
    ]
    
    found_skills = [s for s in common_skills if re.search(r'\b' + re.escape(s) + r'\b', text_lower)]
    
    # Split into core vs nice to have
    core_skills = found_skills[:15] if found_skills else ["python", "sql", "problem solving"]
    nice_skills = found_skills[15:] if len(found_skills) > 15 else ["git", "linux", "communication"]
    
    # Infer roles
    roles = []
    if any(k in text_lower for k in ["data scientist", "machine learning", "deep learning", "ai", "artificial intelligence", "nlp", "computer vision"]):
        roles.append({
            "title": "AI & Machine Learning",
            "english_terms": ["AI Engineer", "Machine Learning Engineer", "Data Scientist", "Computer Vision Engineer", "NLP Engineer", "Deep Learning Engineer"],
            "arabic_terms": ["مهندس ذكاء اصطناعي", "مهندس تعلم الآلة", "عالم بيانات"]
        })
    if any(k in text_lower for k in ["data analyst", "power bi", "tableau", "business intelligence", "analytics", "sql"]):
        roles.append({
            "title": "Data & Business Analytics",
            "english_terms": ["Data Analyst", "Business Intelligence", "BI Analyst", "BI Developer", "Data Analytics", "Analytics Engineer"],
            "arabic_terms": ["محلل بيانات", "ذكاء الأعمال", "محلل ذكاء الأعمال", "تحليلات البيانات"]
        })
    if any(k in text_lower for k in ["backend", "frontend", "full stack", "software engineer", "web developer", "react", "django", "fastapi"]):
        roles.append({
            "title": "Software Development",
            "english_terms": ["Software Engineer", "Backend Developer", "Full Stack Developer"],
            "arabic_terms": ["مطور برمجيات", "مهندس برمجيات"]
        })
    if not roles:
        roles.append({
            "title": "General Technology & Engineering",
            "english_terms": ["Technology Specialist", "Engineer", "Analyst"],
            "arabic_terms": []
        })

    # Infer level
    levels = ["junior", "fresh", "entry", "intern", "trainee"]
    if any(w in text_lower for w in ["senior", "lead", "manager", "architect", "5+ years", "6+ years", "7+ years"]):
        levels = ["senior", "lead", "mid-level"]
    elif any(w in text_lower for w in ["2+ years", "3+ years", "4+ years", "mid-level", "experienced"]):
        levels = ["mid-level", "experienced", "junior"]
        
    brief_skills = ", ".join([s.title() for s in core_skills[:6]])
    level_str = levels[0].title()
    brief = f"I am a {level_str} professional experienced in {brief_skills}. I am actively seeking exciting opportunities matching my core competencies in {roles[0]['title']} and eager to bring impactful results to innovative projects."

    return {
        "status": "success",
        "engine": "heuristic_fallback",
        "resume_keywords": core_skills,
        "suggested_removals": [],
        "target_roles": roles,
        "roles_to_remove": [],
        "target_levels": levels,
        "levels_to_remove": [],
        "user_brief": brief,
        "location": "Egypt"
    }

