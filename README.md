# Jolgue Harness

A small agent workspace for a Qwen model and Z-Image-Turbo running on Kaggle, with the authenticated UI/API and SQLite database hosted separately.

## Architecture

- **ShardCloud:** FastAPI web app, agent tool loop, SQLite history, restricted workspace terminal.
- **Kaggle:** serves Qwen through an OpenAI-compatible API and Z-Image-Turbo through an image API.
- **Port 80:** Docker image listens on port 80. Configure ShardCloud's HTTP service to use container port 80.
- **Cloudflare:** point a Cloudflare Tunnel at `http://127.0.0.1:80` if you manage the tunnel yourself.

Models are not bundled here. Kaggle sessions are temporary; when a session or tunnel restarts, update the endpoint URLs. Store `/data` on a persistent ShardCloud volume to preserve SQLite and workspace files.

## Deploy

1. Deploy branch `agent-harness` from this repository on ShardCloud.
2. Build from the included Dockerfile and expose container port **80**.
3. Mount a persistent volume at `/data` if supported.
4. Set environment variables in the hosting panel. Generate a strong random `APP_API_KEY`.
5. Set `QWEN_BASE_URL` to the OpenAI-compatible base URL on Kaggle (usually ending in `/v1`), and `QWEN_MODEL` to the exact model ID served by your inference server.
6. Set `IMAGE_API_URL` to your image endpoint. It should accept `POST {"prompt":"..."}` and return `{"image_url":"https://..."}`, `{"image_base64":"...","mime_type":"image/png"}`, or an OpenAI-style `{"data":[{"url":"..."}]}`.
7. Publish the ShardCloud service through HTTPS/Cloudflare. If running cloudflared yourself, tunnel to port 80.

## Environment variables

See `.env.example`. Do not commit real API keys. The app refuses authenticated API access if `APP_API_KEY` is unset or left at its placeholder value.

## Features

- Dark web UI.
- Authenticated `POST /v1/agent/run` with a multi-step function-calling loop.
- Web search, workspace list/read/write, and restricted terminal tools.
- Z-Image-Turbo proxy endpoint `POST /v1/images/generations`.
- OpenAI-compatible Qwen passthrough `POST /v1/chat/completions`.
- SQLite conversation/event storage and `GET /health`.

## Safety and limitations

The terminal is intentionally restricted to an allowlist and runs without a shell, inside the workspace, with a timeout. This is a useful baseline, not a strong security sandbox. Do not mount secrets or host directories into the terminal container. Keep the API key private and use HTTPS. The browser stores the key in session storage for the current tab.

This project has not been tested against your actual Kaggle model or ShardCloud account yet. Check the model ID, GPU capacity, inference API route and image endpoint format before relying on it.

## Local run

```bash
pip install -r requirements.txt
export APP_API_KEY='replace-with-a-long-random-secret'
export QWEN_BASE_URL='https://your-kaggle-endpoint/v1'
export QWEN_MODEL='your-served-model-id'
uvicorn app:app --host 0.0.0.0 --port 80
```
