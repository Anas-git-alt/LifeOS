## 📋 Setup Guide B: VPS (Fresh Ubuntu 24.04 LTS)

### 1. Initial Server Setup

```bash
# SSH in as root
ssh root@your-server-ip

# Create non-root user
adduser lifeos
usermod -aG sudo lifeos

# SSH hardening
nano /etc/ssh/sshd_config
# Set: PermitRootLogin no
# Set: PasswordAuthentication no  (after adding SSH key)
systemctl restart sshd

# Switch to new user
su - lifeos
```

### 2. Install Docker

```bash
sudo apt update && sudo apt upgrade -y
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker
```

### 3. Deploy

```bash
git clone <your-repo-url> ~/LifeOS && cd ~/LifeOS
mkdir -p .venv && cp .env.example .venv/.env
nano .venv/.env  # Add secrets
docker compose up --build -d
```

### 4. Firewall

```bash
sudo apt install -y ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 3100/tcp   # WebUI (or restrict to your IP)
# Do NOT expose 8100 directly to public internet unless required
sudo ufw enable
```

### 5. Optional: HTTPS with Caddy

If you have a domain:

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy

# Add to /etc/caddy/Caddyfile
# yourdomain.com {
#     reverse_proxy localhost:3100
# }

sudo systemctl restart caddy
```

### 6. Backups & Persistence

```bash
# Docker volumes are in standard locations
# SQLite DB is in ./storage/lifeos.db (mounted volume)

# Automated backup via cron
crontab -e
# Add: 0 2 * * * cd /home/lifeos/LifeOS && ./scripts/backup.sh >> /tmp/backup.log 2>&1

# Restore from backup
./scripts/restore.sh backup-2026-02-27
```

### 7. Optional: fail2ban

```bash
sudo apt install -y fail2ban
sudo systemctl enable fail2ban
```

---