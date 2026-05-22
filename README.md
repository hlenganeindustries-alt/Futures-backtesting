# Futures Mean Reversion Research

A quantitative futures trading research project studying how futures behave when opening below the 200-period moving average.

---

## Strategy Overview

This project investigates whether futures contracts that open significantly below their 200 MA tend to bounce back shortly after the NY market open.

The system:

- Downloads intraday futures data
- Cleans and structures data
- Measures opening deviation from the 200 MA
- Simulates trades with TP/SL logic
- Performs statistical bucket analysis
- Generates interactive Plotly dashboards
- Automatically updates GitHub outputs

---

## Example Dashboards

### Trade Overview

<img width="2533" height="1036" alt="YMF_single_day_detail" src="https://github.com/user-attachments/assets/cf955b9f-0c90-466a-9896-ae5b9b07dc8c" />


### Win Rate Analysis
<img width="3283" height="1333" alt="NQF_trade_overview" src="https://github.com/user-attachments/assets/d5071e05-7cce-4ba5-8845-34dbac0f89dc" />


---


## Data Limitation Disclaimer

Yahoo Finance has  limited historical 5-minute futures data. 

Because of this limitation, backtests are performed in rolling batches of approximately 40 days at a time.

The system automatically stitches and processes these batches to allow larger historical analysis while remaining within Yahoo Finance API limits.
This is the most recent backtest results for the periods (24 March -14 May)

---

## Repository Structure


```text
outputs/
    csv/
    html/
    screenshots/
```

---

## Latest Results


### NQ=F

- Optimal Deviation Bucket: 1.00% - 1.25%
- Win Rate: 100.00%
- Sample Size: 1

### YM=F

- Optimal Deviation Bucket: 0.50% - 0.75%
- Win Rate: 100.00%
- Sample Size: 1


---

## Technologies Used

- Python
- pandas
- numpy
- yfinance
- plotly
- matplotlib

---

## Project Purpose

This repository was built to demonstrate:

- Quantitative research workflows
- Statistical analysis
- Financial data engineering
- Interactive visualization
- Automated reporting
