#!/usr/bin/env bash

nohup python Tools/01_mcp_valuation_analysis.py >/dev/null 2>&1 &
nohup python Tools/02_mcp_financial_health.py >/dev/null 2>&1 &
nohup python Tools/05_news_sentiment.py >/dev/null 2>&1 &
nohup python Tools/08_sec_intelligence.py >/dev/null 2>&1 &
nohup python Tools/06_mcp_local_latex_builder.py >/dev/null 2>&1 &
nohup python Tools/gmail/gmail_mcp.py > gmail.log 2>&1 &
#tail -f gmail.log

