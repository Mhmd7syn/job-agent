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

function cleanLocation(location) {
    if (!location) return '';
    const cleaned = String(location).replace(/^(?:On-site|Onsite|Remote|Hybrid|عن بعد|حضوري|هجين)\s*[-–—|:]\s*/i, '').trim();
    return cleaned || String(location).trim();
}

function formatSiteName(site) {
    if (!site) return 'Web';
    const s = String(site).trim().toLowerCase();
    if (s === 'linkedin') return 'LinkedIn';
    if (s === 'linkedin_posts' || s === 'linkedin_post') return 'LinkedIn Posts';
    if (s === 'wuzzuf') return 'Wuzzuf';
    if (s === 'glassdoor') return 'Glassdoor';
    if (s === 'indeed') return 'Indeed';
    if (s === 'bayt') return 'Bayt';
    if (s === 'tanqeeb') return 'Tanqeeb';
    if (s === 'lnkd') return 'LinkedIn Posts';
    if (s === 'whatsapp_export') return 'WhatsApp Export';
    return site.charAt(0).toUpperCase() + site.slice(1);
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



        if (appliedFilter === 'applied' && job.is_applied !== 1) return false;
        if (appliedFilter === 'not_applied' && job.is_applied === 1) return false;

        if (roleFilter !== 'all') {
            const roleConfig = currentConfig.ROLES.find(r => r.title === roleFilter);
            if (roleConfig) {
                const t = (job.title || '').toLowerCase();
                const terms = (roleConfig.english_terms || roleConfig.terms || [])
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
            const setup = (job.workplace_setup || '').toLowerCase();
            const loc = (job.location || '').toLowerCase();
            const title = (job.title || '').toLowerCase();
            const isRemote = setup === 'remote' || loc.includes('remote') || title.includes('remote') || loc.includes('work from home');
            const isHybrid = setup === 'hybrid' || loc.includes('hybrid') || title.includes('hybrid');
            
            if (setupFilter === 'remote' && !isRemote) return false;
            if (setupFilter === 'hybrid' && !isHybrid) return false;
            if (setupFilter === 'onsite' && (isRemote || isHybrid)) return false;
        }

        if (siteFilter !== 'all') {
            const s = (job.site || '').toLowerCase();
            if (siteFilter === 'linkedin') {
                if (s !== 'linkedin' && s !== 'linkedin_posts' && s !== 'lnkd') return false;
            } else if (siteFilter === 'linkedin_posts') {
                if (s !== 'linkedin_posts' && s !== 'lnkd') return false;
            } else if (s !== siteFilter.toLowerCase()) {
                return false;
            }
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

    const isApplied = job.is_applied === 1;
    const hasLink = Boolean(job.job_url && String(job.job_url).trim() && job.job_url !== 'nan' && (String(job.job_url).startsWith('http://') || String(job.job_url).startsWith('https://')));

    const detailsBtnHtml = `<button type="button" class="btn btn-secondary btn-details" onclick="openJobDetailsModal('${job.job_id}')" title="View Full Details & Application Info" style="grid-column: 1 / -1;"><i class="fa-solid fa-circle-info"></i>Details</button>`;

    let actionsHtml = '';
    if (job.status === 'not_related') {
        actionsHtml = `
            <div style="grid-column: 1 / -1; display: flex; align-items: center; justify-content: center; color: var(--danger); font-weight: 500; cursor: pointer; transition: opacity 0.2s; padding: 0.25rem 0;" onclick="handleAction('${job.job_id}', 'pending')" title="Click to undo and move back to Pending" onmouseover="this.style.opacity=0.7" onmouseout="this.style.opacity=1">
                <i class="fa-solid fa-circle-xmark" style="margin-right: 6px;"></i>Not Related (Click to Undo)
            </div>
            ${detailsBtnHtml}
        `;
    } else {
        actionsHtml = `
            ${job.status !== 'liked' ? 
                `<button class="btn btn-like" onclick="handleAction('${job.job_id}', 'liked')"><i class="fa-regular fa-heart"></i>Like</button>` : 
                `<button class="btn btn-like" disabled style="opacity: 0.5"><i class="fa-solid fa-heart"></i>Liked</button>`
            }
            <button class="btn btn-reject" onclick="handleAction('${job.job_id}', 'not_related')"><i class="fa-solid fa-xmark"></i>Not Related</button>
            ${detailsBtnHtml}
        `;
    }

    const isScholarship = (job.job_type || '').toLowerCase() === 'scholarship';
    const typeTagIcon = isScholarship ? 'fa-solid fa-graduation-cap' : 'fa-solid fa-clock';
    const typeTagClass = isScholarship ? 'tag tag-scholarship' : 'tag';

    const siteTagHtml = hasLink ?
        `<div class="tag"><i class="fa-solid fa-globe"></i>${escapeHtml(formatSiteName(job.site))}</div>` :
        `<div class="tag tag-manual" title="Added manually by you (not scraped from job boards)"><i class="fa-solid fa-user-pen"></i>Added by Me</div>`;

    // Channel Badge
    let channelTagHtml = '';
    const applyType = (job.apply_type || 'manual').toLowerCase();
    let cardPayload = {};
    if (job.apply_payload) {
        try {
            cardPayload = typeof job.apply_payload === 'string' ? JSON.parse(job.apply_payload) : job.apply_payload;
        } catch (e) {
            cardPayload = {};
        }
    }

    if (applyType === 'email') {
        channelTagHtml = `<div class="tag-channel tag-channel-email" title="Direct HR Email Application"><i class="fa-solid fa-envelope"></i>Email</div>`;
    } else if (applyType === 'whatsapp') {
        channelTagHtml = `<div class="tag-channel tag-channel-whatsapp" title="WhatsApp Recruiter Contact"><i class="fa-brands fa-whatsapp"></i>WhatsApp</div>`;
    } else if (applyType === 'form') {
        channelTagHtml = `<div class="tag-channel tag-channel-form" title="Online Application Form"><i class="fa-solid fa-file-waveform"></i>Form</div>`;
    } else if (applyType === 'easy_apply') {
        channelTagHtml = `<div class="tag-channel tag-channel-easyapply" title="Quick Easy Apply"><i class="fa-solid fa-bolt"></i>Easy Apply</div>`;
    } else if (applyType === 'platform') {
        const platName = cardPayload.platform || 'ATS';
        const displayPlat = platName.charAt(0).toUpperCase() + platName.slice(1);
        channelTagHtml = `<div class="tag-channel tag-channel-platform" title="Company ATS Portal (${escapeHtml(displayPlat)})"><i class="fa-solid fa-network-wired"></i>${escapeHtml(displayPlat)}</div>`;
    } else if (applyType === 'social_post') {
        channelTagHtml = `<div class="tag-channel tag-channel-social" title="LinkedIn Hiring Post"><i class="fa-brands fa-linkedin"></i>LinkedIn Post</div>`;
    } else if (applyType === 'job_board') {
        const board = cardPayload.board_name || job.site || 'Job Board';
        channelTagHtml = `<div class="tag-channel tag-channel-board" title="Job Board Listing (${escapeHtml(board)})"><i class="fa-solid fa-briefcase"></i>${escapeHtml(board)}</div>`;
    } else {
        const isEmployerSite = cardPayload && cardPayload.source === 'employer_site';
        const label = isEmployerSite ? 'Employer Site' : 'External';
        const title = isEmployerSite ? 'Apply on Employer Site' : 'External Application';
        channelTagHtml = `<div class="tag-channel tag-channel-manual" title="${title}"><i class="fa-solid fa-arrow-up-right-from-square"></i>${label}</div>`;
    }

    div.innerHTML = `
        <div class="card-header">
            <h3 class="job-title" title="${job.title}">${job.title}</h3>
            <div style="display: flex; align-items: center; gap: 0.5rem; flex-shrink: 0;">
                ${isApplied ? `<span class="tag-channel tag-channel-email" style="font-size: 0.72rem; padding: 0.15rem 0.45rem; border-radius: 999px;" title="Applied"><i class="fa-solid fa-check"></i>Applied</span>` : ''}
                <span class="job-score" title="Relevance Score"><i class="fa-solid fa-star" style="color:var(--warning); margin-right:4px;"></i>${Math.round(job.relevance_score || 0)}</span>
                <button class="btn btn-delete" onclick="deleteSingleJob('${job.job_id}')" title="Delete Job Permanently" style="padding: 0.35rem 0.6rem; font-size: 0.8rem; border-radius: 0.4rem;">
                    <i class="fa-solid fa-trash-can"></i>
                </button>
            </div>
        </div>
        <div class="job-company"><i class="fa-regular fa-building" style="margin-right:6px;"></i>${job.company || 'Unknown Company'}</div>
        
        <div class="tags">
            <div class="tag"><i class="fa-solid fa-location-dot"></i>${escapeHtml(cleanLocation(job.location) || 'Remote')}</div>
            <div class="${typeTagClass}"><i class="${typeTagIcon}"></i>${job.job_type || 'Full-time'}</div>
            ${siteTagHtml}
            ${channelTagHtml}
        </div>
        
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
    initTagInput('config-global-remote', currentConfig.GLOBAL_REMOTE_KEYWORDS || ['africa', 'middle east', 'mena', 'worldwide', 'global']);
    initTagInput('config-restricted-remote', currentConfig.RESTRICTED_REMOTE_KEYWORDS || ['us only', 'uk only', 'eu only']);
    
    renderCareerLevelsUI();
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
    const userInput = document.getElementById('telegram-username');
    const badge = document.getElementById('telegram-status-badge');
    const openBotBtn = document.getElementById('telegram-open-bot-btn') || document.getElementById('telegram-open-web-btn');
    if (!badge) return;

    try {
        const res = await fetch('/api/telegram/status');
        const data = await res.json();
        if (userInput && data.username !== undefined) {
            userInput.value = (data.username || '').replace(/^@/, '');
        }

        const botUrl = data.bot_url || (data.bot_username ? `https://t.me/${data.bot_username}` : 'https://t.me/JobAgent_Mhmd7syn_bot');
        if (openBotBtn) {
            openBotBtn.href = botUrl;
        }

        if (data.username) {
            const userDisplay = data.username.replace(/^@/, '');
            if (data.has_chat_id) {
                badge.innerHTML = `<span style="color: var(--success);"><i class="fa-solid fa-circle-check"></i> Connected to @${userDisplay}. Chat linked & ready to sync jobs!</span>`;
            } else {
                badge.innerHTML = `<span style="color: #f59e0b;"><i class="fa-solid fa-clock"></i> Configured for @${userDisplay}. Open the bot chat above & tap Start to link!</span>`;
            }
        } else {
            badge.innerHTML = '<span style="color: var(--text-muted);"><i class="fa-solid fa-circle-info"></i> Enter your Telegram username above to connect Mobile Sync.</span>';
        }
    } catch (e) {
        console.error('Failed to load Telegram status:', e);
    }
}

function switchSettingsSection(sectionId) {
    const tabs = document.querySelectorAll('.settings-nav-tab');
    tabs.forEach(t => t.classList.remove('active'));
    const targetTab = document.getElementById(`tab-sec-${sectionId}`);
    if (targetTab) targetTab.classList.add('active');

    const panes = document.querySelectorAll('.settings-section-pane');
    panes.forEach(p => p.classList.remove('active'));
    const targetPane = document.getElementById(`section-${sectionId}`);
    if (targetPane) targetPane.classList.add('active');

    if (sectionId === 'profile') {
        loadProfileSettingsUI();
    } else if (sectionId === 'auto-apply') {
        loadAutoApplySettingsUI();
    }
}

function switchSettingsSubSection(sectionId, subSectionId) {
    const sectionEl = document.getElementById(`section-${sectionId}`);
    if (!sectionEl) return;

    const pills = sectionEl.querySelectorAll('.settings-subnav-pill');
    pills.forEach(p => p.classList.remove('active'));
    const targetPill = document.getElementById(`pill-${sectionId}-${subSectionId}`) ||
                       document.getElementById(`pill-apply-${subSectionId}`) ||
                       document.getElementById(`pill-${subSectionId}`);
    if (targetPill) targetPill.classList.add('active');

    const subPanes = sectionEl.querySelectorAll('.settings-subsection-pane');
    subPanes.forEach(p => p.classList.remove('active'));
    const targetSubPane = document.getElementById(`subpane-${sectionId}-${subSectionId}`) ||
                          document.getElementById(`subpane-apply-${subSectionId}`) ||
                          document.getElementById(`subpane-${subSectionId}`);
    if (targetSubPane) targetSubPane.classList.add('active');
}

let currentProfileData = null;

async function loadProfileSettingsUI() {
    try {
        const res = await fetch('/api/profile');
        if (!res.ok) return;
        const data = await res.json();
        currentProfileData = data;

        const pInfo = data.personal_info || {};
        const screening = data.smart_screening || {};

        const nameEl = document.getElementById('profile-full-name');
        if (nameEl) nameEl.value = pInfo.full_name || '';

        const emailEl = document.getElementById('profile-email');
        if (emailEl) emailEl.value = pInfo.email || '';

        const phoneEl = document.getElementById('profile-phone');
        if (phoneEl) phoneEl.value = pInfo.phone || '';

        const cityCountryEl = document.getElementById('profile-city-country');
        if (cityCountryEl) {
            cityCountryEl.value = `${pInfo.city || 'Cairo'}, ${pInfo.country || 'Egypt'}`;
        }

        const linkedinEl = document.getElementById('profile-linkedin');
        if (linkedinEl) linkedinEl.value = pInfo.linkedin_url || '';

        const githubEl = document.getElementById('profile-github');
        if (githubEl) githubEl.value = pInfo.github_url || '';

        const resumeDirEl = document.getElementById('profile-resume-dir');
        if (resumeDirEl) resumeDirEl.value = pInfo.resume_base_dir || '';

        const militaryEl = document.getElementById('screening-military');
        if (militaryEl) militaryEl.value = screening.military_status || 'Exempted / Completed';

        const noticeEl = document.getElementById('screening-notice');
        if (noticeEl) noticeEl.value = screening.notice_period_days !== undefined ? screening.notice_period_days : 30;

        const salEgpEl = document.getElementById('screening-salary-egp');
        if (salEgpEl) salEgpEl.value = screening.expected_salary_egp || 35000;

        const salUsdEl = document.getElementById('screening-salary-usd');
        if (salUsdEl) salUsdEl.value = screening.expected_salary_usd || 1500;

        const drivingCb = document.getElementById('screening-driving');
        if (drivingCb) drivingCb.checked = Boolean(screening.driving_license);

        const sponsorCb = document.getElementById('screening-sponsorship-rule');
        if (sponsorCb) sponsorCb.checked = screening.sponsorship_outside_home_only !== false;

        const relocateCb = document.getElementById('screening-relocate-rule');
        if (relocateCb) relocateCb.checked = screening.relocate_outside_home_only !== false;

        // Automatically trigger resume scan preview
        triggerScanResumesUI(pInfo.resume_base_dir);
    } catch (e) {
        console.error('Failed to load profile:', e);
    }
}

async function triggerScanResumesUI(customDir = null) {
    const resumeDirEl = document.getElementById('profile-resume-dir');
    const baseDir = customDir || (resumeDirEl ? resumeDirEl.value.trim() : '');
    const resultsContainer = document.getElementById('resume-scan-results');
    const icon = document.getElementById('scan-resumes-icon');

    if (icon) icon.classList.add('fa-spin');

    try {
        const url = baseDir ? `/api/profile/scan-resumes?base_dir=${encodeURIComponent(baseDir)}` : '/api/profile/scan-resumes';
        const res = await fetch(url);
        const data = await res.json();

        if (resultsContainer) {
            if (!data.exists) {
                resultsContainer.innerHTML = `<div style="color: var(--danger); font-size: 0.85rem;"><i class="fa-solid fa-triangle-exclamation"></i> Resume directory not found: <code>${escapeHtml(data.base_dir)}</code></div>`;
                return;
            }

            const roles = data.roles_found || {};
            const roleKeys = Object.keys(roles);

            if (roleKeys.length === 0) {
                resultsContainer.innerHTML = `<div style="color: var(--warning); font-size: 0.85rem;"><i class="fa-solid fa-circle-info"></i> No role subfolders containing PDF resumes found in directory.</div>`;
                return;
            }

            let html = `<div style="font-size: 0.82rem; font-weight: 600; color: var(--text-main); margin-bottom: 0.4rem;"><i class="fa-solid fa-circle-check" style="color: var(--success); margin-right: 0.35rem;"></i> Discovered ${roleKeys.length} Mapped Role Folders:</div>`;
            roleKeys.forEach(r => {
                const info = roles[r];
                const cvName = info.primary_cv ? info.primary_cv.filename : 'None';
                const cvSize = info.primary_cv ? `${info.primary_cv.size_kb} KB` : '';
                const statusBadge = info.primary_cv ? 
                    `<span style="color: var(--success); font-size: 0.8rem;"><i class="fa-solid fa-file-pdf"></i> ${escapeHtml(cvName)} (${cvSize})</span>` :
                    `<span style="color: var(--danger); font-size: 0.8rem;"><i class="fa-solid fa-xmark"></i> No PDF found</span>`;

                html += `
                    <div style="display: flex; justify-content: space-between; align-items: center; background: rgba(255,255,255,0.04); border: 1px solid var(--card-border); padding: 0.5rem 0.75rem; border-radius: 0.4rem; font-size: 0.85rem;">
                        <span style="font-weight: 500; color: var(--text-main);"><i class="fa-solid fa-folder" style="color: #f59e0b; margin-right: 6px;"></i>${escapeHtml(r)}</span>
                        ${statusBadge}
                    </div>
                `;
            });

            if (data.ignored_items && data.ignored_items.length > 0) {
                html += `<div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 0.3rem;">Ignored non-CV files/folders: ${escapeHtml(data.ignored_items.join(', '))}</div>`;
            }

            resultsContainer.innerHTML = html;
        }
    } catch (e) {
        console.error('Failed to scan resumes:', e);
        if (resultsContainer) {
            resultsContainer.innerHTML = `<div style="color: var(--danger); font-size: 0.85rem;">Failed to scan resume directory: ${escapeHtml(e.message)}</div>`;
        }
    } finally {
        if (icon) icon.classList.remove('fa-spin');
    }
}

// ==========================================
// Auto-Pilot Engine Master State (Pause/Resume)
// ==========================================
function updateAutoPilotStatusUI(isEnabled) {
    const card = document.getElementById('autopilot-status-card');
    const indicator = document.getElementById('autopilot-status-indicator');
    const title = document.getElementById('autopilot-status-title');
    const badge = document.getElementById('autopilot-status-badge');
    const desc = document.getElementById('autopilot-status-desc');
    const cb = document.getElementById('apply-autopilot-enabled');
    const quickBtn = document.getElementById('apply-autopilot-quick-btn');

    if (cb) cb.checked = Boolean(isEnabled);

    if (isEnabled) {
        if (card) {
            card.style.background = 'rgba(16, 185, 129, 0.08)';
            card.style.borderColor = 'rgba(16, 185, 129, 0.3)';
        }
        if (indicator) {
            indicator.style.backgroundColor = '#10b981';
            indicator.style.boxShadow = '0 0 8px #10b981';
        }
        if (title) {
            title.style.color = '#34d399';
            title.innerHTML = '<i class="fa-solid fa-play"></i> Auto-Pilot Engine: Active';
        }
        if (badge) {
            badge.textContent = 'ACTIVE';
            badge.style.background = 'rgba(16, 185, 129, 0.2)';
            badge.style.color = '#34d399';
            badge.style.borderColor = 'rgba(16, 185, 129, 0.4)';
        }
        if (desc) {
            desc.textContent = 'Auto-Pilot is active and will automatically execute scheduled application runs based on your daily rate limits and score threshold.';
        }
        if (quickBtn) {
            quickBtn.innerHTML = '<i class="fa-solid fa-pause"></i> Pause Auto-Pilot';
            quickBtn.style.borderColor = 'rgba(239, 68, 68, 0.4)';
            quickBtn.style.color = '#fca5a5';
        }
    } else {
        if (card) {
            card.style.background = 'rgba(239, 68, 68, 0.08)';
            card.style.borderColor = 'rgba(239, 68, 68, 0.3)';
        }
        if (indicator) {
            indicator.style.backgroundColor = '#ef4444';
            indicator.style.boxShadow = '0 0 8px #ef4444';
        }
        if (title) {
            title.style.color = '#f87171';
            title.innerHTML = '<i class="fa-solid fa-pause"></i> Auto-Pilot Engine: Paused';
        }
        if (badge) {
            badge.textContent = 'PAUSED';
            badge.style.background = 'rgba(239, 68, 68, 0.2)';
            badge.style.color = '#fca5a5';
            badge.style.borderColor = 'rgba(239, 68, 68, 0.4)';
        }
        if (desc) {
            desc.textContent = 'Auto-Pilot background execution is paused. No automated emails or messages will be sent until you resume it here.';
        }
        if (quickBtn) {
            quickBtn.innerHTML = '<i class="fa-solid fa-play"></i> Resume Auto-Pilot';
            quickBtn.style.borderColor = 'rgba(16, 185, 129, 0.4)';
            quickBtn.style.color = '#34d399';
        }
    }
}

async function onAutoPilotToggleSwitchChange(isChecked) {
    await setRemoteAutoPilotState(Boolean(isChecked));
}

async function toggleAutoPilotQuickAction() {
    const cb = document.getElementById('apply-autopilot-enabled');
    const newState = cb ? !cb.checked : false;
    await setRemoteAutoPilotState(newState);
}

async function setRemoteAutoPilotState(enableState) {
    updateAutoPilotStatusUI(enableState);
    try {
        const res = await fetch('/api/autopilot/toggle-state', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: enableState })
        });
        if (res.ok) {
            showToast(
                enableState ? '🚀 Auto-Pilot resumed! Autonomous runs are active.' : '⏸️ Auto-Pilot paused. Scheduled runs are halted.',
                'info',
                enableState ? 'fa-play' : 'fa-pause'
            );
            if (currentProfileData && currentProfileData.auto_apply_settings) {
                currentProfileData.auto_apply_settings.enabled = enableState;
            }
        } else {
            showToast('Failed to update Auto-Pilot state.', 'danger', 'fa-circle-xmark');
        }
    } catch (e) {
        console.error('Error updating Auto-Pilot state:', e);
    }
}

