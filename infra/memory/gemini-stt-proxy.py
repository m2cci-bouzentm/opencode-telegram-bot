#!/usr/bin/env python3
"""Tiny proxy: Whisper-compatible /audio/transcriptions → Gemini API."""
import base64
import json
import os
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_STT_MODEL", "gemini-2.5-flash")
PORT = int(os.environ.get("STT_PROXY_PORT", "8787"))


def transcribe_with_gemini(audio_bytes, mime_type="audio/ogg"):
    audio_b64 = base64.standard_b64encode(audio_bytes).decode()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_KEY}"
    body = json.dumps({
        "contents": [{
            "parts": [
                {"inlineData": {"mimeType": mime_type, "data": audio_b64}},
                {"text": "Transcribe this audio exactly. Return only the transcription text, nothing else."}
            ]
        }],
        "generationConfig": {"temperature": 0}
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    resp = urllib.request.urlopen(req, timeout=60)
    result = json.loads(resp.read())
    text = result["candidates"][0]["content"]["parts"][0]["text"]
    return text.strip()


MIME_MAP = {
    ".ogg": "audio/ogg", ".oga": "audio/ogg", ".opus": "audio/ogg",
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
    ".webm": "audio/webm", ".flac": "audio/flac",
}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if "/audio/transcriptions" not in self.path:
            self.send_response(404)
            self.end_headers()
            return

        content_type = self.headers.get("Content-Type", "")
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        boundary = content_type.split("boundary=")[-1].encode()
        parts = body.split(b"--" + boundary)

        audio_data = None
        filename = "audio.ogg"
        for part in parts:
            if b'name="file"' in part:
                header_end = part.find(b"\r\n\r\n")
                if header_end == -1:
                    continue
                header_section = part[:header_end].decode(errors="ignore")
                audio_data = part[header_end + 4:].rstrip(b"\r\n--")
                fn_start = header_section.find('filename="')
                if fn_start != -1:
                    fn_start += 10
                    fn_end = header_section.find('"', fn_start)
                    filename = header_section[fn_start:fn_end]

        if not audio_data:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(json.dumps({"error": "no audio file"}).encode())
            return

        ext = os.path.splitext(filename)[1].lower()
        mime = MIME_MAP.get(ext, "audio/ogg")

        try:
            text = transcribe_with_gemini(audio_data, mime)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"text": text}).encode())
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def log_message(self, fmt, *args):
        print(f"[stt-proxy] {fmt % args}", file=sys.stderr)


if __name__ == "__main__":
    if not GEMINI_KEY:
        print("GEMINI_API_KEY not set", file=sys.stderr)
        sys.exit(1)
    print(f"Gemini STT proxy on :{PORT}, model={GEMINI_MODEL}", file=sys.stderr)
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
