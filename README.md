# Job Agent

> [!WARNING]
> This project is currently under editing and active development; it may have some problems. If anyone has recommendations or can help in the developing, please send them to me.

An intelligent, fully automated job scraping and filtering agent designed to find, score, and evaluate the most relevant job postings across multiple platforms based on your personal profile.

## Overview

Job Agent runs silently in the background (or on demand) to continuously search for jobs across platforms like LinkedIn, Glassdoor, Wuzzuf, Bayt, Tanqeeb, and Indeed. It applies advanced logic and AI evaluation (via Gemini API) to filter out irrelevant posts and present you with high-quality job matches tailored to your specific preferences, resume keywords, and career level.

## Key Features

- **Multi-Platform Scraping**: Automatically gathers jobs from LinkedIn, Wuzzuf, Glassdoor, Bayt, Tanqeeb, and Indeed.
- **Smart Filtering & Scoring Engine**: Calculates a `relevance_score` for each job based on your resume keywords, target locations, excluded keywords, and preferred companies.
- **AI-Powered Evaluation**: Uses Google's Gemini API to evaluate run results, provide a summary brief, and auto-tune your configuration for better future results.
- **Desktop Dashboard**: Includes a user-friendly desktop application (built with PyWebview and FastAPI) to review top-matching jobs comfortably.
- **Background Automation**: Sets up a Windows Scheduled Task to run silently in the background (e.g., twice a week).
- **Auto-Updates**: Automatically pulls the latest code from GitHub to ensure you have the latest features and bug fixes.
- **Smart Feedback Loop**: Learns from the jobs you "like" to boost similar roles in the future.

## UI Preview

### 📽️ Interactive Video Demo
Watch how to filter curated jobs, switch between platforms, and customize your AI matching settings directly in the dashboard:

<video src="./Job_agent_Demo.mp4" controls="controls" muted="muted" width="100%">
  Your browser does not support the video tag. <a href="./Job_agent_Demo.mp4">Click here to view the Job Agent Demo Video</a>.
</video>

*[Click here to watch or download the video demo](./Job_agent_Demo.mp4)*

### 📸 Dashboard Preview
![Dashboard Photo](./Dashboard_Photo.png)

## Prerequisites

- **Python 3.9+** must be installed and added to your system `PATH`.
- **Windows OS** (due to batch scripts, desktop app bindings, and scheduled tasks).

## How to Setup (Graphical 1-Click Installation)