function openSettingsToAutoApply() {
    hideApplicationsHub();
    showSettings();
    switchSettingsSection('auto-apply');
    switchSettingsSubSection('auto-apply', 'schedule');
}

async function loadAutoApplySettingsUI() {
    try {
        const res = await fetch('/api/auto-apply/settings');
        if (!res.ok) return;
        const data = await res.json();

        updateAutoPilotStatusUI(Boolean(data.enabled));

        const bSizeEl = document.getElementById('apply-batch-size');
        if (bSizeEl) bSizeEl.value = data.batch_size_per_run || 3;

        const maxRunsEl = document.getElementById('apply-max-runs');
        if (maxRunsEl) maxRunsEl.value = data.max_runs_per_day || 5;

        const minScoreEl = document.getElementById('apply-min-score');
        if (minScoreEl) minScoreEl.value = data.min_relevance_score || 70;

        const smtpHostEl = document.getElementById('apply-smtp-host');
        if (smtpHostEl) smtpHostEl.value = data.smtp_host || 'smtp.gmail.com';

        const smtpPortEl = document.getElementById('apply-smtp-port');
        if (smtpPortEl) smtpPortEl.value = data.smtp_port || 465;

        const smtpEmailEl = document.getElementById('apply-smtp-email');
        if (smtpEmailEl) smtpEmailEl.value = data.smtp_email || '';

        const smtpPassEl = document.getElementById('apply-smtp-password');
        if (smtpPassEl) smtpPassEl.value = data.smtp_app_password || '';

        const sigEl = document.getElementById('apply-email-signature');
        if (sigEl) sigEl.value = data.email_signature_personal || '';

        const waModeEl = document.getElementById('apply-whatsapp-mode');
        if (waModeEl) waModeEl.value = data.whatsapp_mode || 'deep_link';

        const waLangEl = document.getElementById('apply-whatsapp-lang');
        if (waLangEl) waLangEl.value = data.whatsapp_default_language || 'auto';

        const chans = data.channels_enabled || {};
        const emailCb = document.getElementById('chan-email');
        if (emailCb) emailCb.checked = chans.email !== false;

        const waCb = document.getElementById('chan-whatsapp');
        if (waCb) waCb.checked = chans.whatsapp !== false;

        const easyCb = document.getElementById('chan-easyapply');
        if (easyCb) easyCb.checked = chans.easy_apply !== false;

        const platCb = document.getElementById('chan-platform');
        if (platCb) platCb.checked = chans.platform !== false;

    } catch (e) {
        console.error('Failed to load auto-apply settings:', e);
    }
}

async function saveProfileAndApplySettingsFromDOM() {
    try {
        const pInfo = currentProfileData?.personal_info || {};
        const screening = currentProfileData?.smart_screening || {};
        const autoApply = currentProfileData?.auto_apply_settings || {};

        // 1. Personal Info
        const fullName = document.getElementById('profile-full-name')?.value.trim() || pInfo.full_name || 'Mohamed Hussein';
        const parts = fullName.split(' ');
        pInfo.full_name = fullName;
        pInfo.first_name = parts[0] || 'Mohamed';
        pInfo.last_name = parts.slice(1).join(' ') || 'Hussein';
        pInfo.email = document.getElementById('profile-email')?.value.trim() || pInfo.email || '';
        pInfo.phone = document.getElementById('profile-phone')?.value.trim() || pInfo.phone || '';
        
        const cityCountry = document.getElementById('profile-city-country')?.value.trim() || 'Cairo, Egypt';
        const ccParts = cityCountry.split(',');
        pInfo.city = ccParts[0]?.trim() || 'Cairo';
        pInfo.country = ccParts[1]?.trim() || 'Egypt';
        
        pInfo.linkedin_url = document.getElementById('profile-linkedin')?.value.trim() || pInfo.linkedin_url || '';
        pInfo.github_url = document.getElementById('profile-github')?.value.trim() || pInfo.github_url || '';
        pInfo.resume_base_dir = document.getElementById('profile-resume-dir')?.value.trim() || pInfo.resume_base_dir || '';

        // 2. Smart Screening
        screening.military_status = document.getElementById('screening-military')?.value.trim() || 'Exempted / Completed';
        screening.notice_period_days = parseInt(document.getElementById('screening-notice')?.value) || 30;
        screening.expected_salary_egp = parseInt(document.getElementById('screening-salary-egp')?.value) || 35000;
        screening.expected_salary_usd = parseInt(document.getElementById('screening-salary-usd')?.value) || 1500;
        screening.driving_license = Boolean(document.getElementById('screening-driving')?.checked);
        screening.sponsorship_outside_home_only = Boolean(document.getElementById('screening-sponsorship-rule')?.checked);
        screening.relocate_outside_home_only = Boolean(document.getElementById('screening-relocate-rule')?.checked);
        screening.home_country = pInfo.country || 'Egypt';
        screening.home_city = pInfo.city || 'Cairo';

        // 3. Auto-Apply Settings
        autoApply.enabled = Boolean(document.getElementById('apply-autopilot-enabled')?.checked);
        autoApply.batch_size_per_run = parseInt(document.getElementById('apply-batch-size')?.value) || 3;
        autoApply.max_runs_per_day = parseInt(document.getElementById('apply-max-runs')?.value) || 5;
        autoApply.min_relevance_score = parseInt(document.getElementById('apply-min-score')?.value) || 70;
        autoApply.smtp_host = document.getElementById('apply-smtp-host')?.value.trim() || 'smtp.gmail.com';
        autoApply.smtp_port = parseInt(document.getElementById('apply-smtp-port')?.value) || 465;
        autoApply.smtp_email = document.getElementById('apply-smtp-email')?.value.trim() || '';
        autoApply.smtp_app_password = document.getElementById('apply-smtp-password')?.value.trim() || '';
        autoApply.email_signature_personal = document.getElementById('apply-email-signature')?.value || '';
        autoApply.whatsapp_mode = document.getElementById('apply-whatsapp-mode')?.value || 'deep_link';
        autoApply.whatsapp_default_language = document.getElementById('apply-whatsapp-lang')?.value || 'auto';

        autoApply.channels_enabled = {
            email: Boolean(document.getElementById('chan-email')?.checked),
            whatsapp: Boolean(document.getElementById('chan-whatsapp')?.checked),
            easy_apply: Boolean(document.getElementById('chan-easyapply')?.checked),
            platform: Boolean(document.getElementById('chan-platform')?.checked)
        };

        const updatedProfile = {
            personal_info: pInfo,
            smart_screening: screening,
            auto_apply_settings: autoApply,
            custom_qa_pairs: currentProfileData?.custom_qa_pairs || {}
        };

        await fetch('/api/profile', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(updatedProfile)
        });
        currentProfileData = updatedProfile;
    } catch (err) {
        console.error('Failed to save profile/apply settings:', err);
    }
}

