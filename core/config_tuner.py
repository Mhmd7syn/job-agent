import json
import logging
import os
import ctypes
import uuid
from core.llm_parser import client
from pydantic import BaseModel, Field
from core.career_levels import normalize_category_name, CAREER_LEVEL_CATEGORIES

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')
ALERT_PATH = os.path.join(os.path.dirname(__file__), 'pending_alerts.json')

def _get_alert_path():
    return ALERT_PATH

def load_current_config():
    """Safely loads and returns active config.json dictionary."""
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Error loading config.json: {e}")
    return {}

def format_config_for_prompt(config_data):
    """Formats active configuration into a concise summary string for LLM prompts."""
    return f"""
    CURRENT ACTIVE CONFIGURATION:
    - RESUME_KEYWORDS: {json.dumps(config_data.get('RESUME_KEYWORDS', []))}
    - EXCLUDE_KEYWORDS: {json.dumps(config_data.get('EXCLUDE_KEYWORDS', []))}
    - FAVORITE_COMPANIES: {json.dumps(config_data.get('FAVORITE_COMPANIES', []))}
    - EXCLUDED_COMPANIES: {json.dumps(config_data.get('EXCLUDED_COMPANIES', []))}
    - TARGET_LEVELS: {json.dumps(config_data.get('TARGET_LEVELS', []))}
    - TARGET_LOCATIONS: {json.dumps(config_data.get('TARGET_LOCATIONS', []))}
    - SITES: {json.dumps(config_data.get('SITES', []))}
    - USER_BRIEF: {json.dumps(config_data.get('USER_BRIEF', ''))}
    """

def ask_user_permission(title, message):
    """Shows a YES/NO message box. Returns True if YES, False if NO."""
    style = 4 | 32 | 262144
    result = ctypes.windll.user32.MessageBoxW(0, message, title, style)
    return result == 6  # 6 is IDYES

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
    resume_keywords_add: list[str] = Field(default=[], description="New high-priority core skills missing in config that should be added. Extract atomic, single standalone skills only (e.g., 'python', 'sql', 'instructor'). DO NOT extract compounded/combined skills or combinations like 'python mentor', 'python instructor', or 'sql developer' when base skills already exist or can be atomic.")
    resume_keywords_remove: list[str] = Field(default=[], description="Outdated, irrelevant, or conflicting skills currently in config that should be removed.")
    exclude_keywords_add: list[str] = Field(default=[], description="New negative keywords missing in config that should be excluded.")
    exclude_keywords_remove: list[str] = Field(default=[], description="Negative keywords currently in config that should no longer be excluded.")
    favorite_companies_add: list[str] = Field(default=[], description="New companies to add to favorite companies.")
    favorite_companies_remove: list[str] = Field(default=[], description="Companies currently in favorite companies to remove.")
    excluded_companies_add: list[str] = Field(default=[], description="Spam or irrelevant companies to add to excluded companies.")
    excluded_companies_remove: list[str] = Field(default=[], description="Companies currently in excluded companies to remove.")
    target_levels_add: list[str] = Field(default=[], description="Seniority levels missing in config that should be added.")
    target_levels_remove: list[str] = Field(default=[], description="Seniority levels currently in config that should be removed.")
    target_locations_add: list[str] = Field(default=[], description="Target locations missing in config that should be added.")
    target_locations_remove: list[str] = Field(default=[], description="Target locations currently in config that should be removed.")
    disable_sites: list[str] = Field(default=[], description="Scraper sites currently in config that should be disabled/removed.")
    enable_sites: list[str] = Field(default=[], description="Scraper sites missing in config that should be enabled/added.")
    user_brief_update: str = Field(default="", description="Suggested updated profile summary brief if needed.")

