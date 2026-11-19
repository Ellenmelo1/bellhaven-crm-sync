# ============================================================
# CRM CLIENT - everything that talks to the CRM API lives here
# ============================================================

import json
import requests
from config import API_URL, HEADERS


class CRMError(Exception):
    """Raised when the API rejects a request (we keep its message for the reviewer)."""


def _check(response):
    if not response.ok:
        raise CRMError(f"{response.status_code}: {response.text[:500]}")
    return response.json() if response.text else {}


def fetch_all_accounts():
    """The API returns accounts in pages of 50. Request page by page until we have them all."""
    accounts = []
    page = 1
    while True:
        body = _check(requests.get(f"{API_URL}/accounts", headers=HEADERS,
                                   params={"page": page, "page_size": 50}, timeout=30))
        accounts.extend(body["data"])
        if len(accounts) >= body["total"] or not body["data"]:
            break
        page += 1
    return accounts


def get_account(account_id):
    return _check(requests.get(f"{API_URL}/accounts/{account_id}", headers=HEADERS, timeout=30))


def update_account(account_id, fields):
    """PATCH = change only the fields we send."""
    return _check(requests.patch(f"{API_URL}/accounts/{account_id}", headers=HEADERS,
                                 json=fields, timeout=30))


def create_account(fields):
    """POST = create a new account. Returns the created account (with its new account_id)."""
    return _check(requests.post(f"{API_URL}/accounts", headers=HEADERS, json=fields, timeout=30))


if __name__ == "__main__":
    accounts = fetch_all_accounts()
    json.dump(accounts, open("data/crm_accounts.json", "w"), indent=2)
    print(f"   saved {len(accounts)} accounts to data/crm_accounts.json")
