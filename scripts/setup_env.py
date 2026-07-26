import os
import getpass
from cryptography.fernet import Fernet

def main():
    print("-" * 57)
    print("PRIVACY NOTICE: This is a safe process. Your credentials")
    print("will ONLY be stored locally on your device in the .env file.")
    print("They will not be sent to any external servers or shared.")
    print("-" * 57)
    print("SECURITY WARNING: The .env file should not be shared with")
    print("anyone. The project uses encryption to prevent moving/sharing")
    print("credentials. If the .env file is moved to another computer,")
    print("it will not work without the secret key stored locally.")
    print("-" * 57)
    print("OPTIONAL: You can press ENTER to skip any of these.")
    print()
    print("[Why add LinkedIn?]")
    print("- Allows the agent to automatically scrape thousands of")
    print("  high-quality jobs directly from LinkedIn.")
    print()
    print("[Why add Gemini API Key?]")
    print("- Enables the AI to deeply analyze job descriptions, filter")
    print("  out irrelevant jobs, and give you a smart 'Match Score'.")
    print("-" * 57)
    print("SAFETY WARNINGS:")
    print("- Don't run it constantly: The default schedule (twice a week)")
    print("  is incredibly safe. Running it every hour will eventually")
    print("  trigger a captcha or a security block.")
    print("- Use a \"Burner\" Account (Optional): If you are extremely")
    print("  worried about your main LinkedIn profile, you can create a")
    print("  secondary, empty LinkedIn account just for the script to use.")
    print("  It doesn't need connections to search for jobs!")
    print("-" * 57)

    li_email = input("LinkedIn Email (Optional): ").strip()
    li_password = getpass.getpass("LinkedIn Password (Optional): ").strip()
    gemini_key = getpass.getpass("Gemini API Key (Optional): ").strip()

    # Generate encryption key
    key = Fernet.generate_key()
    fernet = Fernet(key)

    # Save the key securely in %APPDATA%\JobAgent
    appdata = os.getenv('APPDATA')
    if not appdata:
        appdata = os.path.expanduser('~')
    
    key_dir = os.path.join(appdata, 'JobAgent')
    os.makedirs(key_dir, exist_ok=True)
    key_path = os.path.join(key_dir, 'secret.key')

    with open(key_path, 'wb') as key_file:
        key_file.write(key)

    # Encrypt values
    enc_li_email = fernet.encrypt(li_email.encode()).decode() if li_email else ""
    enc_li_password = fernet.encrypt(li_password.encode()).decode() if li_password else ""
    enc_gemini_key = fernet.encrypt(gemini_key.encode()).decode() if gemini_key else ""

    # Create .env file
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(project_root, '.env')

    with open(env_path, 'w', encoding='utf-8') as env_file:
        env_file.write(f'LINKEDIN_EMAIL="{enc_li_email}"\n')
        env_file.write(f'LINKEDIN_PASSWORD="{enc_li_password}"\n')
        env_file.write(f'GEMINI_API_KEY="{enc_gemini_key}"\n')

    print("\n.env file created and credentials encrypted successfully!")
    print(f"Encryption key stored safely at: {key_path}")

if __name__ == "__main__":
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(project_root, '.env')
    if not os.path.exists(env_path):
        main()
    else:
        print(".env file already exists. Skipping environment configuration.")
