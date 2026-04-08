# Chrome DevTools MCP — Real Browser Setup

## Problem

Chrome DevTools MCP by default spawns its own Chromium/Chrome with automation flags (`--enable-automation`, `--remote-debugging-pipe`, separate `--user-data-dir`). This causes:
- Google blocks sign-in: "This browser or app may not be secure"
- Fresh profile with no cookies/sessions
- Detected as automated browser by websites

## Solution

Use the user's real Chromium with remote debugging, not the MCP's spawned browser.

### Step 1: Remove Google Chrome

The MCP prefers Google Chrome over Chromium. If both are installed, it ignores `--browser-url` and spawns Chrome anyway.

```bash
# Arch Linux
sudo pacman -R google-chrome
# Or just remove the binary
sudo rm -f /opt/google/chrome/chrome /usr/bin/google-chrome
```

### Step 2: Launch real Chromium with remote debugging

The key is: no `--headless`, no `--user-data-dir`, no `--no-sandbox`. Just your normal Chromium + the debug port.

On Hyprland/Wayland (systemd service):

```ini
[Unit]
Description=Chromium with Remote Debugging
After=graphical-session.target

[Service]
Type=simple
User=mohamed
Environment=WAYLAND_DISPLAY=wayland-1
Environment=XDG_RUNTIME_DIR=/run/user/1000
ExecStart=/usr/bin/chromium --remote-debugging-port=9222
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

This uses:
- Default user profile (all saved logins, cookies, extensions)
- Real GUI on the display (not headless)
- No automation flags (websites can't detect it)

### Step 3: Configure MCP to connect to it

Two approaches — try A first, use B if A doesn't work.

**Approach A: HTTP URL (simpler, stable across restarts)**

```json
{
  "mcp": {
    "chrome-devtools": {
      "type": "local",
      "command": ["npx", "-y", "chrome-devtools-mcp@latest", "--browser-url=http://127.0.0.1:9222"]
    }
  }
}
```

If the MCP ignores this and spawns its own browser, remove any competing Chrome binary (see Step 1) or use Approach B.

**Approach B: WebSocket URL (forces direct connection)**

First get the current websocket URL:
```bash
curl -s http://127.0.0.1:9222/json/version | python3 -c "import sys,json; print(json.load(sys.stdin)['webSocketDebuggerUrl'])"
# Output: ws://127.0.0.1:9222/devtools/browser/<uuid>
```

Then use it:
```json
{
  "mcp": {
    "chrome-devtools": {
      "type": "local",
      "command": ["npx", "-y", "chrome-devtools-mcp@latest", "--browser-ws-url=ws://127.0.0.1:9222/devtools/browser/<uuid>"]
    }
  }
}
```

**Caveat**: The UUID changes every time Chromium restarts. You can automate this with a wrapper script:

```bash
#!/bin/bash
WS_URL=$(curl -s http://127.0.0.1:9222/json/version | python3 -c "import sys,json; print(json.load(sys.stdin)['webSocketDebuggerUrl'])")
exec npx -y chrome-devtools-mcp@latest --browser-ws-url="$WS_URL"
```

Save as `chrome-devtools-wrapper.sh`, then in config:
```json
{
  "mcp": {
    "chrome-devtools": {
      "type": "local",
      "command": ["/path/to/chrome-devtools-wrapper.sh"]
    }
  }
}
```

### Step 4: Verify

```bash
# Check Chromium is running with debug port
curl -s http://127.0.0.1:9222/json/version | python3 -m json.tool

# Should show your real Chromium, not a headless one
```

### What can go wrong

| Issue | Cause | Fix |
|---|---|---|
| MCP spawns its own Chrome | Google Chrome installed alongside Chromium | Remove Google Chrome (Step 1) |
| "This browser or app may not be secure" | MCP using its own browser with `--enable-automation` | Ensure `--browser-url` is reaching the MCP (Step 1 + 3) |
| Screenshot shows `chrome://new-tab-page` only | MCP connected to its own browser, not yours | Check `ps aux | grep chrome` — kill any Chrome not on port 9222 |
| `--browser-url` ignored by npx | npm eats the flag | Ensure `--` separator or remove competing Chrome binary |
| Display issues on Wayland | Missing env vars | Set `WAYLAND_DISPLAY=wayland-1` and `XDG_RUNTIME_DIR=/run/user/1000` |

### macOS (local dev machine)

On macOS, use `--autoConnect` instead of `--browser-url`:

1. Open Chrome → `chrome://inspect/#remote-debugging` → enable
2. Config:
```json
{
  "mcpServers": {
    "chrome-devtools": {
      "command": "npx",
      "args": ["-y", "chrome-devtools-mcp@latest", "--autoConnect"]
    }
  }
}
```
3. Chrome shows a permission dialog → click Allow
