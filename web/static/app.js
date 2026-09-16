let allJobs = [];
let currentConfig = {};
let currentJobsPage = 1;
const JOBS_PER_PAGE = 30;
let filteredJobsList = [];

function escapeHtml(text) {
    if (!text) return '';
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

document.addEventListener('DOMContentLoaded', () => {
    fetchJobs();
    fetchConfig();
    checkPendingUpdates();
    pollScraper();
    
    document.getElementById('search-input').addEventListener('input', applyFiltersAndSort);
    document.getElementById('show-not-related').addEventListener('change', applyFiltersAndSort);
    document.getElementById('applied-filter').addEventListener('change', applyFiltersAndSort);
    document.getElementById('role-filter').addEventListener('change', applyFiltersAndSort);
    document.getElementById('type-filter').addEventListener('change', applyFiltersAndSort);
    document.getElementById('setup-filter').addEventListener('change', applyFiltersAndSort);
    document.getElementById('site-filter').addEventListener('change', applyFiltersAndSort);
    document.getElementById('sort-filter').addEventListener('change', applyFiltersAndSort);

    // Global keyboard shortcuts for pywebview desktop window (F5 or Ctrl+R / Cmd+R, Esc)
    window.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            hideJobTextModal();
        }
        if (e.key === 'F5' || ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'r')) {
            e.preventDefault();
            refreshDashboard();
        }
    });

    // Sync queued mobile jobs on GUI launch or refresh
    setTimeout(() => syncTelegramJobsOnLaunch(false), 600);
});

async function refreshDashboard() {
    const refreshIcon = document.getElementById('refresh-icon');
    const refreshBtn = document.getElementById('refresh-btn');
    if (refreshIcon) refreshIcon.classList.add('fa-spin');
    if (refreshBtn) refreshBtn.disabled = true;

    try {
        const addedNewJobs = await syncTelegramJobsOnLaunch(true);
        await fetchJobs();
        await checkPendingUpdates();
        if (!addedNewJobs) {
            showToast('Dashboard refreshed!', 'info', 'fa-arrows-rotate', 2000);
        }
    } catch (err) {
        console.error('Refresh error:', err);
        showToast('Refresh failed', 'danger', 'fa-triangle-exclamation');
    } finally {
        if (refreshIcon) refreshIcon.classList.remove('fa-spin');
        if (refreshBtn) refreshBtn.disabled = false;
    }
}

async function syncTelegramJobsOnLaunch(isManual = false) {
    try {
        const res = await fetch('/api/telegram/sync');
        if (!res.ok) return false;
        const data = await res.json();
        if (data && data.count > 0) {
            const jobWord = data.count === 1 ? 'job' : 'jobs';
            showToast(`📥 ${data.count} new ${jobWord} added by Telegram bot!`, 'success', 'fa-paper-plane', 6000);
            fetchJobs(); // Refresh grid and update job count!
            return true;
        }
    } catch (e) {
        // Silent on launch
    }
    return false;
}

async function fetchJobs() {
    const loader = document.getElementById('loader');
    const emptyState = document.getElementById('empty-state');

    try {
        const response = await fetch('/api/jobs');
        const data = await response.json();
        
        loader.classList.add('hidden');
        
        if (!data.jobs || data.jobs.length === 0) {
            emptyState.classList.remove('hidden');
            document.getElementById('job-count').innerText = '0';
            return;
        }

        allJobs = data.jobs;
        applyFiltersAndSort();
        
    } catch (error) {
        console.error('Error fetching jobs:', error);
        showToast('Failed to load jobs', 'danger', 'fa-circle-xmark');
    }
}

function applyFiltersAndSort() {
    const searchTerm = document.getElementById('search-input').value.toLowerCase();
    const showNotRelated = document.getElementById('show-not-related').checked;
    const appliedFilter = document.getElementById('applied-filter').value;
    const roleFilter = document.getElementById('role-filter').value;
    const typeFilter = document.getElementById('type-filter').value;
    const setupFilter = document.getElementById('setup-filter').value;
    const siteFilter = document.getElementById('site-filter').value;
    const sortFilter = document.getElementById('sort-filter').value;

    let filtered = allJobs.filter(job => {
        const titleMatch = (job.title || '').toLowerCase().includes(searchTerm);
        const companyMatch = (job.company || '').toLowerCase().includes(searchTerm);
        const descMatch = (job.description || '').toLowerCase().includes(searchTerm);
        if (searchTerm && !titleMatch && !companyMatch && !descMatch) return false;

        // If not showing not_related, filter them out
        if (!showNotRelated) {
            if (job.status === 'not_related') return false;
        }

        // Never display pending jobs with score <= 0 unless scholarship or applied
        const isScholarship = (job.job_type || '').toLowerCase() === 'scholarship';
        const isApplied = job.is_applied === 1;
        if (job.status === 'pending' && !isScholarship && !isApplied && (job.relevance_score || 0) <= 0) {
            return false;
        }

        if (appliedFilter === 'applied' && job.is_applied !== 1) return false;
        if (appliedFilter === 'not_applied' && job.is_applied === 1) return false;

        if (roleFilter !== 'all') {
            const roleConfig = currentConfig.ROLES.find(r => r.title === roleFilter);
            if (roleConfig) {
                const t = (job.title || '').toLowerCase();
                const terms = [...(roleConfig.english_terms || []), ...(roleConfig.arabic_terms || [])]
                                .map(term => term.toLowerCase());
                
                if (terms.length > 0) {
                    const matches = terms.some(term => t.includes(term));
                    if (!matches) return false;
                }
            }
        }

        if (typeFilter !== 'all') {
            const t = (job.job_type || '').toLowerCase();
            if (!t.includes(typeFilter.toLowerCase())) return false;
        }

        if (setupFilter !== 'all') {
            const loc = (job.location || '').toLowerCase();
            const title = (job.title || '').toLowerCase();
            const isRemote = loc.includes('remote') || title.includes('remote') || loc.includes('work from home');
            const isHybrid = loc.includes('hybrid') || title.includes('hybrid');
            
            if (setupFilter === 'remote' && !isRemote) return false;
            if (setupFilter === 'hybrid' && !isHybrid) return false;
            if (setupFilter === 'onsite' && (isRemote || isHybrid)) return false;
        }

        if (siteFilter !== 'all') {
            const s = (job.site || '').toLowerCase();
            if (s !== siteFilter.toLowerCase()) return false;
        }

        return true;
    });

    filtered.sort((a, b) => {
        // Liked jobs at the top always
        if (a.status === 'liked' && b.status !== 'liked') return -1;
        if (b.status === 'liked' && a.status !== 'liked') return 1;

        if (sortFilter === 'score') {
            const scoreDiff = (b.relevance_score || 0) - (a.relevance_score || 0);
            if (scoreDiff !== 0) return scoreDiff;
            return new Date(b.date_posted || 0) - new Date(a.date_posted || 0);
        } else if (sortFilter === 'date_new') {
            return new Date(b.date_posted || 0) - new Date(a.date_posted || 0);
        } else if (sortFilter === 'date_old') {
            return new Date(a.date_posted || 0) - new Date(b.date_posted || 0);
        }
        return 0;
    });

    filteredJobsList = filtered;
    currentJobsPage = 1;
    renderJobs(filteredJobsList);
}

function updateShowMoreButton() {
    const btn = document.getElementById('show-more-btn');
    if (btn) {
        if (currentJobsPage * JOBS_PER_PAGE < filteredJobsList.length) {
            btn.classList.remove('hidden');
        } else {
            btn.classList.add('hidden');
        }
    }
}

