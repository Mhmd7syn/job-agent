import os
from curl_cffi import requests
url = "https://www.glassdoor.com/Job/jobs.htm?sc.keyword=data+scientist&locT=N&locId=69&locKeyword=egypt"

headers = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "max-age=0",
    "Sec-Ch-Ua": "\"Chromium\";v=\"124\", \"Google Chrome\";v=\"124\", \"Not-A.Brand\";v=\"99\"",
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": "\"Windows\"",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1"
}

try:
    response = requests.get(url, impersonate="chrome124", headers=headers, timeout=20)
    print(f"Status: {response.status_code}")
    print(f"job-listing in text? {'job-listing' in response.text}")
except Exception as e:
    print(f"Error: {e}")
