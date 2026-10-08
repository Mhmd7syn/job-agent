import os
import sys
import json
import urllib.parse
import pandas as pd
import datetime
import logging
import re
import concurrent.futures
from bs4 import BeautifulSoup

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.database import is_job_seen
from core.job_utils import normalize_job_dict


def clean_glassdoor_company(company: str) -> str:
    """Strips trailing ratings and review stars glued to employer names (e.g., 'Valeo3.7' -> 'Valeo')."""
    if not company:
        return "Unknown"
    cleaned = re.sub(r'[\s·•|]*\d+(\.\d+)?\s*(★|\*|⭐)?\s*$', '', company.strip())
    return cleaned.strip() if cleaned.strip() else company.strip()


def fetch_glassdoor_job_details(driver, job_url: str) -> dict:
    """Fetches complete description, clean company name, directApply flag, and outbound application URL via live driver."""
    details = {'description': '', 'company': '', 'is_easy_apply': None, 'apply_url': ''}
    if not driver or not job_url or 'glassdoor.com/Job/jobs.htm' in job_url:
        return details
    try:
        driver.uc_open_with_reconnect(job_url, 3)
        if "just a moment" in (driver.title or "").lower():
            try:
                driver.uc_gui_click_captcha()
            except Exception:
                pass
            driver.sleep(3)

        driver.sleep(1.2)
        page_source = driver.get_page_source()
        soup = BeautifulSoup(page_source, 'html.parser')
        
        # 1. Look in JSON-LD
        for s in soup.find_all('script', type='application/ld+json'):
            txt = s.text or s.string or ""
            try:
                data = json.loads(txt)
                items = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
                for item in items:
                    if isinstance(item, dict) and item.get('@type') == 'JobPosting':
                        if item.get('description'):
                            clean_desc = BeautifulSoup(item['description'], 'html.parser').get_text(separator='\n', strip=True)
                            if len(clean_desc) > 30:
                                details['description'] = clean_desc
                        org = item.get('hiringOrganization', {})
                        if isinstance(org, dict) and org.get('name'):
                            details['company'] = org['name'].strip()
                        if 'directApply' in item:
                            details['is_easy_apply'] = bool(item['directApply'])
                        if details['description']:
                            break
                if details['description']:
                    break
            except Exception:
                pass
                
        # 2. Fallback to DOM description container
        if not details['description']:
            desc_div = soup.find('div', class_=lambda c: c and any(k in str(c) for k in [
                'jobDescriptionContent', 'JobDetails_jobDescription', 'desc', 'JobDetails_jobDetailsContainer'
            ])) or soup.find('div', id='JobDescriptionContainer')
            if desc_div:
                text = desc_div.get_text(separator='\n', strip=True)
                if len(text) > 80:
                    details['description'] = text

        # 3. Detect outbound apply URL from page script payload or links
        m_apply = re.search(r'\\?"applyUrl\\?"\s*:\s*\\?"((?:[^\\"]|\\.)*?)\\?"', page_source)
        if m_apply:
            raw_apply = m_apply.group(1)
            try:
                raw_apply = raw_apply.encode('utf-8').decode('unicode_escape')
            except Exception:
                raw_apply = raw_apply.replace(r'\u0026', '&')
            if raw_apply.startswith('/'):
                details['apply_url'] = "https://www.glassdoor.com" + raw_apply
            elif raw_apply.startswith('http'):
                details['apply_url'] = raw_apply

        # 3b. Extract any direct employer career/apply links embedded in the job description or page
        # E.g. McKinsey: <a href="https://www.mckinsey.com/careers/search-jobs">Ready to apply? Search our open roles</a>
        desc_div = soup.find('div', class_=lambda c: c and any(k in str(c) for k in [
            'jobDescriptionContent', 'JobDetails_jobDescription', 'desc', 'JobDetails_jobDetailsContainer'
        ])) or soup.find('div', id='JobDescriptionContainer')
        search_root = desc_div or soup
        candidate_links = []
        for a_tag in search_root.find_all('a', href=True):
            href = a_tag['href'].strip()
            link_text = a_tag.get_text(separator=' ', strip=True).lower()
            if not href.startswith('http') or any(ign in href for ign in ['glassdoor.com', 'indeed.com', 'facebook.com', 'twitter.com', 'google.com']):
                continue
            is_career_link = any(k in href.lower() or k in link_text for k in ['apply', 'career', 'job', 'workday', 'greenhouse', 'lever', 'open role'])
            comp_name = (details.get('company') or '').lower().split()[0] if details.get('company') else ''
            is_company_link = bool(comp_name and len(comp_name) > 3 and comp_name in href.lower())
            if is_career_link or is_company_link:
                candidate_links.append(href)

        if candidate_links:
            prioritized = sorted(candidate_links, key=lambda u: (
                0 if any(k in u.lower() for k in ['apply', 'search-jobs', 'jobdetail', 'req']) else 1
            ))
            details['apply_url'] = prioritized[0]

        # 4. Check apply button for "Apply on employer site" vs "Easy Apply"
        apply_btn = soup.find(attrs={'data-test': re.compile(r'applybutton', re.IGNORECASE)}) or soup.find('button', class_=lambda c: c and 'apply' in str(c).lower())
        if apply_btn:
            btn_text = apply_btn.get_text(separator=' ', strip=True).lower()
            if 'employer site' in btn_text or 'company site' in btn_text:
                details['is_easy_apply'] = False
            elif 'easy apply' in btn_text:
                details['is_easy_apply'] = True

        if details['is_easy_apply'] is None:
            if details.get('apply_url'):
                details['is_easy_apply'] = ('ea=1' in details['apply_url'])
            else:
                # Standard Glassdoor default without Easy Apply is external apply
                details['is_easy_apply'] = False
        if driver is not None:
            try:
                driver._last_gd_details = details
            except Exception:
                pass
    except Exception as e:
        logging.debug(f"Glassdoor job details fetch error for {job_url}: {e}")
    return details


