import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import asyncio
import httpx

# --- SMTP Configuration ---
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER or "noreply@dailysql.in")

# --- Resend Configuration (Alternative) ---
RESEND_API_KEY = os.getenv("RESEND_API_KEY")

# --- Emergency Configuration ---
BYPASS_MAIL_SEND = os.getenv("BYPASS_MAIL_SEND", "false").lower() == "true"

async def send_otp_email(email: str, otp: str) -> bool:
    """
    Sends an OTP email using either Resend API or SMTP.
    If BYPASS_MAIL_SEND is true or services are not configured, it logs the OTP to console.
    """
    subject = f"{otp} is your Daily SQL verification code"
    html_content = f"""
    <div style="font-family: sans-serif; max-width: 500px; margin: auto; padding: 20px; border: 1px solid #eee; border-radius: 10px;">
        <h2 style="color: #333;">Verify your email</h2>
        <p>Your Daily SQL verification code is:</p>
        <div style="font-size: 32px; font-weight: bold; color: #4DD4C4; letter-spacing: 5px; margin: 20px 0; background: #f9f9f9; padding: 15px; text-align: center; border-radius: 5px;">
            {otp}
        </div>
        <p style="color: #666;">This code will expire in 10 minutes.</p>
        <p style="color: #999; font-size: 12px; margin-top: 20px;">If you didn't request this, please ignore this email.</p>
    </div>
    """

    # 1. Emergency Bypass or Log-only
    if BYPASS_MAIL_SEND:
        print(f"\n🔥 [EMERGENCY OTP LOG] Email: {email} | OTP: {otp}\n")
        return True

    # 2. Try Resend API (If configured)
    if RESEND_API_KEY:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
                    json={
                        "from": "Daily SQL <onboarding@resend.dev>" if not SMTP_FROM.endswith("@dailysql.in") else f"Daily SQL <{SMTP_FROM}>",
                        "to": email,
                        "subject": subject,
                        "html": html_content
                    }
                )
                if resp.status_code in [200, 201]:
                    return True
        except Exception as e:
            print(f"Resend error: {e}")

    # 3. Try SMTP (If configured)
    if SMTP_HOST and SMTP_USER and SMTP_PASS:
        def sync_send():
            msg = MIMEMultipart()
            msg['From'] = SMTP_FROM
            msg['To'] = email
            msg['Subject'] = subject
            msg.attach(MIMEText(html_content, 'html'))
            try:
                with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                    server.starttls()
                    server.login(SMTP_USER, SMTP_PASS)
                    server.send_message(msg)
                return True
            except Exception as e:
                print(f"SMTP error: {e}")
                return False
        
        if await asyncio.to_thread(sync_send):
            return True

    # 4. Final Fallback: Log it and Fail (unless it's the only option)
    print(f"\n⚠️ [MAIL NOT SENT] No service configured. OTP for {email} is {otp}\n")
    return False
