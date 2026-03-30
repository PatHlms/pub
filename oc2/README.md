# oc2

AI coding assistant client. Connects to OpenAI and Google Gemini via raw HTTPS.

## Proprietary Software — All Rights Reserved

This software is **not open source** and is **not licensed for use, distribution, modification, or reproduction** in any form without explicit written permission from the author.

No open-source licence (MIT, Apache, GPL, etc.) applies to this codebase. The absence of a licence file does not imply permissive use — it means all rights are reserved by default.

---

## Requirements

- Python 3.12+
- No third-party packages. Stdlib only.

## Setup

```
cd oc2
cp .env .env.local   # edit with your API keys
```

`.env`:
```
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=AI...
```

## Usage

```bash
python main.py                        # OpenAI gpt-4o (default)
python main.py --provider gemini      # Google Gemini
python main.py --model gpt-4o-mini    # Override model
python main.py --config path/to/settings.json
python main.py --verbose              # Debug logging
```

## REPL commands

| Command | Description |
|---|---|
| `/provider openai\|gemini` | Switch provider mid-session |
| `/model <name>` | Switch model |
| `/file <path>` | Attach file to next message |
| `/clear` | Clear conversation history |
| `/help` | Show commands |
| `/quit` | Exit |

## Configuration

`config/settings.json`:

```json
{
  "provider": "openai",
  "system": "You are a helpful coding assistant.",
  "history_limit": 20,
  "openai": { "model": "gpt-4o", "max_tokens": 4096 },
  "gemini": { "model": "gemini-2.0-flash", "max_tokens": 4096 }
}
```

## Tests

```bash
python -m pytest tests/ -v
```