### Zero-Configuration Standalone Setup
You do **not** need to manually clone or download the GitHub repository! 
1. Download simply ONE file: **[Setup_Job_Agent.bat](https://raw.githubusercontent.com/Mhmd7syn/job-agent/main/Setup_Job_Agent.bat)** (or `setup_ui.pyw`) to your computer.
2. Double-click the downloaded setup file.
3. A sleek, dark-mode **GUI Installation Wizard** will launch and allow you to:
   - **📁 Choose Installation Directory**: Pick exactly where on your machine you want Job Agent installed via a simple "Browse..." selector. The wizard automatically downloads and sets up all repository files directly in your chosen folder!
   - **Lightweight Auto-Updates**: Initializes shallow Git auto-updates (`--depth=1`) to keep your agent upgraded effortlessly.
   - **Python Environment**: Automatically sets up an isolated Python virtual environment (`venv`) and cleanly installs dependencies.
   - **📄 AI Smart CV Ingestion**: Click **"Auto-Tune from My CV / Resume (AI)"** to upload your resume (PDF, DOCX, or TXT). Powered by Gemini AI, the wizard will analyze your career history and automatically populate your target job titles, experience level, primary keywords, and draft your AI matching profile brief in seconds!
   - **Personalize Job Search & Location**: Review and customize the sample default preferences (AI/Data Science in Egypt) to match your desired geographic locations, cities, seniority levels, and target roles—without modifying the original repository defaults!
   - **Secure Vault (.env)**: Encrypts and stores optional credentials (LinkedIn & Gemini AI Key) locally using military-grade Fernet encryption.
   - **Automation**: Configures a Windows Scheduled Task for silent background job scraping and adds a convenient Desktop shortcut.

### Zero Hardcoded Settings & Dashboard Customization
Job Agent operates with **100% dynamic, user-configurable settings**. There are **no hardcoded parameters** in the scraping code or backend! All locations, target job sites, seniority levels, remote keywords, scraping intervals, and retention days reside cleanly in `core/config.json`.
- Open the desktop dashboard at any time and click **Settings** (<i class="fa-solid fa-gear"></i>) to view and modify EVERY scraping parameter live!
- Inside the dashboard settings, you can also click **"Import Skills & Preferences from CV"** at any time to re-analyze your updated resume and retune your AI matching criteria on the fly!

### How to Uninstall
To cleanly remove all scheduled tasks, desktop shortcuts, local encryption keys, virtual environments, and scraped databases from your computer, simply double-click **`Uninstall_Job_Agent.bat`** (or `uninstall_ui.pyw`) to launch the automated GUI Uninstaller.


## How to Use

### 1. Desktop Application (Dashboard)
You can launch the dashboard at any time using the **Job Agent** shortcut on your desktop, or by running `Job_Agent.bat`. This will:
1. Check for any available updates from GitHub.
2. Start the local server (FastAPI).
3. Open a desktop window where you can view your curated list of jobs.
4. **Smart Feedback**: You can interact with the jobs in the dashboard. Marking jobs as "Liked" will feed into the Smart Feedback Loop, boosting the relevance score of similar companies and job titles in future runs.

### 2. Background Job Agent (Automated)
By default, the setup creates a Windows Scheduled Task (named "Weekly Job Agent"). 
- **What it does**: It wakes up on your chosen days/times, scrapes all configured platforms, filters and scores the jobs, and evaluates the run using AI (if a Gemini key is provided).
- **Where to find results**: 
  - **SQLite Database**: `output/jobs_state.db` (used by the dashboard).
  - **Raw Data**: Top 100 jobs are saved to CSV files in the `output/` folder.
  - **AI Summary**: Check `output/evaluation_brief.txt` for the Gemini model's evaluation of the latest run.
- **Changing the Schedule**: Open the Windows "Task Scheduler" app, locate "Weekly Job Agent" in the active tasks list, and modify its triggers.

### 3. Manual Run (On-Demand)
If you want to force the agent to search for new jobs immediately without waiting for the background schedule, you do **not** need to use terminal commands!
Simply open the **Job Agent Dashboard** using your desktop shortcut and click the run button directly within the dashboard user interface to initiate an immediate scan.

## Configuration

The agent is highly customizable. You can adjust your job search preferences across two main files:

**1. `core/config.json` (Keywords and Roles)**
Modify this JSON file to adjust:
- `ROLES`: Your target job roles, including English and Arabic search terms, and max years of experience.
- `RESUME_KEYWORDS` & `NICE_TO_HAVE_SKILLS`: Skills to boost a job's relevance score.
- `EXCLUDE_KEYWORDS` & `EXCLUDED_COMPANIES`: Terms and companies to filter out completely.
- `FAVORITE_COMPANIES`: Companies to boost the relevance score of.

**2. `core/config.py` (Locations and Settings)**
Edit this Python file to configure:
- `LOCATION` & `TARGET_LOCATIONS`: Your geographic preferences (e.g., specific cities in Egypt).
- `TARGET_LEVELS`: Seniority levels to look for (e.g., junior, intern).
- `USER_BRIEF`: A short text description of your profile used by the AI evaluator.
- Remote work preferences and other scraper settings.

## Important Safety Warnings

- **LinkedIn Scraping**: Do not run the agent constantly. The default schedule is designed to be safe. Running it too frequently (e.g., every hour) may trigger security blocks or captchas on your LinkedIn account.
- **Burner Account**: If you are concerned about your primary LinkedIn account, you can create a secondary, empty account just for the script to use. Connections are not required to search for jobs.

## Architecture

- **`job_agent.py`**: The core script that orchestrates scrapers, applies the scoring engine, saves results, and triggers the AI evaluation.
- **`scrapers/`**: Contains the individual modules for each supported job board (Playwright is heavily used for dynamic content).
- **`core/`**: Contains configuration, database operations (SQLite), and the LLM parsing logic.
- **`web/`**: Contains the FastAPI server for the desktop application backend.
- **`desktop_app.pyw`**: Boots the Pywebview window connecting to the FastAPI server.

## License

This project is for personal use to automate your job search process.