function loadMoreJobs() {
    currentJobsPage++;
    const jobsToAppend = filteredJobsList.slice((currentJobsPage - 1) * JOBS_PER_PAGE, currentJobsPage * JOBS_PER_PAGE);
    const jobsGrid = document.getElementById('jobs-grid');
    
    jobsToAppend.forEach(job => {
        const card = createJobCard(job);
        jobsGrid.appendChild(card);
    });
    
    updateShowMoreButton();
}

function renderJobs(jobsList) {
    const jobsGrid = document.getElementById('jobs-grid');
    const emptyState = document.getElementById('empty-state');
    const jobCountSpan = document.getElementById('job-count');

    jobsGrid.innerHTML = '';
    jobCountSpan.innerText = jobsList.length;

    if (jobsList.length === 0) {
        jobsGrid.classList.add('hidden');
        emptyState.classList.remove('hidden');
        updateShowMoreButton();
    } else {
        emptyState.classList.add('hidden');
        jobsGrid.classList.remove('hidden');
        
        const jobsToShow = jobsList.slice(0, JOBS_PER_PAGE);
        jobsToShow.forEach(job => {
            const card = createJobCard(job);
            jobsGrid.appendChild(card);
        });
        
        updateShowMoreButton();
    }
}

function createJobCard(job) {
    const div = document.createElement('div');
    div.className = `job-card ${job.status === 'liked' ? 'liked-bg' : ''}`;
    div.id = `job-${job.job_id}`;

    // Format Date
    let dateStr = 'Unknown Date';
    if (job.date_posted && job.date_posted !== 'nan') {
        const dateObj = new Date(job.date_posted);
        if (!isNaN(dateObj)) {
            dateStr = dateObj.toLocaleDateString('en-US', { day: 'numeric', month: 'short', year: 'numeric' });
        } else {
            dateStr = job.date_posted;
        }
    }

    let isApplied = job.is_applied === 1;

    let applyBtnHtml = isApplied ?
        `<button class="btn btn-apply" onclick="toggleApplied('${job.job_id}')" style="background-color: var(--success);"><i class="fa-solid fa-check"></i>Applied</button>` :
        `<button class="btn btn-apply" onclick="toggleApplied('${job.job_id}')"><i class="fa-solid fa-check"></i>Mark Applied</button>`;

    const hasLink = Boolean(job.job_url && String(job.job_url).trim() && job.job_url !== 'nan' && (String(job.job_url).startsWith('http://') || String(job.job_url).startsWith('https://')));

    const viewBtnHtml = hasLink ?
        `<a href="${job.job_url}" target="_blank" class="btn btn-view"><i class="fa-solid fa-arrow-up-right-from-square"></i>View Job</a>` :
        `<button type="button" class="btn btn-view btn-view-text" onclick="openJobTextModal('${job.job_id}')" title="View the job post text you added"><i class="fa-solid fa-file-lines"></i>View Post Text</button>`;

    let actionsHtml = '';
    if (job.status === 'not_related') {
        actionsHtml = `
            <div style="flex-grow: 1; display: flex; align-items: center; color: var(--danger); font-weight: 500; cursor: pointer; transition: opacity 0.2s;" onclick="handleAction('${job.job_id}', 'pending')" title="Click to undo and move back to Pending" onmouseover="this.style.opacity=0.7" onmouseout="this.style.opacity=1">
                <i class="fa-solid fa-circle-xmark" style="margin-right: 6px;"></i>Not Related (Click to Undo)
            </div>
            ${applyBtnHtml}
            ${viewBtnHtml}
        `;
    } else {
        actionsHtml = `
            ${job.status !== 'liked' ? 
                `<button class="btn btn-like" onclick="handleAction('${job.job_id}', 'liked')"><i class="fa-regular fa-heart"></i>Like</button>` : 
                `<button class="btn btn-like" disabled style="opacity: 0.5"><i class="fa-solid fa-heart"></i>Liked</button>`
            }
            <button class="btn btn-reject" onclick="handleAction('${job.job_id}', 'not_related')"><i class="fa-solid fa-xmark"></i>Not Related</button>
            ${applyBtnHtml}
            ${viewBtnHtml}
        `;
    }

    const isScholarship = (job.job_type || '').toLowerCase() === 'scholarship';
    const typeTagIcon = isScholarship ? 'fa-solid fa-graduation-cap' : 'fa-solid fa-clock';
    const typeTagClass = isScholarship ? 'tag tag-scholarship' : 'tag';

    const siteTagHtml = hasLink ?
        `<div class="tag"><i class="fa-solid fa-globe"></i>${job.site || 'Web'}</div>` :
        `<div class="tag tag-manual" title="Added manually by you (not scraped from job boards)"><i class="fa-solid fa-user-pen"></i>Added by Me</div>`;

    const jobTextSnippet = (!hasLink && job.description) ? `
        <div class="manual-job-banner">
            <div class="manual-job-header">
                <span><i class="fa-solid fa-file-lines" style="color: var(--primary); margin-right: 5px;"></i><strong>Job Post Text:</strong></span>
                <button type="button" class="btn-copy-mini" onclick="event.stopPropagation(); copyJobTextById('${job.job_id}')" title="Copy text"><i class="fa-regular fa-copy"></i> Copy</button>
            </div>
            <div class="manual-job-body">${escapeHtml(job.description)}</div>
        </div>
    ` : '';

    div.innerHTML = `
        <div class="card-header">
            <h3 class="job-title" title="${job.title}">${job.title}</h3>
            <div style="display: flex; align-items: center; gap: 0.5rem; flex-shrink: 0;">
                <span class="job-score" title="Relevance Score"><i class="fa-solid fa-star" style="color:var(--warning); margin-right:4px;"></i>${Math.round(job.relevance_score || 0)}</span>
                <button class="btn btn-delete" onclick="deleteSingleJob('${job.job_id}')" title="Delete Job Permanently" style="padding: 0.35rem 0.6rem; font-size: 0.8rem; border-radius: 0.4rem;">
                    <i class="fa-solid fa-trash-can"></i>
                </button>
            </div>
        </div>
        <div class="job-company"><i class="fa-regular fa-building" style="margin-right:6px;"></i>${job.company || 'Unknown Company'}</div>
        
        <div class="tags">
            <div class="tag"><i class="fa-solid fa-location-dot"></i>${job.location || 'Remote'}</div>
            <div class="${typeTagClass}"><i class="${typeTagIcon}"></i>${job.job_type || 'Full-time'}</div>
            ${siteTagHtml}
        </div>

        ${jobTextSnippet}
        
        <div class="job-date"><i class="fa-regular fa-calendar" style="margin-right:6px;"></i>${dateStr}</div>
        
        <div class="card-actions">
            ${actionsHtml}
        </div>
    `;

    return div;
}

async function handleAction(jobId, action) {
    const card = document.getElementById(`job-${jobId}`);
    
    // Optimistic UI update
    if (action === 'liked') {
        card.classList.add('liked-bg');
        // Replace Like button with Liked
        const likeBtn = card.querySelector('.btn-like');
        likeBtn.innerHTML = '<i class="fa-solid fa-heart"></i>Liked';
        likeBtn.disabled = true;
        likeBtn.style.opacity = '0.5';
        showToast('Job marked as liked!', 'liked', 'fa-heart');
    } else {
        // Animate out
        card.style.animation = 'fadeOut 0.3s ease forwards';
        setTimeout(() => {
            card.remove();
            updateJobCount();
        }, 300);
        
        if (action === 'applied') {
            showToast('Awesome! Marked as applied.', 'success', 'fa-check-circle');
        } else if (action === 'not_related') {
            showToast('Job removed.', 'danger', 'fa-trash-can');
        } else if (action === 'pending') {
            showToast('Job restored to pending.', 'success', 'fa-rotate-left');
        }
    }

    // Update global state
    const jobIndex = allJobs.findIndex(j => j.job_id === jobId);
    if (jobIndex > -1) {
        allJobs[jobIndex].status = action;
    }

    // AI notification
    showToast('AI is updating config in background...', 'success', 'fa-robot', 2000);

    try {
        await fetch(`/api/jobs/${encodeURIComponent(jobId)}/${action}`, { method: 'POST' });
    } catch (error) {
        console.error('Error updating job:', error);
        showToast('Failed to update job status.', 'danger', 'fa-circle-xmark');
    }
}