function showSettings() {
    refreshSettingsUI();
    loadProfileSettingsUI();
    loadAutoApplySettingsUI();
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
        const maxExp = maxExpStr !== undefined && maxExpStr !== '' ? parseInt(maxExpStr) : 0;
        const enTerms = getTagInputValues('role-en-' + index);
        if (title || enTerms.length > 0) {
            newRoles.push({
                title: title || 'Unnamed Role',
                years_experience: maxExp,
                english_terms: enTerms
            });
        }
    });
    newConfig.ROLES = newRoles;
    
    newConfig.LOCATION = getTagInputValues('config-location');
    newConfig.TARGET_LOCATIONS = getTagInputValues('config-target-locations');
    newConfig.GLOBAL_REMOTE_KEYWORDS = getTagInputValues('config-global-remote');
    newConfig.RESTRICTED_REMOTE_KEYWORDS = getTagInputValues('config-restricted-remote');
    
    const targetLevels = [];
    const levelExclude = [];
    CAREER_LEVEL_CONFIG.forEach(lvl => {
        const cb = document.getElementById(`lvl-cb-${lvl.id}`);
        if (cb && cb.checked) {
            targetLevels.push(lvl.label);
        } else {
            levelExclude.push(lvl.label);
        }
    });
    newConfig.TARGET_LEVELS = targetLevels;
    newConfig.LEVEL_EXCLUDE = levelExclude;

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
            
            // Save Candidate Profile and Auto-Apply settings concurrently
            await saveProfileAndApplySettingsFromDOM();

            // Save Telegram username
            const tgUserInput = document.getElementById('telegram-username');
            if (tgUserInput) {
                const tgUsername = tgUserInput.value.trim().replace(/^@/, '');
                try {
                    const tgRes = await fetch('/api/telegram/config', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ username: tgUsername })
                    });
                    const tgData = await tgRes.json();
                    if (tgData.status === 'success') {
                        await loadTelegramStatusUI();
                    }
                } catch (tgErr) {
                    console.error("Failed to save Telegram config:", tgErr);
                }
            }

            hideSettings();
            document.getElementById('settings-warning').classList.add('hidden');
            showToast('All settings & profile saved successfully!', 'success', 'fa-wand-magic-sparkles');
            setTimeout(() => {
                fetchJobs();
            }, 800);
        } else {
            showToast('Failed to save settings', 'danger', 'fa-xmark');
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

// Career Seniority Levels Config & UI
const CAREER_LEVEL_CONFIG = [
    { label: "Intern / Student", id: "intern_student", desc: "Internships, students, trainees" },
    { label: "Fresh Graduate / Entry-level", id: "fresh_entry", desc: "0-1 years exp, fresh grads, beginner" },
    { label: "Junior", id: "junior", desc: "1-2 years exp, junior associate" },
    { label: "Mid-Level", id: "mid_level", desc: "2-5 years exp, intermediate, experienced" },
    { label: "Senior / Lead", id: "senior_lead", desc: "5+ years exp, senior, leads, architects" },
    { label: "Manager / Director", id: "manager_director", desc: "Management, team heads, directors, VP" }
];

const CAREER_LEVEL_SYNONYMS_CLIENT = {
    "Intern / Student": ["intern", "internship", "student", "trainee", "undergrad", "undergraduate", "co-op"],
    "Fresh Graduate / Entry-level": ["fresh", "graduate", "fresh graduate", "entry", "entry-level", "starter", "beginner"],
    "Junior": ["junior", "jr", "associate"],
    "Mid-Level": ["mid", "mid-level", "mid level", "intermediate", "experienced"],
    "Senior / Lead": ["senior", "sr", "lead", "principal", "staff", "architect", "expert"],
    "Manager / Director": ["manager", "director", "head", "vp", "executive"]
};

function renderCareerLevelsUI() {
    const container = document.getElementById('config-career-levels');
    if (!container) return;
    container.innerHTML = '';

    const currentTargets = Array.isArray(currentConfig.TARGET_LEVELS) ? currentConfig.TARGET_LEVELS : ["Intern / Student", "Fresh Graduate / Entry-level", "Junior"];
    const currentExcludes = Array.isArray(currentConfig.LEVEL_EXCLUDE) ? currentConfig.LEVEL_EXCLUDE : [];

    const lowerTargets = currentTargets.map(t => String(t).toLowerCase().trim());
    const lowerExcludes = currentExcludes.map(e => String(e).toLowerCase().trim());

    CAREER_LEVEL_CONFIG.forEach(lvl => {
        let isChecked = false;

        // 1. Check if explicitly listed in TARGET_LEVELS
        if (lowerTargets.includes(lvl.label.toLowerCase())) {
            isChecked = true;
        } else if (lowerExcludes.includes(lvl.label.toLowerCase())) {
            isChecked = false;
        } else {
            // 2. Backward compatibility: check if any synonym is in lowerTargets
            const syns = CAREER_LEVEL_SYNONYMS_CLIENT[lvl.label] || [];
            if (syns.some(s => lowerTargets.includes(s.toLowerCase()))) {
                isChecked = true;
            } else if (currentExcludes.length === 0 && ["Intern / Student", "Fresh Graduate / Entry-level", "Junior"].includes(lvl.label)) {
                // Default fallback if brand new config
                isChecked = true;
            }
        }

        const card = document.createElement('div');
        card.className = `career-level-card ${isChecked ? 'checked' : ''}`;
        card.id = `card-lvl-${lvl.id}`;

        card.innerHTML = `
            <div class="career-level-left">
                <input type="checkbox" id="lvl-cb-${lvl.id}" ${isChecked ? 'checked' : ''}>
                <span class="career-level-title">${lvl.label}</span>
            </div>
            <span class="career-level-badge ${isChecked ? 'badge-target' : 'badge-exclude'}" id="lvl-badge-${lvl.id}">
                ${isChecked ? '<i class="fa-solid fa-arrow-up"></i> TARGET (+15)' : '<i class="fa-solid fa-ban"></i> EXCLUDE'}
            </span>
        `;

        const cb = card.querySelector(`#lvl-cb-${lvl.id}`);
        const badge = card.querySelector(`#lvl-badge-${lvl.id}`);

        function updateCardState(checked) {
            cb.checked = checked;
            if (checked) {
                card.classList.add('checked');
                badge.className = 'career-level-badge badge-target';
                badge.innerHTML = '<i class="fa-solid fa-arrow-up"></i> TARGET (+15)';
            } else {
                card.classList.remove('checked');
                badge.className = 'career-level-badge badge-exclude';
                badge.innerHTML = '<i class="fa-solid fa-ban"></i> EXCLUDE';
            }
        }

        cb.addEventListener('change', (e) => {
            e.stopPropagation();
            updateCardState(cb.checked);
        });

        card.addEventListener('click', (e) => {
            if (e.target !== cb) {
                updateCardState(!cb.checked);
            }
        });

        container.appendChild(card);
    });
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
        const userExp = role.years_experience !== undefined ? role.years_experience : 0;
        addRoleCard(container, roleIndexCounter++, role.title, role.english_terms || role.terms || [], userExp);
    });
}

function addRoleUI() {
    const container = document.getElementById('roles-container');
    addRoleCard(container, roleIndexCounter++, 'New Role', [], 0);
}

