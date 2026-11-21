import os
import re
import json
import logging

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


def parse_cv_heuristic(text):
    """Heuristic offline taxonomy matcher for CV text."""
    try:
        from core.role_keywords import extract_skills_from_resume_text
        found_skills = extract_skills_from_resume_text(text)
    except Exception:
        found_skills = []

    text_lower = text.lower()
    if not found_skills:
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
    
    core_skills = found_skills[:15] if found_skills else ["python", "sql", "problem solving"]
    
    # Infer roles
    roles = []
    if any(k in text_lower for k in ["data scientist", "machine learning", "deep learning", "ai", "artificial intelligence", "nlp", "computer vision"]):
        roles.append({
            "title": "AI & Machine Learning",
            "english_terms": ["AI Engineer", "Machine Learning Engineer", "Data Scientist", "Computer Vision Engineer", "NLP Engineer", "Deep Learning Engineer"]
        })
    if any(k in text_lower for k in ["data analyst", "power bi", "tableau", "business intelligence", "analytics", "sql"]):
        roles.append({
            "title": "Data & Business Analytics",
            "english_terms": ["Data Analyst", "Business Intelligence", "BI Analyst", "BI Developer", "Data Analytics", "Analytics Engineer"]
        })
    if any(k in text_lower for k in ["backend", "frontend", "full stack", "software engineer", "web developer", "react", "django", "fastapi"]):
        roles.append({
            "title": "Software Development",
            "english_terms": ["Software Engineer", "Backend Developer", "Full Stack Developer"]
        })
    if not roles:
        roles.append({
            "title": "General Technology & Engineering",
            "english_terms": ["Technology Specialist", "Engineer", "Analyst"]
        })

    # Infer level using canonical categories
    levels = ["Intern / Student", "Fresh Graduate / Entry-level", "Junior"]
    levels_to_remove = ["Mid-Level", "Senior / Lead", "Manager / Director"]
    if any(w in text_lower for w in ["director", "head of", "vp", "chief", "executive", "general manager"]):
        levels = ["Manager / Director", "Senior / Lead"]
        levels_to_remove = ["Intern / Student", "Fresh Graduate / Entry-level", "Junior"]
    elif any(w in text_lower for w in ["senior", "lead", "architect", "principal", "5+ years", "6+ years", "7+ years"]):
        levels = ["Senior / Lead", "Mid-Level"]
        levels_to_remove = ["Intern / Student", "Fresh Graduate / Entry-level", "Junior"]
    elif any(w in text_lower for w in ["2+ years", "3+ years", "4+ years", "mid-level", "experienced"]):
        levels = ["Mid-Level", "Junior"]
        levels_to_remove = ["Senior / Lead", "Manager / Director"]
        
    brief_skills = ", ".join([s.title() for s in core_skills[:6]])
    level_str = levels[-1].split('/')[0].strip()
    brief = f"I am a {level_str} professional experienced in {brief_skills}. I am actively seeking exciting opportunities matching my core competencies in {roles[0]['title']} and eager to bring impactful results to innovative projects."

    return {
        "status": "success",
        "engine": "heuristic_fallback",
        "resume_keywords": core_skills,
        "suggested_removals": [],
        "target_roles": roles,
        "roles_to_remove": [],
        "target_levels": levels,
        "levels_to_remove": levels_to_remove,
        "user_brief": brief,
        "location": "Egypt"
    }

