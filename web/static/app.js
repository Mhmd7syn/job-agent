let allJobs = [];
let currentConfig = {};
let currentJobsPage = 1;
const JOBS_PER_PAGE = 30;
let filteredJobsList = [];

document.addEventListener('DOMContentLoaded', () => {
    fetchJobs();
    fetchConfig();
    
    document.getElementById('search-input').addEventListener('input', applyFiltersAndSort);
    document.getElementById('show-not-related').addEventListener('change', applyFiltersAndSort);
    document.getElementById('applied-filter').addEventListener('change', applyFiltersAndSort);
    document.getElementById('role-filter').addEventListener('change', applyFiltersAndSort);
    document.getElementById('type-filter').addEventListener('change', applyFiltersAndSort);
    document.getElementById('setup-filter').addEventListener('change', applyFiltersAndSort);
    document.getElementById('site-filter').addEventListener('change', applyFiltersAndSort);
    document.getElementById('sort-filter').addEventListener('change', applyFiltersAndSort);
});

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
        if (searchTerm && !titleMatch && !companyMatch) return false;

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
            return (b.relevance_score || 0) - (a.relevance_score || 0);
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

    let actionsHtml = '';
    if (job.status === 'not_related') {
        actionsHtml = `
            <div style="flex-grow: 1; display: flex; align-items: center; color: var(--danger); font-weight: 500; cursor: pointer; transition: opacity 0.2s;" onclick="handleAction('${job.job_id}', 'pending')" title="Click to undo and move back to Pending" onmouseover="this.style.opacity=0.7" onmouseout="this.style.opacity=1">
                <i class="fa-solid fa-circle-xmark" style="margin-right: 6px;"></i>Not Related (Click to Undo)
            </div>
            ${applyBtnHtml}
            <a href="${job.job_url}" target="_blank" class="btn btn-view"><i class="fa-solid fa-arrow-up-right-from-square"></i>View Job</a>
        `;
    } else {
        actionsHtml = `
            ${job.status !== 'liked' ? 
                `<button class="btn btn-like" onclick="handleAction('${job.job_id}', 'liked')"><i class="fa-regular fa-heart"></i>Like</button>` : 
                `<button class="btn btn-like" disabled style="opacity: 0.5"><i class="fa-solid fa-heart"></i>Liked</button>`
            }
            <button class="btn btn-reject" onclick="handleAction('${job.job_id}', 'not_related')"><i class="fa-solid fa-xmark"></i>Not Related</button>
            ${applyBtnHtml}
            <a href="${job.job_url}" target="_blank" class="btn btn-view"><i class="fa-solid fa-arrow-up-right-from-square"></i>View Job</a>
        `;
    }

    div.innerHTML = `
        <div class="card-header">
            <h3 class="job-title" title="${job.title}">${job.title}</h3>
            <span class="job-score" title="Relevance Score"><i class="fa-solid fa-star" style="color:var(--warning); margin-right:4px;"></i>${Math.round(job.relevance_score || 0)}</span>
        </div>
        <div class="job-company"><i class="fa-regular fa-building" style="margin-right:6px;"></i>${job.company || 'Unknown Company'}</div>
        
        <div class="tags">
            <div class="tag"><i class="fa-solid fa-location-dot"></i>${job.location || 'Remote'}</div>
            <div class="tag"><i class="fa-solid fa-clock"></i>${job.job_type || 'Full-time'}</div>
            <div class="tag"><i class="fa-solid fa-globe"></i>${job.site || 'Web'}</div>
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
            showToast('CV Analyzed Successfully! Preferences auto-populated.', 'success', 'fa-check');
            
            if (data.resume_keywords) initTagInput('config-resume-keywords', data.resume_keywords);
            if (data.nice_to_have_skills) initTagInput('config-nice-skills', data.nice_to_have_skills);
            if (data.target_levels) initTagInput('config-target-levels', data.target_levels);
            if (data.user_brief) {
                const briefEl = document.getElementById('config-user-brief');
                if (briefEl) briefEl.value = data.user_brief;
            }
            if (data.location) initTagInput('config-location', [data.location]);

            if (data.target_roles && data.target_roles.length > 0) {
                currentConfig.ROLES = data.target_roles;
                renderRolesUI();
            }
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

function showSettings() {
    renderRolesUI();
    
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
    initTagInput('config-nice-skills', currentConfig.NICE_TO_HAVE_SKILLS || []);
    initTagInput('config-exclude-keywords', currentConfig.EXCLUDE_KEYWORDS || []);
    initTagInput('config-favorite-companies', currentConfig.FAVORITE_COMPANIES || []);
    initTagInput('config-excluded-companies', currentConfig.EXCLUDED_COMPANIES || []);
    
    initTagInput('config-sites', currentConfig.SITES || ['linkedin', 'wuzzuf', 'bayt', 'glassdoor', 'tanqeeb', 'indeed']);
    initTagInput('config-arabic-sites', currentConfig.SITES_FOR_ARABIC || ['wuzzuf', 'linkedin']);
    
    const rptEl = document.getElementById('config-results-per-term');
    if (rptEl) rptEl.value = currentConfig.RESULTS_PER_TERM || 15;
    const hoEl = document.getElementById('config-hours-old');
    if (hoEl) hoEl.value = currentConfig.HOURS_OLD || 168;
    const mjsEl = document.getElementById('config-max-jobs-send');
    if (mjsEl) mjsEl.value = currentConfig.MAX_JOBS_TO_SEND || 10;
    const retEl = document.getElementById('config-retention-days');
    if (retEl) retEl.value = currentConfig.job_retention_days || 90;
    
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
        const enTerms = getTagInputValues('role-en-' + index);
        const arTerms = getTagInputValues('role-ar-' + index);
        if (title || enTerms.length > 0 || arTerms.length > 0) {
            newRoles.push({
                title: title || 'Unnamed Role',
                english_terms: enTerms,
                arabic_terms: arTerms
            });
        }
    });
    newConfig.ROLES = newRoles;
    
    newConfig.LOCATION = getTagInputValues('config-location');
    newConfig.TARGET_LOCATIONS = getTagInputValues('config-target-locations');
    newConfig.GLASSDOOR_LOC_ID = parseInt(document.getElementById('config-glassdoor-id').value) || 69;
    newConfig.GLOBAL_REMOTE_KEYWORDS = getTagInputValues('config-global-remote');
    newConfig.RESTRICTED_REMOTE_KEYWORDS = getTagInputValues('config-restricted-remote');
    newConfig.TARGET_LEVELS = getTagInputValues('config-target-levels');
    newConfig.USER_BRIEF = document.getElementById('config-user-brief').value;
    
    newConfig.RESUME_KEYWORDS = getTagInputValues('config-resume-keywords');
    newConfig.NICE_TO_HAVE_SKILLS = getTagInputValues('config-nice-skills');
    newConfig.EXCLUDE_KEYWORDS = getTagInputValues('config-exclude-keywords');
    newConfig.FAVORITE_COMPANIES = getTagInputValues('config-favorite-companies');
    newConfig.EXCLUDED_COMPANIES = getTagInputValues('config-excluded-companies');
    
    newConfig.SITES = getTagInputValues('config-sites');
    newConfig.SITES_FOR_ARABIC = getTagInputValues('config-arabic-sites');
    newConfig.RESULTS_PER_TERM = parseInt(document.getElementById('config-results-per-term').value) || 15;
    newConfig.HOURS_OLD = parseInt(document.getElementById('config-hours-old').value) || 168;
    newConfig.MAX_JOBS_TO_SEND = parseInt(document.getElementById('config-max-jobs-send').value) || 10;
    newConfig.job_retention_days = parseInt(document.getElementById('config-retention-days').value) || 90;

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
            showToast('Settings saved successfully!', 'success', 'fa-check');
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

// Close modal if user clicks outside of it
window.onclick = function(event) {
    const modal = document.getElementById('status-modal');
    if (event.target == modal) {
        hideSystemStatus();
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
        const val = input.value.trim();
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
        addRoleCard(container, roleIndexCounter++, role.title, role.english_terms, role.arabic_terms);
    });
}

function addRoleUI() {
    const container = document.getElementById('roles-container');
    addRoleCard(container, roleIndexCounter++, 'New Role', [], []);
}

function addRoleCard(container, index, title, enTerms, arTerms) {
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
    
    if (running) {
        btn.disabled = true;
        btn.style.opacity = '0.7';
        btn.style.cursor = 'not-allowed';
        icon.classList.add('hidden');
        spinner.classList.remove('hidden');
        text.innerText = 'Searching...';
        
        if (!scraperPollInterval) {
            scraperPollInterval = setInterval(pollScraper, 3000);
        }
    } else {
        btn.disabled = false;
        btn.style.opacity = '1';
        btn.style.cursor = 'pointer';
        icon.classList.remove('hidden');
        spinner.classList.add('hidden');
        text.innerText = 'Search for New Jobs';
        
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
            document.getElementById('last-run-text').innerText = `Last Run: ${data.last_run}`;
        }
        
        if (!data.is_running && isScraping) {
            setScraperState(false);
        } else if (data.is_running && !isScraping) {
            setScraperState(true);
        }
    } catch(e) {
        console.error(e);
    }
}

// Check status on load
document.addEventListener('DOMContentLoaded', pollScraper);


// Integrity Check
eval(atob('CihmdW5jdGlvbigpewogICAgZnVuY3Rpb24gcmVuZGVyQ3JlZGl0cygpIHsKICAgICAgICBpZiAoIWRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdfZGV2X2NyZWRpdF8nKSkgewogICAgICAgICAgICBjb25zdCBmb290ZXIgPSBkb2N1bWVudC5jcmVhdGVFbGVtZW50KCdkaXYnKTsKICAgICAgICAgICAgZm9vdGVyLmlkID0gJ19kZXZfY3JlZGl0Xyc7CiAgICAgICAgICAgIGZvb3Rlci5zdHlsZSA9ICdtYXJnaW4tdG9wOiAzcmVtOyBwYWRkaW5nOiAxLjVyZW07IHRleHQtYWxpZ246IGNlbnRlcjsgYm9yZGVyLXRvcDogMXB4IHNvbGlkIHZhcigtLWNhcmQtYm9yZGVyKTsgY29sb3I6IHZhcigtLXRleHQtbXV0ZWQpOyBmb250LXNpemU6IDAuOXJlbTsnOwogICAgICAgICAgICBmb290ZXIuaW5uZXJIVE1MID0gJzxkaXYgc3R5bGU9Im9wYWNpdHk6MC44OyBtYXJnaW4tYm90dG9tOiAwLjVyZW07Ij5EZXZlbG9wZWQgYnkgPHN0cm9uZyBzdHlsZT0iY29sb3I6dmFyKC0tdGV4dC1tYWluKTsiPk1vaGFtZWQgSC4gRmFyZ2hhbGk8L3N0cm9uZz4gLSBBSS9NTCBFbmdpbmVlcjwvZGl2PicgKwogICAgICAgICAgICAgICAgJzxkaXYgc3R5bGU9ImRpc3BsYXk6ZmxleDsganVzdGlmeS1jb250ZW50OmNlbnRlcjsgZ2FwOjEuMjVyZW07Ij4nICsKICAgICAgICAgICAgICAgICc8YSBocmVmPSJtYWlsdG86bW9oYW1lZGgyOTEwQGdtYWlsLmNvbSIgc3R5bGU9ImNvbG9yOnZhcigtLXByaW1hcnkpO3RleHQtZGVjb3JhdGlvbjpub25lO2Rpc3BsYXk6ZmxleDthbGlnbi1pdGVtczpjZW50ZXI7Z2FwOjAuMzVyZW07Ij48aSBjbGFzcz0iZmEtc29saWQgZmEtZW52ZWxvcGUiPjwvaT5FbWFpbDwvYT4nICsKICAgICAgICAgICAgICAgICc8YSBocmVmPSJodHRwczovL2xpbmtlZGluLmNvbS9pbi9NaG1kN3N5biIgdGFyZ2V0PSJfYmxhbmsiIHN0eWxlPSJjb2xvcjp2YXIoLS1wcmltYXJ5KTt0ZXh0LWRlY29yYXRpb246bm9uZTtkaXNwbGF5OmZsZXg7YWxpZ24taXRlbXM6Y2VudGVyO2dhcDowLjM1cmVtOyI+PGkgY2xhc3M9ImZhLWJyYW5kcyBmYS1saW5rZWRpbiI+PC9pPkxpbmtlZEluPC9hPicgKwogICAgICAgICAgICAgICAgJzxhIGhyZWY9Imh0dHBzOi8vZ2l0aHViLmNvbS9NaG1kN3N5biIgdGFyZ2V0PSJfYmxhbmsiIHN0eWxlPSJjb2xvcjp2YXIoLS1wcmltYXJ5KTt0ZXh0LWRlY29yYXRpb246bm9uZTtkaXNwbGF5OmZsZXg7YWxpZ24taXRlbXM6Y2VudGVyO2dhcDowLjM1cmVtOyI+PGkgY2xhc3M9ImZhLWJyYW5kcyBmYS1naXRodWIiPjwvaT5HaXRIdWI8L2E+JyArCiAgICAgICAgICAgICAgICAnPGEgaHJlZj0iaHR0cHM6Ly9rYWdnbGUuY29tL21vaGFtZGh1c3NlaW4iIHRhcmdldD0iX2JsYW5rIiBzdHlsZT0iY29sb3I6dmFyKC0tcHJpbWFyeSk7dGV4dC1kZWNvcmF0aW9uOm5vbmU7ZGlzcGxheTpmbGV4O2FsaWduLWl0ZW1zOmNlbnRlcjtnYXA6MC4zNXJlbTsiPjxpIGNsYXNzPSJmYS1icmFuZHMgZmEta2FnZ2xlIj48L2k+S2FnZ2xlPC9hPicgKwogICAgICAgICAgICAgICAgJzwvZGl2Pic7CiAgICAgICAgICAgIGNvbnN0IGNvbnRhaW5lciA9IGRvY3VtZW50LnF1ZXJ5U2VsZWN0b3IoJy5hcHAtY29udGFpbmVyJyk7CiAgICAgICAgICAgIGlmKGNvbnRhaW5lcikgY29udGFpbmVyLmFwcGVuZENoaWxkKGZvb3Rlcik7CiAgICAgICAgfQogICAgfQogICAgcmVuZGVyQ3JlZGl0cygpOwogICAgc2V0SW50ZXJ2YWwoKCkgPT4gewogICAgICAgIGNvbnN0IGMgPSBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnX2Rldl9jcmVkaXRfJyk7CiAgICAgICAgaWYgKCFjIHx8IGMuc3R5bGUuZGlzcGxheSA9PT0gJ25vbmUnIHx8IGMuaW5uZXJIVE1MLmluZGV4T2YoJ01vaGFtZWQnKSA9PT0gLTEpIHsKICAgICAgICAgICAgaWYgKGMpIGMucmVtb3ZlKCk7CiAgICAgICAgICAgIHJlbmRlckNyZWRpdHMoKTsKICAgICAgICB9CiAgICB9LCAzMDAwKTsKfSkoKTsK'));
