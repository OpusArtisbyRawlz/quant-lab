"""
SQLite connection and schema management for the quant agent system.

Single database: agents/quant_agents.db
All tables created here via create_all_tables().
Schema versioning is handled by a simple schema_version table.
"""

from __future__ import annotations
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "quant_agents.db"

SCHEMA_VERSION = 12

_CREATE_SCHEMA_VERSION = """
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_CREATE_EXPERIMENTS = """
CREATE TABLE IF NOT EXISTS experiments (
    experiment_id           TEXT PRIMARY KEY,
    project                 TEXT,
    date                    TEXT,
    hypothesis              TEXT,
    target                  TEXT,
    features                TEXT,       -- JSON array
    model                   TEXT,
    market                  TEXT,
    universe                TEXT,
    -- Milestone 10 PR-4: bar sampling clock for this experiment. First-class,
    -- typed field (one of protocol.SUPPORTED_BAR_TYPES). Defaults to 'time' so
    -- every pre-M10 experiment is unambiguously a time-bar experiment.
    bar_type                TEXT NOT NULL DEFAULT 'time',
    validation_method       TEXT,
    expected_improvement    TEXT,
    success_criteria        TEXT,       -- JSON object
    -- Experiment type taxonomy
    -- portfolio: cross-sectional long/short, return-based strategies
    -- classification: directional prediction (AUC, accuracy, precision, recall)
    -- regression: return magnitude prediction (MSE, MAE, R²)
    -- risk_overlay: drawdown-aware exposure overlays (calmar, avg_exposure, MDD reduction)
    experiment_type         TEXT,

    -- Portfolio / risk overlay metrics (NULL for other types)
    primary_metric          TEXT,
    sharpe                  REAL,
    mdd                     REAL,
    cagr                    REAL,
    vol                     REAL,
    calmar                  REAL,

    -- Milestone 5: net-of-cost metrics, turnover, and robustness (NULL pre-M5)
    net_sharpe                  REAL,
    net_mdd                     REAL,
    net_cagr                    REAL,
    net_vol                     REAL,
    net_calmar                  REAL,
    turnover_annualized         REAL,
    turnover_average_period     REAL,
    transaction_cost_annualized REAL,
    slippage_annualized         REAL,
    robustness_flags            TEXT,   -- JSON array of flag strings

    -- Milestone 7: provenance for experiments created from an approved LLM idea
    -- (NULL for experiments that did not originate from the idea generator)
    source_idea_id              TEXT,   -- originating pending_ideas.idea_id
    source_model                TEXT,   -- model that proposed the idea

    -- Native metrics stored as-is from metrics.json, regardless of type
    -- e.g. {"auc": 0.54, "accuracy": 0.59} for classification experiments
    raw_metrics             TEXT,       -- JSON object

    result_summary          TEXT,
    conclusion              TEXT,
    status                  TEXT,       -- active / completed / rejected
    decision                TEXT,       -- keep / reject / retest
    next_action             TEXT,
    artifact_path           TEXT,
    created_at              TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at              TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_CREATE_SIGNAL_LIBRARY = """
CREATE TABLE IF NOT EXISTS signal_library (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    feature_name                TEXT NOT NULL UNIQUE,
    signal_type                 TEXT,       -- momentum / mean_reversion / volatility / macro / composite
    market                      TEXT,
    universe                    TEXT,
    project_source              TEXT,
    experiment_ids              TEXT,       -- JSON array of experiment_id strings
    performance_contribution    REAL,       -- avg IC or Sharpe contribution; NULL if not yet measured
    weakness                    TEXT,
    possible_combinations       TEXT,       -- JSON array of feature_name strings
    keep_reject_retest          TEXT,       -- keep / reject / retest
    notes                       TEXT,
    -- Milestone 9: context-aware signal lifecycle (activates the dormant
    -- lifecycle; also reconciled onto pre-v7 DBs via _ADDITIVE_COLUMNS).
    lifecycle_state             TEXT NOT NULL DEFAULT 'observed',  -- observed/candidate/promoted/retired
    generalization_class        TEXT,       -- universal/market_specific/universe_specific/regime_specific/unproven
    promoted_at                 TEXT,
    retired_at                  TEXT,
    last_evaluated_at           TEXT,
    created_at                  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at                  TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_CREATE_LESSONS_LEARNED = """
CREATE TABLE IF NOT EXISTS lessons_learned (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id   TEXT NOT NULL,
    cycle_id        TEXT,
    category        TEXT,   -- signal / risk / overfitting / regime / portfolio / other
    finding         TEXT NOT NULL,
    implication     TEXT,
    confidence      TEXT,   -- high / medium / low
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id)
)
"""

_CREATE_STRATEGY_VARIANTS = """
CREATE TABLE IF NOT EXISTS strategy_variants (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id       TEXT NOT NULL,
    strategy_name       TEXT NOT NULL,
    sharpe              REAL,
    mdd                 REAL,
    cagr                REAL,
    vol                 REAL,
    calmar              REAL,
    avg_exposure        REAL,
    extra_metrics       TEXT,       -- JSON for any additional columns
    promoted_to_library INTEGER NOT NULL DEFAULT 0,  -- 0/1 flag
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id),
    UNIQUE (experiment_id, strategy_name)
)
"""

_CREATE_MIGRATIONS = """
CREATE TABLE IF NOT EXISTS migrations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    applied_at  TEXT NOT NULL DEFAULT (datetime('now')),
    notes       TEXT
)
"""

_CREATE_PENDING_IDEAS = """
CREATE TABLE IF NOT EXISTS pending_ideas (
    idea_id             TEXT PRIMARY KEY,
    cycle_id            TEXT,
    hypothesis          TEXT NOT NULL,
    suggested_signals   TEXT NOT NULL,   -- JSON array of feature names
    rationale           TEXT,
    source_model        TEXT NOT NULL,   -- provenance: which model proposed this
    -- Milestone 7: market/universe stored on the idea so an approved idea is
    -- self-contained and reproducible regardless of later default changes.
    market              TEXT NOT NULL DEFAULT 'unknown',
    universe            TEXT NOT NULL DEFAULT 'unknown',
    -- Milestone 10 PR-4: bar sampling clock carried from the hypothesis through
    -- to the experiment spec (one of protocol.SUPPORTED_BAR_TYPES). 'time' for
    -- ad-hoc / pre-M10 ideas.
    bar_type            TEXT NOT NULL DEFAULT 'time',
    metadata            TEXT,            -- JSON: {"scores": {...}, ...} advisory only
    status              TEXT NOT NULL,   -- pending / approved / executing / executed / rejected
    validation_ok       INTEGER NOT NULL,        -- 0/1
    validation_reasons  TEXT,            -- JSON array of rejection reasons
    experiment_id       TEXT,            -- set when executed (idea -> experiment link)
    -- Milestone 10: originating research campaign (NULL for ad-hoc ideas;
    -- also reconciled onto pre-v8 DBs via _ADDITIVE_COLUMNS).
    campaign_id         TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    reviewed_at         TEXT,
    reviewer_note       TEXT
)
"""

_CREATE_AGENT_CONVERSATIONS = """
CREATE TABLE IF NOT EXISTS agent_conversations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id        TEXT NOT NULL,
    sender          TEXT NOT NULL,
    recipient       TEXT NOT NULL,
    message_type    TEXT NOT NULL,  -- hypothesis / spec / result / critique / lesson / summary
    payload         TEXT NOT NULL,  -- JSON blob
    timestamp       TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

