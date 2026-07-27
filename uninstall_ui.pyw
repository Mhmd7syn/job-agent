import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import os
import sys
import subprocess
import threading
import queue
import time
import shutil

# Windows creation flag to hide console window
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
DANGER_HOV = "#dc2626"

class ModernProgressBar(tk.Canvas):
    def __init__(self, parent, width=620, height=22, bg=BG_INPUT, fill_color=DANGER, **kwargs):
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

class UninstallWizard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Job Agent — Uninstall & System Cleanup")
        self.geometry("680x620")
        self.minsize(640, 560)
        self.configure(bg=BG_DARK)
        
        icon_path = os.path.join(PROJECT_ROOT, 'logo.ico')
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass
        
        self.center_window()
        
        self.log_queue = queue.Queue()
        self.current_screen = 0
        self.uninstall_completed = False
        self.protocol("WM_DELETE_WINDOW", self.exit_and_cleanup)
        
        # Checkbox selection variables
        self.remove_venv_var = tk.BooleanVar(value=True)
        self.remove_task_var = tk.BooleanVar(value=True)
        self.remove_shortcut_var = tk.BooleanVar(value=True)
        self.remove_keys_var = tk.BooleanVar(value=True)
        self.remove_data_var = tk.BooleanVar(value=True)
        self.remove_project_var = tk.BooleanVar(value=True) # Delete entire folder by default
        
        # Synchronization logic so folder deletion cannot be selected if any component is preserved
        self._updating_vars = False
        def on_component_change(*args):
            if self._updating_vars: return
            self._updating_vars = True
            all_checked = all(v.get() for v in (
                self.remove_venv_var, self.remove_task_var, self.remove_shortcut_var,
                self.remove_keys_var, self.remove_data_var, self.remove_playwright_var
            ))
            if not all_checked and self.remove_project_var.get():
                self.remove_project_var.set(False)
            elif all_checked and not self.remove_project_var.get():
                self.remove_project_var.set(True)
            self._updating_vars = False

        def on_project_change(*args):
            if self._updating_vars: return
            self._updating_vars = True
            if self.remove_project_var.get():
                for v in (self.remove_venv_var, self.remove_task_var, self.remove_shortcut_var,
                          self.remove_keys_var, self.remove_data_var, self.remove_playwright_var):
                    v.set(True)
            self._updating_vars = False

        for var in (self.remove_venv_var, self.remove_task_var, self.remove_shortcut_var,
                    self.remove_keys_var, self.remove_data_var, self.remove_playwright_var):
            var.trace_add("write", on_component_change)
        self.remove_project_var.trace_add("write", on_project_change)

        self.container = tk.Frame(self, bg=BG_DARK, padx=25, pady=20)
        self.container.pack(fill=tk.BOTH, expand=True)

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

    def create_button(self, parent, text, command, bg=ACCENT, hover_bg=ACCENT_HOV, fg="white", px=15, py=8):
        btn = tk.Button(
            parent, text=text, command=command, bg=bg, fg=fg,
            activebackground=hover_bg, activeforeground=fg,
            font=("Segoe UI", 10, "bold"), relief="flat", cursor="hand2",
            padx=px, pady=py, borderwidth=0
        )
        btn.bind("<Enter>", lambda e: btn.config(bg=hover_bg))
        btn.bind("<Leave>", lambda e: btn.config(bg=bg))
        return btn

    def create_card(self, parent, title=None, padx=18, pady=15, expand=False):
        card_border = tk.Frame(parent, bg=BORDER_COL, padx=1, pady=1)
        card_border.pack(fill=tk.BOTH, expand=expand, pady=(0, 10))
        card = tk.Frame(card_border, bg=BG_CARD, padx=padx, pady=pady)
        card.pack(fill=tk.BOTH, expand=True)
        if title:
            lbl = tk.Label(card, text=title, font=("Segoe UI", 11, "bold"), fg=FG_TEXT, bg=BG_CARD, anchor="w")
            lbl.pack(fill=tk.X, pady=(0, 10))
        return card_border, card

    def show_screen(self, index):
        self.current_screen = index
        self.clear_container()
        if index == 0:
            self.render_selection_screen()
        elif index == 1:
            self.render_progress_screen()

    def render_selection_screen(self):
        title = tk.Label(self.container, text="Uninstall & Clean Job Agent", font=("Segoe UI", 18, "bold"), fg=FG_TEXT, bg=BG_DARK, anchor="w")
        title.pack(fill=tk.X, pady=(0, 5))
        
        sub = tk.Label(self.container, text="Select which components, schedules, and environments to remove.", font=("Segoe UI", 11), fg=FG_MUTED, bg=BG_DARK, anchor="w")
        sub.pack(fill=tk.X, pady=(0, 15))

        _, card = self.create_card(self.container, title="🗑️ Select Cleanup Options:", padx=20, pady=15, expand=True)
        
        options = [
            ("Remove Python Virtual Environment (venv directory)", self.remove_venv_var),
            ("Unschedule & Delete Windows Task ('Weekly Job Agent')", self.remove_task_var),
            ("Delete Desktop Shortcut ('Job Agent.lnk')", self.remove_shortcut_var),
            ("Delete Encrypted Vault (%APPDATA%\\JobAgent\\secret.key & .env)", self.remove_keys_var),
            ("Remove Playwright Browser Profiles & Cache", self.remove_playwright_var),
            ("Clear Scraped Job Logs, CSVs & Databases (output/ folder)", self.remove_data_var)
        ]

        for label_text, var in options:
            row = tk.Frame(card, bg=BG_CARD)
            row.pack(fill=tk.X, pady=5)
            chk = tk.Checkbutton(
                row, text=label_text, variable=var, bg=BG_CARD, fg=FG_TEXT,
                selectcolor=BG_INPUT, activebackground=BG_CARD, activeforeground=FG_TEXT,
                font=("Segoe UI", 10), relief="flat", highlightthickness=0
            )
            chk.pack(anchor="w")

        # Separator before full project directory deletion
        sep = tk.Frame(card, bg=BORDER_COL, height=1)
        sep.pack(fill=tk.X, pady=8)

        row_proj = tk.Frame(card, bg=BG_CARD)
        row_proj.pack(fill=tk.X, pady=(2, 5))
        chk_proj = tk.Checkbutton(
            row_proj, text="Delete Entire Job Agent Project Folder from Disk (Requires all options above)",
            variable=self.remove_project_var, bg=BG_CARD, fg=DANGER,
            selectcolor=BG_INPUT, activebackground=BG_CARD, activeforeground=DANGER,
            font=("Segoe UI", 10, "bold"), relief="flat", highlightthickness=0
        )
        chk_proj.pack(anchor="w")

        # Note
        tk.Label(self.container, text="⚠️ This action cleanly removes background tasks and system footprints.", font=("Segoe UI", 10), fg=DANGER, bg=BG_DARK, anchor="w").pack(fill=tk.X, pady=(15, 0))

        bottom = tk.Frame(self.container, bg=BG_DARK)
        bottom.pack(fill=tk.X, side=tk.BOTTOM, pady=(15, 0))
        
        self.create_button(bottom, "Cancel", self.exit_and_cleanup, bg="#33334b", hover_bg="#474766", fg=FG_TEXT).pack(side=tk.LEFT)
        self.create_button(bottom, "🗑️ Uninstall Selected", lambda: self.show_screen(1), bg=DANGER, hover_bg=DANGER_HOV).pack(side=tk.RIGHT)

    def render_progress_screen(self):
        self.prog_title = tk.Label(self.container, text="Uninstalling Job Agent...", font=("Segoe UI", 18, "bold"), fg=FG_TEXT, bg=BG_DARK, anchor="w")
        self.prog_title.pack(fill=tk.X, pady=(0, 5))
        
        self.prog_sub = tk.Label(self.container, text="Please wait while selected components are removed.", font=("Segoe UI", 11), fg=FG_MUTED, bg=BG_DARK, anchor="w")
        self.prog_sub.pack(fill=tk.X, pady=(0, 15))

        self.status_label = tk.Label(self.container, text="Starting cleanup...", font=("Segoe UI", 11, "bold"), fg=DANGER, bg=BG_DARK, anchor="w")
        self.status_label.pack(fill=tk.X, pady=(0, 6))

        self.progress_bar = ModernProgressBar(self.container, width=620, height=22, fill_color=DANGER)
        self.progress_bar.pack(fill=tk.X, pady=(0, 15))

        _, log_card = self.create_card(self.container, title="📋 Uninstallation Log:", padx=10, pady=10, expand=True)
        self.log_area = scrolledtext.ScrolledText(log_card, bg=BG_INPUT, fg=FG_TEXT, insertbackground="white", font=("Consolas", 10), relief="flat", height=12, state="disabled", borderwidth=0)
        self.log_area.pack(fill=tk.BOTH, expand=True)

        self.bottom_prog = tk.Frame(self.container, bg=BG_DARK)
        self.bottom_prog.pack(fill=tk.X, side=tk.BOTTOM, pady=(15, 0))

        threading.Thread(target=self.run_uninstall, daemon=True).start()

    def run_uninstall(self):
        try:
            # Change CWD away from project root to prevent OS folder lock
            try:
                os.chdir(os.path.expanduser("~"))
            except Exception:
                pass

            # Task 1: Scheduled Task
            self.log_queue.put(("progress", 15, "Removing Windows Scheduled Task..."))
            if self.remove_task_var.get():
                self.log("Removing Windows Scheduled Task ('Weekly Job Agent')...")
                res = subprocess.run(["schtasks", "/delete", "/tn", "Weekly Job Agent", "/f"], capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
                if res.returncode == 0:
                    self.log("✓ Scheduled Task deleted.")
                else:
                    self.log("Notice: Scheduled Task was not found or already deleted.")
            else:
                self.log("Skipped Scheduled Task deletion.")

            # Task 2: Desktop Shortcut
            self.log_queue.put(("progress", 30, "Removing Desktop Shortcut..."))
            if self.remove_shortcut_var.get():
                shortcut_path = os.path.join(os.path.expanduser("~"), "Desktop", "Job Agent.lnk")
                self.log(f"Checking for Desktop Shortcut at: {shortcut_path}")
                if os.path.exists(shortcut_path):
                    try:
                        os.remove(shortcut_path)
                        self.log("✓ Desktop Shortcut deleted.")
                    except Exception as e:
                        self.log(f"Notice: {e}")
                else:
                    self.log("Notice: Desktop Shortcut not found.")
            else:
                self.log("Skipped Desktop Shortcut deletion.")

            # Task 3: Encryption Keys & .env
            self.log_queue.put(("progress", 45, "Removing encrypted credentials and secret vault..."))
            if self.remove_keys_var.get():
                self.log("Cleaning encrypted credentials & vault...")
                env_path = os.path.join(PROJECT_ROOT, ".env")
                if os.path.exists(env_path):
                    try:
                        os.remove(env_path)
                        self.log("✓ Local .env credentials file removed.")
                    except Exception as e:
                        self.log(f"Notice: {e}")
                
                appdata = os.getenv("APPDATA") or os.path.expanduser("~")
                vault_dir = os.path.join(appdata, "JobAgent")
                if os.path.exists(vault_dir):
                    try:
                        shutil.rmtree(vault_dir, ignore_errors=True)
                        self.log(f"✓ Encryption vault ({vault_dir}) deleted.")
                    except Exception as e:
                        self.log(f"Notice: {e}")
            else:
                self.log("Skipped encryption key & .env removal.")

            # Task 4: Playwright profiles
            self.log_queue.put(("progress", 60, "Cleaning Playwright browser profiles..."))
            if self.remove_playwright_var.get():
                pw_dir = os.path.join(PROJECT_ROOT, "playwright_profile")
                if os.path.exists(pw_dir):
                    self.log("Removing Playwright browser profiles and cache...")
                    shutil.rmtree(pw_dir, ignore_errors=True)
                    self.log("✓ Playwright profile folder removed.")
            else:
                self.log("Skipped Playwright profile removal.")

            # Task 5: Data & Logs
            self.log_queue.put(("progress", 75, "Cleaning scraped job output & databases..."))
            if self.remove_data_var.get():
                out_dir = os.path.join(PROJECT_ROOT, "output")
                if os.path.exists(out_dir):
                    self.log("Cleaning output logs, CSVs, and databases...")
                    for item in os.listdir(out_dir):
                        path = os.path.join(out_dir, item)
                        if os.path.isdir(path):
                            shutil.rmtree(path, ignore_errors=True)
                        else:
                            try: os.remove(path)
                            except Exception: pass
                    self.log("✓ Output directory cleared.")
            else:
                self.log("Skipped scraped data and logs cleanup.")

            # Task 6: Virtual Environment
            self.log_queue.put(("progress", 90, "Removing Python Virtual Environment (venv)..."))
            if self.remove_venv_var.get():
                venv_dir = os.path.join(PROJECT_ROOT, "venv")
                if os.path.exists(venv_dir):
                    self.log("Deleting Python virtual environment folder (this may take a few seconds)...")
                    shutil.rmtree(venv_dir, ignore_errors=True)
                    self.log("✓ Virtual environment removed.")
            else:
                self.log("Skipped venv folder deletion.")

            # Task 7: Project Folder Deletion Preparation
            self.log_queue.put(("progress", 95, "Preparing folder removal..."))
            if self.remove_project_var.get():
                self.log(f"Configuring complete removal of project directory:\n -> {PROJECT_ROOT}")
                self.log("⚠️ Folder will be permanently deleted from disk upon closing this window.")
            else:
                self.log("Skipped entire folder removal (project files preserved).")

            self.log("=========================================")
            self.log("🎉 Uninstallation and cleanup completed successfully.")
            self.log_queue.put(("progress", 100, "Uninstallation Completed!"))
            self.log_queue.put(("done",))

        except Exception as e:
            self.log(f"\nCRITICAL ERROR DURING UNINSTALL: {str(e)}")
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
                    self.progress_bar.set_progress(item[1])
                    self.status_label.config(text=item[2])
                elif msg_type == "done":
                    self.uninstall_completed = True
                    self.progress_bar.set_progress(100, color=SUCCESS)
                    self.prog_title.config(text="✅ Cleanup Completed")
                    if self.remove_project_var.get():
                        self.prog_sub.config(text="All components cleaned. Folder will be completely deleted upon closing.")
                    else:
                        self.prog_sub.config(text="Selected Job Agent components have been removed from your system.")
                    self.status_label.config(text="✓ Selected items cleanly removed!", fg=SUCCESS)
                    btn_text = "Close & Delete Folder" if self.remove_project_var.get() else "Close Uninstaller"
                    self.create_button(self.bottom_prog, btn_text, self.exit_and_cleanup, bg=SUCCESS, hover_bg="#059669").pack(side=tk.RIGHT)
                elif msg_type == "error":
                    self.progress_bar.set_progress(100, color=DANGER)
                    self.prog_title.config(text="⚠️ Error Encountered", fg=DANGER)
                    self.status_label.config(text="Check log above for error details.", fg=DANGER)
                    self.create_button(self.bottom_prog, "Close", self.exit_and_cleanup, bg="#33334b", hover_bg="#474766", fg=FG_TEXT).pack(side=tk.RIGHT)
            except queue.Empty:
                break
        self.after(100, self.process_queue)

    def exit_and_cleanup(self):
        if getattr(self, 'uninstall_completed', False) and self.remove_project_var.get():
            try:
                home_dir = os.path.expanduser("~")
                try:
                    os.chdir(home_dir)
                except Exception:
                    pass
                
                ps_script = (
                    f"Start-Sleep -Seconds 2; "
                    f"for ($i=0; $i -lt 5; $i++) {{ "
                    f"    if (-not (Test-Path -LiteralPath '{PROJECT_ROOT}')) {{ break }}; "
                    f"    Remove-Item -LiteralPath '{PROJECT_ROOT}' -Recurse -Force -ErrorAction SilentlyContinue; "
                    f"    cmd.exe /c 'rmdir /s /q \"{PROJECT_ROOT}\" 2>nul'; "
                    f"    Start-Sleep -Seconds 1; "
                    f"}}"
                )
                subprocess.Popen(
                    ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_script],
                    cwd=home_dir,
                    creationflags=CREATE_NO_WINDOW | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
                )
            except Exception as e:
                print(f"Error launching folder deletion script: {e}")
        try:
            self.destroy()
        except Exception:
            pass
        sys.exit(0)

if __name__ == "__main__":
    app = UninstallWizard()
    app.mainloop()