function updateJobCount() {
    const currentCount = document.querySelectorAll('.job-card').length;
    document.getElementById('job-count').innerText = currentCount;
    
    if (currentCount === 0) {
        document.getElementById('empty-state').classList.remove('hidden');
        document.getElementById('jobs-grid').classList.add('hidden');
    }
}

function showToast(message, type = 'success', icon = 'fa-check-circle', duration = 3000) {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    
    toast.innerHTML = `
        <i class="fa-solid ${icon}"></i>
        <span>${message}</span>
    `;
    
    container.appendChild(toast);
    
    setTimeout(() => {
        toast.style.animation = 'slideOut 0.3s cubic-bezier(0.16, 1, 0.3, 1) forwards';
        setTimeout(() => {
            toast.remove();
        }, 300);
    }, duration);
}

async function toggleApplied(jobId) {
    try {
        const response = await fetch(`/api/jobs/${jobId}/apply`, { method: 'POST' });
        const result = await response.json();
        if (result.status === 'success') {
            const jobIndex = allJobs.findIndex(j => j.job_id === jobId);
            if (jobIndex > -1) {
                allJobs[jobIndex].is_applied = result.is_applied;
                const appliedFilter = document.getElementById('applied-filter').value;
                if ((appliedFilter === 'applied' && result.is_applied !== 1) || 
                    (appliedFilter === 'not_applied' && result.is_applied === 1)) {
                    const card = document.getElementById(`job-${jobId}`);
                    if (card) {
                        card.style.transform = 'scale(0.95)';
                        card.style.opacity = '0';
                        setTimeout(() => {
                            card.style.height = '0';
                            card.style.margin = '0';
                            card.style.padding = '0';
                            card.style.overflow = 'hidden';
                            setTimeout(() => applyFiltersAndSort(), 300);
                        }, 200);
                    } else {
                        applyFiltersAndSort();
                    }
                } else {
                    applyFiltersAndSort();
                }
                showToast(result.is_applied ? 'Marked as Applied!' : 'Unmarked as Applied.', 'success', 'fa-check');
            }
        }
    } catch (e) {
        showToast('Error updating status.', 'danger', 'fa-xmark');
    }
}

async function showSystemStatus() {
    const modal = document.getElementById('status-modal');
    modal.classList.remove('hidden');
    
    const evalText = document.getElementById('eval-text');
    const logText = document.getElementById('log-text');
    
    evalText.innerHTML = 'Fetching evaluation...';
    logText.innerText = 'Fetching logs...';
    
    try {
        const response = await fetch('/api/status');
        const data = await response.json();
        
        if (data.evaluation) {
            let cleanEval = data.evaluation.replace(/^={5,}\s*(.*?)\s*={5,}$/gm, '### $1').replace(/={10,}/g, '---');
            evalText.innerHTML = typeof marked !== 'undefined' ? marked.parse(cleanEval) : cleanEval.replace(/\n/g, '<br>');
        } else {
            evalText.innerHTML = 'No evaluation available yet.';
        }
        logText.innerText = data.logs || 'No logs available.';
    } catch (error) {
        console.error('Error fetching status:', error);
        document.getElementById('eval-text').innerHTML = "Failed to load status.";
        document.getElementById('log-text').innerText = "Failed to load logs.";
    }
}

async function fetchConfig() {
    try {
        const response = await fetch('/api/config');
        currentConfig = await response.json();
        
        const lastReviewed = new Date(currentConfig.last_reviewed_date || new Date());
        const now = new Date();
        const diffTime = Math.abs(now - lastReviewed);
        const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
        
        if (diffDays > 90) {
            document.getElementById('settings-warning').classList.remove('hidden');
        } else {
            document.getElementById('settings-warning').classList.add('hidden');
        }

        // Dynamically populate role-filter
        const roleFilterEl = document.getElementById('role-filter');
        if (roleFilterEl) {
            const currentRoleFilter = roleFilterEl.value;
            roleFilterEl.innerHTML = '<option value="all">All Roles</option>';
            if (currentConfig.ROLES) {
                currentConfig.ROLES.forEach(role => {
                    const opt = document.createElement('option');
                    opt.value = role.title;
                    opt.textContent = role.title;
                    roleFilterEl.appendChild(opt);
                });
            }
            if (Array.from(roleFilterEl.options).some(o => o.value === currentRoleFilter)) {
                roleFilterEl.value = currentRoleFilter;
            } else {
                roleFilterEl.value = 'all';
            }
        }

        const settingsModal = document.getElementById('settings-modal');
        if (settingsModal && !settingsModal.classList.contains('hidden')) {
            refreshSettingsUI();
        }

    } catch (e) {
        console.error("Failed to load config", e);
    }
}

async function handleCVUpload(files) {
    if (!files || files.length === 0) return;
    const file = files[0];
    const formData = new FormData();
    formData.append('file', file);

    const btnIcon = document.getElementById('cv-btn-icon');
    const btnSpinner = document.getElementById('cv-btn-spinner');
    const btnText = document.getElementById('cv-btn-text');

    if (btnIcon) btnIcon.classList.add('hidden');
    if (btnSpinner) btnSpinner.classList.remove('hidden');
    if (btnText) btnText.textContent = "AI Analysing Resume...";

    try {
        const res = await fetch('/api/parse-cv', {
            method: 'POST',
            body: formData
        });
        const data = await res.json();
        
        if (data.status === 'success' || !data.error) {
            showToast('CV Analyzed Successfully! Generated proposals for your review.', 'success', 'fa-check');
            await checkPendingUpdates();
            openProposalsModal();
        } else {
            showToast('Error analyzing CV: ' + (data.error || 'Unknown error'), 'danger', 'fa-xmark');
        }
    } catch (e) {
        showToast('Upload failed: ' + e.message, 'danger', 'fa-xmark');
    } finally {
        if (btnIcon) btnIcon.classList.remove('hidden');
        if (btnSpinner) btnSpinner.classList.add('hidden');
        if (btnText) btnText.textContent = "Import Skills & Preferences from CV";
        const inputEl = document.getElementById('cv-upload-input');
        if (inputEl) inputEl.value = "";
    }
}

function refreshSettingsUI() {
    renderRolesUI();
    checkPendingUpdates();
    
    initTagInput('config-location', currentConfig.LOCATION || ['Egypt']);
    initTagInput('config-target-locations', currentConfig.TARGET_LOCATIONS || ['cairo', 'giza', 'new capital']);
    const gdEl = document.getElementById('config-glassdoor-id');
    if (gdEl) gdEl.value = currentConfig.GLASSDOOR_LOC_ID || 69;
    initTagInput('config-global-remote', currentConfig.GLOBAL_REMOTE_KEYWORDS || ['africa', 'middle east', 'mena', 'worldwide', 'global']);
    initTagInput('config-restricted-remote', currentConfig.RESTRICTED_REMOTE_KEYWORDS || ['us only', 'uk only', 'eu only']);
    
    initTagInput('config-target-levels', currentConfig.TARGET_LEVELS || ['junior', 'fresh', 'student', 'intern', 'entry']);
    const briefEl = document.getElementById('config-user-brief');
    if (briefEl) briefEl.value = currentConfig.USER_BRIEF || '';

    initTagInput('config-resume-keywords', currentConfig.RESUME_KEYWORDS || []);
    initTagInput('config-exclude-keywords', currentConfig.EXCLUDE_KEYWORDS || []);
    initTagInput('config-favorite-companies', currentConfig.FAVORITE_COMPANIES || []);
    initTagInput('config-excluded-companies', currentConfig.EXCLUDED_COMPANIES || []);
    
    initTagInput('config-sites', currentConfig.SITES || ['linkedin', 'wuzzuf', 'bayt', 'glassdoor', 'tanqeeb', 'indeed']);
    
    const minSkillsEl = document.getElementById('config-min-matched-skills');
    if (minSkillsEl) minSkillsEl.value = currentConfig.MIN_MATCHED_SKILLS !== undefined ? currentConfig.MIN_MATCHED_SKILLS : 2;
    const rptEl = document.getElementById('config-results-per-term');
    if (rptEl) rptEl.value = currentConfig.RESULTS_PER_TERM || 15;
    const retEl = document.getElementById('config-retention-days');
    if (retEl) retEl.value = currentConfig.job_retention_days || 90;

    loadTelegramStatusUI();
}

