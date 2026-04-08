# OpenCode Telegram Bot — Monorepo

[![npm version](https://img.shields.io/npm/v/@grinev/opencode-telegram-bot)](https://www.npmjs.com/package/@grinev/opencode-telegram-bot)
[![CI](https://github.com/grinev/opencode-telegram-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/grinev/opencode-telegram-bot/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Secure Telegram client for [OpenCode](https://opencode.ai) with multi-user support, semantic memory, browser automation, speech-to-text, and LinkedIn tooling.

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
│  │ STT Server       │◀─────│ Telegram bots (voice msgs)   │ │
│  │ :8787            │       └──────────────────────────────┘ │
│  └─────────────────┘                                         │
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ ingest-memory.timer (every 5 min)                       │ │
│  │ opencode.db + chat_history.jsonl → ChromaDB             │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## Packages

| Package | Description |
|---|---|
| [`packages/stt-server`](packages/stt-server/README.md) | Whisper-compatible STT with Parakeet + Gemini providers |
| [`packages/memory-server`](packages/memory-server/README.md) | ChromaDB semantic memory MCP server |
| [`packages/linkedin-scraper`](packages/linkedin-scraper/README.md) | LinkedIn competitor analysis helper |

## Systemd Services

| Service | Description | Port |
|---|---|---|
| `opencode-serve.service` | OpenCode API (Mohamed) | :4096 |
| `opencode-serve-2.service` | OpenCode API (Iyed) | :4097 |
| `opencode-telegram-bot.service` | Telegram bot (Mohamed) | — |
| `opencode-telegram-bot-2.service` | Telegram bot (Iyed) | — |
| `chromium-debug.service` | Real Chromium with remote debugging | :9222 |
| `stt-server.service` | Whisper-compatible STT proxy | :8787 |
| `ingest-memory.timer` | Memory ingestion every 5 min | — |
| `ingest-memory.service` | Oneshot ingestion runner | — |

All service files live in [`systemd/`](systemd/).

## Quick Start

```bash
# 1. Install the bot
npm install -g @grinev/opencode-telegram-bot

# 2. Start OpenCode server
opencode serve

# 3. Run the bot (interactive wizard on first launch)
opencode-telegram start

# 4. Set up Python packages
cd packages/memory-server && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt

# 5. Install systemd services
sudo cp systemd/*.service systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now opencode-serve opencode-telegram-bot chromium-debug ingest-memory.timer stt-server
```

## Skills

| Skill | Location |
|---|---|
| LinkedIn Post Creator | [`skills/linkedin-post-creator`](skills/linkedin-post-creator) |

Skills are installed to `~/.claude/skills/` for OpenCode agent use.

## Docs

| Document | Description |
|---|---|
| [Chrome DevTools Setup](docs/CHROME-DEVTOOLS.md) | Browser automation via remote debugging |
| [Localization Guide](docs/LOCALIZATION_GUIDE.md) | Adding new UI languages |
| [Contributing](CONTRIBUTING.md) | Commit conventions and release process |
| [Product Roadmap](PRODUCT.md) | Current task list and planned features |

## License

[MIT](LICENSE) © Ruslan Grinev
