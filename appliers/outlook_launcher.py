import os
import sys
import json
import logging
import subprocess
import tempfile
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


def launch_outlook_compose(
    recipient: str,
    subject: str,
    body: str,
    cv_path: Optional[str] = None,
    raw_body: Optional[str] = None,
    personal_signature: Optional[str] = None,
    mode: str = "classic"
) -> Dict[str, Any]:
    """
    Launches Classic Outlook (OUTLOOK.EXE via COM automation) to compose an email:
    - Automatically attaches the tailored CV PDF directly into the compose window.
    - Preserves existing Outlook signatures (including images/logos) via WordEditor.Range.InsertBefore.
    - Displays the compose window on screen for the candidate to review and send.
    """
    if sys.platform != "win32":
        return {
            "status": "error",
            "message": "Classic Outlook COM automation is only supported on Windows."
        }

    try:
        payload = {
            "recipient": recipient or "",
            "subject": subject or "",
            "body": body or "",
            "raw_body": raw_body or body or "",
            "cv_path": os.path.abspath(cv_path) if (cv_path and os.path.exists(cv_path)) else "",
            "personal_signature": personal_signature or ""
        }

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            temp_json_path = f.name

        ps_script = r"""
param([string]$JsonPath)
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $data = Get-Content -Raw -Path $JsonPath -Encoding UTF8 | ConvertFrom-Json
    $outlook = New-Object -ComObject Outlook.Application
    $mail = $outlook.CreateItem(0)
    if ($data.recipient) { $mail.To = $data.recipient }
    if ($data.subject) { $mail.Subject = $data.subject }
    if ($data.cv_path -and (Test-Path $data.cv_path)) {
        $mail.Attachments.Add($data.cv_path)
    }
    $mail.Display()

    # Check whether Outlook already populated a default/personal signature (text or HTML/image)
    $existingBody = $mail.Body
    $existingHtml = $mail.HTMLBody
    $hasExistingSig = ($existingBody -ne $null -and $existingBody.Trim().Length -gt 5) -or ($existingHtml -match "<img|v:imagedata|<table")

    if ($hasExistingSig -and $data.raw_body) {
        $textToInsert = $data.raw_body + "`r`n`r`n"
    } else {
        $textToInsert = $data.body + "`r`n`r`n"
    }

    $inspector = $mail.GetInspector
    $editor = $inspector.WordEditor
    if ($editor) {
        $editor.Range(0, 0).InsertBefore($textToInsert)
    } else {
        $mail.Body = $textToInsert
    }
    try { $mail.Activate() } catch {}
    Write-Output "SUCCESS"
} catch {
    Write-Error $_.Exception.Message
    exit 1
}
"""
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".ps1", delete=False) as f:
            f.write(ps_script)
            temp_ps1_path = f.name

        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", temp_ps1_path, temp_json_path]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=20)

        try:
            os.remove(temp_json_path)
            os.remove(temp_ps1_path)
        except Exception:
            pass

        if res.returncode == 0 and "SUCCESS" in res.stdout:
            return {
                "status": "success",
                "client": "classic_outlook",
                "recipient": recipient,
                "subject": subject,
                "attached": bool(cv_path and os.path.exists(cv_path)),
                "cv_filename": os.path.basename(cv_path) if cv_path else None,
                "cv_path": cv_path,
                "instructions": "Classic Outlook opened with CV attached. Review your message and click Send in Outlook.",
                "message": "Classic Outlook opened successfully with CV attached."
            }
        else:
            err_msg = res.stderr.strip() or res.stdout.strip() or "Unknown PowerShell COM error"
            logger.error(f"Classic Outlook COM execution failed: {err_msg}")
            return {
                "status": "error",
                "message": f"Failed to open Classic Outlook: {err_msg}"
            }

    except Exception as e:
        logger.error(f"Error launching Classic Outlook: {e}")
        return {
            "status": "error",
            "message": f"Error launching Classic Outlook: {str(e)}"
        }
