# Bellhaven CRM sync

Keeps the CRM's parent-company links for Bellhaven Senior Living in line with Bellhaven's own website.
A daily pipeline scrapes the website, compares it with the CRM, and builds **proposals**.
A reviewer approves or rejects each one in a small local app. **Nothing is written to the CRM without approval.**

## Run it

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp config.example.py config.py      # then paste your CRM token into config.py
python pipeline.py                  # scrape website -> pull CRM -> build proposals
streamlit run app.py                # review queue at http://localhost:8501
```

## Files

| File | What it does |
|---|---|
| `pipeline.py` | The daily job: runs the scraper, pulls all CRM accounts, builds proposals. Never writes to the CRM. |
| `scraper.py` | Collects every location from the directory pages **and the homepage** (the new Findlay location is only linked there), then reads each location page. |
| `crm_client.py` | All API calls: paginated read, `PATCH` (update), `POST` (create). |
| `normalize.py` | Cleans addresses before comparing (`North Blanchard Street` -> `n blanchard st`, `Northwest` -> `nw`, `Pk` -> `pike`). |
| `propose.py` | The matching and business rules. Turns the data into proposals with evidence and the exact API calls. |
| `app.py` | Streamlit review app: evidence, Approve / Reject, reviewer comment, decision history. |
| `compare.py` | Side-by-side spreadsheet (`data/comparison.csv`) used for the manual review that shaped the rules. |
| `.github/workflows/daily.yml`, `schedule.cron` | Daily schedule (GitHub Actions or local cron). Not live. |
| `data/decisions.json` | Every approved / rejected proposal. This is what makes re-runs safe. |

## Rules (see the top of `propose.py`)

- **Matching:** address + ZIP first, then a similar address in the same city/state, then name only (low confidence).
  Names change in a rebrand; buildings don't. Locations are only compared with accounts in the same city/state, so a
  same-name facility in another state (Amberly Manor, CO) is never touched.
- **Duplicates:** several accounts at one address. One survivor is kept using a fixed ladder:
  1) has billing history, 2) already under Bellhaven, 3) street written like the website, 4) no parent.
  The others get `duplicate_of_account` = survivor and status `Inactive`.
- **Change of ownership (SOP):** only when an account must move to another parent.
  Revenue > 0 **and** outstanding AR > 0 -> leave the old account untouched, create a new one under the right parent,
  and set `chow_current_account` on the old one. Otherwise re-parent directly.
  If the new owner's account already exists (Sandusky -> Millstone), CHOW points to it instead of creating a duplicate.
- **Fixes:** rename to the website name; fix ZIP when the street matches. A billing street is never changed silently:
  a name-only match with a different street is a `LOW CONFIDENCE` proposal for a person to decide (it may be a PO Box).
- **Orphans** (under Bellhaven, not on the website): another account at the same address = sold (SOP applies);
  no evidence -> `Needs Review` with a note, never deactivated blindly.
- **Create:** on the website, no account at that address -> new account under Bellhaven.

## Safe re-runs

Every proposal has a stable key. Approved changes stop being proposed because the CRM now matches the website.
Rejected or flagged items stay in `data/decisions.json` and are skipped on every later run.

## Result of the review

28 approved, 1 rejected. Final pipeline run: `3 proposals found, 3 already decided, 0 pending review`.

| Type | Count | Accounts |
|---|---|---|
| CHOW | 3 | Marietta, Tiffin (new account under Bellhaven) · Sandusky (sold to Millstone; points to existing account) |
| Re-parent | 4 | Lima, Findlay (revenue but $0 AR) · Zanesville, Kettering (+ rename) |
| Duplicate | 7 | Monroe x2, Kettering x2, Owosso, Port Clinton, Erie |
| Update | 8 | 7 outdated names (incl. rebrands like Riverbend Manor -> Bellhaven of Chagrin Falls) + Portsmouth ZIP typo |
| Create | 4 | Batavia, Carlisle, Amberly Manor, Union Square |
| Needs Review | 2 | Alliance, Coldwater |
| Rejected | 1 | Ashtabula: replace PO Box billing street with physical address (PO Box is likely intentional) |

Known limitation: `decisions.json` is local, so a hosted schedule would need it in shared storage (or committed back
to the repo) for the review app and the scheduled job to see the same decisions.
