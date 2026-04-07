# Infrastructure — Telegram Bot + Semantic Memory + Browser Automation

Custom additions on top of `@grinev/opencode-telegram-bot`.

## What's included

- **Multi-user setup** — Two isolated bot instances (separate Telegram bots, separate OpenCode serve ports, separate settings)
- **ChromaDB vector memory** — GPU-accelerated embeddings (`BAAI/bge-large-en-v1.5`) with MCP tools (`search_memory`, `save_to_memory`, `send_telegram_*`)
- **Memory ingestion timer** — Indexes OpenCode sessions + chat logs into ChromaDB every 5 minutes
- **Chrome DevTools MCP** — Controls the user's real Chromium browser (with GUI, default profile, all cookies/sessions) via remote debugging on `:9222`
- **Gemini STT proxy** — Whisper-compatible voice-to-text using Gemini 2.5 Flash (replaces Groq)
- **LinkedIn competitor scraper** — Transport-free Python helper producing JSON, scheduled via the bot's native `/task`
- **LinkedIn post creator skill** — OpenCode skill for scraping, analyzing, and generating LinkedIn posts

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        VPS                                   │
│                                                              │
│  ┌─────────────────┐       ┌──────────────────────────────┐ │
│  │ Telegram Bot 1   │──────▶│ opencode serve :4096         │ │
│  │ (Mohamed)        │       │                              │ │
│  └─────────────────┘       │  MCP servers:                │ │
│                             │  ├── memory (ChromaDB)       │ │
│  ┌─────────────────┐       │  ├── chrome-devtools (:9222) │ │
│  │ Telegram Bot 2   │──────▶│  └── playwright             │ │
│  │ (Iyed)           │       └──────────────────────────────┘ │
│  └─────────────────┘                                         │
│         │                   ┌──────────────────────────────┐ │
│         │                   │ opencode serve :4097         │ │
│         └──────────────────▶│ (Iyed's isolated instance)   │ │
│                             └──────────────────────────────┘ │
│                                                              │
│  ┌─────────────────┐       ┌──────────────────────────────┐ │
│  │ Chromium (GUI)   │◀─────│ chrome-devtools MCP          │ │
│  │ :9222 debug port │       │ (controls real browser)      │ │
│  │ default profile  │       └──────────────────────────────┘ │
│  └─────────────────┘                                         │
│                                                              │
│  ┌─────────────────┐       ┌──────────────────────────────┐ │
│  │ Gemini STT Proxy │◀─────│ Telegram bots (voice msgs)   │ │
│  │ :8787            │       └──────────────────────────────┘ │
│  └─────────────────┘                                         │
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ ingest-memory.timer (every 5 min)                       │ │
│  │ opencode.db + chat_history.jsonl → ChromaDB             │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## Systemd services

| Service | Description | Port |
|---|---|---|
| `opencode-serve.service` | OpenCode API (Mohamed) | :4096 |
| `opencode-serve-2.service` | OpenCode API (Iyed) | :4097 |
| `opencode-telegram-bot.service` | Telegram bot (Mohamed) | — |
| `opencode-telegram-bot-2.service` | Telegram bot (Iyed) | — |
| `chromium-debug.service` | Real Chromium with remote debugging | :9222 |
| `gemini-stt-proxy.service` | Whisper→Gemini voice-to-text proxy | :8787 |
| `ingest-memory.timer` | Memory ingestion every 5 min | — |
| `ingest-memory.service` | Oneshot ingestion runner | — |

## Setup

```bash
# 1. Install the bot
npm install -g @grinev/opencode-telegram-bot

# 2. Install Chromium
sudo pacman -S chromium   # Arch
# sudo apt install chromium  # Debian/Ubuntu

# 3. Symlink opencode to PATH (bot needs to find it)
sudo ln -sf ~/.opencode/bin/opencode /usr/local/bin/opencode

# 4. Set up Python venv for memory server
cd infra/memory
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 5. Copy and edit env files
cp .env.example ~/bot/engine/.env
# Edit with your tokens, keys, chat IDs

# 6. Install systemd services
sudo cp systemd/*.service systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now \
  chromium-debug \
  opencode-serve \
  opencode-telegram-bot \
  ingest-memory.timer \
  gemini-stt-proxy

# 7. For multi-user: configure second instance
mkdir -p ~/.config/opencode-telegram-bot-2
# Copy .env with different bot token, user ID, and port 4097
sudo systemctl enable --now opencode-serve-2 opencode-telegram-bot-2

# 8. Add MCP servers to OpenCode config (~/.config/opencode/opencode.json)
# "mcp": {
#   "memory": { "type": "local", "command": ["venv/bin/python3", "memory_server.py"] },
#   "chrome-devtools": { "type": "local", "command": ["npx", "-y", "chrome-devtools-mcp@latest", "--browser-url=http://127.0.0.1:9222"] }
# }

# 9. Install skills
cp -r skills/linkedin-post-creator ~/.claude/skills/
```

## Chrome DevTools

The Chromium runs with GUI (not headless) using the user's default profile — all saved logins, cookies, and sessions are available. Google sign-in works because there are no automation flags.

The `chrome-devtools` MCP connects via `--browser-url=http://127.0.0.1:9222` and gives agents full browser control: navigation, form filling, screenshots, performance audits, network inspection, console debugging.

## Voice-to-Text

Gemini STT proxy translates the Whisper-compatible API to Gemini 2.5 Flash. No Groq dependency.

```
Voice → bot → http://127.0.0.1:8787/audio/transcriptions → Gemini 2.5 Flash → text
```

## Scheduled Tasks

Use the bot's native `/task` command. Example tasks:

- **Weather + transport**: Daily at 8am — checks weather and train/metro disruptions
- **LinkedIn monitor**: Daily at 12pm — scrapes competitors, ranks posts, proposes content ideas

Tasks are stored in `~/.config/opencode-telegram-bot/settings.json`.

## Memory

Search results include role labels:
```
👤 User: find me vespa 50cc offers...
🤖 Assistant: Found 84 results in Île-de-France...
```

Memory is indexed from:
- OpenCode sessions (`opencode.db`)
- Chat history (`chat_history.jsonl`)
- Manual saves via `save_to_memory` tool