def generate_proposals(candidate_updates, current_config=None, source_name="AI Recommendation", reason_context=""):
    """
    SINGLE MASTER FUNCTION for creating, validating, and saving proposals across ALL sources.
    
    Validates every candidate proposal against current_config:
      - ADD: allowed ONLY if item is NOT in current_config[field]
      - REMOVE: allowed ONLY if item IS in current_config[field]
      - UPDATE: allowed ONLY if value IS DIFFERENT from current_config[field]
      
    Saves validated proposals to pending_alerts.json and returns the generated proposal dicts.
    """
    if current_config is None:
        current_config = load_current_config()

    if hasattr(candidate_updates, "model_dump"):
        raw_updates = candidate_updates.model_dump()
    elif hasattr(candidate_updates, "dict"):
        raw_updates = candidate_updates.dict()
    elif isinstance(candidate_updates, dict):
        raw_updates = candidate_updates
    else:
        raw_updates = {}

    proposals = []

    def _get_existing_set(field):
        val = current_config.get(field, [])
        if isinstance(val, list):
            return set(str(x).lower().strip() for x in val)
        return set()

    # Mappings: (updates_key, field_name, p_type, display_prefix, default_reason)
    field_mappings = [
        ("resume_keywords_add", "RESUME_KEYWORDS", "add", "Skill", "Extracted core skill recommendation"),
        ("resume_keywords", "RESUME_KEYWORDS", "add", "Skill", "Extracted core skill recommendation"),
        ("resume_keywords_remove", "RESUME_KEYWORDS", "remove", "Skill", "Suggested skill removal"),
        ("suggested_removals", "RESUME_KEYWORDS", "remove", "Skill", "AI identified as unsuited for candidate profile"),
        ("exclude_keywords_add", "EXCLUDE_KEYWORDS", "add", "Exclude", "New negative keyword"),
        ("exclude_keywords_remove", "EXCLUDE_KEYWORDS", "remove", "Exclude", "Suggested removal from negative keywords"),
        ("favorite_companies_add", "FAVORITE_COMPANIES", "add", "Favorite Company", "Recommended favorite company"),
        ("favorite_companies_remove", "FAVORITE_COMPANIES", "remove", "Favorite Company", "Suggested removal from favorite companies"),
        ("excluded_companies_add", "EXCLUDED_COMPANIES", "add", "Excluded Company", "Irrelevant or spam company"),
        ("excluded_companies_remove", "EXCLUDED_COMPANIES", "remove", "Excluded Company", "Suggested removal from excluded companies"),
        ("target_levels_add", "TARGET_LEVELS", "add", "Experience Level", "Recommended experience level"),
        ("target_levels", "TARGET_LEVELS", "add", "Experience Level", "Inferred experience level"),
        ("target_levels_remove", "TARGET_LEVELS", "remove", "Experience Level", "Suggested removal from experience levels"),
        ("levels_to_remove", "TARGET_LEVELS", "remove", "Experience Level", "Conflicts with experience level"),
        ("target_locations_add", "TARGET_LOCATIONS", "add", "Target Location", "Recommended target location"),
        ("target_locations_remove", "TARGET_LOCATIONS", "remove", "Target Location", "Suggested removal from target locations"),
        ("disable_sites", "SITES", "remove", "Disable Site", "Suggested disabling failing scraper site"),
        ("enable_sites", "SITES", "add", "Enable Site", "Suggested enabling scraper site"),
    ]

    for key, field, p_type, prefix, def_reason in field_mappings:
        items = raw_updates.get(key, [])
        if not isinstance(items, list):
            continue
        existing_set = _get_existing_set(field)
        for item in items:
            if not item:
                continue
            item_raw = str(item).strip()
            if not item_raw:
                continue
            if field == "TARGET_LEVELS":
                item_clean = normalize_category_name(item_raw)
            else:
                item_clean = item_raw.lower()

            item_key = item_clean.lower()

            # Validation against current_config
            if p_type == "add" and item_key in existing_set:
                continue  # Skip if already in config
            if p_type == "remove" and item_key not in existing_set:
                continue  # Skip if not in config to begin with

            reason_str = f"{reason_context} - {def_reason}" if reason_context else def_reason
            proposals.append({
                "id": f"prop_{uuid.uuid4().hex[:8]}",
                "source": source_name,
                "field": field,
                "type": p_type,
                "value": item_clean,
                "display_name": f"{prefix}: {item_clean if len(item_clean) < 30 else item_clean[:27] + '...'}",
                "reason": reason_str
            })
            if p_type == "add":
                existing_set.add(item_key)
            elif p_type == "remove" and item_key in existing_set:
                existing_set.remove(item_key)

    # 2. Location (Country residency addition)
    cv_loc = raw_updates.get("location")
    if cv_loc and isinstance(cv_loc, str) and cv_loc.strip():
        loc_clean = cv_loc.strip()
        existing_locs = _get_existing_set("LOCATION")
        if loc_clean.lower() not in existing_locs:
            reason_str = f"{reason_context} - Residency location extracted" if reason_context else "Residency location extracted"
            proposals.append({
                "id": f"prop_{uuid.uuid4().hex[:8]}",
                "source": source_name,
                "field": "LOCATION",
                "type": "add",
                "value": loc_clean,
                "display_name": f"Location: {loc_clean}",
                "reason": reason_str
            })

    # 3. Target Roles (Dict or string)
    for key, p_type, def_reason in [("target_roles", "add", "Recommended target role"), ("roles_add", "add", "Recommended target role"), ("roles_to_remove", "remove", "Role to remove"), ("roles_remove", "remove", "Role to remove")]:
        items = raw_updates.get(key, [])
        if not isinstance(items, list):
            continue
        existing_roles = current_config.get("ROLES", [])
        existing_titles = set(r.get("title", "").strip().lower() for r in existing_roles if isinstance(r, dict))

        for r in items:
            title = r.get("title", "").strip() if isinstance(r, dict) else str(r).strip()
            if not title:
                continue
            title_lower = title.lower()

            if p_type == "add" and title_lower in existing_titles:
                continue
            if p_type == "remove" and title_lower not in existing_titles:
                continue

            role_obj = r if isinstance(r, dict) else {"title": title, "english_terms": [title]}
            reason_str = f"{reason_context} - {def_reason}" if reason_context else def_reason
            proposals.append({
                "id": f"prop_{uuid.uuid4().hex[:8]}",
                "source": source_name,
                "field": "ROLES",
                "type": p_type,
                "value": role_obj,
                "display_name": f"Role: {title}",
                "reason": reason_str
            })
            if p_type == "add":
                existing_titles.add(title_lower)
            elif p_type == "remove" and title_lower in existing_titles:
                existing_titles.remove(title_lower)

    # 4. User Brief (Update string)
    new_brief = raw_updates.get("user_brief") or raw_updates.get("user_brief_update")
    if new_brief and isinstance(new_brief, str) and new_brief.strip():
        current_brief = str(current_config.get("USER_BRIEF", "")).strip()
        if new_brief.strip() != current_brief:
            reason_str = f"{reason_context} - Profile brief update" if reason_context else "Updated profile summary"
            proposals.append({
                "id": f"prop_{uuid.uuid4().hex[:8]}",
                "source": source_name,
                "field": "USER_BRIEF",
                "type": "add",
                "value": new_brief.strip(),
                "display_name": "Profile Brief: Tailored Summary",
                "reason": reason_str
            })

    if proposals:
        save_proposals(proposals)
    
    return proposals

