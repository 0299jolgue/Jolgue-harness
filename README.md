# Jolgue Harness

A small agent workspace for a Qwen model and Z-Image-Turbo running on Kaggle, with the authenticated UI/API and SQLite database hosted separately.

## ShardCloud deploy

**This app supports ShardCloud's `python app.py` launcher and binds to port 80.** The server starts from the bottom of `app.py`; it will no longer exit immediately after Python executes the file.

1. Deploy branch `agent-harness` from this repository on ShardCloud.
2. Keep the start command as `python app.py` and expose port **80**.
3. Edit `config.json` in your deployment to set a long, private `app_api_key`. Do not commit a real key to a public GitHub repository.
4. Set `qwen_base_url` to the OpenAI-compatible Kaggle gateway URL ending in `/v1`, and `qwen_model` to the exact served model ID.
5. Set `image_api_url` to the Kaggle gateway's `/v1/images/generations` URL if image generation is available.
6. Mount persistent storage at `/data` if ShardCloud supports it, so SQLite history and workspace files survive restarts.
7. Check `https://YOUR-SHARD-CLOUD-HOST/health`. It should return JSON including `"ok": true` and `"port": 80`.

You can override config values with hosting-panel environment variables if desired; a `.env` file is not required. The JSON file is the primary config.

## config.json

- `host`: normally `0.0.0.0`
- `port`: `80` (do not change for this ShardCloud service)
- `app_api_key`: replace the public placeholder with a private, long random secret in the deployed config
- `qwen_base_url`, `qwen_api_key`, `qwen_model`: Qwen endpoint details
- `image_api_url`, `image_api_key`: image endpoint details
- `database_path`, `workspace_path`: persistent data locations
- `max_tool_steps`, `request_timeout_seconds`: agent limits

The API refuses authenticated requests until `app_api_key` is changed from its placeholder. Keep the key private and use HTTPS.

## Architecture

- **ShardCloud:** FastAPI app, agent tool loop, SQLite history, restricted workspace terminal.
- **Kaggle:** model gateway forwards requests to the Qwen and Z-Image-Turbo inference services.
- **Port 80:** ShardCloud app and Kaggle gateway are intended to expose port 80. Internal model servers can use private loopback ports.
- **Cloudflare Tunnel:** if you run cloudflared yourself, point it to `http://127.0.0.1:80`.

Models are not bundled here. Kaggle sessions and temporary Cloudflare URLs can expire; update `qwen_base_url` and `image_api_url` when the tunnel URL changes.

## Features

- Dark web UI.
- Authenticated `POST /v1/agent/run` with multi-step function calling.
- Web search, workspace list/read/write, and restricted terminal tools.
- Z-Image-Turbo proxy endpoint `POST /v1/images/generations`.
- OpenAI-compatible Qwen passthrough `POST /v1/chat/completions`.
- SQLite conversation/event storage and `GET /health`.

## Safety and limitations

The terminal uses an allowlist, no shell, a timeout, and the workspace as its working directory. This is a baseline, not a strong sandbox. Do not mount secrets or host directories into the terminal container. The browser stores the API key in session storage for the current tab.

The app/gateway do not load model weights by themselves. Start the inference servers on Kaggle, then point the gateway at them. This project has not yet been validated against your actual ShardCloud account or Kaggle model endpoints.

## Local run

```bash
pip install -r requirements.txt
# Edit config.json first, then:
python app.py
```
