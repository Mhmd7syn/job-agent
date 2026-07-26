from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import sys
import os
import json

# Add the parent directory to sys.path so we can import core modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import get_jobs_by_status, update_job_status, get_job_by_id, toggle_job_applied
from core.config_tuner import analyze_job_and_tune_config

app = FastAPI(title="Job Dashboard")

# Mount static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
def read_root():
    return FileResponse(os.path.join(static_dir, "index.html"))

@app.get("/api/jobs")
def get_jobs():
    """Returns all jobs so the frontend can filter them by status."""
    jobs = get_jobs_by_status(['pending', 'liked', 'not_related'])
    return {"jobs": jobs}

@app.get("/api/config")
def get_config():
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'core', 'config.json')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/config")
async def update_config(request: Request):
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'core', 'config.json')
    try:
        new_config = await request.json()
        from datetime import datetime
        new_config["last_reviewed_date"] = datetime.now().strftime("%Y-%m-%d")
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(new_config, f, indent=2, ensure_ascii=False)
        return {"status": "success", "last_reviewed_date": new_config["last_reviewed_date"]}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/status")
def get_status():
    """Returns the latest AI evaluation brief and the last few lines of the log."""
    output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
    eval_file = os.path.join(output_dir, "evaluation_brief.txt")
    log_file = os.path.join(output_dir, "job_agent.log")
    
    eval_text = "No evaluation available yet."
    if os.path.exists(eval_file):
        with open(eval_file, "r", encoding="utf-8") as f:
            eval_text = f.read()
            
    log_text = "No logs available."
    if os.path.exists(log_file):
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            log_text = "".join(lines[-20:]) # Last 20 lines
            
    return {"evaluation": eval_text, "logs": log_text}

@app.post("/api/jobs/{job_id}/apply")
def toggle_applied(job_id: str):
    """Toggles the is_applied boolean flag for a job."""
    job = get_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    
    new_state = 0 if job.get('is_applied') == 1 else 1
    toggle_job_applied(job_id, new_state)
    return {"status": "success", "job_id": job_id, "is_applied": new_state}

@app.post("/api/jobs/{job_id}/{action}")
def update_job(job_id: str, action: str, background_tasks: BackgroundTasks):
    """
    Updates a job's status and triggers the AI background task to tune the config.
    Valid actions: 'liked', 'not_related', 'pending'
    """
    valid_actions = ['liked', 'not_related', 'pending']
    if action not in valid_actions:
        raise HTTPException(status_code=400, detail="Invalid action.")

    job = get_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    update_job_status(job_id, action)
    
    # Trigger background AI task to extract keywords and tune the config
    background_tasks.add_task(analyze_job_and_tune_config, job, action)

    return {"status": "success", "job_id": job_id, "action": action}

import subprocess

scraper_process = None

@app.post("/api/run-scraper")
def run_scraper():
    global scraper_process
    if scraper_process and scraper_process.poll() is None:
        return {"status": "already_running"}
    
    script_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "job_agent.py")
    python_exe = sys.executable
    
    creationflags = 0
    if os.name == 'nt':
        creationflags = 0x08000000
        
    scraper_process = subprocess.Popen(
        [python_exe, script_path],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        creationflags=creationflags
    )
    return {"status": "started"}

@app.get("/api/scraper-status")
def scraper_status():
    from datetime import datetime
    global scraper_process
    is_running = False
    if scraper_process and scraper_process.poll() is None:
        is_running = True
        
    last_run_str = "Unknown"
    try:
        eval_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "evaluation_brief.txt")
        if os.path.exists(eval_path):
            mtime = os.path.getmtime(eval_path)
            last_run_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %I:%M %p")
    except Exception:
        pass

    return {"is_running": is_running, "last_run": last_run_str}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
