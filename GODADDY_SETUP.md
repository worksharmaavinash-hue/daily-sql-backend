# 🌐 GoDaddy DNS Setup for DailySQL

This guide explains how to point your domain (`dailysql.in`) to your VPS so your API works at `https://api.dailysql.in` (instead of the IP address).

---

## ✅ Step 1: Login to GoDaddy & Find DNS Settings

1.  **Log in** to your GoDaddy account.
2.  Go to **My Products**.
3.  Find your domain **`dailysql.in`**.
4.  Click the **DNS** button (or "Manage DNS") next to it.

---

## 🛠 Step 2: Add "A" Records (Point Domain to VPS)

You need to tell the internet that `api.dailysql.in` lives at your VPS IP address: **`147.93.97.128`**.

### 1️⃣ Add the API Subdomain (for Backend)
In the DNS Management page, click **Add New Record** (or "Add"):

| Type | Name | Value (Points to) | TTL |
| :--- | :--- | :--- | :--- |
| **A** | **api** | `147.93.97.128` | **1/2 Hour** (or 600 seconds) |

> **What this does:**
> It makes `api.dailysql.in` point to your VPS.

### 2️⃣ Verify the Main Domain (Optional - if Frontend is also on VPS)
If your frontend (`www.dailysql.in`) is hosted elsewhere (like Vercel), **DO NOT** change the `@` or `www` records unless you know what you are doing (Vercel usually handles those).

**Summary of what you should see in GoDaddy:**
- `A` | `api` | `147.93.97.128` | ...

---

## 🔄 Step 3: Update Your Backend (VPS)

Once you've added the record in GoDaddy, wait about **10-30 minutes** for it to propagate (sometimes up to 24 hours, but usually fast).

### 1. Update `Caddyfile` on your PC
Edit `d:\Radrix\Daily SQL\Daily SQL - Backend\Caddyfile`:

```caddyfile
# Replace the nip.io line with your actual domain
api.dailysql.in {
    reverse_proxy dailysql-api:8000
}
```

### 2. Push Changes to Git
```bash
git add Caddyfile
git commit -m "feat: use real domain api.dailysql.in"
git push origin main
```

### 3. Deploy on VPS
SSH into your VPS and run:
```bash
cd ~/daily-sql-backend
git pull origin main
docker compose -f docker-compose.prod.yml up -d --build
```

---

## 🎨 Step 4: Update Frontend (Vercel/Local)

Now that your API has a real domain, update your frontend to use it.

### 1. Edit `.env.production` (or Vercel Env Vars)
Update `NEXT_PUBLIC_API_URL`:

```ini
NEXT_PUBLIC_API_URL=https://api.dailysql.in
```

### 2. Redeploy Frontend
- If using Vercel/Netlify: Trigger a new deployment.

---

## 🧪 Step 5: Verify

1.  Open **`https://api.dailysql.in/health`** in your browser.
    - You should see: `{"status":"ok"}` with a secure lock icon (🔒).
2.  Open your frontend app and test the login/admin panel.

🎉 **Done!**
