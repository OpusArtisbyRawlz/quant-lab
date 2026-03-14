# Project 3 – Directional Alpha (SPY 5-Day Direction)

## Objective
The goal of this project was to test whether short-term price behaviour and market activity indicators contain predictive information about the **direction of SPY over the next 5 trading days**.

## Model
Logistic Regression

## Features
- 5-day return
- 10-day return
- 20-day return
- 20-day realized volatility (rv20)
- volume ratio (volume / 20-day volume average)

## Target
Binary target indicating whether the **5-day forward return is positive**.

## Baseline
The baseline model predicts that the market always goes up.

Baseline accuracy ≈ **0.589**, reflecting the natural upward drift of equity markets.

## Results
Model accuracy ≈ **0.586**

ROC AUC ≈ **0.539**
AUC ( random forest) = 0.50
## Observations

- Classification accuracy does not exceed the baseline due to the structural upward bias in equity markets.
- ROC AUC above 0.5 indicates the model has **weak but non-random ranking ability** when distinguishing between upward and non-upward moves.
- Probability bin analysis shows that **higher predicted probabilities correspond to higher average forward returns**, suggesting the model captures a modest directional signal.
- Calibration analysis indicates that predicted probabilities are **reasonably aligned with observed outcome frequencies**.
- Scatter analysis of predicted probabilities versus forward returns shows a **noisy distribution**, but the regression trend line slopes upward, confirming that higher probabilities are associated with slightly higher average returns.
- Individual predictions still frequently produce negative returns due to the **high noise inherent in financial markets**.

Random forest performed worse (AUC ≈ 0.506), suggesting that nonlinear
interactions between the tested features do not meaningfully improve
directional prediction.

This indicates that the predictive signal, if present, is small and
primarily linear.

## Conclusion
The directional model exhibits a **weak but consistent predictive signal**. While it does not outperform the naive baseline in classification accuracy, the predicted probabilities appear useful for **ranking or filtering trading opportunities** rather than direct binary prediction.

## Potential Improvements
- Combine the directional signal with **volatility regime filters** to remove unstable market conditions.
- Experiment with alternative models such as tree-based methods.
- Test probability thresholds in a **backtesting framework** to evaluate real trading performance.

