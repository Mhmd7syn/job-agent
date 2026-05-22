import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    # Telegram max message length is 4096 chars
    MAX_LENGTH = 4000
    
    # Split text into chunks if it's too long
    chunks = []
    while len(text) > 0:
        if len(text) <= MAX_LENGTH:
            chunks.append(text)
            break
            
        # Find the last newline before the limit to avoid breaking HTML tags or words
        split_point = text.rfind('\n', 0, MAX_LENGTH)
        if split_point == -1:
            split_point = MAX_LENGTH
            
        chunks.append(text[:split_point])
        text = text[split_point:].lstrip()
        
    for chunk in chunks:
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            print("✅ Message chunk successfully sent to Telegram.")
        else:
            print(f"❌ Failed to send message chunk. Error: {response.text}")
        
        # Small delay to avoid Telegram rate limits
        import time
        time.sleep(1)
