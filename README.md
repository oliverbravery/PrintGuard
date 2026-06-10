# PrintGuard POC

Monolithic PyScript + FastAPI POC. One Python module (`core.py`) owns the math; backends differ only in where the model runs.

## Layout
- `core.py` — `load_assets`, `preprocess`, `classify`. Pure numpy, runs on CPython and Pyodide.
- `backends.py` — `ServerBackend` (ai-edge-litert, CPython).
- `server.py` — FastAPI: serves `main.html` + `models/`, exposes `POST /infer`.
- `main.html` + `app.py` — PyScript client. Toggle `local` (LiteRT.js) / `hub` (HTTP).
- `models/` — `encoder_float32.tflite`, `metadata.json`, `prototypes.json`.

## Run
```bash
uv sync
uv run uvicorn server:app --host 0.0.0.0 --port 8000
```
Open <http://localhost:8000>, start camera, hit Detect, toggle between modes.

## How the modes share logic
| Step | Local (PyScript) | Hub (PyScript → FastAPI) |
|---|---|---|
| Preprocess | `core.preprocess` | server: `core.preprocess` |
| Model run | LiteRT.js WASM | server: ai-edge-litert |
| Classify | `core.classify` | server: `core.classify` |

Adding a transform or class rule = one edit in `core.py`, both modes inherit it.
