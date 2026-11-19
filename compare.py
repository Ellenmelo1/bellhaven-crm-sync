# ============================================================
# COMPARE - puts the website and the CRM side by side and writes
# a spreadsheet for the analyst to review (data/comparison.csv)
# Confidence order (address beats name, because names change in a
# rebrand but the building stays put):
#   EXACT ADDRESS  >  SIMILAR ADDRESS  >  NAME ONLY
# ============================================================

import csv
import json
from rapidfuzz import fuzz
from config import BELLHAVEN_PARENT_ID
from normalize import normalize_text, normalize_street, normalize_zip

site = json.load(open("data/site_locations.json"))
crm = json.load(open("data/crm_accounts.json"))


def crm_address(a):
    return f'{a.get("billing_street")}, {a.get("billing_city")}, {a.get("billing_state")} {a.get("billing_zip")}'


rows = []
matched_ids = set()

for loc in site:
    site_street = normalize_street(loc["street"])
    site_zip = normalize_zip(loc["zip"])
    site_address = f'{loc["street"]}, {loc["city"]}, {loc["state"]} {loc["zip"]}'
    candidates = []

    for a in crm:
        crm_street = normalize_street(a.get("billing_street"))
        same_city = (normalize_text(a.get("billing_city")) == normalize_text(loc["city"])
                     and a.get("billing_state") == loc["state"])
        address_score = fuzz.ratio(site_street, crm_street) if crm_street else 0
        name_score = fuzz.token_set_ratio(normalize_text(loc["name"]), normalize_text(a["name"]))

        if site_street and site_street == crm_street and site_zip == normalize_zip(a.get("billing_zip")):
            level = "1 EXACT ADDRESS"
        elif same_city and address_score >= 85:
            level = "2 SIMILAR ADDRESS"
        elif same_city and name_score >= 80:
            level = "3 NAME ONLY"
        else:
            continue
        candidates.append((level, address_score, name_score, a))

    if not candidates:
        rows.append({"site_name": loc["name"], "site_address": site_address,
                     "match_level": "NOT IN CRM"})
    for level, address_score, name_score, a in sorted(candidates, key=lambda c: c[0]):
        matched_ids.add(a["account_id"])
        rows.append({
            "site_name": loc["name"], "site_address": site_address, "match_level": level,
            "address_similarity": round(address_score), "name_similarity": round(name_score),
            "crm_id": a["account_id"], "crm_name": a["name"], "crm_address": crm_address(a),
            "crm_parent": a.get("parent_name") or "(no parent)", "crm_status": a.get("status"),
            "lifetime_revenue": a.get("lifetime_revenue"), "outstanding_ar": a.get("outstanding_ar"),
            "crm_duplicate_of": a.get("duplicate_of_account"), "crm_note": a.get("note"),
        })

# Accounts under Bellhaven in the CRM that matched nothing on the website = possible ORPHANS.
# For each orphan we also ask a second question: is there ANOTHER account at the same
# address? If so, the facility was probably sold to that account's parent.
def same_address(a, b):
    return (normalize_street(a.get("billing_street")) == normalize_street(b.get("billing_street"))
            and normalize_zip(a.get("billing_zip")) == normalize_zip(b.get("billing_zip")))

for a in crm:
    if a.get("parent_id") == BELLHAVEN_PARENT_ID and a["account_id"] not in matched_ids:
        others = [b for b in crm if b["account_id"] != a["account_id"] and b.get("billing_street")
                  and same_address(a, b)]
        if others:
            level = "ORPHAN - SAME ADDRESS AS: " + "; ".join(
                f'{b["name"]} ({b["account_id"]}, parent: {b.get("parent_name") or "none"})' for b in others)
        else:
            level = "ORPHAN UNDER BELLHAVEN (no other account at this address)"
        rows.append({
            "site_name": "(not on website)", "match_level": level,
            "crm_id": a["account_id"], "crm_name": a["name"], "crm_address": crm_address(a),
            "crm_parent": a.get("parent_name"), "crm_status": a.get("status"),
            "lifetime_revenue": a.get("lifetime_revenue"), "outstanding_ar": a.get("outstanding_ar"),
            "crm_note": a.get("note"),
        })

columns = ["site_name", "site_address", "match_level", "address_similarity", "name_similarity",
           "crm_id", "crm_name", "crm_address", "crm_parent", "crm_status", "lifetime_revenue",
           "outstanding_ar", "crm_duplicate_of", "crm_note"]
with open("data/comparison.csv", "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)

print(f"   saved {len(rows)} rows to data/comparison.csv (open it in Excel)")
