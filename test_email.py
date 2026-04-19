import asyncio
import os
from dotenv import load_dotenv

# Load local .env (it is in the same directory as this script)
load_dotenv()

# We need to add the backend path to sys.path so we can import from app
import sys
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from app.services.mail_service import send_otp_email

async def test_email():
    test_email = input("Enter an email to receive the test OTP: ")
    print(f"Testing email sending to {test_email}...")
    
    success = await send_otp_email(test_email, "123456")
    
    if success:
        print("✅ Success! Check your inbox.")
    else:
        print("❌ Failed. Check console logs above for errors.")

if __name__ == "__main__":
    asyncio.run(test_email())