def fetch_glassdoor_full_description(job_url: str, driver=None) -> str:
    """Fetches the complete full job description and requirements from a Glassdoor job page."""
    if not job_url or 'glassdoor.com/Job/jobs.htm' in job_url:
        return ""

    if driver is not None:
        det = fetch_glassdoor_job_details(driver, job_url)
        if det.get('description'):
            return det['description']

    try:
        from curl_cffi import requests as c_requests
        resp = c_requests.get(job_url, impersonate="chrome120", timeout=5)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.content, 'html.parser')
            # 1. Look for description container
            desc_div = soup.find('div', class_=lambda c: c and any(k in str(c) for k in [
                'jobDescriptionContent', 'JobDetails_jobDescription', 'desc', 'JobDetails_jobDetailsContainer'
            ])) or soup.find('div', id='JobDescriptionContainer') or soup.find('section', class_=lambda c: c and 'job-description' in str(c))
            if desc_div:
                text = desc_div.get_text(separator='\n', strip=True)
                if len(text) > 80:
                    return text

            # 2. Check JSON-LD fallback
            for s in soup.find_all('script', type='application/ld+json'):
                try:
                    data = json.loads(s.string or "")
                    if isinstance(data, dict) and data.get('@type') == 'JobPosting' and data.get('description'):
                        clean_desc = BeautifulSoup(data['description'], 'html.parser').get_text(separator='\n', strip=True)
                        if len(clean_desc) > 80:
                            return clean_desc
                except Exception:
                    pass
    except Exception as e:
        logging.debug(f"Glassdoor full description fetch failed for {job_url}: {e}")
    return ""


def build_glassdoor_url(search_term: str, location: str, hours_old: int = None, page: int = 1) -> str:
    """
    Builds a clean Glassdoor search URL using locKeyword without hardcoded locId.
    Dynamically applies remote filters for remote searches and supports pagination via &p=page.
    """
    loc_str = (location or "").strip()
    is_remote = loc_str.lower() in ("remote", "worldwide", "anywhere") or "remote" in search_term.lower()

    params = [
        ("sc.keyword", search_term),
        ("sortBy", "date_desc"),
    ]

    if is_remote:
        params.append(("locKeyword", "Remote"))
        params.append(("remoteWorkType", "1"))
    elif loc_str:
        params.append(("locKeyword", loc_str))

    if hours_old:
        days = int(hours_old / 24)
        if days > 0:
            params.append(("fromAge", str(days)))

    if page > 1:
        params.append(("p", str(page)))

    query_str = urllib.parse.urlencode(params)
    return f"https://www.glassdoor.com/Job/jobs.htm?{query_str}"


