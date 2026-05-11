# AI Agent Skills

Developer documentation for the four AI agents in korbPuls. Each agent is a
[LlamaIndex FunctionAgent](https://docs.llamaindex.ai/) with a dedicated
**skill file** (loaded as the system prompt) and a **Pydantic output model**
(for structured responses).

> **Note:** The skill `.md` files are loaded directly into the agent's system
> prompt. Keep them lean — every token counts against the context window.

---

## Architecture

```mermaid
graph LR
    subgraph Prompt
        CM[Common Instructions] --> SK[Skill Markdown]
    end
    SK --> AG[FunctionAgent]
    TO[run_korb_command tool] --> AG
    AG -->|structured output| PY[Pydantic Model]
    AG -->|retry up to 3x| AG
```

- **Common instructions** (`agents.py` → `_COMMON_INSTRUCTIONS`): shared
  constraints (exact team names, German output, HTML only, no jargon).
- **Skill markdown**: step-by-step analysis workflow loaded per agent.
- **Tool**: `run_korb_command` — scoped access to the `korb` CLI for fetching
  standings, schedules, results, and predictions.
- **Retry logic** (`main.py` → `_retry_agent`): up to 3 attempts with
  exponential backoff. Handles both exceptions and `None` structured output.

### Trigger Modes

| Agent | Trigger | When |
|---|---|---|
| Commentator | **Auto** | After every data refresh (if data changed or AI missing) |
| Oracle | **Auto** | After every data refresh (if prediction-eligible) |
| Analyst | **Manual** | Button on team page |
| Scout | **Manual** | Button on matchup page |

A startup recovery hook (`_recover_ai_analyses`) re-triggers any missing or
failed auto-generated analyses after server restarts.

---

## Agents

### 1. Analyst → Team Analysis

**Role:** Deep-dive on a single team — identity, strengths, weaknesses, peer
comparison.

**Skill:** [`TEAM_ANALYSIS.md`](TEAM_ANALYSIS.md)
**Output model:** `TeamAnalysis` (2–3 `<p>` elements, 10–15 sentences)

```mermaid
graph TD
    A["Inputs: TEAM_NAME, LIGA_ID"] --> B["Step 1: Read standings<br/><code>--json standings</code>"]
    B --> B1["Extract: rank, record, scoring profile"]
    B --> B2["Extract: league-wide comparative data<br/>top-4, offense/defense ranking, peer group"]
    B1 --> C["Step 2: Read team results<br/><code>--json team TEAM_NAME</code>"]
    B2 --> C
    C --> C1["Recent sample: last 5 → record, momentum"]
    C --> C2["Opponent-tier split: vs top-4 vs rest"]
    C1 --> D["Step 3: Read predictions<br/><code>--json predict</code>"]
    C2 --> D
    D --> E{"Predictions empty?"}
    E -->|"Yes"| F["Season finalized → retrospective"]
    E -->|"No"| G["Note predicted rank"]
    E -->|"Error"| H["Skip (optional)"]
    F --> I["Step 4: Internal worksheet<br/>(not included in output)"]
    G --> I
    H --> I
    I --> J["Step 5: Write analysis"]
    J --> J1["¶1: Identity & season story (3–4 sentences)"]
    J --> J2["¶2: Strengths & weaknesses (4–5 sentences)"]
    J --> J3["¶3: Peer comparison & verdict (3–4 sentences)"]
    J1 --> K["Output: TeamAnalysis"]
    J2 --> K
    J3 --> K
```

---

### 2. Commentator → Standings Narrative

**Role:** Quick, accessible league overview — one interesting storyline.

**Skill:** [`STANDINGS_NARRATIVE.md`](STANDINGS_NARRATIVE.md)
**Output model:** `StandingsNarrative` (1 `<p>` element, 3–5 sentences)

```mermaid
graph TD
    A["Input: LIGA_ID"] --> B["Step 1: Read standings<br/><code>--json standings</code>"]
    B --> B1["Extract: leader, chasers, bottom,<br/>league shape, notable stats"]
    B1 --> C["Step 2: Check predictions (optional)<br/><code>--json predict</code>"]
    C --> D{"Very few games played?<br/>(1–3 per team)"}
    D -->|"Yes"| E["Early season: hedge, use 'bisher'"]
    D -->|"No"| F["Step 3: Choose one storyline<br/>tight race? runaway? compressed middle?"]
    E --> F
    F --> G["Step 4: Write narrative"]
    G --> G1["Open: headline takeaway"]
    G --> G2["Support: 1–2 concrete data points"]
    G --> G3["Close: forward-looking or retrospective"]
    G1 --> H["Output: StandingsNarrative"]
    G2 --> H
    G3 --> H
```

---

### 3. Oracle → League Prediction

**Role:** Predicted final standings table with explanatory analysis.

**Skill:** [`LEAGUE_PREDICTION.md`](LEAGUE_PREDICTION.md)
**Output model:** `LeaguePrediction` (HTML `<table>` + 1 `<p>` element)

```mermaid
graph TD
    A["Input: LIGA_ID"] --> B["Step 1: Read standings<br/><code>--json standings</code>"]
    B --> C["Step 2: Run prediction<br/><code>--json predict</code>"]
    C --> D{"Predictions empty?"}
    D -->|"Yes"| E["Season finalized:<br/>use current standings as final table,<br/>write retrospective (past tense)"]
    D -->|"No"| F["Use predicted standings table"]
    D -->|"Error"| G["Fall back to current standings"]
    E --> H["Step 3: Choose league story<br/>runaway? two-horse? compressed?"]
    F --> H
    G --> H
    H --> I["Step 4: Build HTML table<br/>Columns: Team, W, L, Pts, Diff<br/>Format diff with sign (+120 / -48)"]
    I --> J["Step 5: Write explanation"]
    J --> J1["Lead: league story"]
    J --> J2["Shape: settled, unstable, tightly packed"]
    J --> J3["Most meaningful battle"]
    J --> J4["Close: verdict or caution"]
    J1 --> K["Output: LeaguePrediction"]
    J2 --> K
    J3 --> K
    J4 --> K
```

---

### 4. Scout → Matchup Preview

**Role:** Pre-game analysis for an upcoming head-to-head matchup.

**Skill:** [`MATCHUP_PREVIEW.md`](MATCHUP_PREVIEW.md)
**Output model:** `MatchupPreview` (2–3 `<p>` elements, 8–12 sentences)

```mermaid
graph TD
    A["Inputs: HOME_TEAM, AWAY_TEAM, LIGA_ID"] --> B["Step 1: Read standings<br/><code>--json standings</code>"]
    B --> B1["Extract both teams:<br/>rank, record, scoring profile"]
    B1 --> B2["Compare directly:<br/>who ranks higher, better diff,<br/>scores more, allows fewer"]
    B2 --> C["Step 2: Read team results<br/><code>--json team HOME</code><br/><code>--json team AWAY</code>"]
    C --> C1["Recent form: last 5 for both"]
    C --> C2["Head-to-head: check each other's results"]
    C1 --> D["Step 3: Read ergebnisse<br/><code>--json ergebnisse</code>"]
    C2 --> D
    D --> D1["Find all previous meetings this season<br/>Note scores, outcomes, patterns"]
    D1 --> E["Step 4: Internal worksheet<br/>(not included in output)"]
    E --> F["Step 5: Write preview"]
    F --> F1["¶1: The matchup on paper (3–4 sentences)"]
    F --> F2["¶2: Form and head-to-head (3–4 sentences)"]
    F --> F3["¶3: What to watch for (2–3 sentences)"]
    F1 --> G["Output: MatchupPreview"]
    F2 --> G
    F3 --> G
```

---

## Common Constraints

All agents share these rules (defined in `_COMMON_INSTRUCTIONS`):

| Rule | Rationale |
|---|---|
| Use exact team names from standings data | Prevents hallucinated/mismatched names |
| Write in German with proper umlauts (ä, ö, ü, ß) | Target audience is German amateur basketball community |
| Generate original analysis — never copy skill examples | Prevents template-like output |
| Always use HTML, never Markdown | Output is rendered directly in web templates |
| No jargon | Audience includes parents and casual fans |
| Return only structured output required by schema | Keeps responses focused and parseable |

## Adding a New Agent

1. Create a skill file in `src/korbpuls/ai/skills/NEW_SKILL.md`
2. Define a Pydantic output model in `agents.py`
3. Create a `get_<name>()` factory function in `agents.py`
4. Add the trigger logic in `main.py` (auto via `_fetch_and_auto_generate` or manual via POST route)
5. If auto-generated, add recovery logic to `_recover_ai_analyses`