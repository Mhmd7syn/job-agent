import json
import logging
import os
import re
import ctypes
from core.llm_parser import client
from pydantic import BaseModel, Field

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')

def ask_user_permission(title, message):
    """Shows a YES/NO message box. Returns True if YES, False if NO."""
    # MB_YESNO = 4, MB_ICONQUESTION = 32, MB_TOPMOST = 262144
    style = 4 | 32 | 262144
    result = ctypes.windll.user32.MessageBoxW(0, message, title, style)
    return result == 6  # 6 is IDYES

def save_pending_alert(title, message, updates):
    alert_path = os.path.join('data', 'pending_alerts.json')
    alerts = []
    if os.path.exists(alert_path):
        try:
            with open(alert_path, 'r', encoding='utf-8') as f:
                alerts = json.load(f)
        except:
            pass
    # Overwrite previous alerts of the same type to prevent popup spam
    alerts = [a for a in alerts if a.get('title') != title]
    alerts.append({'title': title, 'message': message, 'updates': updates})
    with open(alert_path, 'w', encoding='utf-8') as f:
        json.dump(alerts, f, indent=2)

def process_pending_alerts():
    alert_path = os.path.join('data', 'pending_alerts.json')
    if not os.path.exists(alert_path):
        return
    try:
        with open(alert_path, 'r', encoding='utf-8') as f:
            alerts = json.load(f)
    except:
        alerts = []
    
    if not alerts:
        return

    for alert in alerts:
        if ask_user_permission(alert.get('title', 'Alert'), alert.get('message', '')):
            if alert.get('updates'):
                apply_config_updates(alert['updates'])
                logging.info(f"User approved deferred alert updates: {alert.get('title')}")
        else:
            logging.info(f"User rejected deferred alert updates: {alert.get('title')}")
            
    try:
        os.remove(alert_path)
    except:
        pass

class ConfigUpdateSchema(BaseModel):
    resume_keywords: list[str] = Field(default=[], description="New high-priority core skills to add (e.g. programming languages, frameworks).")
    nice_to_have_skills: list[str] = Field(default=[], description="New secondary skills or concepts to add.")
    exclude_keywords: list[str] = Field(default=[], description="New negative keywords to exclude (e.g. senior, manager, irrelevant fields).")
    favorite_companies: list[str] = Field(default=[], description="New companies to favorite.")
    excluded_companies: list[str] = Field(default=[], description="New companies to exclude.")
    feature_error_message: str = Field(default="", description="If a specific feature or scraper is failing, describe the issue and how to solve it.")
    disable_sites: list[str] = Field(default=[], description="If a scraper site is consistently failing or blocking, suggest disabling it by adding to this list.")

def analyze_job_and_tune_config(job_dict, action):
    """
    Action: 'liked', 'applied', or 'not_related'
    """
    if not client:
        logging.warning("No Gemini API key, cannot auto-tune config.")
        return

    prompt = f"""
    You are an expert career assistant. The user just interacted with a job posting.
    
    Job Title: {job_dict.get('title', '')}
    Company: {job_dict.get('company', '')}
    Description: {job_dict.get('description', '')[:2000]}  # Truncated for token limit
    
    The user marked this job as: '{action.upper()}'
    
    If the action is LIKED or APPLIED:
    - Extract up to 3 core technical skills from this job that the user might have and add to `resume_keywords` (keep them lowercase and brief).
    - Extract up to 3 secondary skills/tools and add to `nice_to_have_skills` (lowercase).
    - If the company seems highly relevant, add its name to `favorite_companies` (lowercase).
    
    If the action is NOT_RELATED:
    - Identify WHY it's not related (e.g., requires 'Senior', 'Manager', or is in an irrelevant field like 'Finance', 'Sales').
    - Extract up to 3 negative keywords that would help filter out similar bad jobs in the future, and add to `exclude_keywords` (lowercase).
    - Optionally add the company to `excluded_companies` if it seems like a spam or completely irrelevant company.
    
    Return ONLY new keywords that should be ADDED. Do not return keywords that are extremely generic like "and", "or", "experience", "job".
    """

    try:
        from google.genai import types
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ConfigUpdateSchema,
            )
        )
        
        updates = json.loads(response.text)
        apply_config_updates(updates)
        logging.info(f"Auto-tuned config based on action {action} for job: {job_dict.get('title')}")
        
    except Exception as e:
        logging.error(f"Failed to auto-tune config: {e}")

