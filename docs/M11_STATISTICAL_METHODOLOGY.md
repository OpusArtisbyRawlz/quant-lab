# M11 — Statistical Methodology (Normative Specification)

**Status:** specification-only. No code. This is the *normative* math behind M11.
Where the architecture doc
([`M11_RESEARCH_INTELLIGENCE_DESIGN.md`](./M11_RESEARCH_INTELLIGENCE_DESIGN.md),
**frozen**) says *"accumulate evidence"* or *"evidence-gated promotion"*, this
document says **exactly how**, with equations, constants, and determinism rules.
It defines the contract that `agents/research_intelligence/statistics.py`,
`promotion_engine.py`, `retirement_engine.py`, and the evidence-budget allocator
must implement.

Everything here is **closed-form or fixed-seed** — no wall-clock, no unseeded RNG
— so every quantity is reproducible and carries a `method` version tag
(`stat_v1`, `promotion_v1`, `budget_v1`).

### What changed in this revision (v1 → v2 of the methodology)

1. **No single "confidence" scalar.** Evidence is reported as **four orthogonal
   axes** — *Statistical Quality* $Q$, *Reproducibility* $R$, *Generalisation*
   $G$, *Economic Value* $V$ — that are **never collapsed** into one number.
   Promotion is an **AND of per-axis gates**, and each axis stays separately
   visible and explainable.
2. **Bayesian posterior updating is the conceptual model of learning.** Each
   experiment updates a posterior over a latent effect; "learning" *is* the
   posterior sharpening. Frequentist tests survive only as cross-checks.
3. **Every point estimate ships with an explicit credible interval / uncertainty.**
4. **Retirement is a first-class lifecycle track**, with its own entry predicates
   and terminal states — not a demotion side-effect.
5. **An evidence budget** caps how much research any one hypothesis can consume,
   allocated by expected information gain with a hard per-hypothesis ceiling.

---

## 0. Principles

1. **The unit of evidence is one experiment's realised performance in one context
   cell** — not one daily return. Experiments are the independent trials; intra-
   experiment daily returns are *not* the sample size (the Sharpe-inflation trap).
2. **Latent-effect model.** Behind each context cell $c$ is an unknown true
   after-cost effect $\theta_c$ (in annualised-Sharpe units). Every experiment is
   a noisy measurement of $\theta_c$. We never observe $\theta_c$; we hold a
   **posterior distribution** over it and refine it as experiments arrive.
3. **Four questions, four axes, kept apart:**
   - $Q$ — *is the effect statistically real?* (posterior mass above break-even + precision)
   - $R$ — *do independent trials agree?* (cross-experiment reproducibility)
   - $G$ — *does it survive across contexts?* (breadth over markets/regimes/bars/periods)
   - $V$ — *is it economically worth trading?* (posterior net-Sharpe magnitude after costs/turnover/drawdown)
   A great $V$ with poor $R$ is a fluke; a strong $Q$ with $G=1$ is a
   context-specific quirk. Collapsing them hides exactly the distinctions M11
   exists to make.
4. **Conservative by construction.** Sharpe is deflated for selection; priors are
   skeptical; multiple testing is corrected; evidence decays; promotion needs a
   holdout.

### Notation

| Symbol | Meaning |
| --- | --- |
| $h$ | a hypothesis (hypothesis-tree node) |
| $c$ | a context cell $(\text{market},\text{universe},\text{regime},\text{bar\_type})$ |
| $i$ | an experiment |
| $N$ | periods-per-year (from `BarResult.periods_per_year`; 252 daily) |
| $T_i$ | return periods in experiment $i$ |
| $\hat S_i$ | net (post-cost) annualised Sharpe of experiment $i$ |
| $\mathrm{se}_i$ | standard error of $\hat S_i$ |
| $\theta_c,\theta_h$ | latent true effect of cell / hypothesis |
| $\mu,\sigma^2$ | posterior mean / variance of an effect |
| $\omega_i$ | evidence weight (decay × precision) of experiment $i$ |

---

## 1. Bayesian measurement model (the learning engine)

