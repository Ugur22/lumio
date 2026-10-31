# Features: rules and limits

## Writing

- **Streaming replies.** Any provider that speaks the OpenAI chat-completions API. Replies render as Markdown with syntax highlighting. `"Quoted speech"` and `*actions*` are styled, and the model is asked to use `[[key]]`, `[[note]]` and `[[warn]]` tags for emphasis. Chats store the raw text; styling is applied when rendering, and reply text is sanitized because it is untrusted.
- **Story bible.** Free-text canon for the chat, up to 20,000 characters, sent with every message.
- **Triggered lore.** Named entries with trigger keys, up to 200 per chat. An enabled entry is sent only when one of its keys appears, as a whole word and ignoring case, in the last 6 messages or the message being sent.
- **Summaries.** The **Generate** button on the Summary tab asks the model to condense older messages; you edit the proposal and save it (up to 20,000 characters). Messages covered by the summary stay stored and visible but are no longer sent. The latest 6 messages are never summarized, so Generate is unavailable until a chat has more than 6 messages beyond the last summary. Summaries are never created automatically.
- **Per-chat behavior.** A system prompt (up to 10,000 characters), temperature, top-p, frequency penalty, max tokens, and an optional provider and model for the chat. If a chat's provider is deleted, the chat falls back to the default profile.
- **Context meter.** Shows used tokens against the context window. The total is the prompt token count the provider reported on the last reply, and an estimate (characters / 4) before that. The breakdown by system prompt, bible, lore, summary and history is always an estimate. The window size is entered on the provider profile (prefilled when the provider's model list reports it, as OpenRouter's does), so the percentage appears only when a window is known.

## Media and tools

- **Illustrations.** If the profile has an image model, an **Illustrate** toggle appears in the composer. The model is asked to place up to three `[[image: …]]` lines per reply, and each prompt (cut to 1,000 characters) is sent to the provider's `/images/generations` endpoint, expecting `b64_json` responses. Extra lines beyond three are dropped. A failed image is dropped and reported; the text stays. The xAI preset fills in an image model; for other providers you set one yourself.
- **Image input.** Attach, paste or drop up to 4 images, 5 MB each, when the profile is marked vision-capable. Sending images to a profile not marked as vision is refused, and so is illustrating without an image model.
- **Web search (optional).** With a Tavily key saved in **Providers**, the **Web** toggle searches for each message. Links you paste (up to 3) are fetched whether or not a key is set. Pages are added to the prompt as untrusted reference text and shown as sources under the reply.
  - Fetch limits: 1 MB per page, 10 s timeout, 6,000 characters kept per page, up to 4 redirects.
  - Only public addresses are fetched; localhost and private networks are refused, including after redirects.
  - Pages that need JavaScript to render are not readable.
- **Code execution.** Fenced `python` and `javascript` blocks get a **Run** button. Code runs in your browser in a hidden sandboxed iframe with no network access and a time limit. Python uses Pyodide, bundled with the app, so it works offline. `input()` and `prompt()` read from a stdin field. Other languages get no Run button. The Cypress journey covers running a JavaScript block; the Python path has unit tests for the sandbox pieces but no end-to-end test.

## Chats

- Saved chats can be renamed and deleted; deleting a chat removes its images.
- One reply per chat can be generated at a time. A second send to a chat that is still replying gets `409`; other chats are unaffected.
- Light and dark themes.
