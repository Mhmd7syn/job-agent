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

## How to Setup

### Initial Installation
1. Clone or download the repository to your local machine.
2. Run `setup.bat` by double-clicking it.
3. The setup script will automatically:
   - Check for Python and Git (installing Git if necessary).
   - Initialize the Git repository for auto-updates.
   - Create a Python virtual environment and install all dependencies (including Playwright browsers).
   - Prompt you to configure your `.env` file for **LinkedIn credentials** (optional) and **Gemini API Key** (optional). *Note: These credentials are encrypted and stored locally.*
   - Create a Windows Scheduled Task to run the agent silently in the background on your preferred days and time.
   - Create a Desktop Shortcut for easy access.

### Modifying Credentials Later
If you skipped entering your LinkedIn credentials or Gemini API key during the initial setup, or need to update them:
1. Delete the `.env` file in the project root if it exists.
2. Open a terminal in the project folder and run:
   ```cmd
   call venv\Scripts\activate.bat
   python scripts\setup_env.py
   ```

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

### 3. Manual Run
If you want to force the agent to search for jobs immediately without waiting for the schedule, you can run it manually:
```cmd
call venv\Scripts\activate.bat
python job_agent.py
```

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
