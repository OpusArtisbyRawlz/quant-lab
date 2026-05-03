# 📊 Project 04 – Return Forecast Alpha

## 🔷 Overview
This project develops a cross-sectional long/short equity strategy using machine learning-based return forecasts. The goal is to transform predictive signals into a robust, risk-aware portfolio through systematic portfolio construction, diversification, and risk management techniques.

---

## 🔷 Methodology

- Built predictive signals for forward 5-day returns across a multi-asset equity universe  
- Constructed long/short portfolios using percentile-based selection (LS 20%, LS 30%)  
- Evaluated portfolio performance using Sharpe, CAGR, Maximum Drawdown (MDD), Volatility, and Calmar ratio  
- Explored enhancements including:
  - Portfolio blending
  - Volatility-based scaling
  - Exposure normalization and neutrality constraints  

---

## 🔷 Key Findings

The initial concentrated strategy (LS 20%) demonstrated strong predictive power, achieving high Sharpe and CAGR, but exhibited significant drawdowns, indicating that while the signal contains meaningful alpha, it is highly volatile.

Expanding the portfolio to a broader selection (LS 30%) improved stability by reducing drawdown and volatility, though at the cost of lower returns. This highlights the fundamental trade-off between concentration (alpha capture) and diversification (risk reduction).

Blending these strategies (60% LS 20%, 40% LS 30%) provided the most effective structural improvement. This approach preserved most of the alpha while achieving a more balanced risk-return profile, demonstrating that combining concentrated and diversified portfolios is more effective than relying on either individually.

Volatility-based scaling applied at the weight level had limited impact, as these adjustments were largely neutralized during normalization and did not materially change overall portfolio exposure. In contrast, portfolio-level volatility targeting successfully reduced drawdowns by dynamically adjusting exposure over time; however, aggressive targeting significantly reduced returns and overall efficiency, making it less suitable for this strategy.

Additionally, enforcing strict market neutrality (removing net exposure) reduced performance, indicating that part of the strategy’s returns are driven by directional market exposure (beta), not purely cross-sectional alpha.

---

## 🔷 Final Strategy Design

### 🟢 Primary Strategy – Blend 60/40 (LS20 + LS30)
- Strong overall performance  
- High Sharpe (1.5)  
- Balanced return and risk  

### 🟢 Secondary Strategy – LS 30%
- Lower drawdown (-55%)  
- More stable performance  
- Acts as a defensive alternative  

---

## 🔷 Conclusion

The most effective improvements came from portfolio construction decisions—specifically diversification and blending—rather than aggressive scaling or constraints. The final framework balances concentrated alpha generation with structural stability, resulting in a robust and flexible long/short strategy suitable for further enhancements such as position sizing, turnover control, or regime-based allocation.

---

## 🔷 Next Steps

- Refine position sizing (e.g., tighter max weight constraints)  
- Explore turnover reduction and signal smoothing  
- Implement regime-aware allocation between primary and defensive strategies  
- Integrate into a broader multi-strategy portfolio framework