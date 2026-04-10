# 🏀 korbPuls.de

> Basketball league stats at your fingertips — standings, schedules & AI-powered predictions.

korbPuls is a lightweight FastAPI web app that wraps the
[korb](https://github.com/malvavisc0/korb) CLI to serve German basketball
league data (from [basketball-bund.net](https://www.basketball-bund.net)) as
clean, browsable HTML pages — optimised for both desktop and mobile.

## ✨ Features

### Core

- **Standings** — full league table with rank, wins, losses, points scored/allowed, differentials, and per-game averages
- **Team detail** — game-by-game results, win streaks, computed quality metrics (win rate, average margins, blowouts, close games), and upcoming fixtures
- **Schedule** — complete season schedule sorted by date, with cancelled-game indicators
- **Predictions** — forecasted results for remaining games and a projected final standings table (available once at least half the season is played)

### AI-powered (optional)

When configured with an OpenAI-compatible LLM endpoint, korbPuls adds:

- **Team analysis** — AI-generated narrative about a team's form, strengths, weaknesses, and season trajectory
- **League prediction narrative** — AI explanation contextualising the statistical predictions with qualitative insights

AI features are fully optional — the app works without them.

### Technical

- **Eager caching** — all league data fetched once via korb and served from disk; one-hour TTL with manual refresh
- **Background fetching** — data downloads run asynchronously; users see a loading spinner with auto-refresh
- **Mobile-first responsive design** — optimised layouts for phones (360px+), tablets, and desktops
- **API endpoints** — JSON API with token-based access control for programmatic access
- **Dark theme** — "Court Night" design with custom typography (Syne + Source Serif 4)

## 🚀 Quickstart

### Local development

```bash
# install dependencies
uv sync

# run with live reload
RELOAD=true ./run.sh
```

The app starts at **http://localhost:8000**. Enter a Liga-ID from basketball-bund.net to get started.

### Docker

```bash
docker compose up --build
```

The container exposes port `8000` and persists cached data in a named Docker volume.

## 🚢 Deployment

### Docker Compose (recommended)

1. Clone the repository:
   ```bash
   git clone https://github.com/malvavisc0/korbpuls.de.git
   cd korbpuls.de
   ```

2. Create a `.env` file with your configuration:
   ```env
   # Required
   KORBPULS_API_KEY=your-secret-api-key

   # Optional — AI features (leave empty to disable)
   OPENAILIKE_API_BASE=https://api.example.com/v1
   OPENAILIKE_API_KEY=sk-...
   OPENAILIKE_LLM=gpt-4o-mini
   ```

3. Start the service:
   ```bash
   docker compose up -d --build
   ```

4. The app is now running at `http://localhost:8000`.

### Behind a reverse proxy (Nginx / Caddy)

korbPuls serves plain HTTP on the configured `PORT`. Put it behind a reverse proxy for TLS:

```nginx
# Nginx example
server {
    listen 443 ssl;
    server_name korbpuls.de;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```
# Caddyfile example
korbpuls.de {
    reverse_proxy localhost:8000
}
```

### Manual deployment (no Docker)

```bash
# Install dependencies
uv sync --no-dev

# Set environment variables
export KORB_CMD="uv run korb"
export CACHE_DIR="./files"
export KORBPULS_API_KEY="your-secret-api-key"

# Run with production settings
WORKERS=4 ./run.sh
```

## 🔧 Configuration

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8000` | HTTP listen port |
| `HOST` | `0.0.0.0` | Bind address |
| `WORKERS` | `2` | Uvicorn worker count (use 1 per CPU core) |
| `RELOAD` | `false` | Enable live reload (development only) |
| `CACHE_DIR` | `files` (local) / `/data/cache` (Docker) | Directory for cached league data |
| `KORBPULS_API_KEY` | — | API key for protected `/api/` endpoints |
| `KORB_CMD` | `uv run korb` (local) / `korb` (Docker) | Command to invoke the korb CLI |

### AI configuration (optional)

| Variable | Default | Description |
|---|---|---|
| `OPENAILIKE_API_BASE` | — | Base URL for an OpenAI-compatible API |
| `OPENAILIKE_API_KEY` | — | API key for the LLM provider |
| `OPENAILIKE_LLM` | — | Model name (e.g., `gpt-4o-mini`, `llama-3.1-70b`) |

Set all three to enable AI features. Leave any empty to disable.

## 📡 API

Protected endpoints require the `X-API-Key` header matching `KORBPULS_API_KEY`.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/liga/{ligaid}/standings` | League standings as JSON |
| `GET` | `/api/liga/{ligaid}/spielplan` | Schedule as JSON |
| `GET` | `/api/liga/{ligaid}/prognose` | Predictions as JSON |
| `GET` | `/api/liga/{ligaid}/team/{slug}` | Team results as JSON |

## 📂 Project structure

```
src/korbpuls/
├── __init__.py        # version
├── main.py            # FastAPI routes (HTML + API)
├── auth.py            # API key validation
├── cache.py           # disk-based league data cache
├── korb_client.py     # korb CLI wrapper
├── presenters.py      # data → view model transformation
├── slugify.py         # URL-safe slug generation
├── ai/
│   ├── config.py      # AI env-var configuration
│   ├── agents.py      # LlamaIndex AI agents
│   ├── tools.py       # korb tool bindings for agents
│   └── skills/        # AI prompt templates
├── templates/         # Jinja2 HTML templates
└── static/            # CSS and static assets
```

## 🛠️ Development

```bash
# lint
uv run ruff check src/

# type check
uv run mypy

# test
uv run pytest
```

## 📜 License

[MIT](LICENSE)

---

Made with ❤️ · Powered by [korb](https://github.com/malvavisc0/korb)