async function loadTelegramStatusUI() {
    const tokenInput = document.getElementById('telegram-bot-token');
    const chatIdInput = document.getElementById('telegram-chat-id');
    const badge = document.getElementById('telegram-status-badge');
    if (!badge) return;

    try {
        const res = await fetch('/api/telegram/status');
        const data = await res.json();
        if (data.is_configured) {
            if (tokenInput && !tokenInput.value) {
                tokenInput.placeholder = `Configured (${data.masked_token}) - Enter new token to change`;
            }
            if (chatIdInput && !chatIdInput.value) {
                chatIdInput.value = data.chat_id || '';
            }
            const statusText = data.is_configured
                ? '<span style="color: var(--success);"><i class="fa-solid fa-circle-check"></i> Mobile Sync is active (queued jobs pull on app launch / refresh).</span>'
                : '<span style="color: var(--text-muted);"><i class="fa-solid fa-circle-info"></i> Not configured yet. Paste your bot token above to link your phone.</span>';
            badge.innerHTML = statusText;
        } else {
            badge.innerHTML = '<span style="color: var(--text-muted);"><i class="fa-solid fa-circle-info"></i> Not configured yet. Paste your bot token above to link your phone.</span>';
        }
    } catch (e) {
        console.error('Failed to load Telegram status:', e);
    }
}

function toggleTokenVisibility() {
    const input = document.getElementById('telegram-bot-token');
    const icon = document.getElementById('token-eye-icon');
    if (!input) return;
    if (input.type === 'password') {
        input.type = 'text';
        if (icon) {
            icon.classList.remove('fa-eye');
            icon.classList.add('fa-eye-slash');
        }
    } else {
        input.type = 'password';
        if (icon) {
            icon.classList.remove('fa-eye-slash');
            icon.classList.add('fa-eye');
        }
    }
}

async function detectTelegramChatId() {
    const tokenInput = document.getElementById('telegram-bot-token');
    const chatIdInput = document.getElementById('telegram-chat-id');
    const detectBtn = document.getElementById('detect-chat-btn');
    const token = tokenInput ? tokenInput.value.trim() : '';

    const origHtml = detectBtn.innerHTML;
    detectBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Detecting...';
    detectBtn.disabled = true;

    try {
        const res = await fetch('/api/telegram/detect-chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ bot_token: token, chat_id: '' })
        });
        const data = await res.json();
        if (data.status === 'success' && data.chat_id) {
            chatIdInput.value = data.chat_id;
            showToast(`Connected to @${data.username || 'User'} (ID: ${data.chat_id})`, 'success', 'fa-check');
            loadTelegramStatusUI();
        } else {
            showToast(data.message || data.detail || 'Could not find messages. Send a message to your bot first!', 'warning', 'fa-triangle-exclamation');
        }
    } catch (e) {
        showToast('Detection error: ' + e.message, 'danger', 'fa-xmark');
    } finally {
        detectBtn.innerHTML = origHtml;
        detectBtn.disabled = false;
    }
}

function showSettings() {
    refreshSettingsUI();
    document.getElementById('settings-modal').classList.remove('hidden');
}

function hideSettings() {
    document.getElementById('settings-modal').classList.add('hidden');
}

async function saveSettings() {
    const newConfig = { ...currentConfig };
    
    // Extract ROLES from DOM
    const rolesContainer = document.getElementById('roles-container');
    const newRoles = [];
    const roleCards = rolesContainer.querySelectorAll('.role-card');
    roleCards.forEach(card => {
        const index = card.dataset.index;
        const title = card.querySelector('.role-title-input').value.trim();
        const maxExpStr = card.querySelector('.role-max-exp-input')?.value;
        const maxExp = maxExpStr !== undefined && maxExpStr !== '' ? parseInt(maxExpStr) : 1;
        const enTerms = getTagInputValues('role-en-' + index);
        const arTerms = getTagInputValues('role-ar-' + index);
        if (title || enTerms.length > 0 || arTerms.length > 0) {
            newRoles.push({
                title: title || 'Unnamed Role',
                years_experience: maxExp,
                max_years_experience: maxExp,
                english_terms: enTerms,
                arabic_terms: arTerms
            });
        }
    });
    newConfig.ROLES = newRoles;
    
    newConfig.LOCATION = getTagInputValues('config-location');
    newConfig.TARGET_LOCATIONS = getTagInputValues('config-target-locations');
    newConfig.GLASSDOOR_LOC_ID = parseInt(document.getElementById('config-glassdoor-id')?.value) || 69;
    newConfig.GLOBAL_REMOTE_KEYWORDS = getTagInputValues('config-global-remote');
    newConfig.RESTRICTED_REMOTE_KEYWORDS = getTagInputValues('config-restricted-remote');
    newConfig.TARGET_LEVELS = getTagInputValues('config-target-levels');
    newConfig.USER_BRIEF = document.getElementById('config-user-brief')?.value || '';
    
    newConfig.RESUME_KEYWORDS = getTagInputValues('config-resume-keywords');
    newConfig.EXCLUDE_KEYWORDS = getTagInputValues('config-exclude-keywords');
    newConfig.FAVORITE_COMPANIES = getTagInputValues('config-favorite-companies');
    newConfig.EXCLUDED_COMPANIES = getTagInputValues('config-excluded-companies');
    
    newConfig.SITES = getTagInputValues('config-sites');
    const minSkillsVal = parseInt(document.getElementById('config-min-matched-skills')?.value);
    newConfig.MIN_MATCHED_SKILLS = !isNaN(minSkillsVal) ? minSkillsVal : 2;
    newConfig.RESULTS_PER_TERM = parseInt(document.getElementById('config-results-per-term')?.value) || 15;
    newConfig.HOURS_OLD = currentConfig.HOURS_OLD || 168;
    newConfig.MAX_JOBS_TO_SEND = currentConfig.MAX_JOBS_TO_SEND || 10;
    newConfig.job_retention_days = parseInt(document.getElementById('config-retention-days')?.value) || 90;

    try {
        const response = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(newConfig)
        });
        const result = await response.json();
        if (result.status === 'success') {
            currentConfig = newConfig;
            currentConfig.last_reviewed_date = result.last_reviewed_date;
            hideSettings();
            document.getElementById('settings-warning').classList.add('hidden');
            showToast('Settings saved & jobs rescored in background!', 'success', 'fa-wand-magic-sparkles');
            setTimeout(() => {
                fetchJobs();
            }, 800);
        } else {
            showToast('Failed to save settings', 'danger', 'fa-xmark');
        }

        // Save Telegram Bot credentials if changed
        const tgTokenInput = document.getElementById('telegram-bot-token');
        const tgChatInput = document.getElementById('telegram-chat-id');
        const tgToken = tgTokenInput ? tgTokenInput.value.trim() : '';
        const tgChat = tgChatInput ? tgChatInput.value.trim() : '';

        if (tgToken || tgChat) {
            try {
                await fetch('/api/telegram/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ bot_token: tgToken, chat_id: tgChat })
                });
            } catch (tgErr) {
                console.error("Failed to save Telegram config:", tgErr);
            }
        }
    } catch (e) {
        showToast('Error saving settings', 'danger', 'fa-xmark');
    }
}

