# Memory Server — Semantic Search MCP

ChromaDB vector memory with GPU-accelerated embeddings (BAAI/bge-large-en-v1.5). Exposes MCP tools for OpenCode.

## Tools

- **search_memory**: Semantic search across all sessions (with role labels)
- **save_to_memory**: Pin important info permanently
- **memory_stats**: Count indexed memories
- **ingest_sessions**: Index OpenCode + Claude Code sessions
- **send_telegram_message/photo/file**: Send to Telegram users

## Config

```
MEMORY_PATH=/path/to/memory
EMBED_MODEL=BAAI/bge-large-en-v1.5
EMBED_DEVICE=cuda
```

Ingestion runs every 5 minutes via `ingest-memory.timer`.
