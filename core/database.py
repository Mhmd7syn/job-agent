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

def get_jobs_by_status(status_list):
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    placeholders = ','.join('?' for _ in status_list)
    cursor.execute(f"SELECT * FROM jobs WHERE status IN ({placeholders}) ORDER BY relevance_score DESC, date_posted DESC", status_list)
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

# Initialize DB when module is loaded
init_db()

def cleanup_old_jobs(days=90):
    from datetime import timedelta
    conn = sqlite3.connect(DB_PATH, timeout=15)
    cursor = conn.cursor()
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    cursor.execute("DELETE FROM jobs WHERE timestamp < ?", (cutoff,))
    deleted_count = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted_count
