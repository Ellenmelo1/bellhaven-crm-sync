# ============================================================
# STEP 1 - EXPLORE THE API (read only, changes nothing)
# Goal: learn how the API works and download a sample of
# accounts to inspect.
# ============================================================

import requests
from config import BASE_URL, API_URL, HEADERS


def save(filename, content):
    """Save any result inside the data/ folder."""
    with open(f"data/{filename}", "w") as f:
        f.write(content)
    print(f"   saved to data/{filename}")


# 1) The machine-readable API spec (OpenAPI) lists every endpoint and field.
print("1) Looking for the API spec...")
for path in ["/api/openapi.json", "/openapi.json", "/api/v1/openapi.json"]:
    r = requests.get(BASE_URL + path, headers=HEADERS)
    print(f"   {path} -> status {r.status_code}")
    if r.status_code == 200:
        save("openapi.json", r.text)
        break

# 2) Ask for the list of accounts (GET = read)
print("\n2) Requesting the account list...")
r = requests.get(API_URL + "/accounts", headers=HEADERS)
print(f"   status {r.status_code}")
save("accounts_sample.json", r.text)

print("\nDone.")
