# ============================================================
# PIPELINE - the daily job: scrape -> pull CRM -> propose
# Run with:  python pipeline.py
# ============================================================
# Safe to run any number of times:
#   - it never writes to the CRM (only the review app does, on approval)
#   - proposals already approved or rejected are never proposed again
# ============================================================

import json
from datetime import datetime
import crm_client
import propose
import scraper

print(f"Pipeline run {datetime.now().isoformat(timespec='seconds')}")

print("1) Scraping the Bellhaven website...")
locations = scraper.scrape_website()
json.dump(locations, open("data/site_locations.json", "w"), indent=2)

print("2) Pulling all CRM accounts...")
accounts = crm_client.fetch_all_accounts()
json.dump(accounts, open("data/crm_accounts.json", "w"), indent=2)
print(f"   {len(accounts)} accounts")

print("3) Building proposals...")
propose.run()
print("Done. Review pending proposals with:  streamlit run app.py")
