import os
import shutil
import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, UploadFile, File

from core.applicant_profile import load_profile, save_profile, scan_resume_directory
from core.database import backfill_job_classifications
from core.task_scheduler import sync_autopilot_windows_task

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/profile")
def get_profile_endpoint():
    return load_profile()

@router.post("/api/profile")
def save_profile_endpoint(profile_data: Dict[str, Any]):
    success = save_profile(profile_data)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save profile data.")
    if "auto_apply_settings" in profile_data:
        sync_autopilot_windows_task(profile_data["auto_apply_settings"])
    return {"status": "success", "profile": load_profile()}

@router.api_route("/api/profile/scan-resumes", methods=["GET", "POST"])
def scan_resumes_endpoint(base_dir: Optional[str] = None):
    return scan_resume_directory(base_dir)

@router.post("/api/upload-role-resume")
async def upload_role_resume_endpoint(file: UploadFile = File(...)):
    """Uploads a role resume PDF/DOCX to data/resumes and returns its saved absolute path."""
    try:
        resumes_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "resumes")
        os.makedirs(resumes_dir, exist_ok=True)
        safe_filename = os.path.basename(file.filename)
        dest_path = os.path.join(resumes_dir, safe_filename)
        with open(dest_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        abs_path = os.path.abspath(dest_path)
        return {
            "status": "success",
            "filename": safe_filename,
            "file_path": abs_path,
            "size_kb": round(os.path.getsize(dest_path) / 1024, 1)
        }
    except Exception as e:
        logger.error(f"Error uploading role resume: {e}")
        return {"status": "error", "error": str(e)}

@router.post("/api/check-resume-file")
async def check_resume_file_endpoint(req: Dict[str, Any]):
    """Checks whether a given resume file path exists on disk and returns its metadata."""
    path = (req.get("path") or "").strip()
    if not path:
        return {"exists": False, "filename": "", "size_kb": 0}
    
    if not os.path.isabs(path):
        resolved = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), path)
    else:
        resolved = path
        
    exists = os.path.exists(resolved) and os.path.isfile(resolved)
    size_kb = round(os.path.getsize(resolved) / 1024, 1) if exists else 0
    return {
        "exists": exists,
        "path": os.path.abspath(resolved) if exists else path,
        "filename": os.path.basename(resolved),
        "size_kb": size_kb
    }

@router.get("/api/auto-apply/settings")
def get_auto_apply_settings_endpoint():
    profile = load_profile()
    return profile.get("auto_apply_settings", {})

@router.post("/api/auto-apply/settings")
def save_auto_apply_settings_endpoint(settings_data: Dict[str, Any]):
    profile = load_profile()
    profile["auto_apply_settings"] = settings_data
    save_profile(profile)
    sync_autopilot_windows_task(settings_data)
    return {"status": "success", "settings": profile.get("auto_apply_settings", {})}

@router.post("/api/jobs/classify-all")
def classify_all_jobs_endpoint():
    count = backfill_job_classifications()
    return {"status": "success", "classified_count": count}
