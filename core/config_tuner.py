import json
import logging
import os
import re
import ctypes
from core.llm_parser import client
from pydantic import BaseModel, Field

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')
ALERT_PATH = os.path.join(os.path.dirname(__file__), 'pending_alerts.json')

def _get_alert_path():
    return ALERT_PATH

def ask_user_permission(title, message):
    """Shows a YES/NO message box. Returns True if YES, False if NO."""
    # MB_YESNO = 4, MB_ICONQUESTION = 32, MB_TOPMOST = 262144
    style = 4 | 32 | 262144
    result = ctypes.windll.user32.MessageBoxW(0, message, title, style)
    return result == 6  # 6 is IDYES

import uuid

def save_proposals(new_proposals):
    """
    Saves a list of proposal dicts into pending_alerts.json.
    Each proposal has: {id, source, field, type ('add'|'remove'), value, display_name, reason}
    """
    alert_path = _get_alert_path()
    existing_proposals = []
    if os.path.exists(alert_path):
        try:
            with open(alert_path, 'r', encoding='utf-8') as f:
                content = json.load(f)
                if isinstance(content, list):
                    existing_proposals = content
        except Exception:
            pass

    # Deduplicate by field + value + type
    existing_keys = set()
    for p in existing_proposals:
        val_key = json.dumps(p.get('value'), sort_keys=True) if isinstance(p.get('value'), (dict, list)) else str(p.get('value')).lower()
        existing_keys.add(f"{p.get('field')}:{p.get('type')}:{val_key}")

    added_count = 0
    for prop in new_proposals:
        if 'id' not in prop:
            prop['id'] = f"prop_{uuid.uuid4().hex[:8]}"
        val_key = json.dumps(prop.get('value'), sort_keys=True) if isinstance(prop.get('value'), (dict, list)) else str(prop.get('value')).lower()
        dedup_key = f"{prop.get('field')}:{prop.get('type')}:{val_key}"
        if dedup_key not in existing_keys:
            existing_proposals.append(prop)
            existing_keys.add(dedup_key)
            added_count += 1

    with open(alert_path, 'w', encoding='utf-8') as f:
        json.dump(existing_proposals, f, indent=2, ensure_ascii=False)

    return added_count

def save_pending_alert(title, message, updates):
    """Legacy helper maintained for backward compatibility. Converts updates to proposals."""
    proposals = []
    for category, items in updates.items():
        if not items:
            continue
        field_name = category.upper()
        if category in ['resume_keywords', 'exclude_keywords', 'favorite_companies', 'excluded_companies']:
            for item in items:
                proposals.append({
                    "id": f"prop_{uuid.uuid4().hex[:8]}",
                    "source": title,
                    "field": field_name,
                    "type": "add",
                    "value": str(item).lower().strip(),
                    "display_name": f"{field_name.replace('_', ' ').title()}: {item}",
                    "reason": message.split('\n')[0]
                })
    if proposals:
        save_proposals(proposals)


class ConfigUpdateSchema(BaseModel):
    resume_keywords_add: list[str] = Field(default=[], description="New high-priority core skills to add.")
    resume_keywords_remove: list[str] = Field(default=[], description="Outdated or irrelevant skills to remove.")
    exclude_keywords_add: list[str] = Field(default=[], description="New negative keywords to exclude.")
    exclude_keywords_remove: list[str] = Field(default=[], description="Negative keywords that should no longer be excluded.")
    favorite_companies_add: list[str] = Field(default=[], description="New companies to favorite.")
    excluded_companies_add: list[str] = Field(default=[], description="New companies to exclude.")
    disable_sites: list[str] = Field(default=[], description="If a scraper site is failing, suggest disabling it.")

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
    Description: {job_dict.get('description', '')[:2000]}
    
    The user marked this job as: '{action.upper()}'
    
    If the action is LIKED or APPLIED:
    - Extract up to 3 core technical skills from this job and add to `resume_keywords_add`.
    - If the company is relevant, add to `favorite_companies_add`.
    
    If the action is NOT_RELATED:
    - Identify WHY it's not related (e.g. Requires Senior/Manager, or irrelevant domain like Finance/Sales).
    - Extract up to 3 negative keywords to add to `exclude_keywords_add`.
    - Optionally suggest removing conflicting keywords from `exclude_keywords_remove` or `resume_keywords_remove`.
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
        job_title = job_dict.get('title', 'Job')

        proposals = []
        for item in updates.get('resume_keywords_add', []):
            proposals.append({"id": f"prop_{uuid.uuid4().hex[:8]}", "source": f"{action.title()} Job", "field": "RESUME_KEYWORDS", "type": "add", "value": item.lower().strip(), "display_name": f"Skill: {item}", "reason": f"From liked job '{job_title}'"})
        for item in updates.get('resume_keywords_remove', []):
            proposals.append({"id": f"prop_{uuid.uuid4().hex[:8]}", "source": f"{action.title()} Job", "field": "RESUME_KEYWORDS", "type": "remove", "value": item.lower().strip(), "display_name": f"Skill: {item}", "reason": f"Conflict identified in '{job_title}'"})
        for item in updates.get('exclude_keywords_add', []):
            proposals.append({"id": f"prop_{uuid.uuid4().hex[:8]}", "source": f"{action.title()} Job", "field": "EXCLUDE_KEYWORDS", "type": "add", "value": item.lower().strip(), "display_name": f"Exclude: {item}", "reason": f"Irrelevant term from '{job_title}'"})
        for item in updates.get('exclude_keywords_remove', []):
            proposals.append({"id": f"prop_{uuid.uuid4().hex[:8]}", "source": f"{action.title()} Job", "field": "EXCLUDE_KEYWORDS", "type": "remove", "value": item.lower().strip(), "display_name": f"Exclude: {item}", "reason": f"Valid term found in '{job_title}'"})
        for item in updates.get('favorite_companies_add', []):
            proposals.append({"id": f"prop_{uuid.uuid4().hex[:8]}", "source": f"{action.title()} Job", "field": "FAVORITE_COMPANIES", "type": "add", "value": item.lower().strip(), "display_name": f"Favorite Company: {item}", "reason": f"From liked job '{job_title}'"})
        for item in updates.get('excluded_companies_add', []):
            proposals.append({"id": f"prop_{uuid.uuid4().hex[:8]}", "source": f"{action.title()} Job", "field": "EXCLUDED_COMPANIES", "type": "add", "value": item.lower().strip(), "display_name": f"Excluded Company: {item}", "reason": f"From non-matching job '{job_title}'"})

        if proposals:
            save_proposals(proposals)
            logging.info(f"Queued {len(proposals)} proposals based on action '{action}' for: {job_title}")
        
    except Exception as e:
        logging.error(f"Failed to auto-tune config: {e}")

