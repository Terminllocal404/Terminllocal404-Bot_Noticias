# Cybersecurity & Tech Intelligence Hub (Discord Bot)

A production-ready Discord bot that aggregates Linux/Windows/cybersecurity intelligence, summarizes content with OpenAI, tracks CVEs, and auto-posts high-signal alerts.

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

## Setup

1. **Create virtual environment and install dependencies**
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configure environment variables**
   ```bash
   cp .env.example .env
   # then edit .env values
   export $(grep -v '^#' .env | xargs)
   ```

3. **Run the bot**
   ```bash
   python main.py
   ```

## Commands

- `!news linux`
- `!news windows`
- `!news security`
- `!alerts`
- `!cve`
- `!trend`

## Notes

- Focuses on defensive security awareness only.
- Uses only public data sources (RSS + CVE API).
- Deduplicates posted links and CVE IDs with SQLite.
