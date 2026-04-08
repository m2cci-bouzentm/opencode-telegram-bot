# STT Server — Speech-to-Text with Provider Pattern

Whisper-compatible API server (POST /audio/transcriptions) with swappable backends.

## Providers

| Provider | Engine | Latency | Cost | GPU needed |
|---|---|---|---|---|
| parakeet | NVIDIA Parakeet v3 ONNX (local) | ~1-3s | Free | Optional (CPU works) |
| gemini | Gemini 2.5 Flash API | ~2-4s | API quota | No |

## Switching providers

Edit .env:
```
STT_PROVIDER=parakeet   # or gemini
```

Then: `sudo systemctl restart stt-server.service`

## Parakeet config

```
PARAKEET_MODEL_DIR=/path/to/models/parakeet-v3-onnx
PARAKEET_USE_GPU=true
```

Download model (~670MB):
```bash
python3 -c "from huggingface_hub import snapshot_download; snapshot_download('istupakov/parakeet-tdt-0.6b-v3-onnx', local_dir='./models/parakeet-v3-onnx')"
```

## Gemini config

```
GEMINI_API_KEY=your_key
GEMINI_STT_MODEL=gemini-2.5-flash
```

## API

POST /audio/transcriptions — multipart form, file field. Returns `{"text": "..."}`. Whisper-compatible.

## Deps

```bash
pip install onnx-asr onnxruntime soundfile ffmpeg-python
```

Needs ffmpeg system-wide.