def apply_single_proposal(proposal, config_data):
    """
    Modifies config_data dictionary in place according to a proposal object.
    Supports 'add' and 'remove' across all config fields.
    """
    field = proposal.get("field")
    p_type = proposal.get("type", "add")
    val = proposal.get("value")

    if not field or val is None:
        return False

    if field == "USER_BRIEF":
        if p_type == "add":
            config_data["USER_BRIEF"] = str(val)
            return True
        return False

    if field == "ROLES":
        roles = config_data.get("ROLES", [])
        if not isinstance(roles, list):
            roles = []
        if p_type == "add":
            target_title = val.get("title", "").strip().lower() if isinstance(val, dict) else str(val).strip().lower()
            existing_titles = [r.get("title", "").strip().lower() for r in roles if isinstance(r, dict)]
            if target_title and target_title not in existing_titles:
                role_obj = val if isinstance(val, dict) else {"title": str(val).strip(), "english_terms": [str(val).strip()], "arabic_terms": []}
                roles.append(role_obj)
                config_data["ROLES"] = roles
                return True
        elif p_type == "remove":
            target_title = val.get("title", "").strip().lower() if isinstance(val, dict) else str(val).strip().lower()
            new_roles = [r for r in roles if isinstance(r, dict) and r.get("title", "").strip().lower() != target_title]
            if len(new_roles) != len(roles):
                config_data["ROLES"] = new_roles
                return True
        return False

    # List fields (RESUME_KEYWORDS, EXCLUDE_KEYWORDS, TARGET_LEVELS, LOCATION, TARGET_LOCATIONS, FAVORITE_COMPANIES, EXCLUDED_COMPANIES, GLOBAL_REMOTE_KEYWORDS, RESTRICTED_REMOTE_KEYWORDS, SITES, etc.)
    current_list = config_data.get(field, [])
    if not isinstance(current_list, list):
        current_list = []

    val_str = str(val).lower().strip()

    if p_type == "add":
        existing_set = set([str(x).lower().strip() for x in current_list])
        if val_str and val_str not in existing_set:
            current_list.append(val_str)
            config_data[field] = current_list
            return True
    elif p_type == "remove":
        new_list = [x for x in current_list if str(x).lower().strip() != val_str]
        if len(new_list) != len(current_list):
            config_data[field] = new_list
            return True

    return False

def apply_config_updates(updates):
    """
    Applies updates to config.json. Accepts either legacy dict of lists or a list of proposal dicts.
    """
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            config_data = json.load(f)

        modified = False

        if isinstance(updates, list):
            for prop in updates:
                if apply_single_proposal(prop, config_data):
                    modified = True
        elif isinstance(updates, dict):
            # Check if it's a single proposal dict
            if "field" in updates and "type" in updates:
                modified = apply_single_proposal(updates, config_data)
            else:
                # Legacy dict mapping
                for cat, items in updates.items():
                    field_name = cat.upper()
                    if isinstance(items, list):
                        for item in items:
                            prop = {"field": field_name, "type": "add", "value": item}
                            if apply_single_proposal(prop, config_data):
                                modified = True

        if modified:
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)
            logging.info("Applied config updates to config.json")

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
    If you notice the agent found highly relevant jobs and the user profile matches new technical skills mentioned in the evaluation, add them to `resume_keywords`.
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
        list_keys = ['resume_keywords', 'exclude_keywords', 'favorite_companies', 'excluded_companies', 'disable_sites']
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