### 1.1 Within-experiment likelihood

Each experiment yields $\hat S_i$ with standard error (Lo, 2002; Gaussian form):

$$
\mathrm{se}_i=\sqrt{\dfrac{1+\tfrac12\hat S_{i,\text{per}}^2}{T_i}}\cdot\sqrt N,\qquad
\hat S_{i,\text{per}}=\hat S_i/\sqrt N .
$$

**Deflation for selection.** With $K_i$ configurations tried inside experiment $i$
(the parameter-sensitivity sweep count),

$$
\hat S_i^{\text{defl}}=\hat S_i-\mathrm{se}_i\,\Phi^{-1}\!\Big(1-\tfrac1{K_i}\Big).
$$

The likelihood of the deflated estimate is Normal:
$\hat S_i^{\text{defl}}\mid\theta_c \sim \mathcal N(\theta_c,\ \mathrm{se}_i^2)$.

### 1.2 Skeptical conjugate prior

Before any evidence, a cell's effect is drawn from a **skeptical** Normal prior
centred at break-even:

$$
\theta_c \sim \mathcal N(\mu_0,\ \sigma_0^2),\qquad \mu_0=0\ (=S_0),\ \ \sigma_0\ \text{small (config, default }0.5\text{ Sharpe)} .
$$

A tight prior at zero means a few lucky experiments cannot run the posterior far
from break-even — the Bayesian analogue of "one seed is not enough."

### 1.3 Posterior update with exponential forgetting (decay)

Conjugate Normal–Normal update over the cell's experiments, each likelihood
**down-weighted** by an evidence weight $\omega_i$ (§6 decay × precision). Using
precision $\phi=1/\sigma^2$:

$$
\phi_c^{\text{post}}=\phi_0+\sum_{i\in c}\omega_i\,\phi_i,\qquad
\mu_c^{\text{post}}=\dfrac{\phi_0\mu_0+\sum_{i\in c}\omega_i\,\phi_i\,\hat S_i^{\text{defl}}}{\phi_c^{\text{post}}},
\qquad \phi_i=1/\mathrm{se}_i^2 .
$$

$$
\boxed{\ \theta_c\mid\text{data}\ \sim\ \mathcal N\!\big(\mu_c,\ \sigma_c^2\big),\quad \mu_c=\mu_c^{\text{post}},\ \sigma_c^2=1/\phi_c^{\text{post}}\ }
$$

This *is* the learning rule: every experiment moves $(\mu_c,\sigma_c^2)$; decay
lets old likelihood mass fade so a strategy that stopped working sees its
posterior drift back toward the skeptical prior (an exponential-forgetting Bayes
filter). Effective sample size $n^{\text{eff}}_c=\big(\sum\omega_i\big)^2/\sum\omega_i^2$
(Kish) is reported alongside.

### 1.4 Hierarchical pooling: cells → hypothesis

Cells of one hypothesis share a hypothesis-level effect via a hierarchy:

$$
\theta_c\sim\mathcal N(\theta_h,\ \tau^2),\qquad \theta_h\sim\mathcal N(\mu_0,\sigma_0^2).
$$

$\tau^2$ (between-cell heterogeneity) is estimated by empirical Bayes
(DerSimonian–Laird). The hypothesis posterior is the partial-pooling combination

$$
\mu_h=\dfrac{\sum_c \tilde\phi_c\,\mu_c}{\sum_c\tilde\phi_c},\quad
\sigma_h^2=\dfrac1{\sum_c\tilde\phi_c},\quad
\tilde\phi_c=\dfrac1{\sigma_c^2+\tau^2}.
$$

Partial pooling shrinks noisy small-$n$ cells toward the hypothesis mean (guards
small samples) while letting genuinely divergent cells stay apart (feeds $G$ and
robustness memory). **No global aggregate is stored as a primary** — every
$(\mu,\sigma^2)$ is re-derived from the immutable per-experiment evidence,
matching the existing `roll_up()` discipline.

### 1.5 Credible intervals (uncertainty is always reported)

Every effect ships a **central credible interval** at level $1-\gamma$
(default $\gamma=0.10$, i.e. 90%):