def analyze_job_and_tune_config(job_dict, action):
    """
    Analyzes job interaction ('liked', 'applied', or 'not_related') and generates validated proposals via generate_proposals.
    """
    if not client:
        logging.warning("No Gemini API key, cannot auto-tune config.")
        return

    current_config = load_current_config()
    config_summary = format_config_for_prompt(current_config)
    job_title = job_dict.get('title', 'Job')

    prompt = f"""
    You are an expert career assistant maintaining a job matching configuration.
    The user just interacted with a job posting.
    
    Job Title: {job_dict.get('title', '')}
    Company: {job_dict.get('company', '')}
    Description: {job_dict.get('description', '')[:2000]}
    
    The user marked this job as: '{action.upper()}'
    
    {config_summary}
    
    If the action is LIKED or APPLIED:
    - Extract core technical skills from this job that are missing from `RESUME_KEYWORDS` and add to `resume_keywords_add`. IMPORTANT: Extract atomic/single skills only (e.g., 'python', 'sql', 'instructor'). DO NOT suggest compounded skills or combinations (such as 'python mentor', 'python instructor', or 'sql developer') when individual skills like 'python' or 'instructor' are already present or can be represented standalone. No combinations.
    - If any keyword in `EXCLUDE_KEYWORDS` incorrectly filtered or conflicted with this liked job, suggest removing it in `exclude_keywords_remove`.
    - If the company is relevant and missing from `FAVORITE_COMPANIES`, add to `favorite_companies_add`.
    
    If the action is NOT_RELATED:
    - Identify WHY it's not related (e.g. irrelevant domain like Sales, HR, Finance, or unwanted tech stack).
    - Extract negative skill/domain keywords missing from `EXCLUDE_KEYWORDS` and add to `exclude_keywords_add`.
    - DO NOT suggest seniority levels (such as 'senior', 'lead', 'manager', 'director', 'mid-level', 'intern', 'junior') in `exclude_keywords_add`. Seniority is handled strictly by the career level settings.
    - If an existing skill in `RESUME_KEYWORDS` was the reason this irrelevant job was picked, suggest removing it in `resume_keywords_remove`.
    """

    try:
        from google.genai import types
        import time

        response = None
        models_to_try = ['gemini-2.5-flash', 'gemini-flash-lite-latest']
        last_error = None

        for model_name in models_to_try:
            for attempt in range(3):
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=ConfigUpdateSchema,
                        )
                    )
                    break
                except Exception as err:
                    last_error = err
                    if any(e_code in str(err) for e_code in ["429", "503", "10051", "10053", "10054", "10060", "getaddrinfo"]):
                        wait_t = 5 * (attempt + 1)
                        logging.warning(f"⚠️ Auto-tune API glitch ({err.__class__.__name__}). Retrying in {wait_t}s ({attempt+1}/3)...")
                        time.sleep(wait_t)
                    else:
                        break
            if response:
                break

        if not response:
            raise last_error or RuntimeError("Failed to generate response after retries")

        updates = json.loads(response.text)
        proposals = generate_proposals(
            candidate_updates=updates,
            current_config=current_config,
            source_name=f"{action.title()} Job",
            reason_context=f"From job '{job_title}'"
        )

        if proposals:
            logging.info(f"Queued {len(proposals)} proposal(s) based on action '{action}' for: {job_title}")
        
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

    if field in ["RESULTS_PER_TERM", "HOURS_OLD", "MAX_JOBS_TO_SEND"]:
        try:
            config_data[field] = type(config_data.get(field, 0))(val)
            return True
        except Exception:
            return False

    if field == "ROLES":
        roles = config_data.get("ROLES", [])
        if not isinstance(roles, list):
            roles = []
        if p_type == "add":
            target_title = val.get("title", "").strip().lower() if isinstance(val, dict) else str(val).strip().lower()
            existing_titles = [r.get("title", "").strip().lower() for r in roles if isinstance(r, dict)]
            if target_title and target_title not in existing_titles:
                role_obj = val if isinstance(val, dict) else {"title": str(val).strip(), "english_terms": [str(val).strip()]}
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

    if field == "TARGET_LEVELS":
        val_cat = normalize_category_name(val)
        existing_set = set([str(x).lower().strip() for x in current_list])
        if p_type == "add":
            if val_cat and val_cat.lower() not in existing_set:
                current_list.append(val_cat)
                config_data[field] = current_list
                config_data["LEVEL_EXCLUDE"] = [c for c in CAREER_LEVEL_CATEGORIES if c.lower() not in set(x.lower() for x in current_list)]
                return True
        elif p_type == "remove":
            new_list = [x for x in current_list if str(x).lower().strip() != val_cat.lower()]
            if len(new_list) != len(current_list):
                config_data[field] = new_list
                config_data["LEVEL_EXCLUDE"] = [c for c in CAREER_LEVEL_CATEGORIES if c.lower() not in set(x.lower() for x in new_list)]
                return True
        return False

    val_str = str(val).lower().strip()

    if field == "EXCLUDE_KEYWORDS":
        from core.career_levels import expand_levels, CAREER_LEVEL_CATEGORIES
        all_career_level_synonyms = expand_levels(CAREER_LEVEL_CATEGORIES)
        all_career_level_synonyms.add("phd")
        if val_str in all_career_level_synonyms:
            return False

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
            if "field" in updates and "type" in updates:
                modified = apply_single_proposal(updates, config_data)
            else:
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
            try:
                import core.config as app_config
                app_config.reload_config()
            except Exception as e:
                logging.warning(f"Could not reload config in-memory: {e}")

    except Exception as e:
        logging.error(f"Error applying updates to config.json: {e}")

