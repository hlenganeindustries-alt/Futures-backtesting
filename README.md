# Futures 200 MA Open-Deviation Bounce Backtest

**Strategy:** At the 9:30 ET open, if price is below the 200-period MA by a threshold %, go long.
- **Take Profit:** +50 points
- **Stop Loss:** −30 points
- **Risk:Reward:** 1:1.7
- **Session window:** 9:30–10:30 ET (5-minute candles)

## Instruments
- NQ=F (Nasdaq 100 Futures)
- YM=F (Dow Jones Futures)

## Results Summary

| Ticker | Optimal Dev Bucket | Win Rate | Sample Days |
|--------|--------------------|----------|-------------|
| NQ=F | 1.00% - 1.25% | 100.0% | 1 |
| YM=F | 0.50% - 0.75% | 100.0% | 1 |

## Charts per Ticker
- `*_trade_overview.png` — all trade entries/exits across the backtest period
- `*_single_day_detail.png` — zoomed single-day candlestick with entry/TP/SL
- `*_win_rate_by_deviation.png` — win rate by deviation bucket (with 30pt SL)
- `*_candlestick_week.png` — sample week with signal overlays
- `*_bounce_probability.png` — original probability chart
- `backtest_results_*.csv` — full daily trade log

## How to Run
```bash
pip install yfinance mplfinance pandas numpy tabulate pytz matplotlib
python futures_ma200_open_bounce.py
```

*Auto-generated 2026-05-20 19:26*