# Kaggle model gateway

This gateway publishes already-running model services through **one HTTP listener on port 80**. It does not install or load the model weights; use a Kaggle notebook compatible with your exact Qwen abliterated checkpoint and Z-Image-Turbo implementation.

## Notebook setup

1. Start your Qwen OpenAI-compatible inference server listening on loopback, normally `127.0.0.1:8000`, with the exact model ID you want to serve. The model server can use a different internal port; only the gateway's public listener is port 80.
2. Start your Z-Image-Turbo API separately. Configure it to accept `POST {"prompt":"..."}` and return `image_url`, `image_base64`/ `mime_type`, or OpenAI-style `data[0].url`. Set its URL in `IMAGE_LOCAL_URL`.
3. Install the gateway dependencies: `pip install fastapi uvicorn httpx`.
4. Set a long random `KAGGLE_API_KEY`. Optionally set `QWEN_LOCAL_API_KEY` and `IMAGE_LOCAL_API_KEY` if your local services need them.
5. Set `QWEN_LOCAL_BASE_URL=http://127.0.0.1:8000/v1` and `IMAGE_LOCAL_URL` to your image API.
6. Start the gateway: `uvicorn kaggle_gateway:app --host 0.0.0.0 --port 80`.
7. Start Cloudflare Tunnel pointing at `http://127.0.0.1:80`. Use the same bearer token as `KAGGLE_API_KEY` in the ShardCloud app's `QWEN_API_KEY` and `IMAGE_API_KEY`, and set:
   - `QWEN_BASE_URL=https://YOUR-TUNNEL-HOST/v1`
   - `IMAGE_API_URL=https://YOUR-TUNNEL-HOST/v1/images/generations`

## Important

- Do not publish this gateway without a strong API key.
- Kaggle runtimes and temporary tunnel URLs can stop/change; update the ShardCloud environment after restarts.
- Qwen 27B and image generation may not fit in GPU memory simultaneously. The right quantization, inference server, and offloading depend on the actual GPU and checkpoint.
- Use the exact repository/model identifier for the model you downloaded; “Qwen 3.8 27B abliterated” may not be the formal model ID.
