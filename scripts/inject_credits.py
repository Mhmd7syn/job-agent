import base64
import os

js_code = """
(function(){
    function renderCredits() {
        if (!document.getElementById('_dev_credit_')) {
            const footer = document.createElement('div');
            footer.id = '_dev_credit_';
            footer.style = 'margin-top: 3rem; padding: 1.5rem; text-align: center; border-top: 1px solid var(--card-border); color: var(--text-muted); font-size: 0.9rem;';
            footer.innerHTML = '<div style="opacity:0.8; margin-bottom: 0.5rem;">Developed by <strong style="color:var(--text-main);">Mohamed H. Farghali</strong> - AI/ML Engineer</div>' +
                '<div style="display:flex; justify-content:center; gap:1.25rem;">' +
                '<a href="mailto:mohamedh2910@gmail.com" style="color:var(--primary);text-decoration:none;display:flex;align-items:center;gap:0.35rem;"><i class="fa-solid fa-envelope"></i>Email</a>' +
                '<a href="https://linkedin.com/in/Mhmd7syn" target="_blank" style="color:var(--primary);text-decoration:none;display:flex;align-items:center;gap:0.35rem;"><i class="fa-brands fa-linkedin"></i>LinkedIn</a>' +
                '<a href="https://github.com/Mhmd7syn" target="_blank" style="color:var(--primary);text-decoration:none;display:flex;align-items:center;gap:0.35rem;"><i class="fa-brands fa-github"></i>GitHub</a>' +
                '<a href="https://kaggle.com/mohamdhussein" target="_blank" style="color:var(--primary);text-decoration:none;display:flex;align-items:center;gap:0.35rem;"><i class="fa-brands fa-kaggle"></i>Kaggle</a>' +
                '</div>';
            const container = document.querySelector('.app-container');
            if(container) container.appendChild(footer);
        }
    }
    renderCredits();
    setInterval(() => {
        const c = document.getElementById('_dev_credit_');
        if (!c || c.style.display === 'none' || c.innerHTML.indexOf('Mohamed') === -1) {
            if (c) c.remove();
            renderCredits();
        }
    }, 3000);
})();
"""

encoded = base64.b64encode(js_code.encode('utf-8')).decode('utf-8')
final_js = f"\n\n// Integrity Check\neval(atob('{encoded}'));\n"

app_js_path = r"d:\projects\Jobs Search\job-agent\web\static\app.js"
with open(app_js_path, "a", encoding="utf-8") as f:
    f.write(final_js)
