# Cyber Intelligence Platform

## Components

- Discord Bot (`bot/bot.py`)
- REST API + Collector Worker (`backend/main.py`, `backend/api.py`)
- Web Dashboard (`frontend/index.html`, `frontend/app.js`, `frontend/style.css`)
- MySQL database

## MySQL Schema

```sql
CREATE DATABASE cyberbot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE cyberbot;

CREATE TABLE IF NOT EXISTS news (
  id INT AUTO_INCREMENT PRIMARY KEY,
  title TEXT NOT NULL,
  link TEXT NOT NULL,
  source VARCHAR(255) NOT NULL,
  category VARCHAR(32) NOT NULL,
  severity VARCHAR(16) NOT NULL,
  summary TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uniq_news_link (link(255))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS cves (
  id INT AUTO_INCREMENT PRIMARY KEY,
  cve_id VARCHAR(64) NOT NULL,
  summary TEXT,
  severity VARCHAR(16) NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uniq_cve_id (cve_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

## Setup Instructions

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create `.env`:

```bash
DISCORD_BOT_TOKEN=your_discord_token
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-4o-mini
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=cyberbot_user
MYSQL_PASSWORD=change_this_password
MYSQL_DATABASE=cyberbot
API_PORT=8000
API_BASE_URL=http://127.0.0.1:8000
COLLECT_INTERVAL_SECONDS=1800
```

Run backend API + worker:

```bash
cd backend
python main.py
```

Run Discord bot:

```bash
cd bot
python bot.py
```

Run frontend (static server):

```bash
cd frontend
python -m http.server 5500
```

Open: `http://127.0.0.1:5500`
