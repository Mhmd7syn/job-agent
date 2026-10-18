import sqlite3
import os
import json
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple, Set

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output", "jobs_state.db")

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            title TEXT,
            company TEXT,
            location TEXT,
            job_url TEXT,
            job_type TEXT,
            date_posted TEXT,
            site TEXT,
            relevance_score REAL,
            description TEXT,
            status TEXT DEFAULT 'pending',
            timestamp TEXT
        )
    """)
    
    # Try adding auto-apply columns if they don't exist
    for col, col_type in [
        ('is_applied', 'INTEGER DEFAULT 0'),
        ('apply_type', "TEXT DEFAULT 'manual'"),
        ('apply_payload', "TEXT DEFAULT '{}'"),
        ('applied_at', 'TEXT'),
        ('apply_channel', 'TEXT'),
        ('apply_status', "TEXT DEFAULT 'unapplied'"),
        ('pending_questions', "TEXT DEFAULT '[]'"),
        ('apply_url', 'TEXT'),
        ('is_easy_apply', 'INTEGER DEFAULT 0'),
        ('workplace_setup', "TEXT DEFAULT 'On-site'")
    ]:
        try:
            cursor.execute(f'ALTER TABLE jobs ADD COLUMN {col} {col_type}')
        except sqlite3.OperationalError:
            pass

    # Migrate any old 'applied' status
    cursor.execute("UPDATE jobs SET is_applied = 1, status = 'liked' WHERE status = 'applied'")
    
    # Add index on job_url and apply_url for high-speed deduplication checks
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_job_url ON jobs(job_url)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_apply_url ON jobs(apply_url)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_apply_type ON jobs(apply_type)")
    
    conn.commit()
    conn.close()

def backfill_job_classifications():
    """Classifies all existing jobs in the database to populate apply_type and apply_payload, and cleans company names."""
    import re
    import json
    from core.apply_classifier import classify_and_extract
    
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs")
    rows = cursor.fetchall()
    
    updated_count = 0
    for r in rows:
        job = dict(r)
        orig_company = job.get('company') or ''
        clean_company = re.sub(r'[\s·•|]*\d+(\.\d+)?\s*(★|\*|⭐)?\s*$', '', orig_company.strip()).strip()
        if clean_company and clean_company != orig_company:
            job['company'] = clean_company
            cursor.execute("UPDATE jobs SET company = ? WHERE job_id = ?", (clean_company, job['job_id']))

        # Re-classify
        classified = classify_and_extract(job)
        apply_type = classified.get("apply_type", "manual")
        apply_payload = json.dumps(classified.get("apply_payload", {}), ensure_ascii=False)
        
        cursor.execute("""
            UPDATE jobs 
            SET apply_type = ?, apply_payload = ?
            WHERE job_id = ?
        """, (apply_type, apply_payload, job['job_id']))
        updated_count += 1
        
    conn.commit()
    conn.close()
    return updated_count

def save_job(job_dict):
    from core.apply_classifier import classify_and_extract

    conn = sqlite3.connect(DB_PATH, timeout=15)
    cursor = conn.cursor()
    
    now = datetime.now().isoformat()
    status = job_dict.get('status', 'pending')
    is_applied = job_dict.get('is_applied', 0)
    
    if not job_dict.get('apply_type'):
        classified = classify_and_extract(job_dict)
        apply_type = classified.get("apply_type", "manual")
        apply_payload = json.dumps(classified.get("apply_payload", {}), ensure_ascii=False)
    else:
        apply_type = job_dict['apply_type']
        raw_payload = job_dict.get('apply_payload', {})
        apply_payload = json.dumps(raw_payload, ensure_ascii=False) if isinstance(raw_payload, dict) else str(raw_payload)

    apply_url = job_dict.get('apply_url', '')
    is_easy_apply = 1 if job_dict.get('is_easy_apply') else 0

    # Insert or ignore (if it already exists, we might not want to overwrite its status)
    cursor.execute("""
        INSERT OR IGNORE INTO jobs 
        (job_id, title, company, location, job_url, job_type, date_posted, site, relevance_score, description, status, timestamp, is_applied, apply_type, apply_payload, apply_url, is_easy_apply, workplace_setup)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        job_dict.get('job_id', ''),
        job_dict.get('title', ''),
        job_dict.get('company', ''),
        job_dict.get('location', ''),
        job_dict.get('job_url', ''),
        job_dict.get('job_type', ''),
        job_dict.get('date_posted', ''),
        job_dict.get('site', ''),
        job_dict.get('relevance_score', 0),
        job_dict.get('description', ''),
        status,
        now,
        is_applied,
        apply_type,
        apply_payload,
        apply_url,
        is_easy_apply,
        job_dict.get('workplace_setup', 'On-site')
    ))
    
    # If we want to update the relevance score for an existing job that is still pending
    cursor.execute("""
        UPDATE jobs 
        SET relevance_score = ?, apply_type = ?, apply_payload = ?,
            apply_url = COALESCE(NULLIF(?, ''), apply_url),
            is_easy_apply = COALESCE(?, is_easy_apply),
            workplace_setup = COALESCE(NULLIF(?, ''), workplace_setup)
        WHERE job_id = ? AND status = 'pending'
    """, (job_dict.get('relevance_score', 0), apply_type, apply_payload, apply_url, is_easy_apply, job_dict.get('workplace_setup', ''), job_dict.get('job_id', '')))

    conn.commit()
    conn.close()

