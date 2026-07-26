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

class RoleSuggestionSchema(BaseModel):
    title: str = Field(description="Title of the recommended job role, e.g., Data Scientist or AI Engineer.")
    english_terms: list[str] = Field(description="List of English search keywords for this role.")
    arabic_terms: list[str] = Field(description="List of Arabic translations or search terms for this role.")

class CVExtractionSchema(BaseModel):
    resume_keywords: list[str] = Field(description="List of core technical skills, programming languages, frameworks, and methodologies found in the CV (in lowercase, e.g., python, sql, machine learning, pytorch, aws).")
    nice_to_have_skills: list[str] = Field(description="List of secondary skills, tools, or bonus technologies mentioned in the CV (in lowercase).")
    target_roles: list[RoleSuggestionSchema] = Field(description="Recommended target job roles based on the candidate's CV experience.")
    target_levels: list[str] = Field(description="Inferred target seniority levels, e.g., junior, fresh, intern, mid-level, senior.")
    user_brief: str = Field(description="A clear, professional 3-4 sentence first-person profile summary describing the user's background, core expertise, experience level, and what kind of roles they are seeking.")
    location: str = Field(default="Egypt", description="The country or primary residency mentioned in the CV if found.")

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
            Extract core technical skills as `resume_keywords`, secondary tools as `nice_to_have_skills`, infer appropriate `target_roles` with search terms in English and Arabic, determine `target_levels` (e.g., junior, fresh, intern, mid, senior), extract residency country `location`, and craft an authoritative 3-4 sentence `user_brief` in first person summarizing the candidate's profile for LLM job scoring.
            
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
            "english_terms": ["AI Engineer", "Machine Learning Engineer", "Data Scientist"],
            "arabic_terms": ["مهندس ذكاء اصطناعي", "عالم بيانات"]
        })
    if any(k in text_lower for k in ["data analyst", "power bi", "tableau", "business intelligence", "analytics", "sql"]):
        roles.append({
            "title": "Data & Business Analytics",
            "english_terms": ["Data Analyst", "Business Intelligence", "Data Analytics"],
            "arabic_terms": ["محلل بيانات"]
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
        "nice_to_have_skills": nice_skills,
        "target_roles": roles,
        "target_levels": levels,
        "user_brief": brief,
        "location": "Egypt"
    }
