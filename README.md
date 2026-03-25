# Cyber Intelligence Bot

Production-ready Discord bot for cybersecurity awareness. It ingests public RSS sources, monitors latest CVEs, summarizes findings with OpenAI, and posts intelligence updates to Discord.

## File Structure

```
.
├── main.py
├── feeds.py
├── cve.py
├── ai.py
├── db.py
├── config.py
├── requirements.txt
└── .env.example
```

## MySQL Setup Instructions

1. Install MySQL Server 8+.
2. Create database and user:

```sql
CREATE DATABASE cyberbot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'cyberbot_user'@'%' IDENTIFIED BY 'change_this_password';
GRANT ALL PRIVILEGES ON cyberbot.* TO 'cyberbot_user'@'%';
FLUSH PRIVILEGES;
```

3. Apply schema:

```sql
USE cyberbot;

CREATE TABLE IF NOT EXISTS news (
  id INT AUTO_INCREMENT PRIMARY KEY,
  title TEXT NOT NULL,
  link TEXT NOT NULL,
  category VARCHAR(50) NOT NULL,
  source VARCHAR(255) NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uniq_link (link(255))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS cves (
  id INT AUTO_INCREMENT PRIMARY KEY,
  cve_id VARCHAR(64) NOT NULL,
  summary TEXT,
  severity VARCHAR(16) NOT NULL,
  cvss FLOAT NOT NULL DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uniq_cve_id (cve_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS logs (
  id INT AUTO_INCREMENT PRIMARY KEY,
  message TEXT NOT NULL,
  level VARCHAR(16) NOT NULL,
  timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS keyword_hits (
  id INT AUTO_INCREMENT PRIMARY KEY,
  keyword VARCHAR(100) NOT NULL,
  hit_count INT NOT NULL DEFAULT 0,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uniq_keyword (keyword)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

## Environment Variables

Copy and configure:

```bash
cp .env.example .env
```

Then set variables:

- `DISCORD_BOT_TOKEN`
- `OPENAI_API_KEY`
- `DISCORD_POST_CHANNEL_ID`
- `POST_INTERVAL_MINUTES` (default `30`)
- `OPENAI_MODEL` (default `gpt-4o-mini`)
- `MYSQL_HOST` (default `127.0.0.1`)
- `MYSQL_PORT` (default `3306`)
- `MYSQL_USER`
- `MYSQL_PASSWORD`
- `MYSQL_DATABASE` (default `cyberbot`)

## Install and Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export $(grep -v '^#' .env | xargs)
python main.py
```

## Commands

- `!news linux`
- `!news windows`
- `!news security`
- `!alerts`
- `!cve`
- `!trend`

## Security Policy

- Public defensive sources only.
- No illegal exploitation instructions.
- Intended for awareness and prioritization.