function hideSystemStatus() {
    const modal = document.getElementById('status-modal');
    modal.classList.add('hidden');
}

// Close modals if user clicks outside
window.onclick = function(event) {
    const statusModal = document.getElementById('status-modal');
    if (event.target == statusModal) {
        hideSystemStatus();
    }
    const addJobModal = document.getElementById('add-job-modal');
    if (event.target == addJobModal) {
        hideAddJobModal();
    }
    const jobTextModal = document.getElementById('job-text-modal');
    if (event.target == jobTextModal) {
        hideJobTextModal();
    }
}

// Tag Input Helper
const tagInputInstances = {};

function initTagInput(containerId, initialTags) {
    const container = document.getElementById(containerId);
    if (!container) return;
    
    container.innerHTML = '';
    container.className = 'tag-input-container';
    
    const tagsWrapper = document.createElement('div');
    tagsWrapper.className = 'tags-wrapper';
    
    const inputWrapper = document.createElement('div');
    inputWrapper.className = 'tag-input-control';
    
    const input = document.createElement('input');
    input.type = 'text';
    input.placeholder = 'Type and press Enter to add...';
    input.style.width = '100%';
    
    inputWrapper.appendChild(input);
    
    container.appendChild(tagsWrapper);
    container.appendChild(inputWrapper);
    
    let tags = [...initialTags].map(t => (typeof t === 'string' ? t.trim() : String(t).trim())).filter(t => t);
    
    function renderTags() {
        tagsWrapper.innerHTML = '';
        tags.forEach((tag, index) => {
            const tagEl = document.createElement('div');
            tagEl.className = 'editable-tag';
            tagEl.innerHTML = `<span>${tag}</span><span class="remove-tag" style="margin-left: 5px; font-weight: bold; font-size: 1.2rem; line-height: 1;">&times;</span>`;
            tagEl.querySelector('.remove-tag').onclick = () => {
                tags.splice(index, 1);
                renderTags();
            };
            tagsWrapper.appendChild(tagEl);
        });
    }
    
    function addTag(e) {
        if(e && e.preventDefault) e.preventDefault();
        const val = input.value.trim().toLowerCase();
        if (val && !tags.includes(val)) {
            tags.push(val);
            input.value = '';
            renderTags();
        }
    }
    
    input.onkeydown = (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            addTag();
        }
    };
    
    renderTags();
    tagInputInstances[containerId] = () => tags;
}

function getTagInputValues(containerId) {
    return tagInputInstances[containerId] ? tagInputInstances[containerId]() : [];
}
// --- Roles UI Logic ---
let roleIndexCounter = 0;

function renderRolesUI() {
    const container = document.getElementById('roles-container');
    container.innerHTML = '';
    const roles = currentConfig.ROLES || [];
    roleIndexCounter = 0;
    
    roles.forEach((role) => {
        const userExp = role.years_experience !== undefined ? role.years_experience : (role.max_years_experience !== undefined ? role.max_years_experience : 1);
        addRoleCard(container, roleIndexCounter++, role.title, role.english_terms, role.arabic_terms, userExp);
    });
}

function addRoleUI() {
    const container = document.getElementById('roles-container');
    addRoleCard(container, roleIndexCounter++, 'New Role', [], [], 1);
}

function addRoleCard(container, index, title, enTerms, arTerms, maxExp) {
    const card = document.createElement('div');
    card.className = 'role-card';
    card.style = 'background: rgba(0, 0, 0, 0.2); padding: 1rem; border-radius: 0.5rem; border: 1px solid var(--card-border); position: relative;';
    card.dataset.index = index;
    
    const removeBtn = document.createElement('button');
    removeBtn.innerHTML = '<i class="fa-solid fa-trash-can"></i>';
    removeBtn.className = 'close-btn';
    removeBtn.style = 'position: absolute; top: 0.5rem; right: 0.5rem; color: var(--danger); font-size: 1rem;';
    removeBtn.onclick = () => card.remove();
    card.appendChild(removeBtn);
    
    const titleLabel = document.createElement('label');
    titleLabel.innerText = 'Role Title';
    const titleInput = document.createElement('input');
    titleInput.type = 'text';
    titleInput.className = 'role-title-input';
    titleInput.value = title || '';
    titleInput.style = 'width: 100%; margin-bottom: 1rem; background: rgba(0, 0, 0, 0.3); border: 1px solid var(--card-border); color: white; padding: 0.5rem; border-radius: 0.25rem;';
    
    const maxExpLabel = document.createElement('label');
    maxExpLabel.innerText = "Your Experience (Years)";
    const maxExpInput = document.createElement('input');
    maxExpInput.type = 'number';
    maxExpInput.min = '0';
    maxExpInput.className = 'role-max-exp-input';
    maxExpInput.value = maxExp !== undefined ? maxExp : 1;
    maxExpInput.style = 'width: 100%; margin-bottom: 1rem; background: rgba(0, 0, 0, 0.3); border: 1px solid var(--card-border); color: white; padding: 0.5rem; border-radius: 0.25rem;';

    const enLabel = document.createElement('label');
    enLabel.innerText = 'English Search Terms';
    const enContainer = document.createElement('div');
    enContainer.id = 'role-en-' + index;
    
    const arLabel = document.createElement('label');
    arLabel.innerText = 'Arabic Search Terms';
    const arContainer = document.createElement('div');
    arContainer.id = 'role-ar-' + index;
    
    card.appendChild(titleLabel);
    card.appendChild(titleInput);
    card.appendChild(maxExpLabel);
    card.appendChild(maxExpInput);
    card.appendChild(enLabel);
    card.appendChild(enContainer);
    card.appendChild(arLabel);
    card.appendChild(arContainer);
    
    container.appendChild(card);
    
    initTagInput(enContainer.id, enTerms || []);
    initTagInput(arContainer.id, arTerms || []);
}

// --- Scraper Control Logic ---
let isScraping = false;
let scraperPollInterval = null;

async function runScraper() {
    if (isScraping) return;
    
    try {
        const res = await fetch('/api/run-scraper', { method: 'POST' });
        const data = await res.json();
        if (data.status === 'started' || data.status === 'already_running') {
            setScraperState(true);
            showToast('Job search started in background.', 'success', 'fa-play');
        }
    } catch(e) {
        showToast('Failed to start scraper', 'danger', 'fa-xmark');
    }
}

function setScraperState(running) {
    isScraping = running;
    const btn = document.getElementById('run-scraper-btn');
    const icon = document.getElementById('scraper-icon');
    const spinner = document.getElementById('scraper-spinner');
    const text = document.getElementById('scraper-text');
    const progressContainer = document.getElementById('scraper-progress-container');
    
    if (running) {
        if (btn) {
            btn.disabled = true;
            btn.style.opacity = '0.7';
            btn.style.cursor = 'not-allowed';
        }
        if (icon) icon.classList.add('hidden');
        if (spinner) spinner.classList.remove('hidden');
        if (text) text.innerText = 'Searching...';
        if (progressContainer) progressContainer.classList.remove('hidden');
        
        if (!scraperPollInterval) {
            scraperPollInterval = setInterval(pollScraper, 2000);
        }
    } else {
        if (btn) {
            btn.disabled = false;
            btn.style.opacity = '1';
            btn.style.cursor = 'pointer';
        }
        if (icon) icon.classList.remove('hidden');
        if (spinner) spinner.classList.add('hidden');
        if (text) text.innerText = 'Search for New Jobs';
        if (progressContainer) progressContainer.classList.add('hidden');
        
        if (scraperPollInterval) {
            clearInterval(scraperPollInterval);
            scraperPollInterval = null;
            showToast('Job search completed!', 'success', 'fa-check');
            fetchJobs(); // refresh the list
        }
    }
}