$$
\mathrm{CI}_h=\big[\mu_h - z_{\gamma/2}\,\sigma_h,\ \ \mu_h + z_{\gamma/2}\,\sigma_h\big],\qquad z_{0.05}=1.645 .
$$

The **point estimate is $\mu_h$; the uncertainty is $\sigma_h$ / $\mathrm{CI}_h$**,
and both are stored on `hypothesis_state` and every `decision_record`. No M11
number is ever surfaced without its interval.

---

## 2. The four evidence axes (never collapsed)

Each axis is a bounded, separately-stored, separately-explained quantity.

### 2.1 Statistical Quality $Q$

"Is the effect real, and how precisely known?" Two reported components:

$$
\underbrace{\pi_h=\Pr(\theta_h>S_0\mid\text{data})=\Phi\!\Big(\tfrac{\mu_h-S_0}{\sigma_h}\Big)}_{\text{posterior exceedance prob.}},
\qquad
\underbrace{\text{prec}_h=1-e^{-n^{\text{eff}}_h/n_0}}_{\text{precision adequacy}} .
$$

$Q$ is reported as the **pair** $(\pi_h,\ \text{prec}_h)$ plus $\mathrm{CI}_h$.
For gating we use the two components independently (a high $\pi$ on a wide,
under-sampled posterior does **not** pass). The frequentist FDR $q_h$ (§7) is a
**cross-check** stored beside $\pi_h$, not a substitute.

### 2.2 Reproducibility $R$

"Do independent experiments agree?" Only distinct `experiment_id`s (and, where
available, distinct data windows) count as replicas. Reported as three parts:

$$
\rho^{\text{sign}}_h=\Big|\tfrac1{W}\textstyle\sum_i\omega_i\,\mathrm{sign}(\hat S_i^{\text{defl}}-S_0)\Big|,\quad
\rho^{\text{disp}}_h=1-\dfrac{\tau^2}{\tau^2+\bar{\mathrm{se}}^2_h},\quad
R^{\text{cnt}}_h=\mathbf 1\{m_h\ge k_{\min}\}\big(1-e^{-m_h/k_0}\big),
$$

$m_h$ = independent-replica count. A single **stability** sub-score (within-
experiment, across subperiods + parameter sweeps, read from
`build_robustness_report`) rides alongside:
$\mathrm{Stab}_i=\big|\tfrac1G\sum_g\mathrm{sign}(S^{(g)})\big|\cdot\sigma(-\kappa_S(\Delta_{\text{param}}-\delta_0))$.
$R$ is stored as the tuple $(\rho^{\text{sign}},\rho^{\text{disp}},R^{\text{cnt}},\mathrm{Stab})$.

### 2.3 Generalisation $G$

"Does it survive across contexts?" Breadth = number of cells whose posterior
clears the cell bar, weighted by **coverage** across the five generalisation
dimensions (market, universe, regime, bar_type, period):

