# korbPuls Coding Standard

## Communication
You are talking to seniors. Be terse — no preamble, no recap, no
hand-holding, no "here's what I did" summaries. State results, not
intentions. Skip explanations unless explicitly asked. Never narrate
tool use. Answer the question; move on.

## Project
korbPuls — a self-hosted FastAPI dashboard for German basketball
leagues. It wraps the [korb](https://github.com/malvavisc0/korb) CLI,
which downloads and parses data from basketball-bund.net, and serves
cached JSON as server-rendered HTML: standings, schedules, results,
team pages, predictions, and optional AI analysis.

## Stack
- Python 3.12+, uv, `pyproject.toml` (hatchling backend, `src/` layout)
- FastAPI + uvicorn; Jinja2 templates in `src/korbpuls/templates/`
- Pydantic models for cache/view data (`src/korbpuls/presenters.py`)
- korb CLI invoked as a subprocess (`src/korbpuls/korb_client.py`),
  command overridable with `KORB_CMD`
- Optional AI via llama-index against an OpenAI-compatible endpoint;
  Langfuse tracing and Sentry error tracking are opt-in
- Type checker: **pyright**
- Lint/format: **ruff** (line-length 88)
- Complexity: **radon**
- Tests: **pytest** (`tests/` contains focused unit tests)

## Commands
```bash
uv sync                                  # install deps
RELOAD=true ./run.sh                     # local server with reload
./run.sh                                 # production-style server

uv run ruff check --fix .                # lint
uv run ruff format .                     # format
uv run pyright src/korbpuls              # type check
uv run radon cc src/korbpuls -s --show-closures   # complexity
uv run pytest                            # tests

docker compose up --build                # container build/run
```

Run `ruff check`, `ruff format --check`, and `pyright` after every
change. Run `radon` when touching a large function, and `pytest` when
tests exist for the area you changed.

## Known baseline
The repository has one accepted exception to the size rule:

- `main.py` and `presenters.py` exceed the 600-line limit. Extract new
  responsibilities into focused modules instead of growing them
  further; splitting the existing modules is a separate refactor.

All other checks are expected to pass: `ruff check`, `ruff format
--check`, `pyright`, `radon` with no C+ blocks, and `pytest`.

## Complexity budget
Do not add a function ranked **C or worse** (radon complexity > 10).
When you touch an existing C+ function, split it in the same pass using
early returns, extracted helpers, or dispatch tables instead of adding
more branches. Verify with:
```bash
uv run radon cc src/korbpuls -s --show-closures
```

## Dead code
No dead code. Remove unused fields, helpers, imports, models, and
template variables in the same change that makes them unused. There is
no vulture configuration; enforce this in review. A hit is a suspect:
check for template references, route registration, and framework
callbacks before deleting.

## Secrets and private data
Never commit secrets or personal data: `.env`, API keys, Langfuse keys,
Sentry DSNs, account-specific analytics IDs, tokens, or production logs.
`files/` is ignored cache — never force-add it.

League and team names from basketball-bund.net are public sports data,
but keep tests and examples synthetic: invented Liga-IDs (e.g. `99999`),
fictional team names, and made-up fixtures. Do not paste production
cache dumps or trace/session IDs into docs, tests, or commit messages.

## Priority
Clean, simple, maintainable code. Nothing else.

## Commits
One-line messages only. No body, no trailers.

## Rules
- DRY, KISS
- No unnecessary complexity
- No speculative fallbacks; but upstream HTML/JSON is untrusted, so a
  single malformed row must not crash a page
- Explicit > implicit
- Type hints always
- PEP 8 (ruff enforces, line-length 88)
- Meaningful names, small functions
- Fail fast on missing configuration and invalid state; degrade
  gracefully on malformed upstream data
- Prefer standard library
- No clever tricks
- Docstrings for public APIs
- No unnecessary inline comments
- Use uv (never pip / system python)
- Avoid new mutable module-level state
- No Python file over 600 lines in `src/`; `main.py` and
  `presenters.py` already exceed it — extract new responsibilities into
  focused modules instead of growing them further
- No `_` prefix on Pydantic fields or route handlers; module-private
  `_helpers` are acceptable for internal implementation

## Style
Write the simplest correct solution. Delete anything that isn't needed.

## Conventions
- Routes live in `src/korbpuls/main.py` and stay thin:
  fetch/validate → present → render. Business logic belongs in
  `presenters.py`, `cache.py`, `scheduler.py`, or a new module.
- `korb_client.py` is the only boundary to korb. Pass arguments as a
  list, never through a shell. `KORB_CMD` is split with `shlex`; keep
  the subprocess CWD aligned with `CACHE_DIR` so korb's relative
  `files/<ligaid>/` downloads land on the persistent volume.
- Cache access goes through `CacheDir`: atomic writes, per-league
  `standings.json`, `schedule.json`, `ergebnisse.json`, `predict.json`,
  `meta.json`, `status.json`, and `teams/*.json`. Never edit cache
  files by hand.
- Dates from basketball-bund are German wall-clock times. Parse with
  `parse_bb_datetime` / `BB_TZ` (Europe/Berlin); do not tag them UTC.
  Day-based decisions use `_today_bb()` so “today” means today in Berlin.
- Results (`ergebnisse.json`) are the source of truth for played games.
  Do not infer “played” from a start time having passed.
- AI features are optional: gate them on `AIConfig.from_env()`.
  Never render LLM output with `|safe`; use the `ai_html`/nh3 allowlist.
  Predictions are forecasts, never presented as facts.
- API routes under `/api/` require the `X-API-Key` header validated by
  `auth.py`. Do not add unprotected API routes.
- Configuration is environment-driven. New variables go into both
  `.env.example` and the README table, and empty AI settings must keep
  AI disabled.
- Tests go under `tests/` and cover pure logic (presenters, date/day
  handling, cache helpers) without network access or real cache files.
- Release commits bump the version in both `pyproject.toml` and
  `src/korbpuls/__init__.py`, then regenerate `uv.lock`.