def apply_config_updates(updates):
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            config_data = json.load(f)

        def append_to_list(list_name, new_items):
            if not new_items:
                return
            
            current_list = config_data.get(list_name, [])
            existing_text = set([str(x).lower().strip() for x in current_list])
            
            for item in new_items:
                item_clean = str(item).lower().strip()
                if item_clean and item_clean not in existing_text:
                    current_list.append(item_clean)
                    existing_text.add(item_clean)
            
            config_data[list_name] = current_list

        append_to_list('RESUME_KEYWORDS', updates.get('resume_keywords', []))
        append_to_list('NICE_TO_HAVE_SKILLS', updates.get('nice_to_have_skills', []))
        append_to_list('EXCLUDE_KEYWORDS', updates.get('exclude_keywords', []))
        append_to_list('FAVORITE_COMPANIES', updates.get('favorite_companies', []))
        append_to_list('EXCLUDED_COMPANIES', updates.get('excluded_companies', []))
        
        disable_sites = updates.get('disable_sites', [])
        if disable_sites:
            current_sites = config_data.get('SITES', [])
            sites_to_remove = set([str(x).lower().strip() for x in disable_sites])
            config_data['SITES'] = [s for s in current_sites if str(s).lower().strip() not in sites_to_remove]

        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)

    except Exception as e:
        logging.error(f"Error applying updates to config.json: {e}")

def analyze_run_and_tune_config(logs_text, eval_text):
    """
    Analyzes the run logs and AI evaluation to extract new keywords, blocked sites, or spam companies.
    """
    if not client:
        logging.warning("No Gemini API key, cannot auto-tune config from run logs.")
        return

    prompt = f"""
    You are an expert AI system administrator maintaining a job scraping agent.
    A scraping run just finished. Read the logs and the AI's evaluation of the run.
    
    AI Evaluation Brief:
    {eval_text}
    
    Agent Logs (Tail):
    {logs_text[-3000:]}  # Truncated to avoid token limit issues
    
    If you notice the agent scraped many irrelevant jobs because of a missing negative keyword (e.g. 'Senior', 'Manager', 'Finance'), add them to `exclude_keywords`.
    If you notice the agent scraped many spam jobs from a specific company, add the company to `excluded_companies`.
    If you notice the agent found highly relevant jobs and the user profile matches new technical skills mentioned in the evaluation, add them to `resume_keywords` or `nice_to_have_skills`.
    If you notice any errors in the logs indicating that a specific scraper (e.g., Glassdoor, LinkedIn) is consistently failing, describe the issue in `feature_error_message` and strongly suggest that the user updates their account, keys, or cookies as the recommended step. Only if the site is completely unrecoverable should you suggest disabling it by adding the site name to `disable_sites`.
    
    Return ONLY new keywords/companies that should be ADDED, or sites to disable. Keep them lowercase and brief. Do not return generic words.
    """

    try:
        from google.genai import types
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ConfigUpdateSchema,
            )
        )
        
        updates = json.loads(response.text)
        
        # Check if there are any config updates
        list_keys = ['resume_keywords', 'nice_to_have_skills', 'exclude_keywords', 'favorite_companies', 'excluded_companies', 'disable_sites']
        has_list_updates = any(bool(updates.get(k)) for k in list_keys)
        
        feature_error = updates.get('feature_error_message', '')
        
        if feature_error:
            msg = f"Alert: A feature/part of the program is not working correctly:\n\n{feature_error}\n"
            if updates.get('disable_sites'):
                msg += f"\nSuggested fix: Disable the following sites: {', '.join(updates.get('disable_sites'))}\n\nDo you want to apply this auto-edit?"
                save_pending_alert("System Error Alert", msg, {'disable_sites': updates.get('disable_sites')})
            else:
                save_pending_alert("System Error Alert", msg, {})
        
        if has_list_updates:
            msg = "Based on the recent run, AI suggests the following config updates in preferences:\n"
            for k in list_keys:
                if k != 'disable_sites' and updates.get(k):
                    msg += f"\n- {k}: {', '.join(updates.get(k))}"
            
            # If there are updates other than disable_sites
            if any(bool(updates.get(k)) for k in list_keys if k != 'disable_sites'):
                msg += "\n\nDo you want to apply these auto-edits?"
                updates_to_save = updates.copy()
                updates_to_save['disable_sites'] = []
                save_pending_alert("AI Auto-Edit Preferences", msg, updates_to_save)
            
    except Exception as e:
        logging.error(f"Failed to auto-tune config from run logs: {e}")
