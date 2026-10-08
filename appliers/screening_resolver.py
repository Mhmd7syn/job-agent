import os
import re
import json
import logging
from typing import Dict, Any, Optional, Tuple, Union

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, '.env'))

from core.applicant_profile import load_profile, resolve_contextual_screening, get_resume_for_role
from core.cv_parser import extract_text_from_file

logger = logging.getLogger(__name__)

# Gemini client initialization for open-ended screening questions
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    try:
        from core.config import decrypt_value
        decrypted_key = decrypt_value(GEMINI_API_KEY)
    except Exception:
        decrypted_key = GEMINI_API_KEY
    try:
        from google import genai
        from google.genai import types
        gemini_client = genai.Client(api_key=decrypted_key)
    except Exception as e:
        logger.warning(f"Failed to initialize google-genai in screening resolver: {e}")
        gemini_client = None
else:
    gemini_client = None


class ScreeningResolver:
    """
    Intelligently maps job application form fields, screening questions,
    and radio/select options to the candidate's profile, CV, and preferences.
    """

    def __init__(self, job_title: str = "", job_location: str = "", company: str = ""):
        self.job_title = job_title
        self.job_location = job_location
        self.company = company
        self.profile = load_profile()
        self.personal_info = self.profile.get("personal_info", {})
        self.smart_screening = self.profile.get("smart_screening", {})
        self.custom_qa = self.profile.get("custom_qa_pairs", {})
        self.contextual = resolve_contextual_screening(self.job_location)

        # Matched role CV
        self.cv_path = get_resume_for_role(job_title)
        self.cv_text = ""
        if self.cv_path and os.path.exists(self.cv_path):
            try:
                self.cv_text = extract_text_from_file(self.cv_path)
            except Exception as e:
                logger.warning(f"Could not extract CV text for screening resolver: {e}")

    def resolve_field_value(self, label: str, field_type: str = "text", options: Optional[list] = None) -> Any:
        """
        Resolves the appropriate answer for an input field based on its label/name/placeholder.
        Returns:
            - string for text/tel/email inputs
            - bool for checkbox/radio
            - matched option string for select dropdowns
        """
        clean_lbl = label.lower().strip()

        # 1. Exact or Fuzzy Custom QA Match
        for q_key, answer in self.custom_qa.items():
            if q_key.lower() in clean_lbl or clean_lbl in q_key.lower():
                return self._format_answer(answer, field_type, options)

        # 2. Contact Information
        if any(k in clean_lbl for k in ["first name", "given name", "forename"]):
            return self.personal_info.get("first_name", "Mohamed")

        if any(k in clean_lbl for k in ["last name", "family name", "surname"]):
            return self.personal_info.get("last_name", "Hussein")

        if any(k in clean_lbl for k in ["full name", "your name"]) or clean_lbl == "name":
            return self.personal_info.get("full_name", "Mohamed Hussein")

        if any(k in clean_lbl for k in ["email", "e-mail"]):
            return self.personal_info.get("email", "mhmd7syn.contact@gmail.com")

        if any(k in clean_lbl for k in ["phone", "mobile", "telephone", "contact number"]):
            raw_phone = self.personal_info.get("phone", "+201012345678")
            if "code" in clean_lbl:
                return "+20"
            return raw_phone

        if any(k in clean_lbl for k in ["city", "town"]):
            return self.personal_info.get("city", "Cairo")

        if any(k in clean_lbl for k in ["country", "nationality"]):
            return self.personal_info.get("country", "Egypt")

        if any(k in clean_lbl for k in ["linkedin"]):
            return self.personal_info.get("linkedin_url", "https://www.linkedin.com/in/mhmd7syn")

        if any(k in clean_lbl for k in ["github", "git"]):
            return self.personal_info.get("github_url", "https://github.com/Mhmd7syn")

        if any(k in clean_lbl for k in ["portfolio", "website", "personal url"]):
            return self.personal_info.get("portfolio_url") or self.personal_info.get("github_url") or ""

        # 3. Work Authorization & Visa Sponsorship
        if any(k in clean_lbl for k in ["authorized to work", "legally authorized", "work authorization", "right to work"]):
            # Authorized in home country, conditional abroad
            is_home = self.contextual.get("is_home_country", True)
            ans_bool = is_home or not self.contextual.get("requires_visa_sponsorship", False)
            return self._format_boolean(ans_bool, field_type, options)

        if any(k in clean_lbl for k in ["sponsorship", "require visa", "visa support"]):
            req_sponsor = self.contextual.get("requires_visa_sponsorship", False)
            return self._format_boolean(req_sponsor, field_type, options)

        # 4. Relocation & Remote
        if any(k in clean_lbl for k in ["willing to relocate", "relocation", "open to relocate"]):
            willing_reloc = self.contextual.get("willing_to_relocate", True)
            return self._format_boolean(willing_reloc, field_type, options)

        # 5. Driving License & Commute
        if any(k in clean_lbl for k in ["driving license", "driver's license", "valid driver"]):
            has_license = self.smart_screening.get("driving_license", False)
            return self._format_boolean(has_license, field_type, options)

        # 6. Notice Period
        if any(k in clean_lbl for k in ["notice period", "availability", "start date", "how soon"]):
            days = self.smart_screening.get("notice_period_days", 30)
            if field_type == "number" or "days" in clean_lbl:
                return days
            return f"{days} days"

        # 7. Military Status
        if any(k in clean_lbl for k in ["military", "army service"]):
            return self.smart_screening.get("military_status", "Exempted / Completed")

        # 8. Salary Expectations
        if any(k in clean_lbl for k in ["salary", "compensation", "expected rate", "pay expectation"]):
            is_home = self.contextual.get("is_home_country", True)
            if "usd" in clean_lbl or not is_home:
                val = self.smart_screening.get("expected_salary_usd", 1500)
            else:
                val = self.smart_screening.get("expected_salary_egp", 35000)
            return val if field_type == "number" else str(val)

        # 9. Years of Experience with Specific Tech / Overall
        if any(k in clean_lbl for k in ["years of experience", "years of", "how many years"]):
            exp = self._resolve_experience_years(clean_lbl)
            return exp if field_type == "number" else str(exp)

        # 10. Open-Ended / AI Question Fallback
        if field_type == "text" or field_type == "textarea":
            ai_ans = self._resolve_with_ai(label)
            if ai_ans:
                return ai_ans

        # Default fallback
        if field_type == "boolean":
            return True
        return ""

    def _resolve_experience_years(self, label: str) -> int:
        """Determines relevant years of experience based on role or keyword."""
        exp_dict = self.smart_screening.get("years_experience_by_role", {})
        
        # Check against role titles
        for role_name, years in exp_dict.items():
            if role_name.lower() in label:
                return years

        # Check job title relevance
        for role_name, years in exp_dict.items():
            if any(term in self.job_title.lower() for term in role_name.lower().split()):
                if years > 0:
                    return years

        # Default reasonable baseline for junior/mid roles: 2 years hands-on
        if "teaching" in label or "instructor" in label:
            return exp_dict.get("Teaching & STEM Instructor", 3)
        return 2

    def _format_boolean(self, value: bool, field_type: str, options: Optional[list] = None) -> Any:
        if field_type == "boolean":
            return value

        if options and len(options) > 0:
            target = "yes" if value else "no"
            for opt in options:
                if str(opt).lower().strip().startswith(target):
                    return opt
            return options[0] if value else options[-1]

        return "Yes" if value else "No"

    def _format_answer(self, answer: str, field_type: str, options: Optional[list] = None) -> Any:
        if field_type == "boolean":
            return str(answer).lower() in ("yes", "true", "1")
        if options and len(options) > 0:
            ans_str = str(answer).lower()
            for opt in options:
                if str(opt).lower() in ans_str or ans_str in str(opt).lower():
                    return opt
            return options[0]
        return str(answer)

    def _resolve_with_ai(self, question: str) -> Optional[str]:
        """Uses Gemini API to formulate a factual, concise 1-2 sentence response grounded in CV."""
        if not gemini_client or not self.cv_text:
            return None

        prompt = f"""You are answering an application screening question for a job candidate.
Answer CONCISELY (1-2 sentences, maximum 40 words) strictly using the candidate's real CV details.
Do NOT invent credentials or lie.

---
### CANDIDATE RESUME SUMMARY:
{self.cv_text[:3000]}

---
### QUESTION:
{question}

---
Answer strictly in professional English:"""

        try:
            resp = gemini_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    max_output_tokens=80,
                )
            )
            ans = resp.text.strip().strip('"\'')
            return ans
        except Exception as e:
            logger.warning(f"Error answering screening question with AI: {e}")
            return None