function addRoleCard(container, index, title, enTerms, maxExp) {
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
    maxExpInput.value = maxExp !== undefined ? maxExp : 0;
    maxExpInput.style = 'width: 100%; margin-bottom: 1rem; background: rgba(0, 0, 0, 0.3); border: 1px solid var(--card-border); color: white; padding: 0.5rem; border-radius: 0.25rem;';

    const enLabel = document.createElement('label');
    enLabel.innerText = 'Search Terms';
    const enContainer = document.createElement('div');
    enContainer.id = 'role-en-' + index;
    
    card.appendChild(titleLabel);
    card.appendChild(titleInput);
    card.appendChild(maxExpLabel);
    card.appendChild(maxExpInput);
    card.appendChild(enLabel);
    card.appendChild(enContainer);
    
    container.appendChild(card);
    
    initTagInput(enContainer.id, enTerms || []);
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
// Job Details & Application Modal Functions
// ---------------------------------------------------------------------------
let currentModalJobId = null;
let currentModalJobText = '';

function openJobDetailsModal(jobId) {
    const job = allJobs.find(j => String(j.job_id) === String(jobId));
    if (!job) return;

    currentModalJobId = jobId;
    currentModalJobText = job.description || 'No job description text provided.';

    const titleEl = document.getElementById('job-details-title');
    const companyEl = document.getElementById('job-details-company');
    const scoreEl = document.getElementById('job-details-score');
    const sourceEl = document.getElementById('job-details-source');
    const tagsEl = document.getElementById('job-details-tags');
    const applyBoxEl = document.getElementById('job-details-apply-box');
    const contentEl = document.getElementById('job-details-content');
    const viewLinkEl = document.getElementById('job-details-view-link');
    const appliedToggleBtn = document.getElementById('job-details-applied-toggle-btn');
    const copilotBtn = document.getElementById('job-details-copilot-btn');

    if (titleEl) titleEl.textContent = job.title || 'Untitled Job';
    if (companyEl) {
        const comp = job.company && job.company !== 'Unknown Company' ? job.company : (job.location || 'Unknown Company');
        companyEl.innerHTML = `<i class="fa-regular fa-building" style="margin-right:6px;"></i>${escapeHtml(comp)}`;
    }
    if (scoreEl) {
        scoreEl.innerHTML = `<i class="fa-solid fa-star" style="color:var(--warning); margin-right:4px;"></i>${Math.round(job.relevance_score || 0)} Match Score`;
    }
    if (sourceEl) {
        const site = formatSiteName(job.site);
        sourceEl.className = 'tag';
        sourceEl.innerHTML = `<i class="fa-solid fa-globe" style="margin-right: 4px;"></i>${escapeHtml(site)}`;
    }

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

    // Render Tag Chips (Location, Setup, Type, Date)
    if (tagsEl) {
        const isScholarship = (job.job_type || '').toLowerCase() === 'scholarship';
        const typeTagIcon = isScholarship ? 'fa-solid fa-graduation-cap' : 'fa-solid fa-clock';
        const typeTagClass = isScholarship ? 'tag tag-scholarship' : 'tag';

        // Detect Setup (Remote/Hybrid/Onsite)
        const setup = (job.workplace_setup || '').toLowerCase();
        const loc = (job.location || '').toLowerCase();
        const t = (job.title || '').toLowerCase();
        let setupIcon = 'fa-solid fa-building';
        let setupText = 'On-site';
        if (setup === 'remote' || loc.includes('remote') || t.includes('remote') || loc.includes('work from home')) {
            setupIcon = 'fa-solid fa-house-laptop';
            setupText = 'Remote';
        } else if (setup === 'hybrid' || loc.includes('hybrid') || t.includes('hybrid')) {
            setupIcon = 'fa-solid fa-shuffle';
            setupText = 'Hybrid';
        } else if (job.workplace_setup) {
            setupText = job.workplace_setup;
        }

        tagsEl.innerHTML = `
            <div class="tag"><i class="fa-solid fa-location-dot"></i>${escapeHtml(cleanLocation(job.location) || 'Remote')}</div>
            <div class="tag"><i class="${setupIcon}"></i>${setupText}</div>
            <div class="${typeTagClass}"><i class="${typeTagIcon}"></i>${escapeHtml(job.job_type || 'Full-time')}</div>
            <div class="tag"><i class="fa-regular fa-calendar"></i>${dateStr}</div>
        `;
    }

    // Parse apply payload
    let payload = {};
    if (job.apply_payload) {
        try {
            payload = typeof job.apply_payload === 'string' ? JSON.parse(job.apply_payload) : job.apply_payload;
        } catch (e) {
            payload = {};
        }
    }

    const applyType = (job.apply_type || 'manual').toLowerCase();
    let primaryActionUrl = '';

    // Render Apply Details Box
    if (applyBoxEl) {
        let channelTitle = '';
        let channelBadgeClass = '';
        let channelIcon = '';
        let detailRows = '';

        if (copilotBtn) {
            copilotBtn.style.backgroundColor = '';
            copilotBtn.style.borderColor = '';
        }

        if (applyType === 'email') {
            channelTitle = 'Direct HR Email Application';
            channelBadgeClass = 'tag-channel-email';
            channelIcon = 'fa-solid fa-envelope';
            const email = payload.recipient_email || 'HR Email specified in description';
            const subject = payload.subject_hint || `Application for ${job.title} - Mohamed Hussein`;
            primaryActionUrl = payload.recipient_email ? `mailto:${payload.recipient_email}` : '';
            detailRows = `
                <div class="detail-row">
                    <span class="detail-label"><i class="fa-solid fa-at"></i> Recipient:</span>
                    <span class="detail-value"><code>${escapeHtml(email)}</code></span>
                </div>
                <div class="detail-row">
                    <span class="detail-label"><i class="fa-solid fa-heading"></i> Subject:</span>
                    <span class="detail-value"><em>${escapeHtml(subject)}</em></span>
                </div>
                <div class="detail-row" style="font-size: 0.8rem; color: #93c5fd;">
                    <i class="fa-solid fa-paperclip"></i> Auto-attaches tailored role PDF from your OneDrive resume folder.
                </div>
            `;
            if (copilotBtn) {
                copilotBtn.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Draft / Send Email (Co-Pilot)';
                copilotBtn.className = 'btn btn-primary';
                copilotBtn.style.display = 'inline-flex';
            }
        } else if (applyType === 'whatsapp') {
            channelTitle = 'WhatsApp Recruiter Outreach';
            channelBadgeClass = 'tag-channel-whatsapp';
            channelIcon = 'fa-brands fa-whatsapp';
            const phone = payload.phone ? `+${payload.phone}` : (payload.whatsapp_url || 'Direct WhatsApp Link');
            primaryActionUrl = payload.whatsapp_url || (payload.phone ? `https://wa.me/${payload.phone}` : '');
            detailRows = `
                <div class="detail-row">
                    <span class="detail-label"><i class="fa-solid fa-phone"></i> WhatsApp Contact:</span>
                    <span class="detail-value"><code>${escapeHtml(phone)}</code></span>
                </div>
                <div class="detail-row" style="font-size: 0.8rem; color: #86efac;">
                    <i class="fa-solid fa-comment-dots"></i> 1-Click opens WhatsApp Web/Desktop with a professional introductory pitch pre-filled.
                </div>
            `;
            if (copilotBtn) {
                copilotBtn.innerHTML = '<i class="fa-brands fa-whatsapp"></i> Chat on WhatsApp';
                copilotBtn.className = 'btn btn-primary';
                copilotBtn.style.backgroundColor = '#25D366';
                copilotBtn.style.borderColor = '#25D366';
                copilotBtn.style.display = 'inline-flex';
            }
        } else if (applyType === 'form') {
            channelTitle = 'Online Application Form';
            channelBadgeClass = 'tag-channel-form';
            channelIcon = 'fa-solid fa-file-waveform';
            const formUrl = payload.form_url || payload.portal_url || job.job_url || '';
            primaryActionUrl = formUrl;
            detailRows = `
                <div class="detail-row">
                    <span class="detail-label"><i class="fa-solid fa-link"></i> Form Link:</span>
                    <span class="detail-value" style="max-width: 450px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;"><a href="${escapeHtml(formUrl)}" target="_blank" style="color: #c084fc;">${escapeHtml(formUrl)}</a></span>
                </div>
                <div class="detail-row" style="font-size: 0.8rem; color: #e9d5ff;">
                    <i class="fa-solid fa-clipboard-check"></i> Standard questionnaire form (Google Forms / MS Forms / Typeform).
                </div>
            `;
            if (copilotBtn) {
                copilotBtn.innerHTML = '<i class="fa-solid fa-file-waveform"></i> Open Form Assistant';
                copilotBtn.className = 'btn btn-primary';
                copilotBtn.style.display = 'inline-flex';
            }
        } else if (applyType === 'platform') {
            const platName = payload.platform ? (payload.platform.charAt(0).toUpperCase() + payload.platform.slice(1)) : 'Company ATS';
            channelTitle = `${platName} ATS Portal`;
            channelBadgeClass = 'tag-channel-platform';
            channelIcon = 'fa-solid fa-network-wired';
            const portalUrl = payload.portal_url || payload.job_url || job.job_url || '';
            primaryActionUrl = portalUrl;
            detailRows = `
                <div class="detail-row">
                    <span class="detail-label"><i class="fa-solid fa-link"></i> Portal Link:</span>
                    <span class="detail-value" style="max-width: 450px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;"><a href="${escapeHtml(portalUrl)}" target="_blank" style="color: #60a5fa;">${escapeHtml(portalUrl || 'Direct ATS Portal')}</a></span>
                </div>
                <div class="detail-row" style="font-size: 0.8rem; color: #93c5fd;">
                    <i class="fa-solid fa-server"></i> Dedicated ATS portal for candidates.
                </div>
            `;
            if (copilotBtn) {
                copilotBtn.innerHTML = '<i class="fa-solid fa-network-wired"></i> Open ATS Co-Pilot';
                copilotBtn.className = 'btn btn-primary';
                copilotBtn.style.display = 'inline-flex';
            }
        } else if (applyType === 'easy_apply') {
            channelTitle = 'Fast-track Easy Apply';
            channelBadgeClass = 'tag-channel-easyapply';
            channelIcon = 'fa-solid fa-bolt';
            primaryActionUrl = payload.job_url || job.job_url || '';
            detailRows = `
                <div class="detail-row">
                    <span class="detail-label"><i class="fa-solid fa-circle-nodes"></i> Channel:</span>
                    <span class="detail-value">Built-in quick application modal</span>
                </div>
                <div class="detail-row" style="font-size: 0.8rem; color: #fde68a;">
                    <i class="fa-solid fa-bolt"></i> Fast application directly on the hosting platform.
                </div>
            `;
            if (copilotBtn) {
                copilotBtn.innerHTML = '<i class="fa-solid fa-bolt"></i> Launch Easy Apply';
                copilotBtn.className = 'btn btn-primary';
                copilotBtn.style.display = 'inline-flex';
            }
        } else if (applyType === 'social_post') {
            channelTitle = 'LinkedIn Hiring Post';
            channelBadgeClass = 'tag-channel-social';
            channelIcon = 'fa-brands fa-linkedin';
            const postUrl = payload.post_url || job.job_url || '';
            primaryActionUrl = postUrl;
            detailRows = `
                <div class="detail-row">
                    <span class="detail-label"><i class="fa-brands fa-linkedin"></i> Post Link:</span>
                    <span class="detail-value" style="max-width: 450px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;"><a href="${escapeHtml(postUrl)}" target="_blank" style="color: #38bdf8;">${escapeHtml(postUrl)}</a></span>
                </div>
                <div class="detail-row" style="font-size: 0.8rem; color: #7dd3fc;">
                    <i class="fa-solid fa-comment-dots"></i> Shared directly by the recruiter / hiring manager on LinkedIn.
                </div>
            `;
            if (copilotBtn) {
                copilotBtn.innerHTML = '<i class="fa-brands fa-linkedin"></i> View Post on LinkedIn';
                copilotBtn.className = 'btn btn-primary';
                copilotBtn.style.display = 'inline-flex';
            }
        } else if (applyType === 'job_board') {
            const boardName = payload.board_name || (job.site ? formatSiteName(job.site) : 'Job Board');
            channelTitle = `${boardName} Job Listing`;
            channelBadgeClass = 'tag-channel-board';
            channelIcon = 'fa-solid fa-briefcase';
            const boardUrl = payload.job_url || job.job_url || '';
            primaryActionUrl = boardUrl;
            detailRows = `
                <div class="detail-row">
                    <span class="detail-label"><i class="fa-solid fa-circle-info"></i> Channel:</span>
                    <span class="detail-value">Direct job listing on ${escapeHtml(boardName)}</span>
                </div>
                <div class="detail-row" style="font-size: 0.8rem; color: #a5b4fc;">
                    <i class="fa-solid fa-arrow-up-right-from-square"></i> Published on ${escapeHtml(boardName)}. Click below to view and apply on the platform.
                </div>
            `;
            if (copilotBtn) {
                copilotBtn.innerHTML = `<i class="fa-solid fa-arrow-up-right-from-square"></i> Open on ${escapeHtml(boardName)}`;
                copilotBtn.className = 'btn btn-primary';
                copilotBtn.style.display = 'inline-flex';
            }
        } else {
            const isEmployer = payload && payload.source === 'employer_site';
            const portalUrl = payload.portal_url || payload.job_url || job.job_url || '';
            primaryActionUrl = portalUrl;

            const isAggregator = Boolean(portalUrl && (() => {
                try {
                    const host = new URL(portalUrl).hostname.toLowerCase();
                    return host.includes('glassdoor.') || host.includes('indeed.') || host.includes('linkedin.') || host.includes('wuzzuf.') || host.includes('bayt.') || host.includes('tanqeeb.');
                } catch (e) {
                    return false;
                }
            })());
            const isDirectEmployer = Boolean(payload.is_direct_employer_link !== undefined 
                ? payload.is_direct_employer_link 
                : (isEmployer && !isAggregator));

            channelTitle = (isEmployer || isDirectEmployer) ? 'Apply on Employer Site' : 'External Application Portal';
            channelBadgeClass = 'tag-channel-manual';
            channelIcon = 'fa-solid fa-arrow-up-right-from-square';

            const compName = (job.company && job.company !== 'Unknown') ? job.company : 'Employer';
            const siteLabel = job.site ? formatSiteName(job.site) : 'Job Board';

            let linkLabel = 'Application Link:';
            let descNote = '';
            let btnText = 'Open Application Link';

            if (isDirectEmployer) {
                linkLabel = 'Employer Application Link:';
                descNote = `Direct application on ${escapeHtml(compName)}'s careers portal.`;
                btnText = `Apply on ${escapeHtml(compName)} Site`;
            } else if (isAggregator && isEmployer) {
                linkLabel = `Listing on ${escapeHtml(siteLabel)}:`;
                descNote = `This role requires applying directly on ${escapeHtml(compName)}'s site. ${escapeHtml(siteLabel)} handles the outbound application redirection.`;
                btnText = `Open on ${escapeHtml(siteLabel)} to Apply`;
            } else {
                const hasDistinctPortal = Boolean(portalUrl && job.job_url && portalUrl.trim().replace(/\/+$/, '') !== job.job_url.trim().replace(/\/+$/, ''));
                descNote = hasDistinctPortal ? 'External employer application portal.' : 'Direct employer application gateway.';
                btnText = 'Open Application Link';
            }

            detailRows = `
                <div class="detail-row">
                    <span class="detail-label"><i class="fa-solid fa-link"></i> ${linkLabel}</span>
                    <span class="detail-value" style="max-width: 450px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;"><a href="${escapeHtml(portalUrl)}" target="_blank" style="color: #60a5fa;">${escapeHtml(portalUrl || 'Direct External Portal')}</a></span>
                </div>
                <div class="detail-row" style="font-size: 0.8rem; color: #93c5fd;">
                    <i class="fa-solid fa-arrow-up-right-from-square"></i> ${descNote}
                </div>
            `;
            if (copilotBtn) {
                copilotBtn.innerHTML = `<i class="fa-solid fa-arrow-up-right-from-square"></i> ${btnText}`;
                copilotBtn.className = 'btn btn-primary';
                copilotBtn.style.display = 'inline-flex';
            }
        }

        applyBoxEl.innerHTML = `
            <div class="badge-header">
                <span style="font-weight: 600; color: var(--text-main); font-size: 0.95rem;">Application Intelligence</span>
                <span class="tag-channel ${channelBadgeClass}"><i class="${channelIcon}"></i>${channelTitle}</span>
            </div>
            ${detailRows}
        `;
    }

    if (contentEl) contentEl.textContent = currentModalJobText;

    // View Original Job link - ONLY show when distinct from primary action destination
    const normJobUrl = (job.job_url || '').trim().replace(/\/+$/, '');
    const normPrimaryUrl = (primaryActionUrl || '').trim().replace(/\/+$/, '');
    const isDistinctAction = Boolean(
        normPrimaryUrl && 
        normJobUrl && 
        normPrimaryUrl !== normJobUrl && 
        !normPrimaryUrl.startsWith('javascript:')
    );

    if (viewLinkEl) {
        const hasJobLink = Boolean(normJobUrl && (normJobUrl.startsWith('http://') || normJobUrl.startsWith('https://')));
        if (hasJobLink && isDistinctAction) {
            viewLinkEl.href = job.job_url;
            const siteLabel = job.site ? formatSiteName(job.site) : 'Listing';
            viewLinkEl.innerHTML = `<i class="fa-solid fa-arrow-up-right-from-square"></i> View on ${escapeHtml(siteLabel)}`;
            viewLinkEl.classList.remove('hidden');
        } else {
            // Hide the duplicate secondary link when primary button opens the same URL
            viewLinkEl.classList.add('hidden');
        }
    }

    // Applied toggle button state
    if (appliedToggleBtn) {
        if (job.is_applied === 1) {
            appliedToggleBtn.innerHTML = '<i class="fa-solid fa-check"></i> Applied';
            appliedToggleBtn.style.backgroundColor = 'var(--success)';
        } else {
            appliedToggleBtn.innerHTML = '<i class="fa-solid fa-check"></i> Mark Applied';
            appliedToggleBtn.style.backgroundColor = '';
        }
    }

    const modal = document.getElementById('job-details-modal');
    if (modal) modal.classList.remove('hidden');
}

function hideJobDetailsModal() {
    const modal = document.getElementById('job-details-modal');
    if (modal) modal.classList.add('hidden');
}

// Backwards compatibility alias
function openJobTextModal(jobId) {
    openJobDetailsModal(jobId);
}

function hideJobTextModal() {
    hideJobDetailsModal();
}

function toggleAppliedFromModal() {
    if (!currentModalJobId) return;
    toggleApplied(currentModalJobId);
    const job = allJobs.find(j => String(j.job_id) === String(currentModalJobId));
    if (job) {
        const appliedToggleBtn = document.getElementById('job-details-applied-toggle-btn');
        if (appliedToggleBtn) {
            // Optimistic toggle
            const newState = job.is_applied === 1 ? 0 : 1;
            if (newState === 1) {
                appliedToggleBtn.innerHTML = '<i class="fa-solid fa-check"></i> Applied';
                appliedToggleBtn.style.backgroundColor = 'var(--success)';
            } else {
                appliedToggleBtn.innerHTML = '<i class="fa-solid fa-check"></i> Mark Applied';
                appliedToggleBtn.style.backgroundColor = '';
            }
        }
    }
}

function launchCoPilotApply() {
    if (!currentModalJobId) return;
    const job = allJobs.find(j => String(j.job_id) === String(currentModalJobId));
    if (!job) return;

    let payload = {};
    if (job.apply_payload) {
        try {
            payload = typeof job.apply_payload === 'string' ? JSON.parse(job.apply_payload) : job.apply_payload;
        } catch (e) {
            payload = {};
        }
    }

    const applyType = (job.apply_type || 'manual').toLowerCase();

    if (applyType === 'email') {
        openEmailCopilotModal(job.job_id);
        return;
    } else if (applyType === 'whatsapp') {
        openWhatsAppCopilotModal(job.job_id);
        return;
    } else if (applyType === 'easy_apply') {
        openEasyApplyCopilotModal(job.job_id);
        return;
    } else if (applyType === 'platform' || applyType === 'form') {
        openAtsCopilotModal(job.job_id);
        return;
    } else if (applyType === 'social_post') {
        const postUrl = payload.post_url || job.job_url;
        if (postUrl) {
            window.open(postUrl, '_blank');
            showToast('Opened LinkedIn post in new tab!', 'info', 'fa-brands fa-linkedin');
        } else {
            showToast('No post URL found.', 'warning', 'fa-circle-exclamation');
        }
    } else if (applyType === 'job_board') {
        const boardUrl = payload.job_url || job.job_url;
        if (boardUrl) {
            window.open(boardUrl, '_blank');
            showToast(`Opened on ${payload.board_name || 'job board'}!`, 'info', 'fa-briefcase');
        } else {
            showToast('No job URL found.', 'warning', 'fa-circle-exclamation');
        }
    } else {
        const targetUrl = payload.portal_url || payload.job_url || job.job_url;
        if (targetUrl) {
            window.open(targetUrl, '_blank');
            showToast('Opening external application portal...', 'info', 'fa-arrow-up-right-from-square');
        } else {
            showToast('No external link found for this job.', 'warning', 'fa-circle-exclamation');
        }
    }
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

// ==========================================
// Direct Email Co-Pilot Modal & Actions
// ==========================================
let currentEmailJobId = null;
let currentEmailCvPath = null;
let currentEmailRawBody = null;
let currentEmailPersonalSig = null;

async function openEmailCopilotModal(jobId) {
    currentEmailJobId = jobId;
    const job = allJobs.find(j => String(j.job_id) === String(jobId));
    if (!job) {
        showToast('Job not found.', 'warning', 'fa-circle-exclamation');
        return;
    }

    const modal = document.getElementById('email-copilot-modal');
    if (!modal) return;

    // Reset status banner
    const statusBanner = document.getElementById('email-copilot-status-banner');
    if (statusBanner) statusBanner.style.display = 'none';

    // Reset fields to loading state
    const titleEl = document.getElementById('email-copilot-job-title');
    if (titleEl) titleEl.textContent = job.title || 'Job Application';
    
    const compEl = document.getElementById('email-copilot-job-company');
    if (compEl) compEl.textContent = (job.company && job.company !== 'Unknown') ? job.company : '';
    
    let payload = {};
    if (job.apply_payload) {
        try {
            payload = typeof job.apply_payload === 'string' ? JSON.parse(job.apply_payload) : job.apply_payload;
        } catch (e) {
            payload = {};
        }
    }
    
    const recipEl = document.getElementById('email-copilot-recipient');
    if (recipEl) recipEl.value = payload.recipient_email || '';

    const subEl = document.getElementById('email-copilot-subject');
    if (subEl) subEl.value = payload.subject_hint || `Application for ${job.title} - Mohamed Hussein`;
    
    const bodyEl = document.getElementById('email-copilot-body');
    if (bodyEl) {
        bodyEl.value = '⏳ Drafting tailored cold email with Gemini AI...\n\nAnalyzing job requirements and extracting relevant highlights from your role CV in OneDrive...';
        bodyEl.disabled = true;
    }

    const outlookBtn = document.getElementById('email-copilot-outlook-btn');
    const appliedBtn = document.getElementById('email-copilot-applied-btn');

    if (outlookBtn) {
        outlookBtn.disabled = true;
        outlookBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Generating AI Draft...';
    }
    if (appliedBtn) {
        appliedBtn.style.display = job.is_applied === 1 ? 'none' : 'inline-flex';
        appliedBtn.className = 'btn btn-secondary';
        appliedBtn.innerHTML = '<i class="fa-solid fa-check"></i> Mark as Applied';
    }

    modal.classList.remove('hidden');

    try {
        const res = await fetch('/api/email/generate-draft', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ job_id: jobId })
        });
        const data = await res.json();

        if (data.status === 'success' || data.body) {
            if (recipEl) recipEl.value = data.recipient_email || payload.recipient_email || '';
            if (subEl) subEl.value = data.subject || `Application for ${job.title} - Mohamed Hussein`;
            if (bodyEl) {
                bodyEl.value = data.body || '';
                bodyEl.disabled = false;
            }

            currentEmailRawBody = data.raw_ai_body || data.body || '';
            currentEmailPersonalSig = data.personal_signature || '';

            const cvInfo = data.attached_cv || {};
            currentEmailCvPath = cvInfo.path || null;

            const cvFilenameEl = document.getElementById('email-copilot-cv-filename');
            const cvMetaEl = document.getElementById('email-copilot-cv-meta');
            if (cvFilenameEl) cvFilenameEl.textContent = cvInfo.filename || 'Mohamed_Hussein_CV.pdf';
            if (cvMetaEl) {
                const sizeText = cvInfo.size_kb ? `${cvInfo.size_kb} KB` : '';
                const pathText = cvInfo.path || 'OneDrive resume folder';
                cvMetaEl.textContent = `${sizeText ? sizeText + ' • ' : ''}${pathText}`;
            }

            const badgeEl = document.getElementById('email-copilot-engine-badge');
            if (badgeEl) {
                if (data.engine === 'gemini') {
                    badgeEl.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Gemini AI Tailored';
                } else {
                    badgeEl.innerHTML = '<i class="fa-solid fa-file-lines"></i> Template Draft';
                }
            }

            if (outlookBtn) {
                outlookBtn.disabled = false;
                outlookBtn.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Open in Outlook (Auto-Attached)';
            }
        } else {
            if (bodyEl) {
                bodyEl.value = 'Failed to generate draft. Please write your message here.';
                bodyEl.disabled = false;
            }
            if (outlookBtn) {
                outlookBtn.disabled = false;
                outlookBtn.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Open in Outlook (Auto-Attached)';
            }
        }
    } catch (err) {
        console.error('Error generating draft:', err);
        if (bodyEl) {
            bodyEl.value = 'Error connecting to server to generate draft. Please enter your email body manually.';
            bodyEl.disabled = false;
        }
        if (outlookBtn) {
            outlookBtn.disabled = false;
            outlookBtn.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Open in Outlook (Auto-Attached)';
        }
    }
}

