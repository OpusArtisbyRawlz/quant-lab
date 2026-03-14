# Idea: Directional Alpha Using Multi-Day Horizon

## Source
Personal research hypothesis.

## Motivation
Daily direction prediction is extremely noisy.
Multi-day horizons (5–10 days) may contain more structure due to:
- momentum persistence
- volatility clustering
- behavioral effects

## Hypothesis
Future 5-day returns may be predictable using:
- momentum features
- volatility features
- mean-reversion indicators
- volume signals

## Target
Binary classification:

1 if forward 5-day return > 0  
0 otherwise

## Universe
SPY daily data.

## Candidate Features
Momentum
- 5-day return
- 10-day return
- 20-day return

Volatility
- RV20
- Volatility ratio

Mean reversion
- RSI (14)
- distance from moving average

Volume
- volume / 20-day average

## Possible Models
- Logistic Regression
- Regularized Logistic Regression
- Tree-based models (later)

## Evaluation
Walk-forward out-of-sample validation.

Metrics:
- ROC AUC
- Brier score
- probability calibration
- return by probability bin

## Potential Extensions
- 10-day horizon
- regime filtering using volatility model
- thresholded labels (e.g. return > 0.5%)

## Next Step
Convert idea into Experiment 001 for Project 3.