def analyze_run_and_tune_config(logs_text, eval_text):
    """
    Analyzes run logs & AI evaluation and generates validated proposals via generate_proposals.
    """
    if not client:
        logging.warning("No Gemini API key, cannot auto-tune config from run logs.")
        return

    current_config = load_current_config()
    config_summary = format_config_for_prompt(current_config)

    prompt = f"""
    You are an expert AI system administrator maintaining a job scraping agent.
    A scraping run just finished. Read the logs, AI evaluation of the run, and the current configuration.
    
    AI Evaluation Brief:
    {eval_text}
    
    Agent Logs (Tail):
    {logs_text[-3000:]}
    
    {config_summary}
    
    Recommend appropriate configuration adjustments:
    - Missing negative domain/skill keywords -> `exclude_keywords_add` (Do NOT include seniority levels like senior, lead, manager; those are managed by career level settings)
    - Conflicting negative keywords -> `exclude_keywords_remove`
    - Spam/irrelevant companies -> `excluded_companies_add`
    - Relevant skills -> `resume_keywords_add` (Extract atomic/single standalone skills only. DO NOT suggest compounded combinations like 'python mentor' or 'python instructor')
    - Irrelevant/outdated skills -> `resume_keywords_remove`
    - Disabling consistently failing scrapers -> `disable_sites`
    """

    try:
        from google.genai import types
        import time

        response = None
        models_to_try = ['gemini-2.5-flash', 'gemini-flash-lite-latest']
        last_error = None

        for model_name in models_to_try:
            for attempt in range(3):
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=ConfigUpdateSchema,
                        )
                    )
                    break
                except Exception as err:
                    last_error = err
                    if any(e_code in str(err) for e_code in ["429", "503", "10051", "10053", "10054", "10060", "getaddrinfo"]):
                        wait_t = 5 * (attempt + 1)
                        logging.warning(f"⚠️ Auto-tune run log API glitch ({err.__class__.__name__}). Retrying in {wait_t}s ({attempt+1}/3)...")
                        time.sleep(wait_t)
                    else:
                        break
            if response:
                break

        if not response:
            raise last_error or RuntimeError("Failed to generate response after retries")

        updates = json.loads(response.text)
        proposals = generate_proposals(
            candidate_updates=updates,
            current_config=current_config,
            source_name="Run Evaluation",
            reason_context="From run evaluation"
        )

        if proposals:
            logging.info(f"Queued {len(proposals)} new proposal(s) from AI run evaluation.")
            
    except Exception as e:
        logging.error(f"Failed to auto-tune config from run logs: {e}")
