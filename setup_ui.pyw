import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import os
import sys
import subprocess
import threading
import queue
import time
import json
import shutil
import urllib.request
import zipfile
import re
import ast

# Windows creation flag to hide console window when invoking subprocesses
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# Modern Dark Theme Colors
BG_DARK = "#181824"
BG_CARD = "#232334"
BG_INPUT = "#13131d"
FG_TEXT = "#f8fafc"
FG_MUTED = "#94a3b8"
BORDER_COL = "#33334b"
ACCENT = "#3b82f6"
ACCENT_HOV = "#2563eb"
SUCCESS = "#10b981"
DANGER = "#ef4444"

class ModernProgressBar(tk.Canvas):
    def __init__(self, parent, width=640, height=22, bg=BG_INPUT, fill_color=ACCENT, **kwargs):
        super().__init__(parent, width=width, height=height, bg=bg, highlightthickness=1, highlightbackground=BORDER_COL, **kwargs)
        self.width = width
        self.height = height
        self.fill_color = fill_color
        self.progress = 0.0
        self.bar_id = self.create_rectangle(0, 0, 0, height, fill=fill_color, outline="")

    def set_progress(self, percentage, color=None):
        self.progress = max(0.0, min(100.0, float(percentage)))
        if color:
            self.itemconfig(self.bar_id, fill=color)
        w = int((self.progress / 100.0) * self.width)
        self.coords(self.bar_id, 0, 0, w, self.height)

