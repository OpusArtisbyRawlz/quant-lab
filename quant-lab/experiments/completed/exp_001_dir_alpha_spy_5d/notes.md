# Experiment Notes

Goal:
Test whether SPY 5-day direction can be predicted using
momentum and volatility features.

Reason:
Daily direction is extremely noisy. Multi-day horizons
may contain more structure.

Initial model:
Logistic regression baseline.

Evaluation method:
Walk-forward out-of-sample testing.

Future tests:
- Try 10-day horizon
- Test tree models
- Add volatility regime filter