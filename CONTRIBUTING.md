# Contributing to Job Agent

Thank you for your interest in contributing to **Job Agent**! We welcome contributions from developers, testers, designers, and documentation writers of all experience levels.

Please take a few moments to review these guidelines before getting started.

---

## 📜 Code of Conduct

This project adheres to the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating in this project, you are expected to uphold this code. Please report unacceptable behavior following the instructions in `CODE_OF_CONDUCT.md`.

---

## 🎯 How to Contribute

### 1. Explore Issues & Backlog
Check our [GitHub Issues](https://github.com/Mhmd7syn/job-agent/issues) for open tasks. Issues are categorized by **Priority** and **Difficulty**:

- **Priority Tiers**:
  - `priority: p0-critical` — Urgent blockers affecting core scraping, scoring, or applying.
  - `priority: p1-high` — High-impact features, architecture improvements, and algorithm upgrades.
  - `priority: p2-quick-wins` — Fast, non-blocking cleanups, UI simplifications, and dead-code removal.
  - `priority: p3-deferred` — Final-phase enhancements and packaging tasks.
- **Difficulty Tiers**:
  - `difficulty: low` & `good first issue` — Perfect starting points for new contributors!
  - `difficulty: low-medium` — Well-defined tasks with minor touches.
  - `difficulty: medium` — Standard tasks touching 1-2 components.
  - `difficulty: high` — Deep architectural refactoring or foundational algorithm changes.

If you find an issue you would like to work on, please comment on the issue stating your intention so we can assign it to you and avoid duplicate work.

### 2. Propose New Features or Report Bugs
- **Bug Reports**: Open an issue using the [Bug Report Template](.github/ISSUE_TEMPLATE/bug_report.yml). Include reproduction steps, environment details, and relevant log snippets.
- **Feature Requests**: Open an issue using the [Feature Request Template](.github/ISSUE_TEMPLATE/feature_request.yml). Explain the problem, your proposed solution, and affected core benefits.

---

## 💻 Development Setup

### Prerequisites
- **Python 3.9+**
- **Git**
- **Windows OS** (recommended for testing full PyWebview desktop UI and Task Scheduler features; core scoring and scraping logic can also be tested on Linux/macOS)

### Local Environment Setup
1. Fork and clone the repository:
   ```bash
   git clone https://github.com/<your-username>/job-agent.git
   cd job-agent
   ```
2. Create and activate a virtual environment:
   ```bash
   # Windows (Command Prompt)
   python -m venv venv
   venv\Scripts\activate.bat

   # Windows (PowerShell)
   python -m venv venv
   .\venv\Scripts\Activate.ps1

   # Linux / macOS
   python3 -m venv venv
   source venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```
4. Copy `.env.example` to `.env` and fill in optional API keys (e.g. Gemini API key):
   ```bash
   copy .env.example .env
   ```

---

## 🧪 Testing Guidelines

Before submitting any code, verify that existing tests pass and add unit tests covering your changes:

```bash
# Run all tests using unittest
python -m unittest discover -s tests

# Or run a specific test file
python -m unittest tests/test_age_penalty.py
```

### Engineering Standards:
- **Simplicity**: Implement clean, direct solutions. Omit speculative abstractions and unnecessary dependencies.
- **Surgical Changes**: Keep diffs focused strictly on the requested feature or fix. Remove associated dead code and unused imports when modifying features.
- **Targeted Tests**: Add unit tests for every new feature or bug fix. Avoid heavy I/O and mock external network/browser calls in unit tests.

---

## 🚀 Submitting a Pull Request (PR)

1. Create a descriptive feature branch from `main`:
   ```bash
   git checkout -b fix/apply-link-extraction
   # or
   git checkout -b feat/cover-letter-generator
   ```
2. Commit cohesive, atomic changes with clear, concise commit messages:
   ```bash
   git commit -m "fix(scrapers): resolve direct external ATS URLs in Wuzzuf"
   ```
3. Push to your fork:
   ```bash
   git push origin feat/cover-letter-generator
   ```
4. Open a Pull Request against `main` on `Mhmd7syn/job-agent`.
5. Fill in the [Pull Request Template](.github/PULL_REQUEST_TEMPLATE.md) completely, referencing the issue number (e.g. `Closes #5`).

---

## 📄 License
By contributing to Job Agent, you agree that your contributions will be licensed under the project's [MIT License](LICENSE).