async function pollScraper() {
    try {
        const res = await fetch('/api/scraper-status');
        const data = await res.json();
        
        if (data.last_run) {
            const lastRunEl = document.getElementById('last-run-text');
            if (lastRunEl) lastRunEl.innerText = `Last Run: ${data.last_run}`;
        }

        const progressContainer = document.getElementById('scraper-progress-container');
        
        if (data.is_running) {
            if (!isScraping) {
                setScraperState(true);
            }
            if (progressContainer) {
                progressContainer.classList.remove('hidden');
            }
            if (data.progress) {
                const p = data.progress;
                const percent = Math.min(100, Math.max(0, p.percent || 0));
                
                const fillEl = document.getElementById('progress-fill');
                if (fillEl) fillEl.style.width = `${percent}%`;

                const percentEl = document.getElementById('progress-percent');
                if (percentEl) percentEl.innerText = `${percent}%`;

                const taskEl = document.getElementById('progress-task');
                if (taskEl) taskEl.innerText = p.task || 'Scraping in progress...';

                const etaEl = document.getElementById('progress-eta');
                if (etaEl) etaEl.innerText = p.eta_str || 'Calculating...';

                const jobsEl = document.getElementById('progress-jobs-found');
                if (jobsEl) jobsEl.innerText = p.jobs_found || 0;

                const detailsEl = document.getElementById('progress-details');
                if (detailsEl) detailsEl.innerText = `Step ${p.current_step || 0} of ${p.total_steps || 0}`;

                const elapsedEl = document.getElementById('progress-elapsed');
                if (elapsedEl) elapsedEl.innerText = `Elapsed: ${p.elapsed_str || '0s'}`;
            }
        } else {
            if (isScraping) {
                setScraperState(false);
            }
            if (progressContainer) {
                progressContainer.classList.add('hidden');
            }
        }
    } catch(e) {
        console.error(e);
    }
}

// Check status on load
document.addEventListener('DOMContentLoaded', pollScraper);



let pendingProposals = [];

async function checkPendingUpdates() {
    try {
        const response = await fetch('/api/pending-updates');
        const data = await response.json();
        pendingProposals = data.proposals || [];
        
        const count = pendingProposals.length;
        const badge = document.getElementById('proposals-badge');
        const navNotification = document.getElementById('settings-notification');

        if (badge) {
            badge.textContent = count;
            if (count > 0) badge.classList.remove('hidden');
            else badge.classList.add('hidden');
        }

        if (navNotification) {
            if (count > 0) {
                navNotification.classList.remove('hidden');
                navNotification.style.animation = 'pulse 2s infinite';
            } else {
                navNotification.classList.add('hidden');
                navNotification.style.animation = 'none';
            }
        }
    } catch(e) {
        console.error("Failed to check pending updates", e);
    }
}

async function openProposalsModal() {
    await checkPendingUpdates();
    renderProposalsModalUI();
    const modal = document.getElementById('ai-proposals-modal');
    if (modal) modal.classList.remove('hidden');
}

function hideProposalsModal() {
    const modal = document.getElementById('ai-proposals-modal');
    if (modal) modal.classList.add('hidden');
    if (typeof loadConfig === 'function') {
        loadConfig().then(() => {
            const settingsModal = document.getElementById('settings-modal');
            if (settingsModal && !settingsModal.classList.contains('hidden')) {
                showSettings();
            }
        });
    }
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function renderProposalsModalUI() {
    const container = document.getElementById('proposals-list-container');
    if (!container) return;

    if (pendingProposals.length === 0) {
        container.innerHTML = `
            <div style="text-align: center; padding: 2.5rem; color: var(--text-muted);">
                <i class="fa-solid fa-circle-check" style="font-size: 2.5rem; color: var(--success); margin-bottom: 0.8rem; display: block;"></i>
                <h4 style="margin: 0 0 0.4rem 0; color: var(--text-main);">No Pending Proposals</h4>
                <p style="margin: 0; font-size: 0.85rem;">Your configuration is fully up to date. AI suggestions from CV imports or job actions will appear here for your review.</p>
            </div>
        `;
        return;
    }

    let html = '';
    pendingProposals.forEach(prop => {
        const isAdd = prop.type === 'add';
        const isUserBrief = prop.field === 'USER_BRIEF';

        if (isUserBrief) {
            const briefContent = typeof prop.value === 'string' ? prop.value : (prop.value?.value || JSON.stringify(prop.value));
            const currentBriefText = currentConfig.USER_BRIEF ? String(currentConfig.USER_BRIEF).trim() : '';

            html += `
                <div style="background: rgba(59, 130, 246, 0.08); border: 1px solid var(--accent); border-radius: 0.6rem; padding: 1rem; display: flex; flex-direction: column; gap: 0.8rem;">
                    <div style="display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap;">
                        <div style="display: flex; align-items: center; gap: 0.6rem;">
                            <span style="background: rgba(59, 130, 246, 0.2); color: var(--accent); border: 1px solid var(--accent); font-size: 0.72rem; font-weight: 700; border-radius: 99px; padding: 3px 10px; flex-shrink: 0;">
                                <i class="fa-solid fa-pen-to-square"></i> PROFILE BRIEF UPDATE
                            </span>
                            <span style="font-size: 0.82rem; color: var(--text-muted);">
                                Source: <strong style="color: var(--text-main);">${escapeHtml(prop.source || 'AI Agent')}</strong>
                            </span>
                        </div>
                        <div style="display: flex; align-items: center; gap: 0.5rem; flex-shrink: 0;">
                            <button class="btn btn-primary" onclick="handleProposalAction('${prop.id}', 'accept')" style="padding: 0.4rem 0.85rem; font-size: 0.82rem; background: var(--success); border: none;" title="Accept New Brief">
                                <i class="fa-solid fa-check"></i> Accept Brief
                            </button>
                            <button class="btn btn-secondary" onclick="handleProposalAction('${prop.id}', 'reject')" style="padding: 0.4rem 0.85rem; font-size: 0.82rem; background: rgba(239, 68, 68, 0.2); color: #ef4444; border: 1px solid #ef4444;" title="Reject New Brief">
                                <i class="fa-solid fa-xmark"></i> Reject
                            </button>
                        </div>
                    </div>

                    ${prop.reason ? `<div style="font-size: 0.8rem; color: var(--text-muted); font-style: italic;">"${escapeHtml(prop.reason)}"</div>` : ''}

                    <div style="display: grid; grid-template-columns: ${currentBriefText ? '1fr 1fr' : '1fr'}; gap: 0.8rem; margin-top: 0.2rem;">
                        ${currentBriefText ? `
                            <div style="background: rgba(0, 0, 0, 0.25); padding: 0.8rem; border-radius: 0.5rem; border: 1px solid var(--card-border);">
                                <div style="font-size: 0.75rem; font-weight: 700; color: var(--text-muted); text-transform: uppercase; margin-bottom: 0.4rem;">Current Brief</div>
                                <div style="font-size: 0.85rem; color: var(--text-muted); line-height: 1.45; white-space: pre-wrap; max-height: 160px; overflow-y: auto;">${escapeHtml(currentBriefText)}</div>
                            </div>
                        ` : ''}
                        <div style="background: rgba(16, 185, 129, 0.1); padding: 0.8rem; border-radius: 0.5rem; border: 1px solid rgba(16, 185, 129, 0.35);">
                            <div style="font-size: 0.75rem; font-weight: 700; color: #10b981; text-transform: uppercase; margin-bottom: 0.4rem;">Proposed Brief</div>
                            <div style="font-size: 0.85rem; color: var(--text-main); line-height: 1.45; white-space: pre-wrap; max-height: 160px; overflow-y: auto;">${escapeHtml(briefContent)}</div>
                        </div>
                    </div>
                </div>
            `;
            return;
        }

        const badgeStyle = isAdd 
            ? 'background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid #10b981;' 
            : 'background: rgba(239, 68, 68, 0.15); color: #ef4444; border: 1px solid #ef4444;';
        const badgeText = isAdd ? '<i class="fa-solid fa-plus"></i> ADD' : '<i class="fa-solid fa-minus"></i> REMOVE';

        let displayVal = prop.display_name || prop.value;
        if (typeof prop.value === 'object' && prop.value !== null) {
            displayVal = prop.value.title || JSON.stringify(prop.value);
        }

        html += `
            <div style="background: rgba(255, 255, 255, 0.03); border: 1px solid var(--card-border); border-radius: 0.6rem; padding: 0.9rem; display: flex; align-items: center; justify-content: space-between; gap: 1rem;">
                <div style="display: flex; align-items: flex-start; gap: 0.8rem;">
                    <span style="${badgeStyle} font-size: 0.72rem; font-weight: 700; border-radius: 99px; padding: 3px 8px; flex-shrink: 0; margin-top: 2px;">${badgeText}</span>
                    <div>
                        <div style="font-weight: 600; color: var(--text-main); font-size: 0.95rem;">${displayVal}</div>
                        <div style="font-size: 0.8rem; color: var(--text-muted); margin-top: 2px;">
                            <span style="color: var(--accent); font-weight: 500;">${prop.field.replace('_', ' ')}</span> &bull; <span>Source: ${prop.source || 'AI Agent'}</span>
                        </div>
                        ${prop.reason ? `<div style="font-size: 0.78rem; color: var(--text-muted); font-style: italic; margin-top: 3px;">"${prop.reason}"</div>` : ''}
                    </div>
                </div>
                <div style="display: flex; align-items: center; gap: 0.5rem; flex-shrink: 0;">
                    <button class="btn btn-primary" onclick="handleProposalAction('${prop.id}', 'accept')" style="padding: 0.35rem 0.75rem; font-size: 0.8rem; background: var(--success); border: none;" title="Accept Change"><i class="fa-solid fa-check"></i> Accept</button>
                    <button class="btn btn-secondary" onclick="handleProposalAction('${prop.id}', 'reject')" style="padding: 0.35rem 0.75rem; font-size: 0.8rem; background: rgba(239, 68, 68, 0.2); color: #ef4444; border: 1px solid #ef4444;" title="Reject Change"><i class="fa-solid fa-xmark"></i> Reject</button>
                </div>
            </div>
        `;
    });
    container.innerHTML = html;
}

async function handleProposalAction(id, action) {
    try {
        const response = await fetch('/api/pending-updates/action', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id, action })
        });
        const result = await response.json();
        if (result.status === 'success') {
            await checkPendingUpdates();
            renderProposalsModalUI();
            await fetchConfig();
            refreshSettingsUI();
            fetchJobs();
            showToast(action === 'accept' ? 'Proposal accepted!' : 'Proposal rejected.', 'success');
        }
    } catch (e) {
        showToast('Error processing update', 'danger', 'fa-xmark');
    }
}

