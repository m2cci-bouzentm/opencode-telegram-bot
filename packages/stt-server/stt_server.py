#!/usr/bin/env python3
import base64
import json
import os
import subprocess
import sys
import tempfile
from abc import ABC, abstractmethod
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request


class STTProvider(ABC):
    @abstractmethod
    def transcribe(self, audio_bytes: bytes, mime_type: str) -> str: ...


class GeminiProvider(STTProvider):
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        self.api_key = api_key
        self.model = model

    def transcribe(self, audio_bytes: bytes, mime_type: str) -> str:
        audio_b64 = base64.standard_b64encode(audio_bytes).decode()
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        body = json.dumps({
            "contents": [{
                "parts": [
                    {"inlineData": {"mimeType": mime_type, "data": audio_b64}},
                    {"text": "Transcribe this audio exactly. Return only the transcription text, nothing else."},
                ]
            }],
            "generationConfig": {"temperature": 0},
        }).encode()
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=60)
        result = json.loads(resp.read())
        text = result["candidates"][0]["content"]["parts"][0]["text"]
        return text.strip()


class ParakeetProvider(STTProvider):
    def __init__(self, model_dir: str, use_gpu: bool = True):
        import onnx_asr
        import onnxruntime as ort

        available = ort.get_available_providers()
        providers = ["CPUExecutionProvider"]
        if use_gpu and "CUDAExecutionProvider" in available:
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]

        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        sess_options.intra_op_num_threads = 4

        self.model = onnx_asr.load_model(
            "nemo-parakeet-tdt-0.6b-v3",
            model_dir,
            quantization="int8",
            providers=providers,
            sess_options=sess_options,
        )

    def transcribe(self, audio_bytes: bytes, mime_type: str) -> str:
        with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as raw:
            raw.write(audio_bytes)
            raw_path = raw.name

        wav_path = raw_path + ".wav"
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", raw_path,
                    "-ar", "16000", "-ac", "1", "-f", "wav", wav_path,
                ],
                capture_output=True, check=True,
            )
            result = self.model.recognize(wav_path)
            return result.strip() if isinstance(result, str) else str(result).strip()
        finally:
            for p in (raw_path, wav_path):
                try:
                    os.unlink(p)
                except OSError:
                    pass


MIME_MAP = {
    ".ogg": "audio/ogg", ".oga": "audio/ogg", ".opus": "audio/ogg",
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
    ".webm": "audio/webm", ".flac": "audio/flac",
}

provider: STTProvider


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
            text = provider.transcribe(audio_data, mime)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"text": text}).encode())
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def log_message(self, fmt, *args):
        print(f"[stt-server] {fmt % args}", file=sys.stderr)


if __name__ == "__main__":
    STT_PROVIDER = os.environ.get("STT_PROVIDER", "parakeet")
    PORT = int(os.environ.get("STT_PORT", os.environ.get("STT_PROXY_PORT", "8787")))

    if STT_PROVIDER == "gemini":
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            print("GEMINI_API_KEY not set", file=sys.stderr)
            sys.exit(1)
        model = os.environ.get("GEMINI_STT_MODEL", "gemini-2.5-flash")
        provider = GeminiProvider(api_key, model)
    elif STT_PROVIDER == "parakeet":
        model_dir = os.environ.get("PARAKEET_MODEL_DIR", "/home/mohamed/bot/models/parakeet-v3-onnx")
        use_gpu = os.environ.get("PARAKEET_USE_GPU", "true").lower() == "true"
        provider = ParakeetProvider(model_dir, use_gpu)
    else:
        print(f"Unknown STT_PROVIDER: {STT_PROVIDER}", file=sys.stderr)
        sys.exit(1)

    print(f"STT server on :{PORT}, provider={STT_PROVIDER}", file=sys.stderr)
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