# ===========================================================================
# Milestone 9 — Context-Aware Signal Intelligence
#
# The atomic unit of signal knowledge is the *context cell*:
#     (feature_name, market, universe, regime, bar_type)
# No global aggregate is ever a stored primary — global / per-market /
# per-universe numbers are derived roll-ups over context cells. This guarantees
# the system can always answer "where does this signal work?" rather than only
# "is this signal good?".
#
# Two-layer model:
#   * signal_context_observation — append-only provenance (one row per
#     experiment x feature). Never updated. Every cache aggregate is
#     reconstructable from it; losing the cache never loses knowledge.
#   * signal_context_performance — recompute cache (materialised roll-up at the
#     context-cell grain), kept solely for reporting efficiency. Droppable and
#     rebuildable from observations at any time.
# ===========================================================================

# Append-only fact table: one row per (experiment x feature). Immutable.
_CREATE_SIGNAL_CONTEXT_OBSERVATION = """
CREATE TABLE IF NOT EXISTS signal_context_observation (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id       TEXT NOT NULL,
    feature_name        TEXT NOT NULL,
    market              TEXT NOT NULL DEFAULT 'unknown',
    universe            TEXT NOT NULL DEFAULT 'unknown',
    regime              TEXT NOT NULL DEFAULT 'all',
    bar_type            TEXT NOT NULL DEFAULT 'time',
    attribution_method  TEXT NOT NULL DEFAULT 'observational',  -- observational / ablation
    net_sharpe          REAL,
    net_calmar          REAL,
    kept                INTEGER,     -- 1 if Critic decision == 'keep', else 0; NULL if unknown
    marginal_net_sharpe REAL,        -- NULL unless attribution_method == 'ablation'
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id),
    UNIQUE (experiment_id, feature_name, attribution_method)
)
"""

