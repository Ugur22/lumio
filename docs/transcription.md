# Local song transcription

Lumio can transcribe a single YouTube video on your own machine with [whisper.cpp](https://github.com/ggml-org/whisper.cpp), then let you edit the text and ask your chat model about it. It is a local-only experiment: it is never offered on a deployed instance (`DOLPHINLLM_PUBLIC_HOST` set), and nothing is downloaded automatically.

## Privacy

- **Transcription is local.** Audio is fetched with yt-dlp from YouTube, converted by FFmpeg and transcribed by whisper.cpp on this computer. No audio is sent to any other service. Temporary audio is deleted after every run, including failed and cancelled ones.
- **Analysis is not local.** When you attach a transcript to a message, the transcript text is sent to your selected chat provider like the rest of the conversation. Only attach text you are willing to share with that provider.
- Transcripts are stored in the chat database (`data/chats/lumio.db`) and deleted with their chat.

## Setup (once, separate from starting Lumio)

You need yt-dlp, FFmpeg (with ffprobe), a JavaScript runtime for YouTube (yt-dlp recommends deno; node.js, bun and QuickJS also work), and whisper.cpp with a model. Install yt-dlp and FFmpeg however you prefer (see the [yt-dlp installation guide](https://github.com/yt-dlp/yt-dlp/wiki/Installation)); Lumio only needs them on `PATH` or at the paths you configure.

### whisper.cpp

Build from source (the route the upstream README documents):

```bash
git clone https://github.com/ggml-org/whisper.cpp.git
cd whisper.cpp
cmake -B build
cmake --build build -j --config Release
```

This produces `build/bin/whisper-cli`. On Apple Silicon, inference runs on the GPU through Metal by default; no extra build flag is needed. Check the flags your build supports with `build/bin/whisper-cli -h`.

### Model (about 3 GB, downloaded by you)

```bash
sh ./models/download-ggml-model.sh large-v3
```

This writes `models/ggml-large-v3.bin`. Lumio never downloads a model itself.

### Configure Lumio

Set these in your environment or `.env` (all optional except the two whisper paths):

| Variable | Default | Meaning |
| --- | --- | --- |
| `DOLPHINLLM_WHISPER_CLI_PATH` | unset | Path to `whisper-cli` |
| `DOLPHINLLM_WHISPER_MODEL_PATH` | unset | Path to `ggml-large-v3.bin` |
| `DOLPHINLLM_YT_DLP_PATH` | `yt-dlp` | yt-dlp executable |
| `DOLPHINLLM_FFMPEG_PATH` | `ffmpeg` | FFmpeg executable |
| `DOLPHINLLM_TRANSCRIBE_MAX_MINUTES` | `20` | Longest video accepted |
| `DOLPHINLLM_TRANSCRIBE_MAX_DOWNLOAD_MB` | `100` | Largest audio download |
| `DOLPHINLLM_TRANSCRIBE_TIMEOUT_MINUTES` | `30` | Whole-run limit |

Until both whisper paths exist and the tools resolve, the feature stays disabled and the dialog says what is missing.

## Limits

One video at a time, one job at a time. Playlists and live streams are rejected. The language is auto-detected unless you name it; naming it is recommended for music, because detection on non-speech audio can pick the wrong language. Lumio does not translate, rewrite or fill in missing lyrics; the original transcript is kept next to your edits.

## Manual evaluation guide

Try 5-10 songs: different languages, one with heavy instrumentation, one with fast or layered vocals, one with a long instrumental section, one repetitive chorus. For each, with the language both on auto and named, compare the transcript to the real lyrics and note:

| Song / language | Missed lines | Repeated text (loops) | Invented words or lines | Wrong language | Run time |
| --- | --- | --- | --- | --- | --- |

Look especially for: lines dropped during loud sections, a phrase repeated many times through an instrumental break (a known Whisper failure), plausible-sounding text where there is only music, and mixed-language lyrics forced into one language. Compare timestamps in the segment list against the video at a few points. Lumio runs whisper-cli with `-mc 0` (no text carried between segments). Without it, a test song came back as "المترجم للقناة" ("translator for the channel", a subtitle credit Whisper learned from its training data) repeated for the whole track; with it, the same audio gave the lyrics. Credit-like lines such as "subscribe to the channel" can still appear over intros and instrumental breaks: they are inventions, not lyrics, and Lumio does not remove them for you, so delete them when you edit. If the whole result is one repeated phrase, Lumio refuses it as a failed transcription. Record findings before changing any whisper-cli options, and check each option against `whisper-cli -h` first.