def save_dropped_jobs(job_records):
    """
    Saves minimal records (job_id, job_url, date_posted, timestamp) with status='filtered'
    and empty description for jobs dropped during preliminary scoring stages.
    Prevents re-scraping via is_job_seen() while allowing normal cleanup via retention days.
    """
    if not job_records:
        return 0
    conn = sqlite3.connect(DB_PATH, timeout=15)
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    
    rows_to_insert = []
    for j in job_records:
        job_url = j.get('job_url', '')
        if not job_url:
            continue
        job_id = j.get('job_id') or j.get('id') or job_url
        date_posted = str(j.get('date_posted', '')) if j.get('date_posted') is not None else ''
        title = j.get('title', '')
        company = j.get('company', '')
        site = j.get('site', '')
        rows_to_insert.append((
            job_id,
            title,
            company,
            '',
            job_url,
            '',
            date_posted,
            site,
            0,
            '',
            'filtered',
            now
        ))

    cursor.executemany("""
        INSERT OR IGNORE INTO jobs 
        (job_id, title, company, location, job_url, job_type, date_posted, site, relevance_score, description, status, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows_to_insert)
    inserted_count = cursor.rowcount
    conn.commit()
    conn.close()
    return inserted_count

def save_or_update_job(job_dict, force_pending=True):
    """
    Saves a job or updates it if it already exists (by job_id or job_url).
    Returns a tuple (saved_job_dict, is_new).
    """
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    job_id = job_dict.get('job_id', '')
    job_url = job_dict.get('job_url', '')

    # Check if job exists by job_id or job_url
    cursor.execute("SELECT * FROM jobs WHERE job_id = ? OR (job_url != '' AND job_url = ?) LIMIT 1", (job_id, job_url))
    existing = cursor.fetchone()
    
    if existing:
        existing_dict = dict(existing)
        target_id = existing_dict['job_id']
        existing_status = existing_dict.get('status', 'pending')
        if job_dict.get('status'):
            status = job_dict['status']
        elif existing_status in ('not_related', 'applied', 'liked'):
            # Preserve user explicit feedback or applied status from being reset to pending
            status = existing_status
        elif force_pending:
            status = 'pending'
        else:
            status = existing_status

        # Preserve is_applied: once applied, do not revert to 0 unless explicitly requested
        existing_applied = 1 if existing_dict.get('is_applied') in (1, '1', True) else 0
        if existing_applied == 1 and not job_dict.get('force_unapplied'):
            is_applied = 1
        else:
            is_applied = job_dict.get('is_applied', existing_applied)
        
        # Determine classification
        merged_dict = {**existing_dict, **job_dict}
        if not job_dict.get('apply_type'):
            from core.apply_classifier import classify_and_extract
            classified = classify_and_extract(merged_dict)
            apply_type = classified.get("apply_type", existing_dict.get('apply_type', 'manual'))
            apply_payload = json.dumps(classified.get("apply_payload", {}), ensure_ascii=False)
        else:
            apply_type = job_dict['apply_type']
            raw_payload = job_dict.get('apply_payload', existing_dict.get('apply_payload', '{}'))
            apply_payload = json.dumps(raw_payload, ensure_ascii=False) if isinstance(raw_payload, dict) else str(raw_payload)

        apply_url = job_dict.get('apply_url') or existing_dict.get('apply_url', '')
        is_easy_apply = job_dict.get('is_easy_apply') if job_dict.get('is_easy_apply') is not None else existing_dict.get('is_easy_apply', 0)
        is_easy_apply_val = 1 if is_easy_apply else 0

        cursor.execute("""
            UPDATE jobs
            SET title = ?, company = ?, location = ?, job_url = ?, job_type = ?, 
                date_posted = ?, site = ?, relevance_score = ?, description = ?, status = ?, timestamp = ?, is_applied = ?,
                apply_type = ?, apply_payload = ?, apply_url = ?, is_easy_apply = ?, workplace_setup = ?
            WHERE job_id = ?
        """, (
            job_dict.get('title') or existing_dict.get('title', ''),
            job_dict.get('company') or existing_dict.get('company', ''),
            job_dict.get('location') or existing_dict.get('location', ''),
            job_url or existing_dict.get('job_url', ''),
            job_dict.get('job_type') or existing_dict.get('job_type', ''),
            str(job_dict.get('date_posted') or existing_dict.get('date_posted', '')),
            job_dict.get('site') or existing_dict.get('site', ''),
            job_dict.get('relevance_score', existing_dict.get('relevance_score', 0)),
            job_dict.get('description') or existing_dict.get('description', ''),
            status,
            now,
            is_applied,
            apply_type,
            apply_payload,
            apply_url,
            is_easy_apply_val,
            job_dict.get('workplace_setup') or existing_dict.get('workplace_setup', 'On-site'),
            target_id
        ))
        conn.commit()
        cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (target_id,))
        updated = dict(cursor.fetchone())
        conn.close()
        return updated, False
    else:
        status = job_dict.get('status', 'pending')
        is_applied = job_dict.get('is_applied', 0)
        apply_url = job_dict.get('apply_url', '')
        is_easy_apply_val = 1 if job_dict.get('is_easy_apply') else 0
        
        if not job_dict.get('apply_type'):
            from core.apply_classifier import classify_and_extract
            classified = classify_and_extract(job_dict)
            apply_type = classified.get("apply_type", "manual")
            apply_payload = json.dumps(classified.get("apply_payload", {}), ensure_ascii=False)
        else:
            apply_type = job_dict['apply_type']
            raw_payload = job_dict.get('apply_payload', {})
            apply_payload = json.dumps(raw_payload, ensure_ascii=False) if isinstance(raw_payload, dict) else str(raw_payload)

        cursor.execute("""
            INSERT INTO jobs 
            (job_id, title, company, location, job_url, job_type, date_posted, site, relevance_score, description, status, timestamp, is_applied, apply_type, apply_payload, apply_url, is_easy_apply, workplace_setup)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            job_id,
            job_dict.get('title', ''),
            job_dict.get('company', ''),
            job_dict.get('location', ''),
            job_url,
            job_dict.get('job_type', ''),
            str(job_dict.get('date_posted', '')),
            job_dict.get('site', ''),
            job_dict.get('relevance_score', 0),
            job_dict.get('description', ''),
            status,
            now,
            is_applied,
            apply_type,
            apply_payload,
            apply_url,
            is_easy_apply_val,
            job_dict.get('workplace_setup', 'On-site')
        ))
        conn.commit()
        cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
        inserted = dict(cursor.fetchone())
        conn.close()
        return inserted, True

