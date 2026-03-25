# Cyber Intelligence Hub

Advanced Discord bot for cybersecurity, Linux, Windows, and threat intelligence monitoring from public/ethical data sources.

## Architecture

```
.
├── main.py
├── feeds.py
├── cve.py
├── ai.py
├── db.py
├── scoring.py
├── config.py
├── requirements.txt
└── .env.example
```

## Data Sources

### RSS
- Cybersecurity
  - https://www.bleepingcomputer.com/feed/
  - https://feeds.feedburner.com/TheHackersNews
  - https://krebsonsecurity.com/feed/
  - https://www.darkreading.com/rss.xml
  - https://www.securityweek.com/feed/
- Linux
  - https://www.phoronix.com/rss.php
  - https://www.omgubuntu.co.uk/feed
  - https://itsfoss.com/feed/
- Windows
  - https://www.windowscentral.com/rss
  - https://msrc.microsoft.com/update-guide/rss

### APIs
- https://cve.circl.lu/api/last

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
  severity_score INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uniq_link (link(255))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS cves (
  id INT AUTO_INCREMENT PRIMARY KEY,
  cve_id VARCHAR(64) NOT NULL,
  summary TEXT,
  severity VARCHAR(16) NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uniq_cve (cve_id)
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

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
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

## Security Constraints
- No TOR/dark-web scraping.
- No illegal hacking instructions.
- Public, ethical, defensive intelligence only.
