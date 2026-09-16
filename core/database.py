import sqlite3
import os
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
    
    # Try adding is_applied if it doesn't exist
    try:
        cursor.execute('ALTER TABLE jobs ADD COLUMN is_applied INTEGER DEFAULT 0')
    except sqlite3.OperationalError:
        pass

    # Migrate any old 'applied' status
    cursor.execute("UPDATE jobs SET is_applied = 1, status = 'liked' WHERE status = 'applied'")
    
    # Add index on job_url for high-speed deduplication checks
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_job_url ON jobs(job_url)")
    
    conn.commit()
    conn.close()

def save_job(job_dict):
    conn = sqlite3.connect(DB_PATH, timeout=15)
    cursor = conn.cursor()
    
    now = datetime.now().isoformat()
    
    # Insert or ignore (if it already exists, we might not want to overwrite its status)
    cursor.execute("""
        INSERT OR IGNORE INTO jobs 
        (job_id, title, company, location, job_url, job_type, date_posted, site, relevance_score, description, status, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
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
        now
    ))
    
    # If we want to update the relevance score for an existing job that is still pending
    cursor.execute("""
        UPDATE jobs 
        SET relevance_score = ? 
        WHERE job_id = ? AND status = 'pending'
    """, (job_dict.get('relevance_score', 0), job_dict.get('job_id', '')))

    conn.commit()
    conn.close()

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
        
        cursor.execute("""
            UPDATE jobs
            SET title = ?, company = ?, location = ?, job_url = ?, job_type = ?, 
                date_posted = ?, site = ?, relevance_score = ?, description = ?, status = ?, timestamp = ?, is_applied = ?
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
        cursor.execute("""
            INSERT INTO jobs 
            (job_id, title, company, location, job_url, job_type, date_posted, site, relevance_score, description, status, timestamp, is_applied)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            is_applied
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
          AND (status != 'pending' OR relevance_score > 0 OR job_type = 'Scholarship' OR is_applied = 1)
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