def get_jobs_by_status(status_list):
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    placeholders = ','.join('?' for _ in status_list)
    cursor.execute(f"""
        SELECT * FROM jobs 
        WHERE status IN ({placeholders})
        ORDER BY relevance_score DESC, date_posted DESC
    """, status_list)
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]

def get_jobs_by_apply_type(apply_type: str, status_list=None):
    """Returns jobs filtered by apply_type (and optional status list)."""
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    if status_list:
        placeholders = ','.join('?' for _ in status_list)
        cursor.execute(f"""
            SELECT * FROM jobs 
            WHERE (apply_type = ? OR (apply_channel IS NOT NULL AND apply_channel = ?))
              AND status IN ({placeholders})
            ORDER BY relevance_score DESC, date_posted DESC
        """, [apply_type, apply_type] + list(status_list))
    else:
        cursor.execute("""
            SELECT * FROM jobs 
            WHERE apply_type = ? OR (apply_channel IS NOT NULL AND apply_channel = ?)
            ORDER BY relevance_score DESC, date_posted DESC
        """, (apply_type, apply_type))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def update_job_status(job_id, status):
    """Updates the status of a specific job."""
    conn = sqlite3.connect(DB_PATH, timeout=15)
    cursor = conn.cursor()
    cursor.execute("UPDATE jobs SET status = ? WHERE job_id = ?", (status, job_id))
    conn.commit()
    conn.close()

