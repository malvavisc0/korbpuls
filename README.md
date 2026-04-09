# 🏀 korbPuls.de

> Basketball league stats at your fingertips — standings, schedules & predictions.

korbPuls is a lightweight FastAPI web app that wraps the
[korb](https://github.com/malvavisc0/korb) CLI to serve German basketball
league data as clean, browsable HTML pages.

## ✨ Features

- **Standings** — full league table with points, wins, losses & differentials
- **Team detail** — game-by-game results and computed metrics for any team
- **Schedule** — upcoming games sorted by date
- **Predictions** — forecasted results and projected final standings
- **Eager caching** — all data fetched once and served instantly from disk
- **API key protection** — simple token-based access control

## 🚀 Quickstart

### Local development

```bash
# install dependencies
uv sync

# run with live reload
RELOAD=true ./run.sh
```

The app starts at **http://localhost:8000**.

### Docker

```bash
docker compose up --build
```

## 🔧 Configuration

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8000` | HTTP listen port |
| `WORKERS` | `2` | Uvicorn worker count |
| `RELOAD` | `false` | Enable live reload (dev only) |
| `CACHE_DIR` | `/data/cache` | Directory for cached league data |
| `KORBPULS_API_KEY` | — | API key for protected endpoints |
| `KORB_CMD` | `korb` | Path to the `korb` binary |

## 📂 Project structure

```
src/korbpuls/
├── __init__.py        # version
├── main.py            # FastAPI routes
├── auth.py            # API key validation
├── cache.py           # disk-based league data cache
├── korb_client.py     # korb CLI wrapper
├── presenters.py      # data formatting for templates
├── slugify.py         # URL-safe slug generation
├── templates/         # Jinja2 HTML templates
└── static/            # static assets
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
