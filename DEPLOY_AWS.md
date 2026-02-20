# Deploy to AWS — Run 24/7 for a Week

**Cost: ~$1.75/week** (t3.micro) or **free** (t2.micro, free tier)

---

## Step 1: Launch an EC2 Instance

1. Go to [AWS Console → EC2](https://console.aws.amazon.com/ec2)
2. Click **Launch Instance**
3. Configure:

| Setting | Value |
|---------|-------|
| **Name** | `polymarket-monitor` |
| **AMI** | Ubuntu Server 24.04 LTS (free tier eligible) |
| **Instance type** | `t3.micro` ($1.75/week) or `t2.micro` (free tier) |
| **Key pair** | Create new → download `.pem` file → save it safely |
| **Security Group** | Create new with these rules ↓ |

### Security Group Rules

| Type | Port | Source | Purpose |
|------|------|--------|---------|
| SSH | 22 | My IP | Terminal access |
| Custom TCP | 8501 | 0.0.0.0/0 | Dashboard (phone/laptop) |

4. Click **Launch Instance**
5. Note the **Public IPv4** address (e.g., `3.14.159.26`)

---

## Step 2: Connect via SSH

```bash
# On your laptop (PowerShell or terminal)
# First, fix key permissions (one-time)
icacls "C:\path\to\your-key.pem" /inheritance:r /grant:r "%USERNAME%:R"

# Connect
ssh -i "C:\path\to\your-key.pem" ubuntu@<YOUR_EC2_PUBLIC_IP>
```

---

## Step 3: Install Dependencies on EC2

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python + pip + screen
sudo apt install -y python3 python3-pip python3-venv screen git

# Clone your repo
git clone https://github.com/vishalyl/crystal-perigee.git
cd crystal-perigee

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install Python packages
pip install -r requirements.txt
```

---

## Step 4: Start the Monitor (Runs Forever)

We use `screen` so processes survive after you disconnect SSH.

```bash
# Start a screen session called "monitor"
screen -S monitor

# Inside screen: start the monitor
cd ~/crystal-perigee
source venv/bin/activate
PYTHONUNBUFFERED=1 python3 crypto_monitor.py

# DETACH from screen (process keeps running):
# Press: Ctrl+A, then D
```

---

## Step 5: Start the Dashboard (Accessible from Phone/Laptop)

```bash
# Start another screen session called "dashboard"
screen -S dashboard

# Inside screen: start streamlit
cd ~/crystal-perigee
source venv/bin/activate
streamlit run dashboard.py --server.port 8501 --server.address 0.0.0.0

# DETACH from screen:
# Press: Ctrl+A, then D
```

---

## Step 6: Access Dashboard

Open in any browser (laptop or phone):

```
http://<YOUR_EC2_PUBLIC_IP>:8501
```

Example: `http://3.14.159.26:8501`

> **Bookmark this on your phone** for quick access!

---

## Step 7: Telegram Setup

Your Telegram bot is already configured. Just:
1. Open Telegram on your phone
2. Send `/start` to your bot
3. The monitor will auto-detect your chat_id
4. You'll get alerts for every trade open, limit hit, and slot summary

---

## Daily Operations

### Check on the monitor (SSH in)
```bash
ssh -i "your-key.pem" ubuntu@<YOUR_EC2_PUBLIC_IP>

# Reattach to monitor screen
screen -r monitor

# See live output, then detach again: Ctrl+A, D
```

### Check on the dashboard
```bash
screen -r dashboard
# Detach: Ctrl+A, D
```

### Restart everything (full wipe)
```bash
screen -r monitor
# Press Ctrl+C to stop

# Wipe and restart
rm -f trades.db trades.db-wal trades.db-shm upcoming_markets.txt
PYTHONUNBUFFERED=1 python3 crypto_monitor.py

# Detach: Ctrl+A, D
```

### Restart after error (keep trades)
```bash
screen -r monitor
# Press Ctrl+C

PYTHONUNBUFFERED=1 python3 crypto_monitor.py
# Detach: Ctrl+A, D
```

### Pull latest code changes
```bash
cd ~/crystal-perigee
git pull origin master
# Then restart monitor (see above)
```

---

## List all running screen sessions
```bash
screen -ls
```

Output:
```
There are screens on:
    12345.monitor    (Detached)
    12346.dashboard  (Detached)
```

---

## Stop Everything & Terminate Instance

When the week is over:

```bash
# Kill all screens
screen -X -S monitor quit
screen -X -S dashboard quit
```

Then go to **AWS Console → EC2 → Instances → Select → Instance State → Terminate**.

> ⚠️ **Don't forget to terminate!** Even a t3.micro costs ~$7.50/month if left running.

---

## Quick Reference

| What | Command |
|------|---------|
| SSH in | `ssh -i key.pem ubuntu@<IP>` |
| See monitor | `screen -r monitor` |
| See dashboard | `screen -r dashboard` |
| Detach screen | `Ctrl+A`, then `D` |
| Dashboard URL | `http://<IP>:8501` |
| Full wipe | `rm -f trades.db* upcoming_markets.txt` |
| Restart monitor | `PYTHONUNBUFFERED=1 python3 crypto_monitor.py` |
| Pull updates | `git pull origin master` |
| Kill everything | `screen -X -S monitor quit` |