function hideEmailCopilotModal() {
    const modal = document.getElementById('email-copilot-modal');
    if (modal) modal.classList.add('hidden');
}

function regenerateEmailDraft() {
    if (currentEmailJobId) {
        openEmailCopilotModal(currentEmailJobId);
    }
}

async function copyCvToClipboard() {
    if (!currentEmailCvPath) {
        showToast('No CV file path found.', 'warning', 'fa-circle-exclamation');
        return;
    }
    try {
        const res = await fetch('/api/email/copy-cv', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ cv_path: currentEmailCvPath })
        });
        const data = await res.json();
        if (data.status === 'success') {
            showToast('Copied CV file to clipboard!', 'success', 'fa-paperclip');
        } else {
            showToast('Could not copy CV to clipboard.', 'warning', 'fa-triangle-exclamation');
        }
    } catch (err) {
        console.error('Error copying CV:', err);
        showToast('Failed to copy CV.', 'error', 'fa-circle-exclamation');
    }
}

async function revealCvInExplorer() {
    if (!currentEmailCvPath) {
        showToast('No CV file path found.', 'warning', 'fa-circle-exclamation');
        return;
    }
    try {
        await fetch('/api/email/reveal-cv', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ cv_path: currentEmailCvPath })
        });
        showToast('Revealed CV in Windows File Explorer.', 'info', 'fa-folder-open');
    } catch (err) {
        console.error('Error revealing CV:', err);
    }
}

async function openDraftInOutlook() {
    const recipient = document.getElementById('email-copilot-recipient')?.value.trim() || '';
    const subject = document.getElementById('email-copilot-subject')?.value.trim() || '';
    const body = document.getElementById('email-copilot-body')?.value || '';

    const outlookBtn = document.getElementById('email-copilot-outlook-btn');
    if (outlookBtn) {
        outlookBtn.disabled = true;
        outlookBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Launching Outlook...';
    }

    try {
        const res = await fetch('/api/email/open-in-outlook', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                job_id: currentEmailJobId,
                recipient: recipient,
                subject: subject,
                body: body,
                raw_body: currentEmailRawBody,
                cv_path: currentEmailCvPath,
                personal_signature: currentEmailPersonalSig
            })
        });
        const data = await res.json();

        if (res.ok && data.status === 'success') {
            // Show status banner inside modal informing user to send & mark applied
            const statusBanner = document.getElementById('email-copilot-status-banner');
            if (statusBanner) {
                statusBanner.style.display = 'flex';
                statusBanner.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }

            // Highlight the Mark as Applied button in the footer
            const appliedBtn = document.getElementById('email-copilot-applied-btn');
            if (appliedBtn) {
                appliedBtn.style.display = 'inline-flex';
                appliedBtn.className = 'btn btn-primary';
                appliedBtn.style.background = '#10b981';
                appliedBtn.style.borderColor = '#10b981';
                appliedBtn.innerHTML = '<i class="fa-solid fa-check"></i> Mark as Applied';
            }

            showToast('✓ Outlook opened with CV attached! Review, click Send in Outlook, then click "Mark as Applied".', 'success', 'fa-envelope-open-text');
        } else {
            showToast(data.detail || 'Failed to open Outlook compose window.', 'danger', 'fa-circle-xmark');
        }
    } catch (err) {
        console.error('Error launching Outlook:', err);
        showToast('Error launching Outlook.', 'danger', 'fa-circle-xmark');
    } finally {
        if (outlookBtn) {
            outlookBtn.disabled = false;
            outlookBtn.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Open in Outlook (Auto-Attached)';
        }
    }
}

async function markCurrentEmailJobApplied() {
    if (!currentEmailJobId) return;

    const recipient = document.getElementById('email-copilot-recipient')?.value.trim() || '';
    const subject = document.getElementById('email-copilot-subject')?.value.trim() || '';
    const body = document.getElementById('email-copilot-body')?.value || '';

    const appliedBtn = document.getElementById('email-copilot-applied-btn');
    if (appliedBtn) {
        appliedBtn.disabled = true;
        appliedBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Marking Applied...';
    }

    try {
        const res = await fetch('/api/email/mark-applied', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                job_id: currentEmailJobId,
                recipient: recipient,
                subject: subject,
                body: body,
                applied_via: 'outlook_copilot'
            })
        });

        if (res.ok) {
            // Update local state
            const job = allJobs.find(j => String(j.job_id) === String(currentEmailJobId));
            if (job) {
                job.is_applied = 1;
                job.apply_status = 'applied';
            }
            const appliedToggleBtn = document.getElementById('job-details-applied-toggle-btn');
            if (appliedToggleBtn) {
                appliedToggleBtn.innerHTML = '<i class="fa-solid fa-check"></i> Applied';
                appliedToggleBtn.style.backgroundColor = 'var(--success)';
            }
            const cardAppliedBtn = document.querySelector(`.job-card[data-job-id="${currentEmailJobId}"] .btn-apply`);
            if (cardAppliedBtn) {
                cardAppliedBtn.innerHTML = '<i class="fa-solid fa-check"></i> Applied';
                cardAppliedBtn.style.backgroundColor = 'var(--success)';
            }

            hideEmailCopilotModal();
            showToast('✓ Job marked as Applied successfully!', 'success', 'fa-circle-check');
        } else {
            showToast('Failed to mark job as applied.', 'danger', 'fa-circle-xmark');
        }
    } catch (err) {
        console.error('Error marking applied:', err);
        showToast('Error marking job as applied.', 'danger', 'fa-circle-xmark');
    } finally {
        if (appliedBtn) {
            appliedBtn.disabled = false;
            appliedBtn.innerHTML = '<i class="fa-solid fa-check"></i> Mark as Applied';
        }
    }
}

// ==========================================
// WhatsApp Application Co-Pilot Functions
// ==========================================
let currentWhatsAppJobId = null;
let currentWhatsAppPhone = null;
let currentWhatsAppCvPath = null;
let currentWhatsAppTargetUrl = null;

async function openWhatsAppCopilotModal(jobId) {
    currentWhatsAppJobId = jobId;
    const job = allJobs.find(j => String(j.job_id) === String(jobId));
    if (!job) {
        showToast('Job details not found.', 'warning', 'fa-circle-exclamation');
        return;
    }

    const modal = document.getElementById('whatsapp-copilot-modal');
    if (!modal) return;

    // Reset status banner
    const statusBanner = document.getElementById('whatsapp-copilot-status-banner');
    if (statusBanner) statusBanner.style.display = 'none';

    // Set job title & company
    const titleEl = document.getElementById('whatsapp-copilot-job-title');
    if (titleEl) titleEl.textContent = job.title || 'Job Application';

    const compEl = document.getElementById('whatsapp-copilot-job-company');
    if (compEl) compEl.textContent = (job.company && job.company !== 'Unknown') ? job.company : '';

    let payload = {};
    if (job.apply_payload) {
        try {
            payload = typeof job.apply_payload === 'string' ? JSON.parse(job.apply_payload) : job.apply_payload;
        } catch (e) {
            payload = {};
        }
    }

    const rawPhone = payload.phone || '';
    const phoneEl = document.getElementById('whatsapp-copilot-phone');
    if (phoneEl) phoneEl.value = rawPhone ? (rawPhone.startsWith('+') ? rawPhone : `+${rawPhone}`) : '';

    const targetUrl = payload.whatsapp_url || (rawPhone ? `https://wa.me/${rawPhone}` : '');
    currentWhatsAppTargetUrl = targetUrl;
    const targetUrlEl = document.getElementById('whatsapp-copilot-target-url');
    if (targetUrlEl) targetUrlEl.value = targetUrl || 'No direct URL';

    const pitchEl = document.getElementById('whatsapp-copilot-pitch');
    if (pitchEl) {
        pitchEl.value = '⏳ Drafting tailored WhatsApp outreach pitch with Gemini AI...\n\nAnalyzing job requirements and extracting relevant highlights from your role CV in OneDrive...';
        pitchEl.disabled = true;
    }

    const desktopBtn = document.getElementById('whatsapp-copilot-desktop-btn');
    const appliedBtn = document.getElementById('whatsapp-copilot-applied-btn');

    if (desktopBtn) {
        desktopBtn.disabled = true;
        desktopBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Generating AI Pitch...';
    }
    if (appliedBtn) {
        appliedBtn.style.display = job.is_applied === 1 ? 'none' : 'inline-flex';
        appliedBtn.className = 'btn btn-secondary';
        appliedBtn.style.borderColor = 'rgba(37, 211, 102, 0.4)';
        appliedBtn.style.color = '#34d399';
        appliedBtn.innerHTML = '<i class="fa-solid fa-check"></i> Mark as Applied';
    }

    modal.classList.remove('hidden');

    try {
        const res = await fetch('/api/whatsapp/generate-pitch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ job_id: jobId })
        });
        const data = await res.json();

        if (data.status === 'success' || data.pitch) {
            if (phoneEl && data.phone) {
                currentWhatsAppPhone = data.phone;
                phoneEl.value = `+${data.phone}`;
            } else if (rawPhone) {
                currentWhatsAppPhone = rawPhone.replace(/\D/g, '');
            }

            if (targetUrlEl && data.whatsapp_url) {
                currentWhatsAppTargetUrl = data.whatsapp_url;
                targetUrlEl.value = data.whatsapp_url;
            }

            if (pitchEl) {
                pitchEl.value = data.pitch || '';
                pitchEl.disabled = false;
            }

            const cvInfo = data.attached_cv || {};
            currentWhatsAppCvPath = cvInfo.path || null;

            const cvFilenameEl = document.getElementById('whatsapp-copilot-cv-filename');
            const cvMetaEl = document.getElementById('whatsapp-copilot-cv-meta');
            if (cvFilenameEl) cvFilenameEl.textContent = cvInfo.filename || 'Mohamed_Hussein_CV.pdf';
            if (cvMetaEl) {
                const sizeText = cvInfo.size_kb ? `${cvInfo.size_kb} KB` : '';
                const pathText = cvInfo.path || 'OneDrive resume folder';
                cvMetaEl.textContent = `${sizeText ? sizeText + ' • ' : ''}${pathText}`;
            }

            const badgeEl = document.getElementById('whatsapp-copilot-engine-badge');
            if (badgeEl) {
                if (data.engine && data.engine.includes('gemini')) {
                    badgeEl.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Gemini AI Tailored';
                } else {
                    badgeEl.innerHTML = '<i class="fa-solid fa-file-lines"></i> Template Pitch';
                }
            }

            if (desktopBtn) {
                desktopBtn.disabled = false;
                desktopBtn.innerHTML = '<i class="fa-brands fa-whatsapp"></i> Open in WhatsApp Desktop (Auto-Attached)';
            }
        } else {
            if (pitchEl) {
                pitchEl.value = 'Failed to generate pitch. Please write your message here.';
                pitchEl.disabled = false;
            }
            if (desktopBtn) {
                desktopBtn.disabled = false;
                desktopBtn.innerHTML = '<i class="fa-brands fa-whatsapp"></i> Open in WhatsApp Desktop';
            }
        }
    } catch (err) {
        console.error('Error generating WhatsApp pitch:', err);
        if (pitchEl) {
            pitchEl.value = 'Error connecting to server to generate pitch. Please enter your message manually.';
            pitchEl.disabled = false;
        }
        if (desktopBtn) {
            desktopBtn.disabled = false;
            desktopBtn.innerHTML = '<i class="fa-brands fa-whatsapp"></i> Open in WhatsApp Desktop';
        }
    }
}

function hideWhatsAppCopilotModal() {
    const modal = document.getElementById('whatsapp-copilot-modal');
    if (modal) modal.classList.add('hidden');
}

function regenerateWhatsAppPitch() {
    if (currentWhatsAppJobId) {
        openWhatsAppCopilotModal(currentWhatsAppJobId);
    }
}

function copyWhatsAppPhone() {
    const phone = document.getElementById('whatsapp-copilot-phone')?.value.trim() || '';
    if (!phone) {
        showToast('No phone number to copy.', 'warning', 'fa-circle-exclamation');
        return;
    }
    navigator.clipboard.writeText(phone).then(() => {
        showToast('Copied phone number to clipboard!', 'success', 'fa-copy');
    }).catch(err => {
        console.error('Clipboard copy failed:', err);
        showToast('Failed to copy phone.', 'error', 'fa-circle-exclamation');
    });
}

