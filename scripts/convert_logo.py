import sys
from PIL import Image

def convert():
    img_path = r"C:\Users\HP\.gemini\antigravity\brain\7d48c7b7-9838-4e36-88d2-3b37ff567a59\job_agent_logo_1784917869047.jpg"
    img = Image.open(img_path)
    # Convert to web logo png
    img.save(r"d:\projects\Jobs Search\job-agent\web\static\logo.png", "PNG")
    # Convert to ico for desktop app and shortcuts
    img.save(r"d:\projects\Jobs Search\job-agent\logo.ico", format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])

if __name__ == '__main__':
    convert()