class SetupWizard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Job Agent — Setup & Configuration Wizard")
        self.geometry("760x680")
        self.minsize(720, 620)
        self.configure(bg=BG_DARK)
        
        # Try setting window icon
        icon_path = os.path.join(PROJECT_ROOT, 'logo.ico')
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass
        
        self.center_window()
        
        # State variables
        self.log_queue = queue.Queue()
        self.current_screen = 0
        self.repo_was_downloaded = False
        default_install = r"C:\Program Files\Job Agent" if sys.platform == "win32" else os.path.join(os.path.expanduser("~"), "Job Agent")
        self.install_path_var = tk.StringVar(value=default_install)
        
        # Career & config customization state
        self.loc_var = tk.StringVar(value="Egypt, Remote")
        self.cities_var = tk.StringVar(value="Cairo, Giza, Remote")
        self.levels_var = tk.StringVar(value="Junior, Entry-level, Intern")
        self.terms_var = tk.StringVar(value="AI Engineer, Data Scientist, Software Engineer")
        self.brief_text_content = (
            "I am a passionate software and AI professional looking for Junior or Entry-level positions.\n"
            "My core skills include Python, SQL, Machine Learning, and problem solving.\n"
            "I prefer Junior, Intern, or Entry-level positions."
        )
        
        # Credentials state
        self.li_email_var = tk.StringVar()
        self.li_pwd_var = tk.StringVar()
        self.gemini_key_var = tk.StringVar()
        self.keep_env_var = tk.BooleanVar(value=os.path.exists(os.path.join(PROJECT_ROOT, ".env")))
        
        # Schedule & shortcut state
        self.day_vars = {
            'MON': tk.BooleanVar(value=False),
            'TUE': tk.BooleanVar(value=True),
            'WED': tk.BooleanVar(value=False),
            'THU': tk.BooleanVar(value=False),
            'FRI': tk.BooleanVar(value=True),
            'SAT': tk.BooleanVar(value=False),
            'SUN': tk.BooleanVar(value=False)
        }
        self.time_var = tk.StringVar(value="05:00")
        self.shortcut_var = tk.BooleanVar(value=True)

        # Main container
        self.container = tk.Frame(self, bg=BG_DARK, padx=25, pady=20)
        self.container.pack(fill=tk.BOTH, expand=True)

        # Start on Welcome Screen
        self.show_screen(0)
        self.after(100, self.process_queue)

    def center_window(self):
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (w // 2)
        y = (self.winfo_screenheight() // 2) - (h // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def clear_container(self):
        for child in self.container.winfo_children():
            child.destroy()

    def create_button(self, parent, text, command, bg=ACCENT, hover_bg=ACCENT_HOV, fg="white", width=None, px=15, py=8, state=tk.NORMAL):
        btn = tk.Button(
            parent, text=text, command=command, bg=bg, fg=fg,
            activebackground=hover_bg, activeforeground=fg,
            font=("Segoe UI", 10, "bold"), relief="flat", cursor="hand2" if state==tk.NORMAL else "arrow",
            padx=px, pady=py, borderwidth=0, state=state
        )
        if width:
            btn.config(width=width)
        if state == tk.NORMAL:
            btn.bind("<Enter>", lambda e: btn.config(bg=hover_bg))
            btn.bind("<Leave>", lambda e: btn.config(bg=bg))
        return btn

    def create_card(self, parent, title=None, padx=15, pady=12, expand=False):
        card_border = tk.Frame(parent, bg=BORDER_COL, padx=1, pady=1)
        card_border.pack(fill=tk.BOTH, expand=expand, pady=(0, 10))
        card = tk.Frame(card_border, bg=BG_CARD, padx=padx, pady=pady)
        card.pack(fill=tk.BOTH, expand=True)
        if title:
            lbl = tk.Label(card, text=title, font=("Segoe UI", 11, "bold"), fg=FG_TEXT, bg=BG_CARD, anchor="w")
            lbl.pack(fill=tk.X, pady=(0, 8))
        return card_border, card

    def show_screen(self, index):
        self.current_screen = index
        self.clear_container()
        
        if index == 0:
            self.render_welcome_screen()
        elif index == 1:
            self.render_initial_setup_screen()
        elif index == 2:
            self.render_config_screen()
        elif index == 3:
            self.render_credentials_screen()
        elif index == 4:
            self.render_schedule_screen()
        elif index == 5:
            self.render_finalize_screen()

    # ==========================
    # SCREEN 0: Welcome
    # ==========================
    def render_welcome_screen(self):
        title = tk.Label(self.container, text="Welcome to Job Agent Setup", font=("Segoe UI", 18, "bold"), fg=FG_TEXT, bg=BG_DARK, anchor="w")
        title.pack(fill=tk.X, pady=(0, 5))
        
        sub = tk.Label(self.container, text="Your intelligent, fully automated job scraping and AI matching assistant.", font=("Segoe UI", 11), fg=FG_MUTED, bg=BG_DARK, anchor="w")
        sub.pack(fill=tk.X, pady=(0, 15))

        _, card = self.create_card(self.container, title="✨ Graphical & Automated Installer", padx=20, pady=15, expand=True)
        
        # Detect if we need to auto-download repository
        repo_exists = os.path.exists(os.path.join(PROJECT_ROOT, "job_agent.py")) and os.path.exists(os.path.join(PROJECT_ROOT, "core", "config.json"))
        
        items = [
            ("🌐 Standalone Auto-Download", "If you downloaded only this setup file, the installer will automatically download all repository code from GitHub for you without any manual cloning!"),
            ("⚙️ Personalize Preferences", "Review and customize job titles, locations, and career preferences in an interactive GUI without losing defaults."),
            ("🐍 Python Environment", "Creates an isolated virtual environment (venv) and cleanly installs all required dependencies."),
            ("🔐 Secure Local Vault", "Encrypts optional scraping & AI credentials (LinkedIn & Gemini API) locally using Fernet."),
            ("⏰ Automation & Shortcuts", "Schedules background job scanning and adds a handy desktop shortcut.")
        ]
        
        grid_frame = tk.Frame(card, bg=BG_CARD)
        grid_frame.pack(fill=tk.BOTH, expand=True, pady=4)
        grid_frame.columnconfigure(1, weight=1)

        for i, (icon_title, desc) in enumerate(items):
            lbl_title = tk.Label(grid_frame, text=icon_title, font=("Segoe UI", 10, "bold"), fg=FG_TEXT, bg=BG_CARD, anchor="w", width=26)
            lbl_title.grid(row=i, column=0, sticky="nw", padx=(0, 15), pady=6)
            lbl_desc = tk.Label(grid_frame, text=desc, font=("Segoe UI", 10), fg=FG_MUTED, bg=BG_CARD, wraplength=400, justify="left", anchor="w")
            lbl_desc.grid(row=i, column=1, sticky="nw", pady=6)

        status_msg = "✓ All local project files found." if repo_exists else "⚡ Ready to download repository files from GitHub automatically."
        status_col = SUCCESS if repo_exists else ACCENT
        tk.Label(self.container, text=status_msg, font=("Segoe UI", 10, "bold"), fg=status_col, bg=BG_DARK, anchor="w").pack(fill=tk.X, pady=(12, 0))

        # Installation Directory Selector
        _, loc_card = self.create_card(self.container, title="📁 Choose Setup & Installation Location:", padx=20, pady=12)
        row = tk.Frame(loc_card, bg=BG_CARD)
        row.pack(fill=tk.X)
        tk.Label(row, text="Target Folder:", font=("Segoe UI", 10, "bold"), fg=FG_TEXT, bg=BG_CARD).pack(side=tk.LEFT, padx=(0, 10))
        tk.Entry(row, textvariable=self.install_path_var, font=("Segoe UI", 10), bg=BG_INPUT, fg=FG_TEXT, relief="flat", insertbackground="white").pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5, padx=(0, 10))
        
        def browse_dir():
            from tkinter import filedialog
            chosen = filedialog.askdirectory(title="Select Job Agent Installation Directory", initialdir=self.install_path_var.get())
            if chosen:
                self.install_path_var.set(os.path.abspath(chosen))
                
        self.create_button(row, "Browse...", browse_dir, bg="#33334b", hover_bg="#474766", px=14, py=5).pack(side=tk.RIGHT)

        # Bottom Bar
        bottom = tk.Frame(self.container, bg=BG_DARK)
        bottom.pack(fill=tk.X, side=tk.BOTTOM, pady=(15, 0))
        
        self.create_button(bottom, "Cancel", self.destroy, bg="#33334b", hover_bg="#474766", fg=FG_TEXT).pack(side=tk.LEFT)
        self.create_button(bottom, "Next: Download & Initialize ➔", lambda: self.confirm_install_dir_and_next(1)).pack(side=tk.RIGHT)

    def confirm_install_dir_and_next(self, next_screen):
        global PROJECT_ROOT
        chosen_path = os.path.abspath(self.install_path_var.get().strip())
        try:
            os.makedirs(chosen_path, exist_ok=True)
        except PermissionError:
            if sys.platform == "win32":
                resp = messagebox.askyesno(
                    "Administrator Privileges Required",
                    f"Creating or accessing '{chosen_path}' requires Administrator privileges.\n\nWould you like to automatically restart setup as Administrator?"
                )
                if resp:
                    try:
                        import ctypes
                        script_path = os.path.abspath(__file__)
                        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, f'"{script_path}"', None, 1)
                        self.destroy()
                        sys.exit(0)
                    except Exception as e:
                        messagebox.showerror("Elevation Failed", f"Could not restart setup as Administrator: {e}")
            else:
                messagebox.showerror("Permission Denied", f"Permission denied creating target directory:\n{chosen_path}")
            return
        except Exception as e:
            messagebox.showerror("Installation Error", f"Could not create target folder ({chosen_path}): {e}")
            return

        try:
            # Grant full user access permissions on Windows so desktop app & scheduled tasks can create files without errors
            if sys.platform == "win32":
                try:
                    username = os.getenv("USERNAME", "Users")
                    subprocess.run(["icacls", chosen_path, "/grant", f"{username}:(OI)(CI)F", "/T"], capture_output=True, creationflags=CREATE_NO_WINDOW)
                except Exception:
                    pass

            if os.path.normcase(PROJECT_ROOT) != os.path.normcase(chosen_path):
                for item in os.listdir(PROJECT_ROOT):
                    if item not in ["venv", ".git", "__pycache__", "output"]:
                        s = os.path.join(PROJECT_ROOT, item)
                        d = os.path.join(chosen_path, item)
                        try:
                            if os.path.isdir(s):
                                shutil.copytree(s, d, dirs_exist_ok=True)
                            else:
                                shutil.copy2(s, d)
                        except Exception:
                            pass
                PROJECT_ROOT = chosen_path
                try:
                    os.chdir(PROJECT_ROOT)
                except Exception:
                    pass
            self.show_screen(next_screen)
        except Exception as e:
            messagebox.showerror("Installation Error", f"Could not initialize target folder ({chosen_path}): {e}")

    # ==========================
    # SCREEN 1: Progress (Download & Dependencies)
    # ==========================
    def render_initial_setup_screen(self):
        self.prog_title = tk.Label(self.container, text="Initializing Environment & Repository...", font=("Segoe UI", 18, "bold"), fg=FG_TEXT, bg=BG_DARK, anchor="w")
        self.prog_title.pack(fill=tk.X, pady=(0, 5))
        
        self.prog_sub = tk.Label(self.container, text="Please wait while setup fetches code, configures Git, and installs dependencies.", font=("Segoe UI", 11), fg=FG_MUTED, bg=BG_DARK, anchor="w")
        self.prog_sub.pack(fill=tk.X, pady=(0, 15))

        self.status_label = tk.Label(self.container, text="Starting installation...", font=("Segoe UI", 11, "bold"), fg=ACCENT, bg=BG_DARK, anchor="w")
        self.status_label.pack(fill=tk.X, pady=(0, 6))

        self.progress_bar = ModernProgressBar(self.container, width=700, height=22)
        self.progress_bar.pack(fill=tk.X, pady=(0, 15))

        btn_row = tk.Frame(self.container, bg=BG_DARK)
        btn_row.pack(fill=tk.X, pady=(0, 10))
        
        self.details_visible = False
        def toggle_details():
            if not self.details_visible:
                self.log_border.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
                self.details_btn.config(text="▲ Hide Details")
                self.details_visible = True
            else:
                self.log_border.pack_forget()
                self.details_btn.config(text="👁 View Details")
                self.details_visible = False

        self.details_btn = self.create_button(btn_row, "👁 View Details", toggle_details, bg="#33334b", hover_bg="#474766", fg=FG_TEXT, px=14, py=5)
        self.details_btn.pack(side=tk.LEFT)

        self.log_border, log_card = self.create_card(self.container, title="📋 Installation Activity Log:", padx=10, pady=10, expand=True)
        self.log_area = scrolledtext.ScrolledText(log_card, bg=BG_INPUT, fg=FG_TEXT, insertbackground="white", font=("Consolas", 10), relief="flat", height=13, state="disabled", borderwidth=0)
        self.log_area.pack(fill=tk.BOTH, expand=True)
        self.log_border.pack_forget() # Hide logs by default as requested by user

        self.bottom_prog = tk.Frame(self.container, bg=BG_DARK)
        self.bottom_prog.pack(fill=tk.X, side=tk.BOTTOM, pady=(15, 0))

        threading.Thread(target=self.run_initial_setup, daemon=True).start()

    def run_initial_setup(self):
        try:
            # Check if repo download is required
            need_download = not (os.path.exists(os.path.join(PROJECT_ROOT, "job_agent.py")) and os.path.exists(os.path.join(PROJECT_ROOT, "core", "config.json")))
            
            if need_download:
                self.log_queue.put(("progress", 10, "Downloading repository codebase..."))
                self.log("Local repository files missing. Downloading directly from GitHub...")
                zip_url = "https://github.com/Mhmd7syn/job-agent/archive/refs/heads/main.zip"
                tmp_zip = os.path.join(PROJECT_ROOT, "repo_temp.zip")
                
                req = urllib.request.Request(zip_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) JobAgentInstaller/1.0'})
                with urllib.request.urlopen(req) as response, open(tmp_zip, 'wb') as out_file:
                    total_bytes = int(response.headers.get('Content-Length', 0))
                    if total_bytes <= 0:
                        total_bytes = 5_500_000
                    downloaded = 0
                    start_t = time.time()
                    while True:
                        chunk = response.read(16384)
                        if not chunk:
                            break
                        out_file.write(chunk)
                        downloaded += len(chunk)
                        elapsed = max(0.1, time.time() - start_t)
                        speed = (downloaded / 1048576) / elapsed
                        rem_secs = int(max(0, (total_bytes - downloaded) / 1048576) / max(0.01, speed))
                        pct = 10 + int((downloaded / max(1, total_bytes)) * 20)
                        self.log_queue.put(("progress", min(30, pct), f"Downloading code: {downloaded/1048576:.2f} MB / {total_bytes/1048576:.2f} MB ({speed:.1f} MB/s) — ~{rem_secs}s remaining"))
                
                self.log_queue.put(("progress", 32, "Extracting archive into working directory..."))
                self.log("Extracting archive into working directory...")
                with zipfile.ZipFile(tmp_zip, 'r') as zip_ref:
                    zip_ref.extractall(PROJECT_ROOT)
                
                extracted_dir = os.path.join(PROJECT_ROOT, "job-agent-main")
                if os.path.exists(extracted_dir):
                    for item in os.listdir(extracted_dir):
                        s = os.path.join(extracted_dir, item)
                        d = os.path.join(PROJECT_ROOT, item)
                        # Overwrite or move cleanly
                        if os.path.exists(d) and os.path.normcase(os.path.abspath(d)) != os.path.normcase(os.path.abspath(sys.argv[0])):
                            if os.path.isdir(d):
                                shutil.rmtree(d, ignore_errors=True)
                            else:
                                try: os.remove(d)
                                except Exception: pass
                        if not os.path.exists(d):
                            shutil.move(s, PROJECT_ROOT)
                    shutil.rmtree(extracted_dir, ignore_errors=True)
                if os.path.exists(tmp_zip):
                    try: os.remove(tmp_zip)
                    except Exception: pass
                self.log("Repository downloaded and extracted successfully!")
                self.repo_was_downloaded = True
            else:
                self.log("Local project codebase verified.")

            # Step: Git check & setup
            self.log_queue.put(("progress", 40, "Configuring Git environments..."))
            git_cmd = "git"
            res = subprocess.run([git_cmd, "--version"], capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
            if res.returncode != 0:
                self.log("Git not found in PATH. Attempting automatic installation via winget...")
                subprocess.run(["winget", "install", "--id", "Git.Git", "-e", "--source", "winget", "--accept-package-agreements", "--accept-source-agreements"], creationflags=CREATE_NO_WINDOW)
                git_cmd = r"C:\Program Files\Git\cmd\git.exe"
            
            if not os.path.exists(os.path.join(PROJECT_ROOT, ".git")):
                self.log("Initializing Git repository for shallow auto-updates...")
                for cmd in [
                    [git_cmd, "init"],
                    [git_cmd, "remote", "add", "origin", "https://github.com/Mhmd7syn/job-agent.git"],
                    [git_cmd, "fetch", "--depth=1", "origin", "main:refs/remotes/origin/main"],
                    [git_cmd, "reset", "--mixed", "origin/main"],
                    [git_cmd, "branch", "-M", "main"],
                    [git_cmd, "branch", "--set-upstream-to=origin/main", "main"]
                ]:
                    try:
                        p = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
                        if p.stdout: self.log(p.stdout.strip())
                    except Exception as e:
                        self.log(f"Git notice: {e}")
            else:
                self.log("Syncing Git repository commit history to latest version...")
                for cmd in [
                    [git_cmd, "fetch", "--depth=1", "origin", "main:refs/remotes/origin/main"],
                    [git_cmd, "reset", "--mixed", "origin/main"]
                ]:
                    try:
                        p = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
                        if p.stdout: self.log(p.stdout.strip())
                    except Exception as e:
                        self.log(f"Git notice: {e}")

            # Step: Virtual Environment creation
            self.log_queue.put(("progress", 55, "Creating Python virtual environment (venv)..."))
            venv_path = os.path.join(PROJECT_ROOT, "venv")
            if not os.path.exists(venv_path) or not os.path.exists(os.path.join(venv_path, "Scripts", "python.exe")):
                self.log(f"Creating virtual environment: {venv_path}")
                subprocess.run([sys.executable, "-m", "venv", "venv"], cwd=PROJECT_ROOT, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
                self.log("Virtual environment created.")
            else:
                self.log("Virtual environment (venv) already present.")

            # Step: Installing Python Requirements
            self.log_queue.put(("progress", 65, "Installing required packages from requirements.txt..."))
            pip_exe = os.path.join(venv_path, "Scripts", "pip.exe")
            req_file = os.path.join(PROJECT_ROOT, "requirements.txt")
            if os.path.exists(req_file):
                with open(req_file, "r", encoding="utf-8") as rf:
                    req_cnt = len([l for l in rf if l.strip() and not l.strip().startswith("#")])
                self.log(f"Installing {req_cnt} required Python libraries...")
                process = subprocess.Popen(
                    [pip_exe, "install", "--prefer-binary", "-r", "requirements.txt"],
                    cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, creationflags=CREATE_NO_WINDOW
                )
                inst_cnt = 0
                t0 = time.time()
                for line in process.stdout:
                    cline = line.strip()
                    self.log("  " + cline)
                    if "Collecting" in cline or "Downloading" in cline:
                        inst_cnt = min(req_cnt - 1, inst_cnt + 1)
                        el = int(time.time() - t0)
                        self.log_queue.put(("progress", 65 + int((inst_cnt/max(1, req_cnt))*25), f"Installing libraries: {inst_cnt}/{req_cnt} completed ({el}s elapsed)..."))
                process.wait()
                self.log("Python libraries installed successfully.")

            self.log("=========================================")
            self.log("Phase 1 Complete: System components ready!")
            self.log_queue.put(("progress", 100, "Initialization Complete!"))
            self.log_queue.put(("init_done",))

        except Exception as e:
            self.log(f"\nCRITICAL ERROR DURING INITIALIZATION: {str(e)}")
            self.log_queue.put(("error", str(e)))

    # ==========================
    # SCREEN 2: Career & Config Customization
    # ==========================
    def render_config_screen(self):
        # Read current configs from files if available
        self.load_current_config()

        title = tk.Label(self.container, text="Personalize Job Search Preferences", font=("Segoe UI", 18, "bold"), fg=FG_TEXT, bg=BG_DARK, anchor="w")
        title.pack(fill=tk.X, pady=(0, 5))
        
        sub = tk.Label(self.container, text="Review and customize default settings to target your desired career and country.", font=("Segoe UI", 11), fg=FG_MUTED, bg=BG_DARK, anchor="w")
        sub.pack(fill=tk.X, pady=(0, 10))

        # Alert Box regarding default configurations
        _, alert_card = self.create_card(self.container, title="📢 Customize Default Configurations:", padx=15, pady=10)
        notice_txt = (
            "Job Agent comes preloaded with sample default preferences (AI & Data Science roles in Egypt). "
            "We strongly encourage you to customize these general settings below for your target country, locations, and career level! "
            "Don't worry—if you prefer these original settings, your configurations will remain untouched."
        )
        tk.Label(alert_card, text=notice_txt, font=("Segoe UI", 10), fg=ACCENT, bg=BG_CARD, wraplength=670, justify="left", anchor="w").pack(fill=tk.X)

        # Form fields frame
        _, form_card = self.create_card(self.container, padx=15, pady=10, expand=True)

        # AI Smart CV Ingestion button
        cv_frame = tk.Frame(form_card, bg=BG_CARD)
        cv_frame.pack(fill=tk.X, pady=(0, 10))
        tk.Label(cv_frame, text="✨ AI Smart CV Setup:", font=("Segoe UI", 10, "bold"), fg=ACCENT, bg=BG_CARD, anchor="w").pack(side=tk.LEFT)
        
        def import_cv():
            from tkinter import filedialog, messagebox
            file_path = filedialog.askopenfilename(title="Select CV / Resume File", filetypes=[("Resume Files", "*.pdf;*.docx;*.txt;*.md"), ("All Files", "*.*")])
            if file_path:
                try:
                    if PROJECT_ROOT not in sys.path:
                        sys.path.append(PROJECT_ROOT)
                    from core.cv_parser import parse_cv_with_ai
                    api_key = self.gemini_key_var.get().strip() if hasattr(self, 'gemini_key_var') and self.gemini_key_var.get() else None
                    res = parse_cv_with_ai(file_path, api_key=api_key)
                    if "error" in res and res.get("status") != "success":
                        messagebox.showerror("CV Parsing Error", str(res["error"]))
                    else:
                        if "location" in res and res["location"]:
                            self.loc_var.set(res["location"])
                        if "target_levels" in res and res["target_levels"]:
                            self.levels_var.set(", ".join(res["target_levels"]))
                        if "target_roles" in res and res["target_roles"]:
                            terms = []
                            for r in res["target_roles"]:
                                terms.extend(r.get("english_terms", []))
                            if terms:
                                self.terms_var.set(", ".join(list(set(terms))))
                        if "user_brief" in res and res["user_brief"]:
                            self.brief_text_widget.delete("1.0", tk.END)
                            self.brief_text_widget.insert(tk.END, res["user_brief"])
                        messagebox.showinfo("Success", "✨ CV successfully analyzed by AI! Your job search preferences and profile brief have been automatically tailored to your career experience.")
                except Exception as e:
                    messagebox.showerror("Error", f"Could not analyze CV: {e}")

        self.create_button(cv_frame, "📄 Auto-Tune from My CV / Resume (AI)", import_cv, bg=ACCENT, hover_bg=ACCENT_HOV, px=12, py=5).pack(side=tk.RIGHT)

        inputs_frame = tk.Frame(form_card, bg=BG_CARD)
        inputs_frame.pack(fill=tk.X, pady=4)
        inputs_frame.columnconfigure(1, weight=1)
        
        def add_input_row(row_idx, label_txt, var):
            lbl = tk.Label(inputs_frame, text=label_txt, font=("Segoe UI", 10, "bold"), fg=FG_TEXT, bg=BG_CARD, anchor="w", width=26)
            lbl.grid(row=row_idx, column=0, sticky="w", padx=(0, 10), pady=6)
            border = tk.Frame(inputs_frame, bg=BORDER_COL, padx=1, pady=1)
            border.grid(row=row_idx, column=1, sticky="ew", pady=6)
            entry = tk.Entry(border, textvariable=var, font=("Segoe UI", 10), bg=BG_INPUT, fg=FG_TEXT, insertbackground="white", relief="flat")
            entry.pack(fill=tk.X, padx=6, pady=4)

        add_input_row(0, "Target Country/Region:", self.loc_var)
        add_input_row(1, "Target Cities/Districts:", self.cities_var)
        add_input_row(2, "Experience Levels:", self.levels_var)
        add_input_row(3, "Primary Job Search Keywords:", self.terms_var)

        # AI Brief text
        lbl_row = tk.Frame(form_card, bg=BG_CARD)
        lbl_row.pack(fill=tk.X, pady=(6, 2))
        tk.Label(lbl_row, text="AI User Profile Brief (Used by Gemini AI to evaluate & score matches):", font=("Segoe UI", 10, "bold"), fg=FG_TEXT, bg=BG_CARD, anchor="w").pack(fill=tk.X)
        
        txt_border = tk.Frame(form_card, bg=BORDER_COL, padx=1, pady=1)
        txt_border.pack(fill=tk.BOTH, expand=True, pady=(0, 5))
        self.brief_text_widget = tk.Text(txt_border, bg=BG_INPUT, fg=FG_TEXT, insertbackground="white", font=("Segoe UI", 10), height=5, relief="flat")
        self.brief_text_widget.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)
        self.brief_text_widget.insert(tk.END, self.brief_text_content)

        # Bottom Bar
        bottom = tk.Frame(self.container, bg=BG_DARK)
        bottom.pack(fill=tk.X, side=tk.BOTTOM, pady=(10, 0))
        self.create_button(bottom, "⬅ Back to Logs", lambda: self.show_screen(1), bg="#33334b", hover_bg="#474766", fg=FG_TEXT).pack(side=tk.LEFT)
        
        right_btn_frame = tk.Frame(bottom, bg=BG_DARK)
        right_btn_frame.pack(side=tk.RIGHT)
        self.create_button(right_btn_frame, "Next: API Credentials ➔", lambda: self.save_config_and_next(3)).pack(side=tk.RIGHT)

    def load_current_config(self):
        try:
            config_py = os.path.join(PROJECT_ROOT, "core", "config.py")
            if os.path.exists(config_py):
                with open(config_py, "r", encoding="utf-8") as f:
                    content = f.read()
                loc_m = re.search(r'LOCATION\s*=\s*(\[[^\]]*\])', content)
                if loc_m:
                    val = ast.literal_eval(loc_m.group(1))
                    self.loc_var.set(", ".join(val))
                tloc_m = re.search(r'TARGET_LOCATIONS\s*=\s*(\[[^\]]*\])', content, re.DOTALL)
                if tloc_m:
                    try:
                        val = ast.literal_eval(tloc_m.group(1))
                        self.cities_var.set(", ".join(val[:4]))
                    except Exception:
                        pass
                lvl_m = re.search(r'TARGET_LEVELS\s*=\s*(\[[^\]]*\])', content, re.DOTALL)
                if lvl_m:
                    val = ast.literal_eval(lvl_m.group(1))
                    self.levels_var.set(", ".join(val[:4]))
                brief_m = re.search(r'USER_BRIEF\s*=\s*"""(.*?)"""', content, re.DOTALL)
                if not brief_m:
                    brief_m = re.search(r"USER_BRIEF\s*=\s*'''(.*?)'''", content, re.DOTALL)
                if brief_m:
                    self.brief_text_content = brief_m.group(1).strip()
            
            config_json = os.path.join(PROJECT_ROOT, "core", "config.json")
            if os.path.exists(config_json):
                with open(config_json, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                terms = cdata.get("SEARCH_TERMS", [])
                if not terms:
                    for r in cdata.get("ROLES", []):
                        terms.extend(r.get("english_terms", []))
                if terms:
                    seen = set()
                    unique = [x for x in terms if not (x in seen or seen.add(x))]
                    self.terms_var.set(", ".join(unique[:3])) # Limit display length to simple defaults
        except Exception as e:
            print("Notice loading defaults:", e)

    def save_config_and_next(self, next_screen):
        # Store brief content from text widget
        if hasattr(self, 'brief_text_widget'):
            self.brief_text_content = self.brief_text_widget.get("1.0", tk.END).strip()
        self.show_screen(next_screen)

    # ==========================
    # SCREEN 3: Credentials
    # ==========================
    def render_credentials_screen(self):
        title = tk.Label(self.container, text="Environment & API Credentials", font=("Segoe UI", 18, "bold"), fg=FG_TEXT, bg=BG_DARK, anchor="w")
        title.pack(fill=tk.X, pady=(0, 5))
        
        sub = tk.Label(self.container, text="Configure optional AI scoring and LinkedIn scraping (encrypted via Fernet).", font=("Segoe UI", 11), fg=FG_MUTED, bg=BG_DARK, anchor="w")
        sub.pack(fill=tk.X, pady=(0, 15))

        _, card = self.create_card(self.container, padx=20, pady=15)
        
        env_exists = os.path.exists(os.path.join(PROJECT_ROOT, ".env"))
        if env_exists:
            chk = tk.Checkbutton(
                card, text="A .env file already exists. Keep current credentials without overwriting.",
                variable=self.keep_env_var, bg=BG_CARD, fg=SUCCESS, selectcolor=BG_INPUT,
                activebackground=BG_CARD, activeforeground=SUCCESS, font=("Segoe UI", 10, "bold"),
                relief="flat", highlightthickness=0, command=self.toggle_env_fields
            )
            chk.pack(anchor="w", pady=(0, 15))

        self.fields_frame = tk.Frame(card, bg=BG_CARD)
        self.fields_frame.pack(fill=tk.X)

        def make_row(label_text, var, show_char=""):
            row = tk.Frame(self.fields_frame, bg=BG_CARD)
            row.pack(fill=tk.X, pady=6)
            tk.Label(row, text=label_text, font=("Segoe UI", 10, "bold"), fg=FG_TEXT, bg=BG_CARD, width=20, anchor="w").pack(side=tk.LEFT)
            border = tk.Frame(row, bg=BORDER_COL, padx=1, pady=1)
            border.pack(side=tk.LEFT, fill=tk.X, expand=True)
            entry = tk.Entry(border, textvariable=var, show=show_char, font=("Segoe UI", 11), bg=BG_INPUT, fg=FG_TEXT, insertbackground="white", relief="flat")
            entry.pack(fill=tk.X, padx=8, pady=6)
            return entry, row

        make_row("LinkedIn Email:", self.li_email_var)
        pwd_entry, pwd_row = make_row("LinkedIn Password:", self.li_pwd_var, show_char="●")
        key_entry, key_row = make_row("Gemini AI API Key:", self.gemini_key_var, show_char="●")

        def add_toggle(row, entry):
            def toggle():
                if entry.cget("show") == "":
                    entry.config(show="●")
                    btn.config(text="👁️ Show")
                else:
                    entry.config(show="")
                    btn.config(text="🔒 Hide")
            btn = tk.Button(row, text="👁️ Show", command=toggle, bg=BG_CARD, fg=FG_MUTED, font=("Segoe UI", 9), relief="flat", cursor="hand2", activebackground=BG_CARD, activeforeground=FG_TEXT, borderwidth=0)
            btn.pack(side=tk.RIGHT, padx=(8, 0))

        add_toggle(pwd_row, pwd_entry)
        add_toggle(key_row, key_entry)

        _, tip_card = self.create_card(self.container, title="🛡️ Security & Privacy Vault:", padx=15, pady=12)
        tips = (
            "• Local Encryption: Credentials are encrypted and saved only in your local .env file using a key in %APPDATA%\\JobAgent.\n"
            "• Why Gemini Key? Enables AI to read full job descriptions, filter irrelevant roles, and assign smart Match Scores.\n"
            "• Why LinkedIn? Enables scraping high-quality jobs directly. Tip: You may use a secondary 'burner' empty account!"
        )
        tk.Label(tip_card, text=tips, font=("Segoe UI", 10), fg=FG_MUTED, bg=BG_CARD, justify="left", anchor="w").pack(fill=tk.X)

        self.toggle_env_fields()

        bottom = tk.Frame(self.container, bg=BG_DARK)
        bottom.pack(fill=tk.X, side=tk.BOTTOM, pady=(15, 0))
        self.create_button(bottom, "⬅ Back to Preferences", lambda: self.show_screen(2), bg="#33334b", hover_bg="#474766", fg=FG_TEXT).pack(side=tk.LEFT)
        self.create_button(bottom, "Next: Automation & Shortcuts ➔", lambda: self.show_screen(4)).pack(side=tk.RIGHT)

    def toggle_env_fields(self):
        if hasattr(self, 'fields_frame'):
            state = "disabled" if (self.keep_env_var.get() and os.path.exists(os.path.join(PROJECT_ROOT, ".env"))) else "normal"
            for widget in self.fields_frame.winfo_children():
                for child in widget.winfo_children():
                    if isinstance(child, tk.Frame):
                        for entry in child.winfo_children():
                            if isinstance(entry, tk.Entry):
                                entry.config(state=state)

    # ==========================
    # SCREEN 4: Schedule & Shortcuts
    # ==========================
    def render_schedule_screen(self):
        title = tk.Label(self.container, text="Automation & Shortcuts", font=("Segoe UI", 18, "bold"), fg=FG_TEXT, bg=BG_DARK, anchor="w")
        title.pack(fill=tk.X, pady=(0, 5))
        
        sub = tk.Label(self.container, text="Choose when Job Agent searches for jobs silently in the background.", font=("Segoe UI", 11), fg=FG_MUTED, bg=BG_DARK, anchor="w")
        sub.pack(fill=tk.X, pady=(0, 15))

        _, sched_card = self.create_card(self.container, title="📅 Weekly Background Schedule", padx=20, pady=15)
        tk.Label(sched_card, text="Select active days for background scraping (Default: Tuesday & Friday):", font=("Segoe UI", 10), fg=FG_TEXT, bg=BG_CARD, anchor="w").pack(fill=tk.X, pady=(0, 10))
        
        days_frame = tk.Frame(sched_card, bg=BG_CARD)
        days_frame.pack(fill=tk.X, pady=5)
        
        for day, var in self.day_vars.items():
            chk = tk.Checkbutton(
                days_frame, text=day, variable=var, bg=BG_CARD, fg=FG_TEXT,
                selectcolor=BG_INPUT, activebackground=BG_CARD, activeforeground=FG_TEXT,
                font=("Segoe UI", 10, "bold"), relief="flat", highlightthickness=0
            )
            chk.pack(side=tk.LEFT, padx=(0, 12))

        time_row = tk.Frame(sched_card, bg=BG_CARD)
        time_row.pack(fill=tk.X, pady=(15, 5))
        tk.Label(time_row, text="Time to trigger search (24H format, e.g. 05:00 or 14:30):", font=("Segoe UI", 10), fg=FG_TEXT, bg=BG_CARD).pack(side=tk.LEFT, padx=(0, 10))
        
        t_border = tk.Frame(time_row, bg=BORDER_COL, padx=1, pady=1)
        t_border.pack(side=tk.LEFT)
        tk.Entry(t_border, textvariable=self.time_var, width=8, font=("Segoe UI", 11, "bold"), bg=BG_INPUT, fg=FG_TEXT, justify="center", relief="flat", insertbackground="white").pack(padx=5, pady=4)

        _, short_card = self.create_card(self.container, title="🖥️ Desktop Integration", padx=20, pady=15)
        tk.Checkbutton(
            short_card, text="Create 'Job Agent.lnk' shortcut on my Desktop for quick dashboard access",
            variable=self.shortcut_var, bg=BG_CARD, fg=FG_TEXT, selectcolor=BG_INPUT,
            activebackground=BG_CARD, activeforeground=FG_TEXT, font=("Segoe UI", 10),
            relief="flat", highlightthickness=0
        ).pack(anchor="w", pady=5)

        tk.Label(self.container, text="⚡ Everything configured! Click below to finalize setup and apply your settings.", font=("Segoe UI", 10), fg=SUCCESS, bg=BG_DARK, anchor="w").pack(fill=tk.X, pady=(15, 0))

        bottom = tk.Frame(self.container, bg=BG_DARK)
        bottom.pack(fill=tk.X, side=tk.BOTTOM, pady=(15, 0))
        self.create_button(bottom, "⬅ Back to Credentials", lambda: self.show_screen(3), bg="#33334b", hover_bg="#474766", fg=FG_TEXT).pack(side=tk.LEFT)
        self.create_button(bottom, "🚀 Finish Setup & Apply Config", lambda: self.show_screen(5), bg=ACCENT, hover_bg=ACCENT_HOV).pack(side=tk.RIGHT)

    # ==========================
    # SCREEN 5: Finalizing Setup
    # ==========================
    def render_finalize_screen(self):
        self.prog_title = tk.Label(self.container, text="Applying Settings & Finalizing...", font=("Segoe UI", 18, "bold"), fg=FG_TEXT, bg=BG_DARK, anchor="w")
        self.prog_title.pack(fill=tk.X, pady=(0, 5))
        
        self.prog_sub = tk.Label(self.container, text="Saving configurations, generating encryption keys, and registering background tasks.", font=("Segoe UI", 11), fg=FG_MUTED, bg=BG_DARK, anchor="w")
        self.prog_sub.pack(fill=tk.X, pady=(0, 15))

        self.status_label = tk.Label(self.container, text="Applying configurations...", font=("Segoe UI", 11, "bold"), fg=ACCENT, bg=BG_DARK, anchor="w")
        self.status_label.pack(fill=tk.X, pady=(0, 6))

        self.progress_bar = ModernProgressBar(self.container, width=700, height=22)
        self.progress_bar.pack(fill=tk.X, pady=(0, 15))

        _, log_card = self.create_card(self.container, title="📋 Finalization Log:", padx=10, pady=10, expand=True)
        self.log_area = scrolledtext.ScrolledText(log_card, bg=BG_INPUT, fg=FG_TEXT, insertbackground="white", font=("Consolas", 10), relief="flat", height=13, state="disabled", borderwidth=0)
        self.log_area.pack(fill=tk.BOTH, expand=True)

        self.bottom_prog = tk.Frame(self.container, bg=BG_DARK)
        self.bottom_prog.pack(fill=tk.X, side=tk.BOTTOM, pady=(15, 0))

        threading.Thread(target=self.run_finalize_setup, daemon=True).start()

    def run_finalize_setup(self):
        try:
            # Step: Apply user career configuration edits
            self.log_queue.put(("progress", 20, "Saving career profile and location configurations..."))
            self.log("Applying personalized preferences to core configurations...")
            
            config_py_path = os.path.join(PROJECT_ROOT, "core", "config.py")
            if os.path.exists(config_py_path):
                with open(config_py_path, "r", encoding="utf-8") as f:
                    cpy = f.read()
                
                locs = [l.strip() for l in self.loc_var.get().split(",") if l.strip()]
                cpy = re.sub(r'LOCATION\s*=\s*\[.*?\]', f'LOCATION = {json.dumps(locs, ensure_ascii=False)}', cpy, flags=re.DOTALL)
                
                sub_locs = [l.strip() for l in self.cities_var.get().split(",") if l.strip()]
                cpy = re.sub(r'TARGET_LOCATIONS\s*=\s*\[.*?\]', f'TARGET_LOCATIONS = {json.dumps(sub_locs, ensure_ascii=False, indent=4)}', cpy, flags=re.DOTALL)
                
                levels = [l.strip() for l in self.levels_var.get().split(",") if l.strip()]
                cpy = re.sub(r'TARGET_LEVELS\s*=\s*\[.*?\]', f'TARGET_LEVELS = {json.dumps(levels, ensure_ascii=False)}', cpy, flags=re.DOTALL)
                
                new_brief = self.brief_text_content.strip()
                if 'USER_BRIEF = """' in cpy:
                    cpy = re.sub(r'USER_BRIEF\s*=\s*""".*?"""', f'USER_BRIEF = """\n{new_brief}\n"""', cpy, flags=re.DOTALL)
                elif "USER_BRIEF = '''" in cpy:
                    cpy = re.sub(r"USER_BRIEF\s*=\s*'''.*?'''", f'USER_BRIEF = """\n{new_brief}\n"""', cpy, flags=re.DOTALL)
                
                with open(config_py_path, "w", encoding="utf-8") as f:
                    f.write(cpy)
                self.log("✓ core/config.py updated with personalized preferences.")

            config_json_path = os.path.join(PROJECT_ROOT, "core", "config.json")
            if os.path.exists(config_json_path):
                with open(config_json_path, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                terms = [t.strip() for t in self.terms_var.get().split(",") if t.strip()]
                if terms:
                    cdata["SEARCH_TERMS"] = terms
                    # Overwrite first role's search terms to ensure matching
                    if cdata.get("ROLES") and isinstance(cdata["ROLES"], list):
                        cdata["ROLES"][0]["english_terms"] = terms
                if locs:
                    cdata["LOCATION"] = locs
                if sub_locs:
                    cdata["TARGET_LOCATIONS"] = sub_locs
                if levels:
                    cdata["TARGET_LEVELS"] = levels
                with open(config_json_path, "w", encoding="utf-8") as f:
                    json.dump(cdata, f, ensure_ascii=False, indent=2)
                self.log("✓ core/config.json updated with personalized preferences.")

            # Step: Configure credentials & .env
            self.log_queue.put(("progress", 50, "Configuring encrypted environment credentials (.env)..."))
            venv_path = os.path.join(PROJECT_ROOT, "venv")
            env_path = os.path.join(PROJECT_ROOT, ".env")
            if not (self.keep_env_var.get() and os.path.exists(env_path)):
                self.log("Encrypting credentials and storing secret key...")
                venv_py = os.path.join(venv_path, "Scripts", "python.exe")
                encrypt_script = """
import sys, os, json
from cryptography.fernet import Fernet
try:
    data = json.loads(sys.stdin.read())
    key = Fernet.generate_key()
    fernet = Fernet(key)
    appdata = os.getenv('APPDATA') or os.path.expanduser('~')
    key_dir = os.path.join(appdata, 'JobAgent')
    os.makedirs(key_dir, exist_ok=True)
    key_path = os.path.join(key_dir, 'secret.key')
    with open(key_path, 'wb') as f:
        f.write(key)
    li_email = data.get('li_email', '').strip()
    li_password = data.get('li_pwd', '').strip()
    gemini_key = data.get('gemini_key', '').strip()
    enc_email = fernet.encrypt(li_email.encode()).decode() if li_email else ""
    enc_pwd = fernet.encrypt(li_password.encode()).decode() if li_password else ""
    enc_gem = fernet.encrypt(gemini_key.encode()).decode() if gemini_key else ""
    with open(os.path.join(data['root'], '.env'), 'w', encoding='utf-8') as f:
        f.write(f'LINKEDIN_EMAIL="{enc_email}"\\n')
        f.write(f'LINKEDIN_PASSWORD="{enc_pwd}"\\n')
        f.write(f'GEMINI_API_KEY="{enc_gem}"\\n')
    print("SUCCESS: Credentials encrypted and saved to .env")
except Exception as e:
    print(f"ERROR: {e}")
"""
                payload = json.dumps({
                    'li_email': self.li_email_var.get(),
                    'li_pwd': self.li_pwd_var.get(),
                    'gemini_key': self.gemini_key_var.get(),
                    'root': PROJECT_ROOT
                })
                res = subprocess.run([venv_py, "-c", encrypt_script], input=payload, capture_output=True, text=True, cwd=PROJECT_ROOT, creationflags=CREATE_NO_WINDOW)
                if res.stdout: self.log("✓ " + res.stdout.strip())
                if res.stderr: self.log(res.stderr.strip())
            else:
                self.log("Keeping existing .env file.")

            # Step: Schedule Windows Task
            self.log_queue.put(("progress", 80, "Registering Windows Scheduled Task..."))
            selected_days = [day for day, var in self.day_vars.items() if var.get()]
            days_str = ",".join(selected_days) if selected_days else "TUE,FRI"
            time_str = self.time_var.get().strip() or "05:00"
            vbs_path = os.path.join(PROJECT_ROOT, "scripts", "run_silent.vbs")
            
            self.log(f"Configuring weekly task for {days_str} at {time_str}...")
            sch_cmd = [
                "schtasks", "/create", "/tn", "Weekly Job Agent",
                "/tr", f'wscript.exe "{vbs_path}"',
                "/sc", "weekly", "/d", days_str, "/st", time_str,
                "/ru", os.getenv("USERNAME", "System"), "/rl", "HIGHEST", "/f"
            ]
            res = subprocess.run(sch_cmd, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
            if res.returncode != 0:
                sch_cmd_no_admin = [
                    "schtasks", "/create", "/tn", "Weekly Job Agent",
                    "/tr", f'wscript.exe "{vbs_path}"',
                    "/sc", "weekly", "/d", days_str, "/st", time_str, "/f"
                ]
                res2 = subprocess.run(sch_cmd_no_admin, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
                if res2.returncode == 0:
                    self.log(f"✓ Task scheduled ({days_str} at {time_str}).")
                else:
                    self.log(f"Task notice: {res2.stderr or res.stderr}")
            else:
                self.log(f"✓ Task scheduled with high privileges ({days_str} at {time_str}).")

            # Step: Desktop Shortcut
            self.log_queue.put(("progress", 95, "Creating Desktop Shortcut..."))
            if self.shortcut_var.get():
                target = os.path.join(PROJECT_ROOT, "Job_Agent.bat").replace("/", "\\")
                icon = os.path.join(PROJECT_ROOT, "logo.ico").replace("/", "\\")
                work_dir = PROJECT_ROOT.replace("/", "\\")
                ps_cmd = (
                    f"$wshell = New-Object -ComObject WScript.Shell; "
                    f"$desktop = $wshell.SpecialFolders.Item('Desktop'); "
                    f"$shortcut = $wshell.CreateShortcut(\"$desktop\\Job Agent.lnk\"); "
                    f"$shortcut.TargetPath = '{target}'; "
                    f"$shortcut.WorkingDirectory = '{work_dir}'; "
                    f"$shortcut.IconLocation = '{icon}'; "
                    f"$shortcut.Save()"
                )
                res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
                if res.returncode == 0:
                    self.log("✓ Desktop shortcut 'Job Agent.lnk' created.")
                else:
                    self.log(f"Notice: Shortcut creation failed: {res.stderr or res.stdout}")

            # Step: Initial First-Run Job Search
            self.log_queue.put(("progress", 98, "Starting initial background job search..."))
            self.log("Starting initial automatic job search...")
            try:
                venv_py = os.path.join(PROJECT_ROOT, "venv", "Scripts", "python.exe")
                if not os.path.exists(venv_py):
                    venv_py = sys.executable
                job_agent_script = os.path.join(PROJECT_ROOT, "job_agent.py")
                if os.path.exists(job_agent_script) and os.path.exists(venv_py):
                    subprocess.Popen([venv_py, job_agent_script], cwd=PROJECT_ROOT, creationflags=CREATE_NO_WINDOW)
                    self.log("✓ First-run job search started automatically in background.")
            except Exception as e:
                self.log(f"Notice: Could not auto-start initial scan: {e}")

            self.log("=========================================")
            self.log("🎉 All setup tasks completed successfully!")
            self.log_queue.put(("progress", 100, "Setup Complete!"))
            self.log_queue.put(("final_done",))

        except Exception as e:
            self.log(f"\nCRITICAL ERROR: {str(e)}")
            self.log_queue.put(("error", str(e)))

    def log(self, message):
        self.log_queue.put(("log", message + "\n"))

    def process_queue(self):
        while not self.log_queue.empty():
            try:
                item = self.log_queue.get_nowait()
                msg_type = item[0]
                
                if msg_type == "log":
                    self.log_area.config(state="normal")
                    self.log_area.insert(tk.END, item[1])
                    self.log_area.see(tk.END)
                    self.log_area.config(state="disabled")
                elif msg_type == "progress":
                    percent, text = item[1], item[2]
                    self.progress_bar.set_progress(percent)
                    self.status_label.config(text=text)
                elif msg_type == "init_done":
                    self.progress_bar.set_progress(100, color=SUCCESS)
                    self.prog_title.config(text="✓ Environment Initialized")
                    self.prog_sub.config(text="Repository and dependencies are ready. Now let's customize your job search preferences.")
                    self.status_label.config(text="✓ Initialization finished successfully!", fg=SUCCESS)
                    self.create_button(self.bottom_prog, "Next: Personalize Preferences ➔", lambda: self.show_screen(2), bg=SUCCESS, hover_bg="#059669").pack(side=tk.RIGHT)
                elif msg_type == "final_done":
                    self.progress_bar.set_progress(100, color=SUCCESS)
                    self.prog_title.config(text="🎉 Setup Complete & Initial Search Started!")
                    self.prog_sub.config(text="Your automated assistant is configured and your initial background job scan is actively running!")
                    self.status_label.config(text="✓ First job scan running right now in background!", fg=SUCCESS)
                    self.create_button(self.bottom_prog, "❌ Close", self.destroy, bg="#33334b", hover_bg="#474766", fg=FG_TEXT).pack(side=tk.LEFT)
                    self.create_button(self.bottom_prog, "🖥️ Launch Job Agent Dashboard Now", self.launch_app, bg=SUCCESS, hover_bg="#059669").pack(side=tk.RIGHT)
                    messagebox.showinfo(
                        "Initial Job Search Auto-Started!",
                        "🎉 Welcome to Job Agent!\n\nSince this is your first time setting up, your initial background job search has been started automatically based on your configured career preferences!\n\nClick 'Launch Job Agent Dashboard Now' to view your live dashboard as new matching jobs and AI scores arrive!"
                    )
                elif msg_type == "error":
                    self.progress_bar.set_progress(100, color=DANGER)
                    self.prog_title.config(text="⚠️ Setup Encountered an Issue", fg=DANGER)
                    self.status_label.config(text="Check activity log for error details.", fg=DANGER)
                    self.create_button(self.bottom_prog, "❌ Close", self.destroy, bg="#33334b", hover_bg="#474766", fg=FG_TEXT).pack(side=tk.LEFT)
            except queue.Empty:
                break
        self.after(100, self.process_queue)

    def launch_app(self):
        try:
            bat_path = os.path.join(PROJECT_ROOT, "Job_Agent.bat")
            if os.path.exists(bat_path):
                subprocess.Popen(f'start "" "{bat_path}"', shell=True, cwd=PROJECT_ROOT, creationflags=CREATE_NO_WINDOW)
            else:
                venv_pyw = os.path.join(PROJECT_ROOT, "venv", "Scripts", "pythonw.exe")
                desktop_app = os.path.join(PROJECT_ROOT, "desktop_app.pyw")
                subprocess.Popen([venv_pyw, desktop_app], cwd=PROJECT_ROOT, creationflags=CREATE_NO_WINDOW)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to launch app: {e}")
        self.destroy()

if __name__ == "__main__":
    app = SetupWizard()
    app.mainloop()