function openDirectWhatsAppUrl() {
    const targetUrl = document.getElementById('whatsapp-copilot-target-url')?.value.trim() || currentWhatsAppTargetUrl;
    if (targetUrl && (targetUrl.startsWith('http://') || targetUrl.startsWith('https://'))) {
        window.open(targetUrl, '_blank');
        showToast('Opened target WhatsApp link in browser!', 'info', 'fa-arrow-up-right-from-square');
    } else {
        showToast('No valid URL to open.', 'warning', 'fa-circle-exclamation');
    }
}

function copyWhatsAppPitchText() {
    const pitch = document.getElementById('whatsapp-copilot-pitch')?.value || '';
    if (!pitch.trim()) {
        showToast('No pitch text to copy.', 'warning', 'fa-circle-exclamation');
        return;
    }
    navigator.clipboard.writeText(pitch).then(() => {
        showToast('Copied message to clipboard!', 'success', 'fa-copy');
    }).catch(err => {
        console.error('Clipboard copy failed:', err);
        showToast('Failed to copy text.', 'error', 'fa-circle-exclamation');
    });
}

async function copyWhatsAppCVFile() {
    if (!currentWhatsAppCvPath) {
        showToast('No CV file path found.', 'warning', 'fa-circle-exclamation');
        return;
    }
    try {
        const res = await fetch('/api/whatsapp/copy-cv', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ cv_path: currentWhatsAppCvPath })
        });
        const data = await res.json();
        if (data.status === 'success') {
            showToast('Copied CV file to clipboard! (Press Ctrl+V in WhatsApp to attach)', 'success', 'fa-paperclip');
        } else {
            showToast('Could not copy CV to clipboard.', 'warning', 'fa-triangle-exclamation');
        }
    } catch (err) {
        console.error('Error copying CV:', err);
        showToast('Failed to copy CV.', 'error', 'fa-circle-exclamation');
    }
}

async function revealWhatsAppCVFolder() {
    if (!currentWhatsAppCvPath) {
        showToast('No CV file path found.', 'warning', 'fa-circle-exclamation');
        return;
    }
    try {
        await fetch('/api/whatsapp/reveal-cv', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ cv_path: currentWhatsAppCvPath })
        });
        showToast('Revealed CV in Windows File Explorer.', 'info', 'fa-folder-open');
    } catch (err) {
        console.error('Error revealing CV:', err);
    }
}

async function openWhatsAppInDesktop() {
    const phoneInput = document.getElementById('whatsapp-copilot-phone')?.value.trim() || '';
    const cleanPhone = phoneInput.replace(/\D/g, '') || currentWhatsAppPhone || '';
    const pitch = document.getElementById('whatsapp-copilot-pitch')?.value || '';

    const desktopBtn = document.getElementById('whatsapp-copilot-desktop-btn');
    if (desktopBtn) {
        desktopBtn.disabled = true;
        desktopBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Launching WhatsApp Desktop...';
    }

    try {
        const res = await fetch('/api/whatsapp/open-in-desktop', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                phone: cleanPhone,
                pitch: pitch,
                cv_path: currentWhatsAppCvPath,
                auto_attach: true
            })
        });
        const data = await res.json();

        if (res.ok && data.status === 'success') {
            // Show guidance banner inside modal
            const statusBanner = document.getElementById('whatsapp-copilot-status-banner');
            if (statusBanner) {
                statusBanner.style.display = 'flex';
                statusBanner.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }

            // Highlight the Mark as Applied button
            const appliedBtn = document.getElementById('whatsapp-copilot-applied-btn');
            if (appliedBtn) {
                appliedBtn.style.display = 'inline-flex';
                appliedBtn.className = 'btn btn-primary';
                appliedBtn.style.background = '#25D366';
                appliedBtn.style.borderColor = '#25D366';
                appliedBtn.style.color = '#000';
                appliedBtn.innerHTML = '<i class="fa-solid fa-check"></i> Mark as Applied';
            }

            showToast('✓ WhatsApp Desktop opened with CV attached! Review, click Send in WhatsApp, then click "Mark as Applied".', 'success', 'fa-brands fa-whatsapp');
        } else {
            showToast(data.detail || 'Failed to open WhatsApp Desktop.', 'danger', 'fa-circle-xmark');
        }
    } catch (err) {
        console.error('Error launching WhatsApp Desktop:', err);
        showToast('Error launching WhatsApp Desktop.', 'danger', 'fa-circle-xmark');
    } finally {
        if (desktopBtn) {
            desktopBtn.disabled = false;
            desktopBtn.innerHTML = '<i class="fa-brands fa-whatsapp"></i> Open in WhatsApp Desktop (Auto-Attached)';
        }
    }
}

async function markCurrentWhatsAppJobApplied() {
    if (!currentWhatsAppJobId) return;

    const phoneInput = document.getElementById('whatsapp-copilot-phone')?.value.trim() || '';
    const cleanPhone = phoneInput.replace(/\D/g, '') || currentWhatsAppPhone || '';
    const pitch = document.getElementById('whatsapp-copilot-pitch')?.value || '';

    const appliedBtn = document.getElementById('whatsapp-copilot-applied-btn');
    if (appliedBtn) {
        appliedBtn.disabled = true;
        appliedBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Marking Applied...';
    }

    try {
        const res = await fetch('/api/whatsapp/mark-applied', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                job_id: currentWhatsAppJobId,
                phone: cleanPhone,
                pitch: pitch,
                applied_via: 'whatsapp_desktop'
            })
        });

        if (res.ok) {
            // Update local state
            const job = allJobs.find(j => String(j.job_id) === String(currentWhatsAppJobId));
            if (job) {
                job.is_applied = 1;
                job.apply_status = 'applied';
            }
            const appliedToggleBtn = document.getElementById('job-details-applied-toggle-btn');
            if (appliedToggleBtn) {
                appliedToggleBtn.innerHTML = '<i class="fa-solid fa-check"></i> Applied';
                appliedToggleBtn.style.backgroundColor = 'var(--success)';
            }
            const cardAppliedBtn = document.querySelector(`.job-card[data-job-id="${currentWhatsAppJobId}"] .btn-apply`);
            if (cardAppliedBtn) {
                cardAppliedBtn.innerHTML = '<i class="fa-solid fa-check"></i> Applied';
                cardAppliedBtn.style.backgroundColor = 'var(--success)';
            }

            hideWhatsAppCopilotModal();
            showToast('✓ Job marked as Applied via WhatsApp successfully!', 'success', 'fa-circle-check');
        } else {
            showToast('Failed to mark job as applied.', 'danger', 'fa-circle-xmark');
        }
    } catch (err) {
        console.error('Error marking WhatsApp job as applied:', err);
        showToast('Error marking job as applied.', 'danger', 'fa-circle-xmark');
    } finally {
        if (appliedBtn) {
            appliedBtn.disabled = false;
            appliedBtn.innerHTML = '<i class="fa-solid fa-check"></i> Mark as Applied';
        }
    }
}

// ==========================================
// Easy Apply Application Co-Pilot Functions
// ==========================================
let currentEasyApplyJobId = null;
let currentEasyApplyJobUrl = null;
let easyApplyPollTimer = null;

async function openEasyApplyCopilotModal(jobId) {
    currentEasyApplyJobId = jobId;
    if (easyApplyPollTimer) {
        clearInterval(easyApplyPollTimer);
        easyApplyPollTimer = null;
    }

    const job = allJobs.find(j => String(j.job_id) === String(jobId));
    if (!job) {
        showToast('Job details not found.', 'warning', 'fa-circle-exclamation');
        return;
    }

    const modal = document.getElementById('easy-apply-copilot-modal');
    if (!modal) return;

    // Reset status banner
    const statusBanner = document.getElementById('easy-apply-status-banner');
    if (statusBanner) statusBanner.style.display = 'none';

    // Set title and company
    const titleEl = document.getElementById('easy-apply-job-title');
    if (titleEl) titleEl.textContent = job.title || 'Easy Apply Application';

    const compEl = document.getElementById('easy-apply-job-company');
    if (compEl) compEl.textContent = (job.company && job.company !== 'Unknown') ? job.company : '';

    const badgeEl = document.getElementById('easy-apply-platform-badge');
    if (badgeEl) {
        const siteName = job.site ? formatSiteName(job.site) : 'Platform';
        badgeEl.innerHTML = `<i class="fa-solid fa-bolt"></i> ${siteName} Easy Apply`;
    }

    // Reset logs box & step tag
    const stepTag = document.getElementById('easy-apply-step-tag');
    if (stepTag) {
        stepTag.textContent = 'Ready';
        stepTag.style.color = '#f59e0b';
    }
    const logsBox = document.getElementById('easy-apply-logs-box');
    if (logsBox) {
        logsBox.innerHTML = '<div style="color: var(--text-muted);">Click "Start Assisted Pre-fill" to launch headed Chrome session.</div>';
    }

    const startBtn = document.getElementById('easy-apply-start-btn');
    const appliedBtn = document.getElementById('easy-apply-applied-btn');
    if (startBtn) {
        startBtn.disabled = false;
        startBtn.innerHTML = '<i class="fa-solid fa-bolt"></i> Start Assisted Pre-fill (Opens Headed Chrome)';
    }
    if (appliedBtn) {
        appliedBtn.style.display = job.is_applied === 1 ? 'none' : 'inline-flex';
        appliedBtn.className = 'btn btn-secondary';
        appliedBtn.style.borderColor = 'rgba(245, 158, 11, 0.4)';
        appliedBtn.style.color = '#fde68a';
        appliedBtn.innerHTML = '<i class="fa-solid fa-check"></i> Mark as Applied';
    }

    modal.classList.remove('hidden');

    try {
        const res = await fetch('/api/easy-apply/prepare', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ job_id: jobId })
        });
        const data = await res.json();

        if (data.status === 'success') {
            currentEasyApplyJobUrl = data.job_url;

            const contact = data.contact_preview || {};
            const nameEl = document.getElementById('easy-apply-contact-name');
            if (nameEl) nameEl.textContent = contact.full_name || 'Mohamed Hussein';

            const detailsEl = document.getElementById('easy-apply-contact-details');
            if (detailsEl) detailsEl.textContent = `${contact.email || ''} • ${contact.phone || ''}`;

            const locEl = document.getElementById('easy-apply-contact-location');
            if (locEl) locEl.innerHTML = `<i class="fa-solid fa-location-dot"></i> ${contact.city || 'Cairo'}, ${contact.country || 'Egypt'}`;

            const cvInfo = data.attached_cv || {};
            const cvFileEl = document.getElementById('easy-apply-cv-filename');
            if (cvFileEl) cvFileEl.textContent = cvInfo.filename || 'Mohamed_Hussein_CV.pdf';

            const cvMetaEl = document.getElementById('easy-apply-cv-meta');
            if (cvMetaEl) cvMetaEl.textContent = cvInfo.path || 'OneDrive role resume folder';

            const screening = data.screening_preview || {};
            const sponsorEl = document.getElementById('easy-apply-preview-sponsor');
            if (sponsorEl) {
                sponsorEl.textContent = screening.requires_sponsorship ? 'Required (Abroad)' : 'Not Required (Home)';
                sponsorEl.style.color = screening.requires_sponsorship ? '#fca5a5' : '#86efac';
            }

            const relocEl = document.getElementById('easy-apply-preview-reloc');
            if (relocEl) relocEl.textContent = screening.willing_to_relocate ? 'Open outside home' : 'Local only';

            const noticeEl = document.getElementById('easy-apply-preview-notice');
            if (noticeEl) noticeEl.textContent = `${screening.notice_period_days || 30} Days`;

            const salaryEl = document.getElementById('easy-apply-preview-salary');
            if (salaryEl) salaryEl.textContent = `${(screening.expected_salary_egp || 35000).toLocaleString()} EGP / $${screening.expected_salary_usd || 1500}`;
        }
    } catch (err) {
        console.error('Error preparing Easy Apply details:', err);
    }
}

function hideEasyApplyCopilotModal() {
    if (easyApplyPollTimer) {
        clearInterval(easyApplyPollTimer);
        easyApplyPollTimer = null;
    }
    const modal = document.getElementById('easy-apply-copilot-modal');
    if (modal) modal.classList.add('hidden');
}

function openEasyApplyJobUrlDirectly() {
    if (currentEasyApplyJobUrl && (currentEasyApplyJobUrl.startsWith('http://') || currentEasyApplyJobUrl.startsWith('https://'))) {
        window.open(currentEasyApplyJobUrl, '_blank');
        showToast('Opened job URL directly in new tab!', 'info', 'fa-arrow-up-right-from-square');
    } else {
        showToast('No valid URL found for this job.', 'warning', 'fa-circle-exclamation');
    }
}

async function startEasyApplySession() {
    if (!currentEasyApplyJobId) return;

    const startBtn = document.getElementById('easy-apply-start-btn');
    if (startBtn) {
        startBtn.disabled = true;
        startBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Launching Chrome...';
    }

    try {
        const res = await fetch('/api/easy-apply/launch-session', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ job_id: currentEasyApplyJobId, headed: true })
        });
        const data = await res.json();

        if (res.ok && data.status === 'success') {
            showToast('✓ Chrome launched! Pre-filling application...', 'info', 'fa-bolt');
            startEasyApplyPolling(currentEasyApplyJobId);
        } else {
            showToast(data.detail || 'Failed to start Easy Apply session.', 'danger', 'fa-circle-xmark');
            if (startBtn) {
                startBtn.disabled = false;
                startBtn.innerHTML = '<i class="fa-solid fa-bolt"></i> Start Assisted Pre-fill (Opens Headed Chrome)';
            }
        }
    } catch (err) {
        console.error('Error starting Easy Apply session:', err);
        showToast('Error launching Chrome session.', 'danger', 'fa-circle-xmark');
        if (startBtn) {
            startBtn.disabled = false;
            startBtn.innerHTML = '<i class="fa-solid fa-bolt"></i> Start Assisted Pre-fill (Opens Headed Chrome)';
        }
    }
}

