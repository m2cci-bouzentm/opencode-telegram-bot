# Infrastructure — Semantic Memory + LinkedIn Scraper

Custom additions on top of `@grinev/opencode-telegram-bot`:
- **ChromaDB vector memory** with GPU-accelerated embeddings (`BAAI/bge-large-en-v1.5`)
- **MCP memory server** exposing `search_memory`, `save_to_memory`, `send_telegram_message`, `send_telegram_photo`, `send_telegram_file`
- **LinkedIn competitor scraper** — transport-free Python helper producing JSON
- **LinkedIn post creator skill** — OpenCode skill for scraping, analyzing, and generating LinkedIn posts
- **Systemd services** for `opencode serve`, the Telegram bot, and periodic memory ingestion

## Architecture

```
Telegram → opencode-telegram-bot → opencode serve (:4096)
                                         │
                                         ├── MCP: memory_server.py (ChromaDB)
                                         ├── OpenCode sessions → opencode.db
                                         └── Skills (linkedin-post-creator, etc.)
                                                │
                                                └── linkedin-competitor-scraper.py

ingest-memory.timer (every 10 min) → opencode.db + chat_history.jsonl → ChromaDB
```

## Setup

```bash
# 1. Install the bot (already done if using the parent repo)
npm install -g @grinev/opencode-telegram-bot

# 2. Set up Python venv for memory server
cd infra/memory
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Copy env
cp ../.env.example .env
# Edit .env with your values

# 4. Install systemd services
sudo cp systemd/*.service systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now opencode-serve opencode-telegram-bot ingest-memory.timer

# 5. Add MCP memory server to OpenCode config
# In ~/.config/opencode/opencode.json, add to "mcp":
# "memory": {
#   "type": "local",
#   "command": ["/path/to/venv/bin/python3", "/path/to/memory_server.py"],
#   "enabled": true
# }

# 6. Install skills
cp -r skills/linkedin-post-creator ~/.claude/skills/
```