async function handleBatchProposalAction(action) {
    try {
        const response = await fetch('/api/pending-updates/batch-action', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action })
        });
        const result = await response.json();
        if (result.status === 'success') {
            await checkPendingUpdates();
            renderProposalsModalUI();
            await fetchConfig();
            refreshSettingsUI();
            fetchJobs();
            showToast(action === 'accept_all' ? 'Accepted all proposals!' : 'Rejected all proposals.', 'success');
        }
    } catch (e) {
        showToast('Error processing batch action', 'danger', 'fa-xmark');
    }
}

// Alias plural name for HTML onclick binding safety
const handleBatchProposalsAction = handleBatchProposalAction;

async function deleteSingleJob(jobId) {
    if (!confirm('Are you sure you want to delete this job permanently?')) {
        return;
    }
    
    const card = document.getElementById(`job-${jobId}`);
    if (card) {
        card.style.animation = 'fadeOut 0.3s ease forwards';
        setTimeout(() => {
            card.remove();
            updateJobCount();
        }, 300);
    }
    
    allJobs = allJobs.filter(j => j.job_id !== jobId);
    filteredJobsList = filteredJobsList.filter(j => j.job_id !== jobId);

    try {
        const response = await fetch(`/api/jobs/${jobId}`, { method: 'DELETE' });
        const data = await response.json();
        if (data.status === 'success') {
            showToast('Job permanently deleted', 'danger', 'fa-trash-can');
        } else {
            showToast('Failed to delete job', 'danger', 'fa-circle-xmark');
            fetchJobs();
        }
    } catch (err) {
        console.error('Error deleting job:', err);
        showToast('Error deleting job', 'danger', 'fa-circle-xmark');
        fetchJobs();
    }
}

// ---------------------------------------------------------------------------
// Add Job by URL Functions
// ---------------------------------------------------------------------------

function showAddJobModal() {
    const modal = document.getElementById('add-job-modal');
    if (modal) {
        modal.classList.remove('hidden');
        const urlInput = document.getElementById('add-job-url');
        if (urlInput) {
            urlInput.focus();
        }
        // Clear status
        const statusDiv = document.getElementById('add-job-status');
        if (statusDiv) {
            statusDiv.className = 'hidden';
            statusDiv.innerHTML = '';
        }
    }
}

function hideAddJobModal() {
    const modal = document.getElementById('add-job-modal');
    if (modal) modal.classList.add('hidden');
    const scholCheck = document.getElementById('add-job-is-scholarship');
    if (scholCheck) scholCheck.checked = false;
}

function onAddJobUrlInput(val) {
    const select = document.getElementById('add-job-scraper-type');
    if (!select || !val) return;
    const url = val.toLowerCase();
    
    // Smart auto-detect helper for scraper selector
    if (url.includes('linkedin.com') || url.includes('eg.linkedin.com')) {
        if (url.includes('/posts/') || url.includes('/feed/update/') || url.includes('activity')) {
            select.value = 'linkedin_post';
        } else {
            select.value = 'linkedin_job';
        }
    } else if (url.includes('wuzzuf.net')) {
        select.value = 'wuzzuf';
    } else if (url.includes('tanqeeb.com')) {
        select.value = 'tanqeeb';
    } else if (url.includes('bayt.com')) {
        select.value = 'bayt';
    } else if (url.includes('http') || url.includes('.')) {
        if (select.value !== 'auto') {
            select.value = 'auto';
        }
    }
}

async function pasteClipboardToUrl() {
    try {
        const text = await navigator.clipboard.readText();
        if (text) {
            const input = document.getElementById('add-job-url');
            if (input) {
                input.value = text.trim();
                onAddJobUrlInput(input.value);
            }
        }
    } catch (err) {
        showToast('Clipboard access denied or unavailable', 'info', 'fa-paste');
    }
}