function startEasyApplyPolling(jobId) {
    if (easyApplyPollTimer) clearInterval(easyApplyPollTimer);

    easyApplyPollTimer = setInterval(async () => {
        try {
            const res = await fetch(`/api/easy-apply/status/${jobId}`);
            if (!res.ok) return;
            const session = await res.json();

            // Update step tag
            const stepTag = document.getElementById('easy-apply-step-tag');
            if (stepTag) {
                stepTag.textContent = session.current_step || session.status;
                if (session.status === 'paused_for_review') {
                    stepTag.style.color = '#34d399';
                } else if (session.status === 'error') {
                    stepTag.style.color = '#f87171';
                } else {
                    stepTag.style.color = '#f59e0b';
                }
            }

            // Update logs box
            const logsBox = document.getElementById('easy-apply-logs-box');
            if (logsBox && session.logs && session.logs.length > 0) {
                logsBox.innerHTML = session.logs.map(line => {
                    const isPause = line.includes('CO-PILOT PAUSE') || line.includes('Paused at');
                    const isSuccess = line.includes('✓');
                    const isErr = line.includes('Error') || line.includes('error');
                    let color = '#cbd5e1';
                    if (isPause) color = '#86efac';
                    else if (isSuccess) color = '#38bdf8';
                    else if (isErr) color = '#fca5a5';
                    return `<div style="color: ${color};">${escapeHtml(line)}</div>`;
                }).join('');
                logsBox.scrollTop = logsBox.scrollHeight;
            }

            // Check if paused at review step
            if (session.status === 'paused_for_review') {
                clearInterval(easyApplyPollTimer);
                easyApplyPollTimer = null;

                const statusBanner = document.getElementById('easy-apply-status-banner');
                if (statusBanner) {
                    statusBanner.style.display = 'flex';
                    statusBanner.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                }

                const appliedBtn = document.getElementById('easy-apply-applied-btn');
                if (appliedBtn) {
                    appliedBtn.style.display = 'inline-flex';
                    appliedBtn.className = 'btn btn-primary';
                    appliedBtn.style.background = '#f59e0b';
                    appliedBtn.style.borderColor = '#f59e0b';
                    appliedBtn.style.color = '#000';
                    appliedBtn.innerHTML = '<i class="fa-solid fa-check"></i> Mark as Applied';
                }

                const startBtn = document.getElementById('easy-apply-start-btn');
                if (startBtn) {
                    startBtn.disabled = false;
                    startBtn.innerHTML = '<i class="fa-solid fa-arrows-rotate"></i> Re-run Pre-fill';
                }

                showToast('⏸ Easy Apply form ready! Review in Chrome and click Submit.', 'success', 'fa-circle-check');
            } else if (session.status === 'error') {
                clearInterval(easyApplyPollTimer);
                easyApplyPollTimer = null;
                const startBtn = document.getElementById('easy-apply-start-btn');
                if (startBtn) {
                    startBtn.disabled = false;
                    startBtn.innerHTML = '<i class="fa-solid fa-bolt"></i> Retry Pre-fill';
                }
            }
        } catch (e) {
            console.error('Polling error:', e);
        }
    }, 1200);
}

async function markCurrentEasyApplyJobApplied() {
    if (!currentEasyApplyJobId) return;

    const appliedBtn = document.getElementById('easy-apply-applied-btn');
    if (appliedBtn) {
        appliedBtn.disabled = true;
        appliedBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Marking Applied...';
    }

    try {
        const res = await fetch('/api/easy-apply/mark-applied', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                job_id: currentEasyApplyJobId,
                applied_via: 'easy_apply_copilot'
            })
        });

        if (res.ok) {
            const job = allJobs.find(j => String(j.job_id) === String(currentEasyApplyJobId));
            if (job) {
                job.is_applied = 1;
                job.apply_status = 'applied';
            }
            const appliedToggleBtn = document.getElementById('job-details-applied-toggle-btn');
            if (appliedToggleBtn) {
                appliedToggleBtn.innerHTML = '<i class="fa-solid fa-check"></i> Applied';
                appliedToggleBtn.style.backgroundColor = 'var(--success)';
            }
            const cardAppliedBtn = document.querySelector(`.job-card[data-job-id="${currentEasyApplyJobId}"] .btn-apply`);
            if (cardAppliedBtn) {
                cardAppliedBtn.innerHTML = '<i class="fa-solid fa-check"></i> Applied';
                cardAppliedBtn.style.backgroundColor = 'var(--success)';
            }

            hideEasyApplyCopilotModal();
            showToast('✓ Job marked as Applied via Easy Apply successfully!', 'success', 'fa-circle-check');
        } else {
            showToast('Failed to mark job as applied.', 'danger', 'fa-circle-xmark');
        }
    } catch (err) {
        console.error('Error marking Easy Apply job as applied:', err);
        showToast('Error marking job as applied.', 'danger', 'fa-circle-xmark');
    } finally {
        if (appliedBtn) {
            appliedBtn.disabled = false;
            appliedBtn.innerHTML = '<i class="fa-solid fa-check"></i> Mark as Applied';
        }
    }
}

// ==========================================
// Batch 5: Company ATS & Web Forms Co-Pilot
// ==========================================
let currentAtsJobId = null;
let currentAtsPortalUrl = '';
let currentAtsCvPath = '';
let currentAtsQuickCopy = {};
let atsPollingInterval = null;

async function openAtsCopilotModal(jobId) {
    currentAtsJobId = jobId;
    const modal = document.getElementById('ats-copilot-modal');
    if (!modal) return;

    const titleEl = document.getElementById('ats-job-title');
    const compEl = document.getElementById('ats-job-company');
    const badgeEl = document.getElementById('ats-platform-badge');
    const cvFileEl = document.getElementById('ats-cv-filename');
    const portalUrlEl = document.getElementById('ats-portal-url-display');
    const logsBox = document.getElementById('ats-logs-box');
    const stepTag = document.getElementById('ats-step-tag');
    const banner = document.getElementById('ats-status-banner');
    const startBtn = document.getElementById('ats-start-btn');
    const clTextEl = document.getElementById('ats-cover-letter-text');

    if (banner) banner.style.display = 'none';
    if (stepTag) stepTag.textContent = 'Ready';
    if (logsBox) logsBox.innerHTML = '<div style="color: var(--text-muted);">Preparing application details...</div>';
    if (startBtn) {
        startBtn.disabled = false;
        startBtn.innerHTML = '<i class="fa-solid fa-network-wired"></i> Start Assisted Pre-fill (Opens Headed Chrome)';
    }

    modal.classList.remove('hidden');

    try {
        const res = await fetch('/api/ats/prepare', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ job_id: jobId })
        });

        if (!res.ok) {
            showToast('Could not load application details.', 'danger', 'fa-circle-xmark');
            return;
        }

        const data = await res.json();
        currentAtsPortalUrl = data.portal_url || '';
        currentAtsCvPath = data.attached_cv ? data.attached_cv.path : '';
        currentAtsQuickCopy = data.quick_copy || {};

        if (titleEl) titleEl.textContent = data.title || 'Position';
        if (compEl) compEl.textContent = `${data.company || 'Company'} • ${data.location || 'Location'}`;

        if (badgeEl && data.platform_meta) {
            const meta = data.platform_meta;
            badgeEl.innerHTML = `<i class="${meta.icon || 'fa-solid fa-server'}"></i> ${meta.name || 'ATS Portal'}`;
            badgeEl.style.backgroundColor = `rgba(${hexToRgb(meta.color || '#6366f1')}, 0.15)`;
            badgeEl.style.color = meta.color || '#818cf8';
            badgeEl.style.borderColor = `rgba(${hexToRgb(meta.color || '#6366f1')}, 0.35)`;
        }

        if (portalUrlEl) {
            portalUrlEl.textContent = currentAtsPortalUrl;
            portalUrlEl.title = currentAtsPortalUrl;
        }

        if (cvFileEl && data.attached_cv) {
            cvFileEl.textContent = data.attached_cv.filename || 'Mohamed_Hussein_CV.pdf';
        }

        // Quick Copy populate
        const qc = data.quick_copy || {};
        const nameEl = document.getElementById('ats-qc-name');
        if (nameEl && qc.full_name) nameEl.textContent = qc.full_name;
        const emailEl = document.getElementById('ats-qc-email');
        if (emailEl && qc.email) emailEl.textContent = qc.email;
        const phoneEl = document.getElementById('ats-qc-phone');
        if (phoneEl && qc.phone) phoneEl.textContent = qc.phone;
        const salEl = document.getElementById('ats-qc-salary');
        if (salEl && qc.expected_salary_egp) salEl.textContent = `${qc.expected_salary_egp} / ${qc.expected_salary_usd}`;
        const noticeEl = document.getElementById('ats-qc-notice');
        if (noticeEl && qc.notice_period) noticeEl.textContent = qc.notice_period;
        const sponsEl = document.getElementById('ats-qc-sponsorship');
        if (sponsEl && qc.sponsorship_statement) sponsEl.textContent = qc.sponsorship_statement;

        // Cover letter populate
        if (clTextEl && data.cover_letter) {
            clTextEl.value = data.cover_letter;
        }

        if (logsBox) {
            logsBox.innerHTML = '<div style="color: #34d399;">✓ Application data prepared. Ready to launch assisted session or copy fields.</div>';
        }
    } catch (err) {
        console.error('Error preparing ATS modal:', err);
        showToast('Failed to load application data.', 'danger', 'fa-circle-xmark');
    }
}

function hexToRgb(hex) {
    hex = hex.replace('#', '');
    if (hex.length === 3) {
        hex = hex.split('').map(c => c + c).join('');
    }
    const num = parseInt(hex, 16);
    return `${(num >> 16) & 255}, ${(num >> 8) & 255}, ${num & 255}`;
}

function hideAtsCopilotModal() {
    if (atsPollingInterval) {
        clearInterval(atsPollingInterval);
        atsPollingInterval = null;
    }
    const modal = document.getElementById('ats-copilot-modal');
    if (modal) modal.classList.add('hidden');
}

function copyAtsField(fieldKey, btnEl) {
    let val = '';
    const qc = currentAtsQuickCopy || {};
    if (fieldKey === 'full_name') val = qc.full_name || 'Mohamed Hussein';
    else if (fieldKey === 'email') val = qc.email || 'mhmd7syn.contact@gmail.com';
    else if (fieldKey === 'phone') val = qc.phone || '+201012345678';
    else if (fieldKey === 'linkedin') val = qc.linkedin_url || 'https://www.linkedin.com/in/mhmd7syn';
    else if (fieldKey === 'github') val = qc.github_url || 'https://github.com/Mhmd7syn';
    else if (fieldKey === 'location') val = `${qc.city || 'Cairo'}, ${qc.country || 'Egypt'}`;
    else if (fieldKey === 'salary') val = qc.expected_salary_egp || '35000 EGP';
    else if (fieldKey === 'notice') val = qc.notice_period || '30 days';
    else if (fieldKey === 'sponsorship') val = qc.sponsorship_statement || 'Authorized for domestic; require visa for international';

    if (!val) return;

    navigator.clipboard.writeText(val).then(() => {
        showToast(`Copied ${fieldKey.replace('_', ' ')}!`, 'info', 'fa-copy');
        if (btnEl) {
            btnEl.classList.add('copied');
            setTimeout(() => btnEl.classList.remove('copied'), 1200);
        }
    }).catch(err => {
        console.error('Clipboard copy failed:', err);
    });
}

function copyAtsCoverLetter(btnEl) {
    const clTextEl = document.getElementById('ats-cover-letter-text');
    if (!clTextEl || !clTextEl.value) return;

    navigator.clipboard.writeText(clTextEl.value).then(() => {
        showToast('Cover letter copied to clipboard!', 'success', 'fa-copy');
        if (btnEl) {
            const orig = btnEl.innerHTML;
            btnEl.innerHTML = '<i class="fa-solid fa-check"></i> Copied!';
            setTimeout(() => { btnEl.innerHTML = orig; }, 1500);
        }
    }).catch(err => {
        console.error('Failed to copy cover letter:', err);
    });
}

async function regenerateAtsCoverLetter() {
    if (!currentAtsJobId) return;
    const clTextEl = document.getElementById('ats-cover-letter-text');
    if (clTextEl) clTextEl.value = 'Regenerating tailored cover letter with AI...';

    try {
        const res = await fetch('/api/ats/generate-cover-letter', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ job_id: currentAtsJobId })
        });
        if (res.ok) {
            const data = await res.json();
            if (clTextEl && data.cover_letter) {
                clTextEl.value = data.cover_letter;
                showToast('Cover letter regenerated!', 'success', 'fa-sparkles');
            }
        } else {
            showToast('Could not regenerate cover letter.', 'danger', 'fa-circle-xmark');
        }
    } catch (e) {
        console.error('Cover letter regeneration failed:', e);
    }
}

async function copyAtsCvFile() {
    if (!currentAtsCvPath) {
        showToast('CV file path not found.', 'warning', 'fa-circle-exclamation');
        return;
    }
    try {
        const res = await fetch('/api/whatsapp/copy-cv', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ cv_path: currentAtsCvPath })
        });
        if (res.ok) {
            showToast('✓ Role CV file copied to Windows clipboard!', 'success', 'fa-clipboard-check');
        } else {
            showToast('Could not copy CV to clipboard.', 'danger', 'fa-circle-xmark');
        }
    } catch (e) {
        console.error('Copy CV file failed:', e);
    }
}

async function revealAtsCvFolder() {
    if (!currentAtsCvPath) {
        showToast('CV file path not found.', 'warning', 'fa-circle-exclamation');
        return;
    }
    try {
        await fetch('/api/whatsapp/reveal-cv', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ cv_path: currentAtsCvPath })
        });
        showToast('Opened resume folder in Windows Explorer.', 'info', 'fa-folder-open');
    } catch (e) {
        console.error('Reveal CV folder failed:', e);
    }
}

function openAtsPortalDirectly() {
    if (currentAtsPortalUrl) {
        window.open(currentAtsPortalUrl, '_blank');
        showToast('Opened application portal in new tab.', 'info', 'fa-arrow-up-right-from-square');
    } else {
        showToast('No application portal URL found.', 'warning', 'fa-circle-exclamation');
    }
}

async function startAtsSession() {
    if (!currentAtsJobId) return;

    const startBtn = document.getElementById('ats-start-btn');
    const logsBox = document.getElementById('ats-logs-box');
    const stepTag = document.getElementById('ats-step-tag');
    const banner = document.getElementById('ats-status-banner');

    if (startBtn) {
        startBtn.disabled = true;
        startBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Initializing Chrome Session...';
    }
    if (banner) banner.style.display = 'none';
    if (stepTag) stepTag.textContent = 'Launching';
    if (logsBox) {
        logsBox.innerHTML = '<div style="color: #60a5fa;">[Init] Starting headed Chrome browser session...</div>';
    }

    try {
        const res = await fetch('/api/ats/launch-session', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                job_id: currentAtsJobId,
                headed: true
            })
        });

        if (res.ok) {
            showToast('🚀 Assisted Chrome session launched!', 'info', 'fa-globe');
            startAtsPolling(currentAtsJobId);
        } else {
            const err = await res.json();
            showToast(err.detail || 'Failed to start browser session.', 'danger', 'fa-circle-xmark');
            if (startBtn) {
                startBtn.disabled = false;
                startBtn.innerHTML = '<i class="fa-solid fa-rotate"></i> Retry Launch';
            }
        }
    } catch (err) {
        console.error('Error starting ATS session:', err);
        showToast('Error starting assisted session.', 'danger', 'fa-circle-xmark');
        if (startBtn) {
            startBtn.disabled = false;
            startBtn.innerHTML = '<i class="fa-solid fa-rotate"></i> Retry Launch';
        }
    }
}

