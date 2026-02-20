# Deploy to AWS — Complete Beginner Guide

**What you'll get:** Your trading bot running 24/7 on AWS, viewable from your phone/laptop, with Telegram alerts.  
**Cost:** FREE (AWS Free Tier — 750 hours/month for 12 months)  
**Time:** ~15 minutes

---

## Part 1: Create an AWS Account (Skip if you already have one)

1. Go to [https://aws.amazon.com](https://aws.amazon.com)
2. Click **"Create an AWS Account"** (top right)
3. Enter your email, password, and account name
4. Enter your credit card (you will NOT be charged — free tier)
5. Choose **"Basic support — Free"**
6. Done! You now have an AWS account

---

## Part 2: Launch Your Server

### Step 1: Open EC2 Dashboard

1. Log into [https://console.aws.amazon.com](https://console.aws.amazon.com)
2. In the search bar at the top, type **EC2** and click it
3. Click the big orange button: **"Launch instance"**

### Step 2: Name Your Server

- **Name:** Type `polymarket-monitor`

### Step 3: Choose Operating System

- Under **"Application and OS Images"**, you'll see **Ubuntu** as an option
- Click **Ubuntu**
- Make sure it says **"Free tier eligible"** underneath
- Leave everything else as default

### Step 4: Choose Server Size

- Under **"Instance type"**, select **t2.micro**
- It should say **"Free tier eligible"** next to it
- This gives you 1 CPU + 1 GB RAM — more than enough

### Step 5: Create a Key Pair (This is Your Password to SSH In)

1. Under **"Key pair"**, click **"Create new key pair"**
2. **Key pair name:** Type `polymarket-key`
3. **Key pair type:** Leave as `RSA`
4. **Private key file format:** Choose `.pem`
5. Click **"Create key pair"**
6. ⚠️ **A file called `polymarket-key.pem` will download. SAVE THIS FILE. You need it to connect later.**
7. Move it somewhere safe, like `C:\Users\visha\Desktop\polymarket-key.pem`

### Step 6: Configure Network (Allow Dashboard + SSH Access)

1. Under **"Network settings"**, click **"Edit"** (on the right)
2. You'll see one rule for SSH (port 22) — leave it
3. Click **"Add security group rule"**
4. Fill in:
   - **Type:** Custom TCP
   - **Port range:** `8501`
   - **Source type:** Anywhere (`0.0.0.0/0`)
   - **Description:** `Dashboard`

### Step 7: Storage

- Change the storage to **20 GB** (free tier allows up to 30 GB)
- This gives enough space for Python packages and trade data

### Step 8: Launch!

1. Click the orange **"Launch instance"** button at the bottom
2. You'll see a green success message
3. Click **"View all instances"**
4. Wait ~30 seconds for the **"Instance state"** to change to **"Running"**
5. Click on your instance → copy the **"Public IPv4 address"**
   - It will look like: `3.14.159.26` — **save this, you'll need it**

---

## Part 3: Connect to Your Server

### On Windows (PowerShell)

1. Open **PowerShell** (search "PowerShell" in Start menu)
2. Run these commands one by one:

```powershell
# Go to where your key file is (change path if needed)
cd C:\Users\visha\Desktop

# Connect to your server (replace <YOUR_IP> with the IP you copied)
ssh -i "polymarket-key.pem" ubuntu@<YOUR_IP>
```

3. It will ask: **"Are you sure you want to continue connecting?"** → Type `yes` and press Enter
4. You're now inside your AWS server! You'll see something like:
```
ubuntu@ip-172-31-xx-xx:~$
```

> **If you get a "permissions" error**, run this first:
> ```powershell
> icacls "polymarket-key.pem" /inheritance:r /grant:r "%USERNAME%:R"
> ```
> Then try the ssh command again.

---

## Part 4: Install Everything on the Server

Copy and paste these commands **one block at a time** into your SSH terminal:

### Block 1: Update the server
```bash
sudo apt update && sudo apt upgrade -y
```
⏱ Wait ~1 minute. Press `Y` if it asks anything.

### Block 2: Install Python and tools
```bash
sudo apt install -y python3 python3-pip python3-venv screen git
```
⏱ Wait ~30 seconds.

### Block 3: Download your code from GitHub
```bash
git clone https://github.com/vishalyl/crystal-perigee.git
cd crystal-perigee
```

### Block 4: Set up Python environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```
⏱ Wait ~1 minute for packages to install.

---

## Part 5: Start the Trading Bot

### Start the Monitor

```bash
# Create a "screen" session (keeps running even after you disconnect)
screen -S monitor

# You're now inside a virtual terminal. Start the bot:
PYTHONUNBUFFERED=1 python3 crypto_monitor.py
```

You should see:
```
Polymarket Multi-Slot Monitor v4
  [STARTUP] Clearing old slots...
  [FETCHER] ...
  ✓ Fresh queue built: 5 upcoming slots
  [TICK] BTC NO: $0.505 ...
```

**Now detach (leave it running in background):**
- Press `Ctrl+A`, then press `D`
- You'll see: `[detached from ...]`

### Start the Dashboard

```bash
# Create another screen session for the dashboard
screen -S dashboard

# Start Streamlit (note the --server.address 0.0.0.0 — this makes it accessible from outside)
cd ~/crystal-perigee
source venv/bin/activate
streamlit run dashboard.py --server.port 8501 --server.address 0.0.0.0
```

You should see:
```
You can now view your Streamlit app in your browser.
  Network URL: http://172.31.xx.xx:8501
```

**Detach again:**
- Press `Ctrl+A`, then press `D`

---

## Part 6: View Your Dashboard! 🎉

Open any browser on your **laptop or phone** and go to:

```
http://<YOUR_IP>:8501
```

Replace `<YOUR_IP>` with the Public IP you saved earlier.  
Example: `http://3.14.159.26:8501`

> 💡 **Pro tip:** Bookmark this URL on your phone's home screen for quick access!

---

## Part 7: Set Up Telegram Alerts

1. Open Telegram on your phone
2. Search for your bot (the one you created with BotFather)
3. Send `/start` to the bot
4. Within a few seconds, you'll see `[TG] Chat ID set: ...` in the monitor logs
5. From now on, you'll get alerts for:
   - 📈 Trade opened
   - ✅ Limit hit (profit!)
   - 🔴 Slot expired (loss)
   - 📊 Hourly summaries

---

## Everyday Usage

### I want to check on my bot

**Option A: Just open the dashboard**
- Go to `http://<YOUR_IP>:8501` on your phone
- Everything is there: trades, equity, live prices

**Option B: Check the terminal logs**
```bash
# SSH in
ssh -i "polymarket-key.pem" ubuntu@<YOUR_IP>

# See the monitor output
screen -r monitor

# When done looking, detach: Ctrl+A, then D

# Disconnect from SSH
exit
```

### Something broke — restart the bot

```bash
# SSH in
ssh -i "polymarket-key.pem" ubuntu@<YOUR_IP>

# Go to the monitor screen
screen -r monitor

# Stop the bot: press Ctrl+C

# Restart it
PYTHONUNBUFFERED=1 python3 crypto_monitor.py

# Detach: Ctrl+A, then D
exit
```

### Full wipe — delete everything and start fresh

```bash
ssh -i "polymarket-key.pem" ubuntu@<YOUR_IP>
screen -r monitor

# Stop the bot: Ctrl+C

# Delete all data
rm -f trades.db trades.db-wal trades.db-shm upcoming_markets.txt

# Restart clean
PYTHONUNBUFFERED=1 python3 crypto_monitor.py

# Detach: Ctrl+A, then D
exit
```

### Pull latest code updates (after you push changes from your laptop)

```bash
ssh -i "polymarket-key.pem" ubuntu@<YOUR_IP>
screen -r monitor
# Ctrl+C to stop

cd ~/crystal-perigee
git pull origin master
PYTHONUNBUFFERED=1 python3 crypto_monitor.py

# Detach: Ctrl+A, then D
exit
```

---

## When You're Done (After 1 Week)

> ⚠️ **IMPORTANT: Don't forget this step or you'll be charged!**

1. Go to [AWS Console → EC2 → Instances](https://console.aws.amazon.com/ec2)
2. Check the box next to `polymarket-monitor`
3. Click **"Instance state"** dropdown (top right)
4. Click **"Terminate instance"**
5. Confirm by clicking **"Terminate"**
6. Done! No more charges.

---

## Cheat Sheet

| I want to... | Do this |
|---|---|
| See my dashboard | Open `http://<YOUR_IP>:8501` in browser |
| SSH into server | `ssh -i "polymarket-key.pem" ubuntu@<YOUR_IP>` |
| See bot logs | `screen -r monitor` |
| See dashboard logs | `screen -r dashboard` |
| Leave a screen | `Ctrl+A`, then `D` |
| Restart bot | `screen -r monitor` → `Ctrl+C` → run command → `Ctrl+A D` |
| Full wipe | `rm -f trades.db* upcoming_markets.txt` then restart |
| Disconnect SSH | Type `exit` |
| Stop paying | Terminate instance in AWS Console |