def scrape_glassdoor(search_term, location, results_wanted=15, hours_old=None, driver=None):
    jobs = []

    if driver is None:
        return pd.DataFrame()

    try:
        candidates = []
        seen_urls = set()
        page = 1
        max_pages = 3

        while len(candidates) < results_wanted and page <= max_pages:
            url = build_glassdoor_url(search_term, location, hours_old, page=page)
            driver.uc_open_with_reconnect(url, 4)
            try:
                driver.uc_gui_click_captcha()
            except Exception:
                pass

            try:
                driver.wait_for_element('li', timeout=8)
            except Exception:
                pass

            html_content = driver.get_page_source()
            soup = BeautifulSoup(html_content, 'html.parser')

            # Map partner apply links from the search page to detect Easy Apply & direct apply URL
            partner_map = {}
            for a in soup.find_all('a', href=True):
                h = a['href']
                if '/partner/jobListing.htm' in h:
                    m = re.search(r'jobListingId=(\d+)', h)
                    if m:
                        jid = m.group(1)
                        full_p = "https://www.glassdoor.com" + h if h.startswith('/') else h
                        is_ea = ('ea=1' in full_p)
                        partner_map[jid] = {'url': full_p, 'is_easy_apply': is_ea}

            job_cards = soup.find_all('li')
            if not job_cards:
                break

            added_in_page = 0
            for card in job_cards:
                if len(candidates) >= results_wanted:
                    break

                a_tag = card.find('a', href=True)
                if not a_tag:
                    continue

                href = a_tag['href']
                if not ('job-listing' in href or '/partner/' in href):
                    continue

                if href.startswith('/'):
                    href = "https://www.glassdoor.com" + href

                if href in seen_urls or is_job_seen(href):
                    continue
                seen_urls.add(href)

                title_elem = card.find(['a', 'span'], class_=lambda c: c and any(k in str(c) for k in ['JobTitle', 'job-title', 'jobTitle'])) or a_tag
                title = title_elem.text.strip() if title_elem else ""
                if not title or len(title) < 2:
                    continue

                comp_elem = card.find(['span', 'div', 'p'], class_=lambda c: c and any(k in str(c) for k in ['EmployerName', 'employer', 'company']))
                raw_company = comp_elem.text.strip() if comp_elem else "Unknown"
                company = clean_glassdoor_company(raw_company)

                loc_elem = card.find(['div', 'span'], class_=lambda c: c and any(k in str(c) for k in ['location', 'Location', 'loc']))
                loc_val = loc_elem.text.strip() if loc_elem else location

                card_desc = card.get_text(separator=' ', strip=True)

                # Determine application method & link from search card and partner map
                jid_match = re.search(r'jl=(\d+)', href) or re.search(r'jobListingId=(\d+)', href)
                jid = jid_match.group(1) if jid_match else card.get('data-jobid', '')

                is_easy_apply = False
                apply_url = href
                if jid and jid in partner_map:
                    apply_url = partner_map[jid]['url']
                    is_easy_apply = partner_map[jid]['is_easy_apply']
                elif 'easyapply' in card.get_text().lower() or any('easyapply' in str(c).lower() for c in card.get('class', [])):
                    is_easy_apply = True

                candidates.append({
                    'title': title,
                    'company': company,
                    'location': loc_val,
                    'job_url': href,
                    'apply_url': apply_url,
                    'is_easy_apply': is_easy_apply,
                    'job_type': 'Not specified',
                    'description': card_desc,
                    'is_remote': 'remote' in search_term.lower() or 'remote' in str(loc_val).lower(),
                    'site': 'glassdoor',
                    'date_posted': datetime.datetime.now().date()
                })
                added_in_page += 1

            if added_in_page == 0:
                break
            page += 1

        # Fetch full job descriptions and details
        for cand in candidates:
            try:
                full_desc = fetch_glassdoor_full_description(cand['job_url'], driver=driver)
                if full_desc and len(full_desc) > len(cand['description']):
                    cand['description'] = full_desc

                det = getattr(driver, '_last_gd_details', None)
                if isinstance(det, dict):
                    if det.get('is_easy_apply') is not None:
                        cand['is_easy_apply'] = det['is_easy_apply']
                    if det.get('apply_url'):
                        cand['apply_url'] = det['apply_url']
                    if det.get('company') and det['company'] != 'Unknown':
                        cand['company'] = clean_glassdoor_company(det['company'])
            except Exception as e:
                logging.debug(f"Glassdoor full desc fetch failed for {cand['job_url']}: {e}")
            jobs.append(normalize_job_dict(cand))

    except Exception as e:
        logging.error(f"⚠️ Glassdoor Scraper Error: {e}")

    return pd.DataFrame(jobs)


if __name__ == "__main__":
    if sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
    print("Testing Glassdoor Scraper...")
    df = scrape_glassdoor("data scientist", "egypt", 5)
    print(df.head())