function startAtsPolling(jobId) {
    if (atsPollingInterval) clearInterval(atsPollingInterval);

    atsPollingInterval = setInterval(async () => {
        try {
            const res = await fetch(`/api/ats/status/${jobId}`);
            if (!res.ok) return;

            const data = await res.json();
            const logsBox = document.getElementById('ats-logs-box');
            const stepTag = document.getElementById('ats-step-tag');
            const banner = document.getElementById('ats-status-banner');
            const startBtn = document.getElementById('ats-start-btn');

            if (stepTag && data.current_step) {
                stepTag.textContent = data.current_step.substring(0, 35);
            }

            if (logsBox && data.logs && data.logs.length > 0) {
                logsBox.innerHTML = data.logs.map(line => {
                    let color = '#cbd5e1';
                    if (line.includes('✓') || line.includes('Finished')) color = '#34d399';
                    else if (line.includes('🛑') || line.includes('Paused') || line.includes('🎯')) color = '#06b6d4';
                    else if (line.includes('Error') || line.includes('failed')) color = '#f87171';
                    else if (line.includes('Filled')) color = '#818cf8';
                    return `<div style="color: ${color};">${escapeHtml(line)}</div>`;
                }).join('');
                logsBox.scrollTop = logsBox.scrollHeight;
            }

            if (data.status === 'paused_for_review') {
                if (banner) banner.style.display = 'flex';
                if (stepTag) {
                    stepTag.textContent = 'Paused for Review';
                    stepTag.style.color = '#06b6d4';
                }
                const appliedBtn = document.getElementById('ats-applied-btn');
                if (appliedBtn) {
                    appliedBtn.classList.remove('btn-secondary');
                    appliedBtn.classList.add('btn-primary');
                    appliedBtn.style.background = '#10b981';
                    appliedBtn.style.borderColor = '#10b981';
                    appliedBtn.style.color = 'white';
                }
                if (startBtn) {
                    startBtn.disabled = false;
                    startBtn.innerHTML = '<i class="fa-solid fa-circle-check"></i> Pre-Fill Complete';
                }
            } else if (data.status === 'completed' || data.status === 'error') {
                clearInterval(atsPollingInterval);
                atsPollingInterval = null;
                if (startBtn) {
                    startBtn.disabled = false;
                    startBtn.innerHTML = '<i class="fa-solid fa-rotate"></i> Re-launch Session';
                }
            }
        } catch (e) {
            console.error('ATS polling error:', e);
        }
    }, 1200);
}

async function markCurrentAtsJobApplied() {
    if (!currentAtsJobId) return;

    const appliedBtn = document.getElementById('ats-applied-btn');
    if (appliedBtn) {
        appliedBtn.disabled = true;
        appliedBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Marking Applied...';
    }

    try {
        const res = await fetch('/api/ats/mark-applied', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                job_id: currentAtsJobId,
                applied_via: 'ats_copilot'
            })
        });

        if (res.ok) {
            const job = allJobs.find(j => String(j.job_id) === String(currentAtsJobId));
            if (job) {
                job.is_applied = 1;
                job.apply_status = 'applied';
            }
            const appliedToggleBtn = document.getElementById('job-details-applied-toggle-btn');
            if (appliedToggleBtn) {
                appliedToggleBtn.innerHTML = '<i class="fa-solid fa-check"></i> Applied';
                appliedToggleBtn.style.backgroundColor = 'var(--success)';
            }
            const cardAppliedBtn = document.querySelector(`.job-card[data-job-id="${currentAtsJobId}"] .btn-apply`);
            if (cardAppliedBtn) {
                cardAppliedBtn.innerHTML = '<i class="fa-solid fa-check"></i> Applied';
                cardAppliedBtn.style.backgroundColor = 'var(--success)';
            }

            hideAtsCopilotModal();
            showToast('✓ Job marked as Applied successfully!', 'success', 'fa-circle-check');
        } else {
            showToast('Failed to mark job as applied.', 'danger', 'fa-circle-xmark');
        }
    } catch (err) {
        console.error('Error marking ATS job as applied:', err);
        showToast('Error marking job as applied.', 'danger', 'fa-circle-xmark');
    } finally {
        if (appliedBtn) {
            appliedBtn.disabled = false;
            appliedBtn.innerHTML = '<i class="fa-solid fa-check"></i> Mark as Applied';
        }
    }
}

// ==========================================
// Batch 8: Applications Hub & Auto-Pilot UI
// ==========================================
let hubSearchTimeout = null;
let hubPollingInterval = null;

async function showApplicationsHub() {
    const modal = document.getElementById('applications-hub-modal');
    if (!modal) return;
    modal.classList.remove('hidden');
    loadApplicationsHubData();
    startHubStatusPolling();
}

function hideApplicationsHub() {
    if (hubPollingInterval) {
        clearInterval(hubPollingInterval);
        hubPollingInterval = null;
    }
    const modal = document.getElementById('applications-hub-modal');
    if (modal) modal.classList.add('hidden');
}

async function loadApplicationsHubData() {
    try {
        const statsRes = await fetch('/api/applications/stats');
        if (statsRes.ok) {
            const stats = await statsRes.json();
            renderHubStats(stats);
        }

        const searchInput = document.getElementById('hub-search-input');
        const channelSelect = document.getElementById('hub-channel-filter');
        const search = searchInput ? searchInput.value.trim() : '';
        const channel = channelSelect ? channelSelect.value : 'all';

        const historyRes = await fetch(`/api/applications/history?channel=${encodeURIComponent(channel)}&search=${encodeURIComponent(search)}&limit=50`);
        if (historyRes.ok) {
            const historyData = await historyRes.json();
            renderHubHistory(historyData.applications || []);
        }
    } catch (e) {
        console.error('Error loading Applications Hub data:', e);
    }
}

function renderHubStats(stats) {
    const totalEl = document.getElementById('hub-stat-total');
    const todayEl = document.getElementById('hub-stat-today');
    const emailsEl = document.getElementById('hub-stat-emails');
    const waEl = document.getElementById('hub-stat-whatsapp');
    const quotaEl = document.getElementById('hub-stat-quota');
    const logsTerminal = document.getElementById('hub-logs-terminal');

    if (totalEl) totalEl.textContent = stats.total_applied_all_time || 0;
    if (todayEl) todayEl.textContent = stats.applied_today || 0;
    if (emailsEl) emailsEl.textContent = stats.emails_sent_today || 0;
    if (waEl) waEl.textContent = stats.whatsapp_sent_today || 0;
    if (quotaEl) quotaEl.textContent = `${stats.daily_runs_done || 0} / ${stats.daily_runs_max || 5}`;

    const pausedBadge = document.getElementById('hub-paused-badge');
    const activeBadge = document.getElementById('hub-active-badge');
    const pausedNotice = document.getElementById('hub-paused-notice');
    const isPaused = stats.is_paused !== undefined ? stats.is_paused : !stats.is_enabled;

    if (pausedBadge) pausedBadge.classList.toggle('hidden', !isPaused);
    if (activeBadge) activeBadge.classList.toggle('hidden', isPaused);
    if (pausedNotice) pausedNotice.classList.toggle('hidden', !isPaused);

    if (logsTerminal && stats.recent_logs && stats.recent_logs.length > 0) {
        logsTerminal.innerHTML = stats.recent_logs.map(line => {
            let color = '#cbd5e1';
            if (line.includes('✓') || line.includes('Successfully')) color = '#34d399';
            else if (line.includes('Skipping') || line.includes('rate_limited') || line.includes('limit')) color = '#fde68a';
            else if (line.includes('Error') || line.includes('Failed')) color = '#f87171';
            else if (line.includes('Initiated') || line.includes('Completed')) color = '#818cf8';
            return `<div style="color: ${color};">${escapeHtml(line)}</div>`;
        }).join('');
        logsTerminal.scrollTop = logsTerminal.scrollHeight;
    }
}

function renderHubHistory(applications) {
    const tbody = document.getElementById('hub-history-tbody');
    if (!tbody) return;

    if (!applications || applications.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; padding: 2rem; color: var(--text-muted);"><i class="fa-solid fa-inbox" style="font-size: 1.5rem; display: block; margin-bottom: 0.5rem; opacity: 0.4;"></i>No applications recorded matching criteria.</td></tr>';
        return;
    }

    tbody.innerHTML = applications.map(app => {
        const title = escapeHtml(app.title || 'Untitled');
        const comp = escapeHtml(app.company || 'Unknown');
        const channel = (app.apply_type || app.apply_channel || 'manual').toLowerCase();
        const dateStr = app.applied_at || app.timestamp || 'Recent';

        let badgeClass = 'tag-channel-manual';
        let channelIcon = 'fa-solid fa-arrow-up-right-from-square';
        let channelName = channel.toUpperCase();

        if (channel === 'email') {
            badgeClass = 'tag-channel-email';
            channelIcon = 'fa-solid fa-envelope';
            channelName = 'Email';
        } else if (channel === 'whatsapp') {
            badgeClass = 'tag-channel-whatsapp';
            channelIcon = 'fa-brands fa-whatsapp';
            channelName = 'WhatsApp';
        } else if (channel === 'easy_apply') {
            badgeClass = 'tag-channel-easyapply';
            channelIcon = 'fa-solid fa-bolt';
            channelName = 'Easy Apply';
        } else if (channel === 'platform') {
            badgeClass = 'tag-channel-platform';
            channelIcon = 'fa-solid fa-server';
            channelName = 'ATS';
        } else if (channel === 'form') {
            badgeClass = 'tag-channel-form';
            channelIcon = 'fa-solid fa-file-waveform';
            channelName = 'Form';
        }

        return `
            <tr style="border-bottom: 1px solid rgba(255,255,255,0.05); transition: background 0.15s;">
                <td style="padding: 0.75rem 0.9rem;">
                    <div style="font-weight: 600; color: var(--text-main); font-size: 0.88rem;">${title}</div>
                    <div style="font-size: 0.76rem; color: var(--text-muted);">${comp}</div>
                </td>
                <td style="padding: 0.75rem 0.9rem;">
                    <span class="tag tag-channel ${badgeClass}" style="font-size: 0.72rem; padding: 0.15rem 0.5rem;">
                        <i class="${channelIcon}"></i> ${channelName}
                    </span>
                </td>
                <td style="padding: 0.75rem 0.9rem; color: var(--text-muted); font-size: 0.8rem; font-family: monospace;">
                    ${escapeHtml(dateStr)}
                </td>
                <td style="padding: 0.75rem 0.9rem;">
                    <span style="display: inline-flex; align-items: center; gap: 0.3rem; font-size: 0.75rem; color: #34d399; background: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.3); padding: 0.15rem 0.5rem; border-radius: 999px;">
                        <i class="fa-solid fa-check"></i> Applied
                    </span>
                </td>
                <td style="padding: 0.75rem 0.9rem; text-align: right;">
                    <button type="button" class="btn btn-secondary btn-sm" onclick="retryJobApplication('${escapeHtml(app.job_id)}')" title="Reset job back to pending state" style="font-size: 0.75rem; padding: 0.2rem 0.5rem;">
                        <i class="fa-solid fa-rotate-left"></i> Reset
                    </button>
                </td>
            </tr>
        `;
    }).join('');
}

function onHubSearchChange() {
    if (hubSearchTimeout) clearTimeout(hubSearchTimeout);
    hubSearchTimeout = setTimeout(() => {
        loadApplicationsHubData();
    }, 300);
}

function onHubFilterChange() {
    loadApplicationsHubData();
}

async function retryJobApplication(jobId) {
    if (!confirm('Reset this job back to unapplied pending state?')) return;
    try {
        const res = await fetch('/api/applications/retry', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ job_id: jobId })
        });
        if (res.ok) {
            showToast('Job reset to pending state.', 'info', 'fa-rotate-left');
            const job = allJobs.find(j => String(j.job_id) === String(jobId));
            if (job) {
                job.is_applied = 0;
                job.apply_status = 'pending';
            }
            loadApplicationsHubData();
        } else {
            showToast('Failed to reset job.', 'danger', 'fa-circle-xmark');
        }
    } catch (e) {
        console.error('Error resetting application:', e);
    }
}

async function triggerAutoPilotCycleNow() {
    const runBtn = document.getElementById('hub-run-cycle-btn');
    const runningBadge = document.getElementById('hub-running-badge');

    if (runBtn) {
        runBtn.disabled = true;
        runBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Running Cycle...';
    }
    if (runningBadge) runningBadge.classList.remove('hidden');

    try {
        const res = await fetch('/api/autopilot/run-cycle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ force: true, dry_run: false })
        });

        if (res.ok) {
            showToast('🚀 Auto-Pilot cycle triggered in background!', 'info', 'fa-rocket');
        } else {
            const err = await res.json();
            showToast(err.message || 'Failed to trigger Auto-Pilot cycle.', 'danger', 'fa-circle-xmark');
        }
    } catch (e) {
        console.error('Error triggering Auto-Pilot cycle:', e);
        showToast('Error triggering cycle.', 'danger', 'fa-circle-xmark');
    } finally {
        setTimeout(() => {
            if (runBtn) {
                runBtn.disabled = false;
                runBtn.innerHTML = '<i class="fa-solid fa-play"></i> Run Auto-Pilot Cycle Now';
            }
            loadApplicationsHubData();
        }, 2500);
    }
}

async function runEmailBatchDirect() {
    showToast('Executing direct email batch...', 'info', 'fa-envelope');
    try {
        const res = await fetch('/api/autopilot/run-email-batch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ force: true, dry_run: false })
        });
        if (res.ok) {
            const data = await res.json();
            showToast(data.message || 'Email batch completed.', 'success', 'fa-envelope-circle-check');
            loadApplicationsHubData();
        } else {
            showToast('Email batch failed.', 'danger', 'fa-circle-xmark');
        }
    } catch (e) {
        console.error('Error running email batch:', e);
    }
}

async function runWhatsAppBatchDirect() {
    showToast('Executing direct WhatsApp batch...', 'info', 'fa-brands fa-whatsapp');
    try {
        const res = await fetch('/api/autopilot/run-whatsapp-batch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ force: true, dry_run: false })
        });
        if (res.ok) {
            const data = await res.json();
            showToast(data.message || 'WhatsApp batch completed.', 'success', 'fa-circle-check');
            loadApplicationsHubData();
        } else {
            showToast('WhatsApp batch failed.', 'danger', 'fa-circle-xmark');
        }
    } catch (e) {
        console.error('Error running WhatsApp batch:', e);
    }
}

function startHubStatusPolling() {
    if (hubPollingInterval) clearInterval(hubPollingInterval);
    hubPollingInterval = setInterval(async () => {
        try {
            const res = await fetch('/api/autopilot/status');
            if (!res.ok) return;
            const data = await res.json();
            const runningBadge = document.getElementById('hub-running-badge');
            if (runningBadge) {
                if (data.is_cycle_running) {
                    runningBadge.classList.remove('hidden');
                } else {
                    runningBadge.classList.add('hidden');
                }
            }
        } catch (e) {
            // silent polling error
        }
    }, 3000);
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
