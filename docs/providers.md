# Providers

A provider is a profile: name, base URL, model, and optional context window, vision flag and image model. The backend calls the profile's base URL directly with the OpenAI Python SDK.

## Presets

Presets fill in a base URL and a default model, both editable. Source: `frontend/src/lib/providers.ts`.

| Preset | Base URL | Default model |
| --- | --- | --- |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| OpenRouter | `https://openrouter.ai/api/v1` | `openai/gpt-4o-mini` |
| Groq | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| xAI (Grok) | `https://api.x.ai/v1` | `grok-4` (image model `grok-imagine-image-2.0`) |
| Together | `https://api.together.xyz/v1` | `meta-llama/Llama-3.3-70B-Instruct-Turbo` |
| Anthropic (OpenAI-compatible) | `https://api.anthropic.com/v1` | `claude-sonnet-5-5` |
| Dolphin | `https://api.dolphinllm.com/v1` | `uncensored` |
| Ollama (local, no key) | `http://localhost:11434/v1` | `llama3.2` |
| Custom | any OpenAI-compatible endpoint | none |

Pasting a key suggests a preset from its prefix; you always confirm.

## Requirements

- An OpenAI-compatible `/chat/completions` endpoint with streaming.
- `/models` is used by the Providers dialog to test a key and list models. A provider without it can still be used by typing the model name.
- Base URLs must be `https`, except localhost.
- Vision, the image model and the context window are set by you; Lumio cannot detect them.
- Image generation uses `/images/generations` with `b64_json` responses.

## Compatibility

Presets are conveniences, not a compatibility guarantee. This repository's tests exercise provider paths only against a local stub server, so behavior against each live API is not verified here. Providers differ in what they support, for example image generation, vision and streaming usage counts (which feed the context meter).

## Local versus deployed

- **Local:** one set of profiles in `profiles.json`; keys in the OS keychain. A local Ollama works.
- **Deployed:** each account has its own profiles and keys. Provider URLs must resolve to public addresses, so a local Ollama cannot be used from a server. A saved key is never sent to a different base URL than the one it was saved for.
- **Legacy key:** a `DOLPHINLLM_API_KEY` in `.env` still works as a fallback for setups that predate profiles; it becomes the "Dolphin" profile. On a server it belongs to the account named by `DOLPHINLLM_ADMIN_USER`.
