# Knowledge Base — Phase 2 Stub

This folder is reserved for the Research Agent's external knowledge store.
Nothing is implemented here in Phase 1.

## Intended schema (Phase 2)

### papers/
Abstracts and relevance scores from arXiv, SSRN, and other sources.

```
papers/
  {arxiv_id}.json   # { title, abstract, authors, year, tags, relevance_score, notes }
```

### notes/
Agent-authored research summaries, linked back to experiments and signals.

```
notes/
  {slug}.md         # Free-form markdown; frontmatter: { experiment_ids, signals, date }
```

### market_regimes/
Regime definitions and per-regime feature performance tables.

```
market_regimes/
  definitions.json  # { regime_name: { description, detection_rule, example_periods } }
  performance/
    {regime_name}.csv  # feature × metric table (IC, Sharpe contribution, hit rate)
```

### external_feeds/ (Phase 3+)
Connectors for live external data sources.

```
external_feeds/
  connectors/
    arxiv.py        # arXiv search API wrapper
    ssrn.py         # SSRN search scraper
    fred.py         # FRED macro data connector
    news.py         # Financial news aggregator
  cache/            # Local cache of fetched content (gitignored)
```

## Design principles

- All external data is cached locally before use (no live API calls during backtests).
- Each paper/note/regime entry is linked to the experiment(s) that prompted it.
- The Idea Generator reads this folder in Phase 2 to enrich hypothesis generation.
- The Research Agent writes to this folder after each external search.
- Nothing in this folder affects backtest results — it is advisory context only.