# Recompute cache: materialised roll-up at the context-cell grain. Composite key.
_CREATE_SIGNAL_CONTEXT_PERFORMANCE = """
CREATE TABLE IF NOT EXISTS signal_context_performance (
    feature_name        TEXT NOT NULL,
    market              TEXT NOT NULL,
    universe            TEXT NOT NULL,
    regime              TEXT NOT NULL,
    bar_type            TEXT NOT NULL,
    attribution_method  TEXT NOT NULL DEFAULT 'observational',
    n_experiments       INTEGER NOT NULL DEFAULT 0,
    n_with_net          INTEGER NOT NULL DEFAULT 0,
    n_kept              INTEGER NOT NULL DEFAULT 0,
    avg_net_sharpe      REAL,
    avg_net_calmar      REAL,
    keep_rate           REAL,
    contribution_score  REAL,        -- avg marginal_net_sharpe (ablation) else avg_net_sharpe
    min_n_met           INTEGER NOT NULL DEFAULT 0,  -- 0/1 evidence-sufficiency flag
    last_rebuilt_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (feature_name, market, universe, regime, bar_type, attribution_method)
)
"""

# Immutable audit of lifecycle-state transitions per signal.
_CREATE_SIGNAL_LIFECYCLE_EVENTS = """
CREATE TABLE IF NOT EXISTS signal_lifecycle_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    feature_name    TEXT NOT NULL,
    from_state      TEXT,
    to_state        TEXT NOT NULL,
    reason_code     TEXT,
    context_scope   TEXT,       -- e.g. 'India/NIFTY50/high_vol/time' or 'global'
    evidence_n      INTEGER,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

# Deterministic regime label per experiment. `method` records the classifier
# version so labels are reproducible and re-labelable.
_CREATE_REGIME_LABEL = """
CREATE TABLE IF NOT EXISTS regime_label (
    experiment_id   TEXT NOT NULL,
    regime          TEXT NOT NULL,
    method          TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (experiment_id, method),
    FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id)
)
"""

# Distilled cross-experiment findings, scoped to a context tuple or roll-up
# level. embedding is nullable; the offline/test path leaves it NULL (TD-5).
_CREATE_RESEARCH_MEMORY = """
CREATE TABLE IF NOT EXISTS research_memory (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scope_key       TEXT NOT NULL,      -- context tuple or roll-up level it summarises
    finding         TEXT NOT NULL,
    implication     TEXT,
    confidence      TEXT,
    embedding       BLOB,               -- nullable; NULL on the offline/test path
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (scope_key, finding)
)
"""

# ===========================================================================
# Milestone 10 — autonomous research campaign layer
# ===========================================================================

# A Research Campaign is a themed, budgeted, multi-experiment investigation.
# CampaignManager is the SOLE writer of this table and campaign_state_events.
# `budget_spent` here is a cached convenience; campaign progress is always
# derivable by recomputing over campaign-tagged experiments/ideas.
_CREATE_RESEARCH_CAMPAIGN = """
CREATE TABLE IF NOT EXISTS research_campaign (
    campaign_id         TEXT PRIMARY KEY,
    theme               TEXT NOT NULL,
    goal_spec           TEXT,            -- JSON: structured research goal
    scope               TEXT,            -- JSON: {markets, universes, signals, bar_types}
    state               TEXT NOT NULL DEFAULT 'DRAFT',  -- DRAFT/ACTIVE/STALLED/COMPLETED/ARCHIVED/DISCARDED
    budget_experiments  INTEGER NOT NULL DEFAULT 0,     -- 0 = unbounded
    budget_spent        INTEGER NOT NULL DEFAULT 0,     -- cached; derivable
    exploration_fraction REAL NOT NULL DEFAULT 0.34,
    stall_patience      INTEGER NOT NULL DEFAULT 3,     -- ticks with no progress before STALLED
    stopping_spec       TEXT,            -- JSON: stopping criteria
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at        TEXT
)
"""

# Immutable, append-only audit of campaign state transitions and the SOURCE OF
# TRUTH for campaign state. Mirrors signal_lifecycle_events: deliberately carries
# NO foreign key to research_campaign, so the event log outlives (and can rebuild)
# the research_campaign projection row. The campaign's authoritative state is
# always the to_state of its most-recent event; research_campaign.state is a
# rebuildable cache of that value.
_CREATE_CAMPAIGN_STATE_EVENTS = """
CREATE TABLE IF NOT EXISTS campaign_state_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id     TEXT NOT NULL,
    from_state      TEXT,
    to_state        TEXT NOT NULL,
    reason_code     TEXT,
    evidence        TEXT,       -- JSON: supporting context for the transition
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

