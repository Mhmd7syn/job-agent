import sqlite3
import os
import json
from datetime import datetime

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
    
    # Add index on job_url for high-speed deduplication checks
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_job_url ON jobs(job_url)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_apply_type ON jobs(apply_type)")
    
    conn.commit()
    conn.close()

    # Automatically ensure existing jobs have accurate classifications
    try:
        backfill_job_classifications()
    except Exception as e:
        print(f"Warning during backfill_job_classifications: {e}")

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
    import json
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
            is_easy_apply = COALESCE(?, is_easy_apply)
        WHERE job_id = ? AND status = 'pending'
    """, (job_dict.get('relevance_score', 0), apply_type, apply_payload, apply_url, is_easy_apply, job_dict.get('job_id', '')))

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
        if job_dict.get('status'):
            status = job_dict['status']
        elif force_pending:
            status = 'pending'
        else:
            status = existing_dict.get('status', 'pending')

        # Preserve is_applied unless specified
        is_applied = job_dict.get('is_applied', existing_dict.get('is_applied', 0))
        
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

def get_liked_jobs():
    return get_jobs_by_status(['liked'])

def get_job_by_id(job_id):
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def is_job_seen(job_url: str) -> bool:
    """Fast pre-AI deduplication check. Returns True if this URL already exists in the DB.
    Always returns False on any error so the scraper proceeds safely."""
    if not job_url:
        return False
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM jobs WHERE job_url = ? LIMIT 1", (job_url,))
        found = cursor.fetchone() is not None
        conn.close()
        return found
    except Exception:
        return False

def get_job_by_url(job_url: str):
    """Returns the existing job dictionary if job_url matches, else None."""
    if not job_url:
        return None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM jobs WHERE job_url = ? LIMIT 1", (job_url,))
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


def cleanup_old_jobs_by_months(months=3):
    """Bulk deletes jobs older than the specified number of months (1, 3, 6)."""
    days = months * 30
    return cleanup_old_jobs(days=days)

def update_job_apply_status(job_id: str, apply_status: str, channel: str = None, payload: dict = None, is_applied: int = None):
    """Updates auto-apply progress and metadata for a job."""
    import json
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