$$
G^{\text{cnt}}_h=\#\{c:\ \Pr(\theta_c>S_0)\ge \tau_\pi\},\qquad
G^{\text{cov}}_h=\tfrac1{5}\sum_{\text{dim}} \dfrac{\#\text{distinct passing values in dim}}{\#\text{available values in dim}} .
$$

Reported as $(G^{\text{cnt}}_h,\ G^{\text{cov}}_h)$. A hypothesis confirmed in
five regimes but one market has high count, low market-coverage — the pair keeps
that visible (and drives robustness-memory entries like "only on futures").

### 2.4 Economic Value $V$

"Is it worth trading after frictions?" The posterior **magnitude**, net of the
costs the pipeline already charges, with its interval:

$$
V_h=\mu_h^{\text{net}}\ \ (\text{posterior mean net Sharpe}),\quad \text{with}\ \mathrm{CI}_h,\ \text{plus }(\text{drawdown},\ \text{turnover},\ \text{cost drag})\ \text{posteriors.}
$$

$V$ deliberately stays in Sharpe/eco units (not squashed to $[0,1]$) so gates can
demand an *economically* meaningful lower credible bound, e.g. $\mathrm{CI}_h^{\text{low}}\ge S^\star$.

> **These four are a vector, not a score.** `hypothesis_state` stores
> $Q,R,G,V$ separately; the Reporter shows them as four columns; promotion gates
> read them independently. There is no weighted sum that could let a strong $V$
> paper over a weak $R$.

---

## 3. Lifecycle: promotion **and** retirement as first-class tracks

Two parallel tracks share one state machine. A hypothesis is always in exactly
one state; transitions are **pure predicates** over $(Q,R,G,V,\text{holdout})$
with hysteresis. History is append-only; nothing is deleted.

```
        ┌─────────── PROMOTION TRACK ───────────┐
Candidate → Promising → Validated → Production Candidate → Archived(✓)
     │           │            │              │
     └────┬──────┴─────┬──────┴──────┬───────┘
          ▼            ▼             ▼
        ┌──────────── RETIREMENT TRACK ─────────────┐
        Retired-Refuted | Retired-Saturated |
        Retired-Redundant | Retired-Decayed   (terminal, budget frozen, history kept)
```

### 3.1 Promotion predicates (AND across axes; per-axis, not summed)

| To stage | $Q$ | $R$ | $G$ | $V$ | other |
| --- | --- | --- | --- | --- | --- |
| **Promising** | $\pi_h\ge0.90$, $\text{prec}_h\ge0.3$ | — | — | $\mu_h^{\text{net}}>0$ | $n^{\text{eff}}_h\ge2$ |
| **Validated** | $\pi_h\ge0.95$, $\text{prec}_h\ge0.6$ | $\rho^{\text{sign}}\ge0.8$, $\rho^{\text{disp}}\ge0.6$, $m_h\ge k_{\min}$ | $G^{\text{cnt}}\ge2$ | $\mathrm{CI}^{\text{low}}_h\ge0$ | no unresolved critical `robustness_flag` |
| **Production Candidate** | $\pi_h\ge0.975$, $q_h\le0.05$ | $R^{\text{cnt}}\ge0.75$ | $G^{\text{cnt}}\ge3$, $G^{\text{cov}}\ge0.5$ | $\mathrm{CI}^{\text{low}}_h\ge S^\star$ | **holdout pass (§5)** |
| **Archived** | terminal success: reached Production Candidate and accepted/superseded downstream; budget released; history frozen |

Defaults; all config. Hysteresis: demote if any *maintenance* gate fails at
$\tau^{\downarrow}=\tau^{\uparrow}-0.10$ (one FDR tier looser for $q$). Promotion
**never** fires on one experiment and **never** on a single axis.

### 3.2 Retirement predicates (first-class, evidence-driven)

A hypothesis enters a retirement state from *any* live stage when its posterior
makes continued investment unjustified. These are not "failures to promote"; they
are positive conclusions the system draws and remembers.

| Retired state | Entry predicate (posterior terms) | Meaning |
| --- | --- | --- |
| **Retired-Refuted** | $\Pr(\theta_h>S_0)\le \varepsilon_{\text{ref}}$ (default 0.05) **and** $\mathrm{CI}^{\text{high}}_h< S^\star$ | posterior mass sits below break-even; the edge is affirmatively absent |
| **Retired-Saturated** | $\sigma_h\le\sigma_{\text{sat}}$ **and** $\mathrm{EVOI}_h\le\eta$ (§4) | posterior already tight; another experiment can't change any decision |
| **Retired-Redundant** | novelty vs an existing live/validated hypothesis $\le\nu_{\min}$ (duplicate concept) | subsumed by another hypothesis; evidence merged, not re-spent |
| **Retired-Decayed** | live stage but $n^{\text{eff}}_h$ (post-decay) $<n_{\text{floor}}$ and $\pi_h$ fell below the maintenance bar | once-supported, now faded with no fresh confirmation |

Retirement **freezes the evidence budget** (§4), writes a
`hypothesis_evidence_event` with the deciding posterior snapshot and reason code,
and **preserves all history**. A retired hypothesis can be *reopened* only by
genuinely new evidence (a new `evidence_event` for it), which re-enters it as
Candidate with its prior posterior retained — reproducible and auditable.

### 3.3 Determinism of the lifecycle

Stage is a pure function of the complete evidence log: posterior → axis vector →
predicates. Replaying the log reproduces the exact promotion/retirement path;
each transition is logged with its evidence snapshot and `promotion_v1` version.

---

## 4. Evidence budget (no hypothesis hogs research)

Research slots are scarce. The budget allocator decides **how many future
experiments each live hypothesis may claim**, so attention flows to where it buys
the most learning — with a hard ceiling so nothing monopolises the platform.

### 4.1 Expected value of information (EVOI)

A new experiment is worth running in proportion to how much it is expected to
**move a decision**. Deterministic proxy: the posterior-predictive probability
that one more experiment flips a promotion/retirement gate. With predictive
variance $\sigma_h^2+\bar{\mathrm{se}}^2$, and $g$ the nearest gate threshold in
effect-space,

$$
\mathrm{EVOI}_h=\underbrace{\phi\!\Big(\tfrac{\mu_h-g}{\sqrt{\sigma_h^2+\bar{\mathrm{se}}^2}}\Big)}_{\text{proximity to a gate}}\cdot\underbrace{\sigma_h}_{\text{remaining uncertainty}}\cdot\underbrace{\pi_h^{\text{prom}}}_{\text{promise}},
$$

$\phi$ = standard-normal pdf, $\pi_h^{\text{prom}}=\Pr(\theta_h>S^\star)$. EVOI is
**high** for uncertain-but-promising hypotheses sitting on a threshold, and
**near zero** for saturated (tiny $\sigma_h$) or clearly refuted ($\pi\to0$) ones
— exactly the "spend more on conflicting/promising, less on saturated/refuted"
policy the objectives demand.

### 4.2 Allocation with a per-hypothesis ceiling

Over the live set $\mathcal H$ (retired hypotheses get 0), the raw share is EVOI-
proportional, then **capped and floored**:

$$
a_h=\mathrm{clip}\!\Big(\dfrac{\mathrm{EVOI}_h}{\sum_{h'\in\mathcal H}\mathrm{EVOI}_{h'}},\ \ a_{\min},\ \ a_{\max}\Big),\quad\text{renormalised}, \qquad b_h=\lfloor a_h\cdot B_{\text{window}}\rfloor .
$$

$a_{\max}$ (default 0.25) is the **hard ceiling**: no hypothesis may take more
than a quarter of a scheduling window's experiments, however promising — this is
the anti-monopoly guarantee. $a_{\min}$ (default a small floor) preserves
exploration. Conflicting evidence (wide $\sigma_h$ straddling $S_0$) naturally
scores high EVOI and attracts budget; duplicates are removed by Retired-Redundant
before allocation so effort isn't double-spent.

### 4.3 Where it plugs in

$b_h$ is consumed by the **ExplorationPlanner / `research_quota`** (`accept`
callback) and the **Scheduler** as a per-hypothesis admission cap — the frozen
architecture's existing quota seam. The allocator is pure (`budget_v1`), reads
only posteriors + EVOI, and writes a `decision_record` explaining each allocation
(EVOI inputs, cap hit or not).

---

## 5. Holdout methodology

Production Candidate requires evidence from data the hypothesis was **not**
developed on.

### 5.1 Deterministic partition

Per (market, universe) the timeline is split **once** by calendar boundary:
earliest $\lfloor(1-\pi)\cdot\text{span}\rfloor$ = **development (IS)**, most
recent $\pi$ (default 0.30) = **holdout (OOS)**; plus a held-out universe slice
where available. Split by date, never random → leakage-safe and reproducible. M11
**tags** each `evidence_event` by the window it ran on; it re-runs nothing.

### 5.2 Two posteriors, compared

Maintain **separate** posteriors $\theta_h^{\text{IS}},\theta_h^{\text{OOS}}$. The
holdout **passes** iff:

$$
\text{(a) } \mathrm{sign}(\mu^{\text{OOS}}_h)=\mathrm{sign}(\mu^{\text{IS}}_h),\quad
\text{(b) } \Pr(\theta^{\text{OOS}}_h>S_0)\ge 0.90,
$$
$$
\text{(c) retention } \tfrac{\mu^{\text{OOS}}_h}{\mu^{\text{IS}}_h}\ge r_{\min}\ (0.5),\quad
\text{(d) overlap } \Pr\!\big(\theta^{\text{IS}}_h-\theta^{\text{OOS}}_h>\Delta_{\max}\big)\le 0.10 .
$$

Large IS→OOS decay (the overfit signature) fails (c)/(d) even when the OOS effect
is still positive. The realised **haircut** $\mu^{\text{IS}}/\mu^{\text{OOS}}$ is
recorded. **No peeking:** OOS statistics are computed only at this gate and never
fed back into development-stage posteriors.

---

## 6. Evidence decay

Old evidence informs but must not dominate. Decay multiplies each experiment's
weight in the posterior update (§1.3).

$$
\omega_i=d(\Delta_i)\cdot\lambda_{\text{regime}}(c)\cdot\phi_i,\qquad d(\Delta_i)=2^{-\Delta_i/H}.
$$

$\Delta_i$ = **experiments elapsed platform-wide** since $i$ (an event count, not
wall-clock) → replay-stable. Half-life $H$ (default 200 experiments);
$H=\infty$ recovers un-decayed pooling (a required test limit).
$\lambda_{\text{regime}}\in(0,1]$ optionally down-weights off-current-regime
evidence (default 1.0 = off) so "only works in low vol" fades when the regime is
elsewhere and **re-strengthens** if it returns — because the raw evidence is
preserved and merely re-weighted. Decay flows into $\mu_h,\sigma_h,n^{\text{eff}}$
uniformly, and is the mechanism behind **Retired-Decayed**: a stale winner's
posterior widens and drifts to the prior until a maintenance gate fails.

---

## 7. Multiple-testing correction

Thousands of experiments across many hypotheses guarantee false "discoveries"
without correction. M11 controls the **false discovery rate** two ways.

### 7.1 Bayesian FDR (primary)

The posterior gives each hypothesis a **local false-discovery probability**
$\text{lfdr}_h=\Pr(\theta_h\le S_0\mid\text{data})=1-\pi_h$. Rank ascending; admit
the largest set $D$ whose **average** lfdr stays under $\alpha$ (default 0.10):

$$
\overline{\text{lfdr}}(D)=\tfrac1{|D|}\sum_{h\in D}(1-\pi_h)\le\alpha .
$$

This is the natural Bayesian control and is deterministic given the posteriors.
Only hypotheses in $D$ are eligible for **Validated+** promotion.

### 7.2 Benjamini–Hochberg (frequentist cross-check)

In parallel, the one-sided frequentist p-values $p_h$ (cell p-values combined by
weighted Stouffer $Z_h=\sum_c\sqrt{\omega_c}\,\Phi^{-1}(1-p_c)/\sqrt{\sum_c\omega_c}$)
are BH-adjusted over the **whole active population**:
$q_{(k)}=\min_{j\ge k}\frac{M p_{(j)}}{j}$. The Production-Candidate gate requires
**both** $\text{lfdr}_h$ inside the Bayesian set **and** $q_h\le0.05$ — belt and
suspenders. BY (divide $\alpha$ by $\sum 1/j$) is a config switch for high-overlap
campaigns. Both use the whole active set (a discovery is relative to everything
tried), and the admitting set + $\alpha$ + variant are snapshotted in the
`decision_record`.

---

## 8. End-to-end per-assess-tick flow

```
per new evidence_event:        Ŝ_i, se_i → deflate → likelihood N(θ, se_i²)     [§1.1]
                               weight ω_i = d(Δ_i)·λ_regime·1/se_i²             [§6]
per cell c:                    posterior N(μ_c, σ_c²), n_eff_c                  [§1.3]
per hypothesis h:              hierarchical pool → N(μ_h, σ_h²), CI_h, τ²        [§1.4-1.5]
                               AXES  Q(π_h,prec_h) · R(sign,disp,cnt,Stab)       [§2]
                                     · G(cnt,cov) · V(μ_h^net,CI)   (kept separate)
population-wide:               Bayesian FDR set D; BH q_h cross-check           [§7]
per hypothesis h:              holdout gate if eligible for Prod-Candidate      [§5]
                               PROMOTE / DEMOTE / RETIRE  (pure predicates)     [§3]
                               EVOI_h → evidence budget b_h (cap a_max)         [§4]
write:                         hypothesis_evidence_event + decision_record
                               (posterior, CI, four axes, q, EVOI, budget,
                                supporting & contradictory experiment_ids)
```

Every step is a pure function; the tick is replay-deterministic and idempotent on
`experiment_id`/transition keys.

---

## 9. Determinism, versioning, testability

- **No RNG** in §§1–7 (all closed-form). Any future resampling uses a seed derived
  from the sorted `experiment_id` set and a new `method` tag.
- **Event-time** decay/ordering → replays reproduce identical numbers.
- **Policy objects:** `StatPolicy` (`stat_v1`), `PromotionPolicy` (`promotion_v1`),
  `BudgetPolicy` (`budget_v1`) hold every constant; changing one bumps the version;
  historical decisions stay reproducible under their recorded version.
- **Isolated unit tests on synthetic evidence logs:**
  - posterior converges to injected $\theta$; CI coverage is calibrated;
  - monotonicity — more supporting evidence ⇒ non-decreasing $\pi_h$, $\mu_h$;
  - no-decay limit ($H=\infty$) equals un-weighted pooling;
  - one experiment never promotes past Candidate;
  - each axis moves **independently** (a $V$-only change leaves $R$ untouched);
  - Retired-Refuted fires on injected sub-break-even effect; Retired-Saturated on
    a tight posterior; Retired-Decayed after evidence starvation;
  - evidence-budget ceiling $a_{\max}$ is never exceeded; retired ⇒ 0 budget;
  - Bayesian-FDR and BH agree on a hand-checked example;
  - holdout gate fails a constructed IS→OOS overfit;
  - shuffled-but-identical log ⇒ identical posteriors, axes, stage, budget.

---

## 10. Default constants (config, `*_v1`)

| Constant | Symbol | Default | Role |
| --- | --- | --- | --- |
| Break-even Sharpe | $S_0$ | 0.0 | null effect |
| Economic Sharpe bar | $S^\star$ | 0.5 | $V$ / holdout floor |
| Prior mean / sd | $\mu_0,\sigma_0$ | 0.0, 0.5 | skeptical prior |
| Precision scale | $n_0$ | 5 | $\text{prec}_h$ saturation |
| Min replicas / scale | $k_{\min},k_0$ | 3, 3 | reproducibility floor |
| Cell posterior bar | $\tau_\pi$ | 0.90 | counts toward $G^{\text{cnt}}$ |
| Decay half-life | $H$ | 200 exps | forgetting rate |
| Regime discount | $\lambda_{\text{regime}}$ | 1.0 | off by default |
| Credible level | $1-\gamma$ | 0.90 | interval width |
| Refutation prob. | $\varepsilon_{\text{ref}}$ | 0.05 | Retired-Refuted |
| Saturation sd / EVOI floor | $\sigma_{\text{sat}},\eta$ | config | Retired-Saturated |
| Redundancy novelty | $\nu_{\min}$ | config | Retired-Redundant |
| FDR level | $\alpha$ | 0.10 | Bayesian + BH |
| Holdout fraction / retention | $\pi, r_{\min}$ | 0.30, 0.50 | OOS gate |
| Budget ceiling / floor | $a_{\max},a_{\min}$ | 0.25, small | anti-monopoly / exploration |
| Hysteresis band | — | 0.10 | promote−demote gap |

Constants are the researcher's knobs; the **equations and the four-axis
separation are fixed by this specification**. Implementation (M11-2/M11-3/M11-4)
must reproduce these formulas exactly and expose the constants through the three
policy objects.
