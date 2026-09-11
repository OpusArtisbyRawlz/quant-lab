# `quant` — Quant Research Factory CLI

A thin, user-facing terminal interface over the **existing** Research Factory. It is
an interface layer only: every command delegates to an existing service
(`CampaignManager`, `PortfolioPlanner`, `FactoryRunner`, `ResearchLoop`, and the
`agents.reporting` read-models). It adds **no** research logic, agents, orchestration,
scheduling, persistence, or state, and does not touch the M11 statistical
methodology. Read-only commands never mutate the database.

## Installation / setup

The CLI ships as a standard console-script entry point. From the repository root,
with the project virtualenv activated:

```bash
source venv/bin/activate          # activate the venv
pip install -e .                  # registers the `quant` command (editable)
quant --help
```

`pip install -e .` adds only the `quant` script; runtime dependencies already live in
the venv (see `requirements.txt`), so nothing else is installed or changed.

By default the CLI uses the repository database at `agents/quant_agents.db`. Point any
command at a different database with a global `--db`:

```bash
quant --db /path/to/other.db status
```

## Commands

```
quant status                       # campaign/portfolio counts

quant campaign list                # id, state, type, priority, portfolio, progress
quant campaign create [--id ID] [--theme T] [--priority P] [--budget N]
                      [--type TYPE] [--portfolio PID] [--activate]
quant campaign show   <campaign_id>
quant campaign run    <campaign_id> [--ticks N]   # ResearchLoop tick(s), then advance
quant campaign pause  <campaign_id>               # archive/shelve (reversible)
quant campaign resume <campaign_id>               # activate

quant portfolio list
quant portfolio show <portfolio_id>
quant portfolio plan <portfolio_id>               # PortfolioPlanner: admitted + cycles
quant portfolio run  <portfolio_id>               # one tick per admitted campaign

quant report campaign  <campaign_id>              # markdown campaign board
quant report portfolio <portfolio_id>             # concise portfolio summary

quant factory run [--ticks N] [--rounds N]        # FactoryRunner driver
quant factory status                              # active campaigns, latest tick

quant shell                                       # interactive command shell
```

Notes:
- **pause/resume** map to the existing campaign transitions: *pause* → `ARCHIVED`
  ("paused / shelved, may be revisited"), *resume* → `ACTIVE`. Both are audited,
  event-sourced transitions through `CampaignManager`.
- **campaign run / portfolio run / factory run** execute real ticks via the existing
  `ResearchLoop` / `FactoryRunner` (append-only, deterministic, checkpoint-resumable);
  they honour the human approval gate and the Project 07 hand-off exactly as before.
- Invalid ids exit non-zero with a clear `error: no such …` message on stderr.

### Examples

```bash
quant status
quant campaign create --id momentum-2024 --theme "cross-sectional momentum" \
      --priority 3 --portfolio equities --activate
quant campaign show momentum-2024
quant portfolio plan equities
quant factory run --ticks 5
quant report campaign momentum-2024 | less
```

## Interactive shell

`quant shell` opens a lightweight interactive command shell over the same handlers.
It is **not** an LLM chatbot and does no natural-language interpretation — it maps
fixed keyword commands to the existing factory APIs:

```
$ quant shell
quant> status
quant> list campaigns
quant> list portfolios
quant> show campaign momentum-2024
quant> show portfolio equities
quant> show active portfolio
quant> plan portfolio equities
quant> run campaign momentum-2024
quant> run portfolio equities
quant> run factory
quant> report campaign momentum-2024
quant> show latest report
quant> help
quant> quit
```

Type `help` for the command list; `quit`/`exit` (or EOF/Ctrl-D) leaves the shell.
(Natural-language interpretation is intentionally out of scope until there is a clean
existing interface for it.)
