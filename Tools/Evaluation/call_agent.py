import os
import json
import requests

URL = "http://localhost:8080/agent"
OUTPUT_DIR = os.path.join("Tools", "Evaluation")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "results_detailed.txt")

headers = {
    "Authorization": "Bearer devtoken123",
    "Content-Type": "application/json",
}

payload = {
    "prompt": """Perform a complete M&A investment evaluation of Microsoft Corporation (MSFT) following this exact workflow:

STEP 1 - INITIAL VALUATION:
- First, resolve the stock ticker symbol for Microsoft Corporation to confirm it's MSFT
- Second, find comparable companies using the NORMAL approach
- Third, calculate the comparable company valuation for MSFT

STEP 2 - FINANCIAL HEALTH ASSESSMENT:
- Get the company's key financial metrics (P/E ratio, debt levels, margins, etc.)
- Get the company's financial growth metrics (revenue growth, earnings growth, etc.)

STEP 3 - CORPORATE STRATEGY ANALYSIS:
- Lookup Microsoft's CIK (Central Index Key) using the ticker symbol MSFT
- Extract the company strategy sections from their SEC filings (10-K, specifically business description and risk factors)

STEP 4 - REGULATORY & INSIDER ACTIVITY CHECK:
- Using the CIK from step 3, get the insider activity summary
- Analyze for any unusual patterns or red flags

STEP 5 - CONDITIONAL SUSPICIOUS ACTIVITY INVESTIGATION:
IF the insider activity summary reveals suspicious patterns (unusual timing, large volumes, coordinated selling), THEN:
  a) Get detailed insider trading activity for deeper analysis
  b) Check alternative data news sentiment for MSFT to correlate with insider moves
  c) Determine if the suspicion is confirmed based on the combination of insider data and news sentiment
  d) IF suspicion is confirmed, THEN:
     - Find comparable companies again using the CONSERVATIVE approach
     - Recalculate the comparable company valuation with conservative assumptions
  e) IF suspicion is NOT confirmed, THEN:
     - Skip the revaluation and proceed with the original NORMAL valuation
IF no suspicious patterns detected, THEN:
  - Skip this entire step and proceed directly to step 6

STEP 6 - FINAL RECOMMENDATION:
- Synthesize all findings from steps 1-5
- Provide an investment recommendation (Buy/Hold/Sell)
- Include key risks and opportunities

STEP 7 - DELIVERY:
- Send the final recommendation via email to: schroedingersagent@gmail.com

Execute this complete workflow systematically, step by step, for Microsoft Corporation."""
}

def main():
    # Make sure the output directory exists
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for i in range(1, 21):
            try:
                response = requests.post(URL, headers=headers, json=payload)
                response.raise_for_status()

                try:
                    data = response.json()
                    formatted = json.dumps(data, indent=2)
                except ValueError:
                    formatted = response.text

                f.write(f"===== RESPONSE {i} =====\n")
                f.write(formatted)
                f.write("\n\n")

                print(f"Call {i} succeeded.")

            except Exception as e:
                error_msg = f"Error on call {i}: {e}"
                f.write(f"===== RESPONSE {i} (ERROR) =====\n{error_msg}\n\n")
                print(error_msg)

if __name__ == "__main__":
    main()