def toggle_job_applied(job_id, is_applied):
    """Sets the is_applied flag of a specific job (1 or 0)."""
    conn = sqlite3.connect(DB_PATH, timeout=15)
    cursor = conn.cursor()
    cursor.execute("UPDATE jobs SET is_applied = ? WHERE job_id = ?", (is_applied, job_id))
    conn.commit()
    conn.close()

def get_job_by_id(job_id: str) -> Optional[Dict[str, Any]]:
    """Fetches job details from the local SQLite database and deserializes apply_payload."""
    if not job_id or not os.path.exists(DB_PATH):
        return None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=15)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            d = dict(row)
            if d.get("apply_payload") and isinstance(d["apply_payload"], str):
                try:
                    d["apply_payload"] = json.loads(d["apply_payload"])
                except Exception:
                    d["apply_payload"] = {}
            return d
    except Exception:
        pass
    return None

def record_job_applied(job_id: str, channel: str = "", extra_payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Marks a job as applied in the database, recording timestamp and channel metadata in apply_payload."""
    if not job_id or not os.path.exists(DB_PATH):
        return {"status": "error", "message": "Database or job_id not found"}
    try:
        now_str = datetime.now().isoformat()
        conn = sqlite3.connect(DB_PATH, timeout=15)
        cursor = conn.cursor()
        cursor.execute("SELECT apply_payload FROM jobs WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        payload = {}
        if row and row[0]:
            try:
                payload = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            except Exception:
                payload = {}
        if channel and extra_payload:
            payload[channel] = extra_payload

        canonical_channel = channel.replace("sent_", "") if (channel and channel.startswith("sent_")) else (channel or "")
        cursor.execute("""
            UPDATE jobs 
            SET is_applied = 1,
                apply_status = 'applied',
                applied_at = ?,
                apply_channel = CASE WHEN ? != '' THEN ? ELSE apply_channel END,
                apply_payload = ?
            WHERE job_id = ?
        """, (now_str, canonical_channel, canonical_channel, json.dumps(payload, ensure_ascii=False), job_id))
        conn.commit()
        conn.close()
        return {"status": "success", "job_id": job_id, "applied_at": now_str}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def is_job_seen(job_url: str) -> bool:
    """Fast pre-AI deduplication check. Returns True if this URL already exists in the DB (as job_url or apply_url).
    Always returns False on any error so the scraper proceeds safely."""
    if not job_url:
        return False
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM jobs WHERE job_url = ? OR (apply_url IS NOT NULL AND apply_url != '' AND apply_url = ?) LIMIT 1",
            (job_url, job_url)
        )
        found = cursor.fetchone() is not None
        conn.close()
        return found
    except Exception:
        return False

def get_job_by_url(job_url: str):
    """Returns the existing job dictionary if job_url matches (as job_url or apply_url), else None."""
    if not job_url:
        return None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM jobs WHERE job_url = ? OR (apply_url IS NOT NULL AND apply_url != '' AND apply_url = ?) LIMIT 1",
            (job_url, job_url)
        )
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None

# Initialize DB when module is loaded
init_db()

def delete_job_by_id(job_id: str) -> bool:
    """Deletes a single job from the database by its ID."""
    if not job_id:
        return False
    conn = sqlite3.connect(DB_PATH, timeout=15)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def cleanup_old_jobs(days=90):
    from datetime import timedelta
    conn = sqlite3.connect(DB_PATH, timeout=15)
    cursor = conn.cursor()
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    cursor.execute("DELETE FROM jobs WHERE timestamp < ? OR (date_posted != '' AND date_posted < ?)", (cutoff, cutoff_date))
    deleted_count = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted_count


def update_job_apply_status(job_id: str, apply_status: str, channel: str = None, payload: dict = None, is_applied: int = None):
    """Updates auto-apply progress and metadata for a job."""
    conn = sqlite3.connect(DB_PATH, timeout=15)
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    
    updates = ["apply_status = ?"]
    params = [apply_status]
    
    if channel:
        updates.append("apply_channel = ?")
        params.append(channel)
        
    if apply_status == 'applied':
        updates.append("applied_at = ?")
        params.append(now)
        updates.append("is_applied = 1")
    elif is_applied is not None:
        updates.append("is_applied = ?")
        params.append(is_applied)
        
    if payload is not None:
        updates.append("apply_payload = ?")
        params.append(json.dumps(payload, ensure_ascii=False))
        
    params.append(job_id)
    query = f"UPDATE jobs SET {', '.join(updates)} WHERE job_id = ?"
    cursor.execute(query, tuple(params))
    conn.commit()
    conn.close()


def _clean_phone(raw_phone: Any) -> str:
    if not raw_phone:
        return ""
    import re
    return re.sub(r'\D', '', str(raw_phone)).strip()


def get_autopilot_applied_tracker(conn=None) -> Dict[str, Set]:
    """
    Builds in-memory lookup sets of applied and not-related identifiers for fast cross-listing deduplication.
    """
    close_conn = False
    if conn is None:
        if not os.path.exists(DB_PATH):
            return {
                "applied_job_ids": set(),
                "applied_urls": set(),
                "applied_title_company": set(),
                "applied_emails": set(),
                "applied_phones": set(),
                "not_related_job_ids": set(),
                "not_related_urls": set(),
                "not_related_title_company": set()
            }
        conn = sqlite3.connect(DB_PATH, timeout=15)
        conn.row_factory = sqlite3.Row
        close_conn = True

    try:
        cursor = conn.cursor()
        
        # 1. Fetch all applied jobs
        cursor.execute("""
            SELECT job_id, title, company, job_url, apply_url, apply_payload
            FROM jobs
            WHERE is_applied = 1
               OR apply_status = 'applied'
               OR status = 'applied'
        """)
        applied_rows = cursor.fetchall()
        
        applied_job_ids = set()
        applied_urls = set()
        applied_title_company = set()
        applied_emails = set()
        applied_phones = set()

        for r in applied_rows:
            jid = (r["job_id"] or "").strip()
            if jid:
                applied_job_ids.add(jid)
            ju = (r["job_url"] or "").strip()
            if ju:
                applied_urls.add(ju)
            au = (r["apply_url"] or "").strip()
            if au:
                applied_urls.add(au)
            t = (r["title"] or "").strip().lower()
            c = (r["company"] or "").strip().lower()
            if t and c:
                applied_title_company.add((t, c))
            
            raw_payload = r["apply_payload"]
            if raw_payload:
                try:
                    payload = json.loads(raw_payload) if isinstance(raw_payload, str) else raw_payload
                    email = (payload.get("recipient_email") or "").strip().lower()
                    if email:
                        applied_emails.add(email)
                    if payload.get("sent_email") and isinstance(payload["sent_email"], dict):
                        se = (payload["sent_email"].get("recipient") or "").strip().lower()
                        if se:
                            applied_emails.add(se)
                    raw_p = payload.get("phone") or ""
                    if not raw_p and payload.get("sent_whatsapp") and isinstance(payload["sent_whatsapp"], dict):
                        raw_p = payload["sent_whatsapp"].get("phone") or ""
                    cleaned_p = _clean_phone(raw_p)
                    if cleaned_p:
                        applied_phones.add(cleaned_p)
                except Exception:
                    pass

        # 2. Fetch all not_related and filtered jobs
        cursor.execute("""
            SELECT job_id, title, company, job_url, apply_url
            FROM jobs
            WHERE status IN ('not_related', 'filtered')
        """)
        not_related_rows = cursor.fetchall()
        
        not_related_job_ids = set()
        not_related_urls = set()
        not_related_title_company = set()

        for r in not_related_rows:
            jid = (r["job_id"] or "").strip()
            if jid:
                not_related_job_ids.add(jid)
            ju = (r["job_url"] or "").strip()
            if ju:
                not_related_urls.add(ju)
            au = (r["apply_url"] or "").strip()
            if au:
                not_related_urls.add(au)
            t = (r["title"] or "").strip().lower()
            c = (r["company"] or "").strip().lower()
            if t and c:
                not_related_title_company.add((t, c))

        return {
            "applied_job_ids": applied_job_ids,
            "applied_urls": applied_urls,
            "applied_title_company": applied_title_company,
            "applied_emails": applied_emails,
            "applied_phones": applied_phones,
            "not_related_job_ids": not_related_job_ids,
            "not_related_urls": not_related_urls,
            "not_related_title_company": not_related_title_company
        }
    finally:
        if close_conn:
            conn.close()


def is_job_eligible_for_autopilot(
    job: Dict[str, Any],
    applied_tracker: Optional[Dict[str, Set]] = None,
    min_score: int = 70,
    channel: Optional[str] = None,
    channels_enabled: Optional[Dict[str, bool]] = None
) -> Tuple[bool, str]:
    """
    Strict validation gate guaranteeing that AutoPilot will NOT apply for:
    1. Channels that are disabled in settings or unsupported for auto-apply.
    2. Not-related jobs (status == 'not_related', status == 'filtered', status not in ('pending', 'liked')).
    3. Jobs with non-positive relevance score (score <= 0) or below user threshold.
    4. Jobs failing core career criteria validation (is_valid_job).
    5. Jobs matching any URL or (title, company) marked 'not_related' in the system.
    6. Already applied jobs (is_applied == 1, apply_status == 'applied', status == 'applied').
    7. Duplicate listings matching any URL or (title, company) of an already applied job.
    8. Recipient contact duplicates (email/phone already applied to).
    """
    if not job:
        return False, "Empty or invalid job record"

    # Channel check if channels_enabled is provided
    if channels_enabled is not None:
        target_channel = channel or job.get("apply_type") or ""
        target_channel = target_channel.strip().lower()
        if target_channel in ("email", "whatsapp", "easy_apply", "platform"):
            default_val = True if target_channel == "email" else False
            if not channels_enabled.get(target_channel, default_val):
                return False, f"Channel '{target_channel}' is disabled in settings"
        elif target_channel in ("manual", "job_board", "social_post"):
            return False, f"Channel '{target_channel}' is not supported for auto-apply"

    job_id = (job.get("job_id") or "").strip()

    # 1. Status checks
    status = (job.get("status") or "pending").strip().lower()
    if status == "not_related":
        return False, "Job is marked as not related"
    if status == "filtered":
        return False, "Job is marked as filtered / dropped"
    if status == "applied":
        return False, "Job is already marked as applied (status='applied')"
    if status not in ("pending", "liked"):
        return False, f"Job status '{status}' is not eligible (must be pending or liked)"

    # 2. Applied flag checks on this record
    if job.get("is_applied") in (1, "1", True):
        return False, "Job is already marked as applied (is_applied=1)"
    apply_status = (job.get("apply_status") or "").strip().lower()
    if apply_status == "applied":
        return False, "Job is already marked as applied (apply_status='applied')"

    # 3. Relevance Score checks
    try:
        score = float(job.get("relevance_score") or 0)
    except (ValueError, TypeError):
        score = 0.0

    if score <= 0:
        return False, f"Job relevance score ({score}) is <= 0 (not related)"
    if score < min_score:
        return False, f"Job relevance score ({score}) is below minimum threshold ({min_score})"

    # 4. Career criteria relevance validation (is_valid_job)
    try:
        from core.scorer import is_valid_job
        if not is_valid_job(job):
            return False, "Job fails career criteria relevance validation"
    except Exception:
        pass

    # 5. Cross-listing deduplication against applied & not_related sets
    if applied_tracker:
        job_url = (job.get("job_url") or "").strip()
        apply_url = (job.get("apply_url") or "").strip()
        t = (job.get("title") or "").strip().lower()
        c = (job.get("company") or "").strip().lower()
        key = (t, c)

        # A. Not-related cross check
        if job_id and job_id in applied_tracker.get("not_related_job_ids", set()):
            return False, "Job ID was marked as not related"
        if (job_url and job_url in applied_tracker.get("not_related_urls", set())) or \
           (apply_url and apply_url in applied_tracker.get("not_related_urls", set())):
            return False, "Job URL was marked as not related in database"
        if key != ("", "") and key in applied_tracker.get("not_related_title_company", set()):
            return False, f"Role '{job.get('title')}' at '{job.get('company')}' was marked as not related in another listing"

        # B. Applied cross check
        if job_id and job_id in applied_tracker.get("applied_job_ids", set()):
            return False, "Job ID is already in applied records"
        if (job_url and job_url in applied_tracker.get("applied_urls", set())) or \
           (apply_url and apply_url in applied_tracker.get("applied_urls", set())):
            return False, "Job URL was already applied to"
        if key != ("", "") and key in applied_tracker.get("applied_title_company", set()):
            return False, f"Already applied for '{job.get('title')}' at '{job.get('company')}' in another listing"

        # C. Contact / Recipient cross check
        raw_payload = job.get("apply_payload", {})
        payload = json.loads(raw_payload) if isinstance(raw_payload, str) else (raw_payload or {})

        if channel == "email" or job.get("apply_type") == "email":
            email = (payload.get("recipient_email") or "").strip().lower()
            if email and email in applied_tracker.get("applied_emails", set()):
                return False, f"Already sent application to recruiter email '{email}'"

        if channel == "whatsapp" or job.get("apply_type") == "whatsapp":
            raw_p = payload.get("phone") or ""
            if not raw_p and payload.get("whatsapp_url"):
                import re
                m = re.search(r'(?:wa\.me/|phone=)(\d+)', payload.get("whatsapp_url", ""))
                if m:
                    raw_p = m.group(1)
            phone = _clean_phone(raw_p)
            if phone and phone in applied_tracker.get("applied_phones", set()):
                return False, f"Already sent WhatsApp message to phone '{phone}'"

    return True, "Eligible"


def register_autopilot_applied(
    job: Dict[str, Any],
    tracker: Dict[str, Set],
    recipient_email: str = "",
    phone: str = ""
) -> None:
    """Updates the in-memory tracker with a newly applied job to prevent duplicate applications in the same batch."""
    if not tracker:
        return
    job_id = (job.get("job_id") or "").strip()
    if job_id:
        tracker.setdefault("applied_job_ids", set()).add(job_id)
    job_url = (job.get("job_url") or "").strip()
    if job_url:
        tracker.setdefault("applied_urls", set()).add(job_url)
    apply_url = (job.get("apply_url") or "").strip()
    if apply_url:
        tracker.setdefault("applied_urls", set()).add(apply_url)
    t = (job.get("title") or "").strip().lower()
    c = (job.get("company") or "").strip().lower()
    if t and c:
        tracker.setdefault("applied_title_company", set()).add((t, c))
    if recipient_email:
        tracker.setdefault("applied_emails", set()).add(recipient_email.strip().lower())
    if phone:
        cleaned_p = _clean_phone(phone)
        if cleaned_p:
            tracker.setdefault("applied_phones", set()).add(cleaned_p)


def get_autopilot_candidate_jobs(
    apply_types: List[str],
    min_score: int = 70,
    limit: int = 50,
    conn = None,
    tracker: Optional[Dict[str, Set]] = None,
    channels_enabled: Optional[Dict[str, bool]] = None
) -> List[Dict[str, Any]]:
    """
    Fetches strictly eligible unapplied, non-not-related jobs for autopilot processing.
    """
    if channels_enabled is not None:
        apply_types = [
            t for t in apply_types
            if channels_enabled.get(t, True if t == "email" else False)
        ]
        if not apply_types:
            return []

    close_conn = False
    if conn is None:
        if not os.path.exists(DB_PATH):
            return []
        conn = sqlite3.connect(DB_PATH, timeout=15)
        conn.row_factory = sqlite3.Row
        close_conn = True

    try:
        if tracker is None:
            tracker = get_autopilot_applied_tracker(conn=conn)

        placeholders = ','.join('?' for _ in apply_types)
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT * FROM jobs
            WHERE is_applied = 0
              AND (apply_status IS NULL OR apply_status != 'applied')
              AND (status IS NULL OR status IN ('pending', 'liked'))
              AND status NOT IN ('not_related', 'filtered', 'applied')
              AND apply_type IN ({placeholders})
              AND relevance_score > 0
              AND relevance_score >= ?
            ORDER BY relevance_score DESC
            LIMIT ?
        """, apply_types + [min_score, max(limit * 4, 30)])
        
        candidates = [dict(r) for r in cursor.fetchall()]
        channel = apply_types[0] if len(apply_types) == 1 else None
        
        filtered = []
        for j in candidates:
            eligible, _ = is_job_eligible_for_autopilot(
                j,
                applied_tracker=tracker,
                min_score=min_score,
                channel=channel,
                channels_enabled=channels_enabled
            )
            if eligible:
                filtered.append(j)
                if len(filtered) >= limit:
                    break
        return filtered
    finally:
        if close_conn:
            conn.close()