async function submitAddJob() {
    const urlInput = document.getElementById('add-job-url');
    const scraperTypeSelect = document.getElementById('add-job-scraper-type');
    const rawTextInput = document.getElementById('add-job-raw-text');
    const submitBtn = document.getElementById('add-job-submit-btn');
    const btnIcon = document.getElementById('add-job-btn-icon');
    const btnSpinner = document.getElementById('add-job-btn-spinner');
    const btnText = document.getElementById('add-job-btn-text');
    const statusDiv = document.getElementById('add-job-status');

    const url = (urlInput ? urlInput.value : '').trim();
    const scraperType = scraperTypeSelect ? scraperTypeSelect.value : 'auto';
    const rawText = (rawTextInput ? rawTextInput.value : '').trim();
    const isScholarship = document.getElementById('add-job-is-scholarship')?.checked || false;

    if (!url && !rawText) {
        if (statusDiv) {
            statusDiv.className = '';
            statusDiv.style.background = 'rgba(239, 68, 68, 0.15)';
            statusDiv.style.border = '1px solid var(--danger)';
            statusDiv.style.color = 'var(--text-main)';
            statusDiv.innerHTML = '<i class="fa-solid fa-circle-exclamation" style="color:var(--danger);margin-right:6px;"></i>Please provide a job link or post text.';
        }
        if (urlInput) urlInput.focus();
        return;
    }

    // Set UI loading state
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.style.opacity = '0.75';
        submitBtn.style.cursor = 'wait';
    }
    if (btnIcon) btnIcon.classList.add('hidden');
    if (btnSpinner) btnSpinner.classList.remove('hidden');
    if (btnText) btnText.innerText = 'Scraping & Adding...';

    if (statusDiv) {
        statusDiv.className = '';
        statusDiv.style.background = 'rgba(59, 130, 246, 0.15)';
        statusDiv.style.border = '1px solid var(--primary)';
        statusDiv.style.color = 'var(--text-main)';
        statusDiv.innerHTML = '<i class="fa-solid fa-spinner fa-spin" style="color:var(--primary);margin-right:6px;"></i>Connecting to site and extracting job details with AI...';
    }

    try {
        const response = await fetch('/api/jobs/add-by-url', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url: url,
                scraper_type: scraperType,
                raw_text: rawText,
                is_scholarship: isScholarship
            })
        });

        const data = await response.json();

        if (response.ok && data.status === 'success' && data.job) {
            const savedJob = data.job;
            hideAddJobModal();

            // Clear inputs for next time
            if (urlInput) urlInput.value = '';
            if (rawTextInput) rawTextInput.value = '';
            if (scraperTypeSelect) scraperTypeSelect.value = 'auto';
            const scholCheck = document.getElementById('add-job-is-scholarship');
            if (scholCheck) scholCheck.checked = false;

            // Insert or update in local state
            const existingIdx = allJobs.findIndex(j => j.job_id === savedJob.job_id || (j.job_url && j.job_url === savedJob.job_url));
            if (existingIdx >= 0) {
                allJobs[existingIdx] = savedJob;
            } else {
                allJobs.unshift(savedJob);
            }

            // Hide empty state if visible
            const emptyState = document.getElementById('empty-state');
            if (emptyState) emptyState.classList.add('hidden');

            // Re-render grid
            applyFiltersAndSort();

            const actionVerb = data.is_new ? 'added to dashboard' : 'updated in dashboard';
            showToast(`"${savedJob.title}" at ${savedJob.company} ${actionVerb}! (Score: ${Math.round(savedJob.relevance_score || 0)})`, 'success', 'fa-circle-check');

            // Scroll to the card and highlight
            setTimeout(() => {
                const card = document.getElementById(`job-${savedJob.job_id}`);
                if (card) {
                    card.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    card.style.transition = 'box-shadow 0.4s ease, border-color 0.4s ease';
                    card.style.boxShadow = '0 0 20px rgba(59, 130, 246, 0.6)';
                    card.style.borderColor = 'var(--primary)';
                    setTimeout(() => {
                        card.style.boxShadow = '';
                        card.style.borderColor = '';
                    }, 2500);
                }
            }, 250);

        } else if (response.ok && data.status === 'pruned') {
            if (statusDiv) {
                statusDiv.className = '';
                statusDiv.style.background = 'rgba(239, 68, 68, 0.15)';
                statusDiv.style.border = '1px solid var(--danger)';
                statusDiv.style.color = 'var(--text-main)';
                statusDiv.innerHTML = `<i class="fa-solid fa-trash-can" style="color:var(--danger);margin-right:6px;"></i>${escapeHtml(data.detail)}`;
            }
            showToast('Role scored 0% (outside target criteria) and was pruned.', 'danger', 'fa-trash-can');
        } else {
            const errDetail = data.detail || data.error || 'Failed to scrape job.';
            if (statusDiv) {
                statusDiv.className = '';
                statusDiv.style.background = 'rgba(239, 68, 68, 0.15)';
                statusDiv.style.border = '1px solid var(--danger)';
                statusDiv.style.color = 'var(--text-main)';
                statusDiv.innerHTML = `<i class="fa-solid fa-circle-xmark" style="color:var(--danger);margin-right:6px;"></i>${errDetail}`;
            }
        }
    } catch (err) {
        console.error('Error adding job by URL:', err);
        if (statusDiv) {
            statusDiv.className = '';
            statusDiv.style.background = 'rgba(239, 68, 68, 0.15)';
            statusDiv.style.border = '1px solid var(--danger)';
            statusDiv.style.color = 'var(--text-main)';
            statusDiv.innerHTML = `<i class="fa-solid fa-circle-xmark" style="color:var(--danger);margin-right:6px;"></i>Network error: ${err.message || err}`;
        }
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.style.opacity = '1';
            submitBtn.style.cursor = 'pointer';
        }
        if (btnIcon) btnIcon.classList.remove('hidden');
        if (btnSpinner) btnSpinner.classList.add('hidden');
        if (btnText) btnText.innerText = 'Scrape & Add Job';
    }
}

// ---------------------------------------------------------------------------
// Job Text Modal Functions (for manual jobs added with no external URL)
// ---------------------------------------------------------------------------
let currentModalJobText = '';

function openJobTextModal(jobId) {
    const job = allJobs.find(j => String(j.job_id) === String(jobId));
    if (!job) return;

    currentModalJobText = job.description || 'No job description text provided.';

    const titleEl = document.getElementById('job-text-title');
    const companyEl = document.getElementById('job-text-company');
    const contentEl = document.getElementById('job-text-content');

    if (titleEl) titleEl.textContent = job.title || 'Untitled Job';
    if (companyEl) {
        const comp = job.company && job.company !== 'Unknown Company' ? job.company : (job.location || 'Manual Entry');
        companyEl.textContent = comp;
    }
    if (contentEl) contentEl.textContent = currentModalJobText;

    const modal = document.getElementById('job-text-modal');
    if (modal) modal.classList.remove('hidden');
}

function hideJobTextModal() {
    const modal = document.getElementById('job-text-modal');
    if (modal) modal.classList.add('hidden');
}

function copyCurrentJobText() {
    if (!currentModalJobText) return;
    navigator.clipboard.writeText(currentModalJobText).then(() => {
        showToast('Job text copied to clipboard!', 'success', 'fa-copy');
    }).catch(err => {
        console.error('Failed to copy to clipboard:', err);
        showToast('Failed to copy text', 'danger', 'fa-circle-xmark');
    });
}

function copyJobTextById(jobId) {
    const job = allJobs.find(j => String(j.job_id) === String(jobId));
    if (!job || !job.description) {
        showToast('No job text available to copy', 'info', 'fa-circle-info');
        return;
    }
    navigator.clipboard.writeText(job.description).then(() => {
        showToast('Job post text copied to clipboard!', 'success', 'fa-copy');
    }).catch(err => {
        console.error('Failed to copy to clipboard:', err);
        showToast('Failed to copy text', 'danger', 'fa-circle-xmark');
    });
}

// Developer Credits
(function() {
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
                '<a href="https://kaggle.com/mohamdHussein" target="_blank" style="color:var(--primary);text-decoration:none;display:flex;align-items:center;gap:0.35rem;"><i class="fa-brands fa-kaggle"></i>Kaggle</a>' +
                '</div>';
            const container = document.querySelector('.app-container');
            if (container) container.appendChild(footer);
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