# ===========================================================================
# Milestone 10 PR-2 — hypothesis evolution tree
# ===========================================================================

# A hypothesis_node is an immutable, fully-auditable record of one research
# hypothesis. Nodes form a tree (a DAG once `combine` merges two lineages): the
# root has parent_id NULL; every other node records its primary parent. Nodes
# are append-only — they are never updated in place, so the tree is reconstructible
# from storage at any time. (The optional idea_id/experiment_id links are stamped
# once when an idea/experiment is created from a node and are not mutated after.)
_CREATE_HYPOTHESIS_NODE = """
CREATE TABLE IF NOT EXISTS hypothesis_node (
    node_id         TEXT PRIMARY KEY,
    campaign_id     TEXT NOT NULL,
    parent_id       TEXT,            -- NULL only for a tree root
    root_id         TEXT NOT NULL,   -- the root of this node's tree (self for a root)
    depth           INTEGER NOT NULL DEFAULT 0,
    hypothesis      TEXT NOT NULL,
    signals         TEXT,            -- JSON array of feature names
    market          TEXT,
    universe        TEXT,
    bar_type        TEXT NOT NULL DEFAULT 'time',
    origin_operator TEXT,            -- evolution operator that produced this node; NULL for root
    rationale       TEXT,
    idea_id         TEXT,            -- set if an idea was generated from this node
    experiment_id   TEXT,            -- set if an experiment was run from this node
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

# A hypothesis_edge is the immutable evolution relationship parent -> child under
# a named operator. Append-only. `combine` produces multiple edges into one child
# (one per merged parent); all other operators produce exactly one edge.
_CREATE_HYPOTHESIS_EDGE = """
CREATE TABLE IF NOT EXISTS hypothesis_edge (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    parent_id   TEXT NOT NULL,
    child_id    TEXT NOT NULL,
    operator    TEXT NOT NULL,   -- refine/vary_bar/cross_market/add_filter/combine/negate
    rationale   TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (parent_id, child_id, operator)
)
"""

# ===========================================================================
# Milestone 10 PR-6 — research scheduler decision log
# ===========================================================================

# A scheduler_event is an immutable, append-only record of one scheduler
# decision about an *already human-approved* idea: dispatched / succeeded /
# failed / retry_scheduled / exhausted. The ResearchScheduler is the SOLE writer
# of this table. It records orchestration decisions only — it never approves or
# executes anything. Because it is append-only and carries the attempt number and
# supporting evidence, every scheduler decision (dispatch ordering, budget calls,
# retries, recovery) is fully reconstructible from storage.
_CREATE_SCHEDULER_EVENT = """
CREATE TABLE IF NOT EXISTS scheduler_event (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    idea_id         TEXT NOT NULL,
    campaign_id     TEXT,            -- NULL for ad-hoc (non-campaign) ideas
    experiment_id   TEXT,            -- set once a dispatched run produces one
    action          TEXT NOT NULL,   -- dispatched/succeeded/failed/retry_scheduled/exhausted
    attempt         INTEGER NOT NULL DEFAULT 1,
    reason          TEXT,
    evidence        TEXT,            -- JSON: plan position, score breakdown, etc.
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_CREATE_LOOP_CHECKPOINT = """
CREATE TABLE IF NOT EXISTS loop_checkpoint (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tick_id         TEXT NOT NULL,    -- deterministic per-tick identifier
    campaign_id     TEXT,             -- NULL for the global (all-campaign) scope
    phase           TEXT NOT NULL,    -- recover/generate/schedule/dispatch/learn/checkpoint
    status          TEXT NOT NULL,    -- started / completed
    evidence        TEXT,             -- JSON: per-phase counts + summary
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_experiments_status    ON experiments(status)",
    "CREATE INDEX IF NOT EXISTS idx_experiments_project   ON experiments(project)",
    "CREATE INDEX IF NOT EXISTS idx_experiments_type      ON experiments(experiment_type)",
    "CREATE INDEX IF NOT EXISTS idx_signal_type           ON signal_library(signal_type)",
    "CREATE INDEX IF NOT EXISTS idx_signal_keep           ON signal_library(keep_reject_retest)",
    "CREATE INDEX IF NOT EXISTS idx_lessons_experiment    ON lessons_learned(experiment_id)",
    "CREATE INDEX IF NOT EXISTS idx_lessons_category      ON lessons_learned(category)",
    "CREATE INDEX IF NOT EXISTS idx_conversations_cycle   ON agent_conversations(cycle_id)",
    "CREATE INDEX IF NOT EXISTS idx_conversations_sender  ON agent_conversations(sender)",
    "CREATE INDEX IF NOT EXISTS idx_variants_experiment   ON strategy_variants(experiment_id)",
    "CREATE INDEX IF NOT EXISTS idx_variants_promoted     ON strategy_variants(promoted_to_library)",
    "CREATE INDEX IF NOT EXISTS idx_pending_ideas_status  ON pending_ideas(status)",
    # Milestone 9 — context-aware signal intelligence
    "CREATE INDEX IF NOT EXISTS idx_sco_feature   ON signal_context_observation(feature_name)",
    "CREATE INDEX IF NOT EXISTS idx_sco_experiment ON signal_context_observation(experiment_id)",
    "CREATE INDEX IF NOT EXISTS idx_sco_context   ON signal_context_observation(market, universe, regime, bar_type)",
    "CREATE INDEX IF NOT EXISTS idx_scp_feature   ON signal_context_performance(feature_name)",
    "CREATE INDEX IF NOT EXISTS idx_scp_market    ON signal_context_performance(market)",
    "CREATE INDEX IF NOT EXISTS idx_scp_context   ON signal_context_performance(market, universe, regime)",
    "CREATE INDEX IF NOT EXISTS idx_sle_feature   ON signal_lifecycle_events(feature_name)",
    "CREATE INDEX IF NOT EXISTS idx_signal_lifecycle_state ON signal_library(lifecycle_state)",
    "CREATE INDEX IF NOT EXISTS idx_research_memory_scope  ON research_memory(scope_key)",
    # Milestone 10 — research campaign layer
    "CREATE INDEX IF NOT EXISTS idx_campaign_state         ON research_campaign(state)",
    "CREATE INDEX IF NOT EXISTS idx_campaign_events_cid    ON campaign_state_events(campaign_id)",
    "CREATE INDEX IF NOT EXISTS idx_pending_ideas_campaign ON pending_ideas(campaign_id)",
    # Milestone 10 PR-2 — hypothesis evolution tree
    "CREATE INDEX IF NOT EXISTS idx_hnode_campaign        ON hypothesis_node(campaign_id)",
    "CREATE INDEX IF NOT EXISTS idx_hnode_parent          ON hypothesis_node(parent_id)",
    "CREATE INDEX IF NOT EXISTS idx_hnode_root            ON hypothesis_node(root_id)",
    "CREATE INDEX IF NOT EXISTS idx_hedge_campaign        ON hypothesis_edge(campaign_id)",
    "CREATE INDEX IF NOT EXISTS idx_hedge_parent          ON hypothesis_edge(parent_id)",
    "CREATE INDEX IF NOT EXISTS idx_hedge_child           ON hypothesis_edge(child_id)",
    # Milestone 10 PR-6 — research scheduler decision log
    "CREATE INDEX IF NOT EXISTS idx_sched_event_idea      ON scheduler_event(idea_id)",
    "CREATE INDEX IF NOT EXISTS idx_sched_event_campaign  ON scheduler_event(campaign_id)",
    "CREATE INDEX IF NOT EXISTS idx_sched_event_action    ON scheduler_event(action)",
    # Milestone 10 PR-7 — research loop checkpoint log
    "CREATE INDEX IF NOT EXISTS idx_loop_ckpt_tick        ON loop_checkpoint(tick_id)",
    "CREATE INDEX IF NOT EXISTS idx_loop_ckpt_campaign    ON loop_checkpoint(campaign_id)",
    "CREATE INDEX IF NOT EXISTS idx_loop_ckpt_phase       ON loop_checkpoint(phase)",
]


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


# Additive column migrations: {table: [(column, type), ...]}.
# Applied idempotently on every create_all_tables() call so existing databases
# gain new columns without a destructive rebuild. Adding a column here is the
# supported way to evolve a table — never drop or rename in place.
_ADDITIVE_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "experiments": [
        ("net_sharpe", "REAL"),
        ("net_mdd", "REAL"),
        ("net_cagr", "REAL"),
        ("net_vol", "REAL"),
        ("net_calmar", "REAL"),
        ("turnover_annualized", "REAL"),
        ("turnover_average_period", "REAL"),
        ("transaction_cost_annualized", "REAL"),
        ("slippage_annualized", "REAL"),
        ("robustness_flags", "TEXT"),
        # Milestone 7 provenance
        ("source_idea_id", "TEXT"),
        ("source_model", "TEXT"),
        # Milestone 10 PR-4: first-class bar sampling clock (default 'time').
        ("bar_type", "TEXT NOT NULL DEFAULT 'time'"),
    ],
    # Milestone 7: evolve pending_ideas for self-contained, executable ideas.
    # NOT NULL columns carry a DEFAULT so the ALTER succeeds on existing rows;
    # the 'unknown' default only ever applies to pre-M7 ideas — new ideas always
    # supply real market/universe at enqueue time.
    "pending_ideas": [
        ("market", "TEXT NOT NULL DEFAULT 'unknown'"),
        ("universe", "TEXT NOT NULL DEFAULT 'unknown'"),
        ("experiment_id", "TEXT"),
        # Milestone 10: link an idea to its originating research campaign
        # (NULL for ad-hoc ideas not generated under a campaign).
        ("campaign_id", "TEXT"),
        # Milestone 10 PR-4: first-class bar sampling clock (default 'time').
        ("bar_type", "TEXT NOT NULL DEFAULT 'time'"),
    ],
    # Milestone 9: activate the dormant signal_library lifecycle (TD-4). All
    # additive with back-compatible defaults so existing rows remain valid.
    "signal_library": [
        ("lifecycle_state", "TEXT NOT NULL DEFAULT 'observed'"),  # observed/candidate/promoted/retired
        ("generalization_class", "TEXT"),  # universal/market_specific/universe_specific/regime_specific/unproven
        ("promoted_at", "TEXT"),
        ("retired_at", "TEXT"),
        ("last_evaluated_at", "TEXT"),
    ],
}


def _existing_columns(conn, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r["name"] for r in rows}


def _table_exists(conn, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def apply_additive_migrations(conn) -> list[str]:
    """
    Add any missing columns declared in _ADDITIVE_COLUMNS.

    Idempotent: only ALTERs columns that are absent. Tables that do not yet
    exist are skipped (they will be created with the full current schema by
    create_all_tables). Returns the list of "table.column" strings that were
    added (empty when already up to date).
    """
    added: list[str] = []
    for table, columns in _ADDITIVE_COLUMNS.items():
        if not _table_exists(conn, table):
            continue
        present = _existing_columns(conn, table)
        for col, col_type in columns:
            if col not in present:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
                added.append(f"{table}.{col}")
    return added


def create_all_tables(db_path: Path = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute(_CREATE_SCHEMA_VERSION)
        conn.execute(_CREATE_EXPERIMENTS)
        conn.execute(_CREATE_SIGNAL_LIBRARY)
        conn.execute(_CREATE_LESSONS_LEARNED)
        conn.execute(_CREATE_AGENT_CONVERSATIONS)
        conn.execute(_CREATE_STRATEGY_VARIANTS)
        conn.execute(_CREATE_PENDING_IDEAS)
        conn.execute(_CREATE_MIGRATIONS)
        # Milestone 9 — context-aware signal intelligence tables
        conn.execute(_CREATE_SIGNAL_CONTEXT_OBSERVATION)
        conn.execute(_CREATE_SIGNAL_CONTEXT_PERFORMANCE)
        conn.execute(_CREATE_SIGNAL_LIFECYCLE_EVENTS)
        conn.execute(_CREATE_REGIME_LABEL)
        conn.execute(_CREATE_RESEARCH_MEMORY)
        # Milestone 10 — autonomous research campaign layer
        conn.execute(_CREATE_RESEARCH_CAMPAIGN)
        conn.execute(_CREATE_CAMPAIGN_STATE_EVENTS)
        conn.execute(_CREATE_HYPOTHESIS_NODE)
        conn.execute(_CREATE_HYPOTHESIS_EDGE)
        conn.execute(_CREATE_SCHEDULER_EVENT)
        conn.execute(_CREATE_LOOP_CHECKPOINT)

        # Reconcile additive columns for databases created before this schema
        # version (fresh DBs already have them via the CREATE statements).
        added = apply_additive_migrations(conn)
        if added:
            conn.execute(
                "INSERT OR IGNORE INTO migrations (name, notes) VALUES (?, ?)",
                (f"schema_v{SCHEMA_VERSION}_additive_columns", ", ".join(added)),
            )

        for idx in _INDEXES:
            conn.execute(idx)
        existing = conn.execute(
            "SELECT version FROM schema_version WHERE version = ?", (SCHEMA_VERSION,)
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,)
            )
        conn.commit()


def get_schema_version(db_path: Path = DB_PATH) -> int | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT MAX(version) AS v FROM schema_version"
        ).fetchone()
        return row["v"] if row else None
