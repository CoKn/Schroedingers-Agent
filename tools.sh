#!/usr/bin/env bash

python3 Tools/01_mcp_valuation_analysis.py &
python3 Tools/02_mcp_financial_health.py &
python3 Tools/03_mcp_reg_comply_insider_signals.py &
python3 Tools/04_corporate_strategy.py &
python3 Tools/05_news_sentiment.py &
python3 Tools/07_mcp_report_generator.py &

wait