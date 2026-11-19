# ============================================================
# PROPOSE - turns the analyst's rules into a list of proposed CRM changes
# ============================================================
# Nothing here writes to the CRM. It only produces PROPOSALS, each with
# its supporting evidence and the exact API calls that would run if a
# reviewer approves it (see app.py).
#
# Rules (decided during the manual review of the data):
#   MATCHING   address + ZIP beats name: names change in a rebrand, buildings don't.
#              A location is only compared with accounts in the same city/state.
#   DUPLICATES several accounts at one address -> keep one "survivor", chosen by:
#              1) has billing history  2) already under Bellhaven
#              3) street written exactly like the website  4) has no parent
#              Losers -> duplicate_of_account = survivor, status Inactive.
#   SOP/CHOW   moving to another parent: revenue > 0 AND open AR > 0 -> keep the
#              old account untouched, create a new one under the right parent and
#              set chow_current_account on the old one. Otherwise re-parent directly.
#   FIXES      rename to the website name; fix ZIP when street matches.
#              Billing street is never changed silently: a name-only match with a different
#              street becomes a LOW CONFIDENCE proposal for a person to decide.
#   ORPHANS    under Bellhaven but not on the website:
#              - another account at the same address under another parent = sold
#                (SOP applies; point CHOW to the existing account, no new duplicate)
#              - no evidence -> Needs Review + note (never deactivate blindly)
#   CREATE     on the website, no account at that address -> new account under Bellhaven.
#
# Re-runs are safe: every proposal has a stable "key". Keys that a reviewer
# already approved or rejected (data/decisions.json) are never proposed again.
# ============================================================

import json
from rapidfuzz import fuzz
from config import BELLHAVEN_PARENT_ID
from normalize import normalize_text, normalize_street, normalize_zip

DECISIONS_FILE = "data/decisions.json"
PROPOSALS_FILE = "data/proposals.json"

# Website care offerings -> CRM care_type vocabulary
CARE_TYPE_MAP = {
    "assisted living": "Assisted Living",
    "memory support": "Memory Care",
    "short-term rehabilitation & nursing": "Skilled Nursing",
}


# ---------- small helpers ----------

def money(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def has_billing(a):
    return money(a.get("lifetime_revenue")) > 0 or money(a.get("outstanding_ar")) > 0


def needs_chow(a):
    """The SOP: revenue history AND outstanding AR greater than zero."""
    return money(a.get("lifetime_revenue")) > 0 and money(a.get("outstanding_ar")) > 0


def site_address(loc):
    return f'{loc["street"]}, {loc["city"]}, {loc["state"]} {loc["zip"]}'


def crm_address(a):
    return f'{a.get("billing_street")}, {a.get("billing_city")}, {a.get("billing_state")} {a.get("billing_zip")}'


def describe(a):
    return (f'{a["name"]} ({a["account_id"]}) | {crm_address(a)} | parent: {a.get("parent_name") or "none"} '
            f'| status: {a.get("status")} | revenue ${money(a.get("lifetime_revenue")):,.0f} '
            f'| AR ${money(a.get("outstanding_ar")):,.0f}')


def same_address(a, b):
    return (normalize_street(a.get("billing_street")) == normalize_street(b.get("billing_street"))
            and normalize_zip(a.get("billing_zip")) == normalize_zip(b.get("billing_zip")))


def care_type_from_site(loc):
    for offering in loc.get("care_offerings", []):
        if offering.lower() in CARE_TYPE_MAP:
            return CARE_TYPE_MAP[offering.lower()]
    return None


def is_open(a):
    """Accounts already resolved (inactive, duplicate, or CHOW'd) are left alone."""
    return (a.get("status") != "Inactive" and not a.get("duplicate_of_account")
            and not a.get("chow_current_account") and a["account_id"] != BELLHAVEN_PARENT_ID)


# ---------- matching ----------

def find_candidates(loc, accounts):
    """Return [(level, account)] for CRM accounts that look like this website location."""
    site_street, site_zip = normalize_street(loc["street"]), normalize_zip(loc["zip"])
    found = []
    for a in accounts:
        if not is_open(a):
            continue
        same_city = (normalize_text(a.get("billing_city")) == normalize_text(loc["city"])
                     and a.get("billing_state") == loc["state"])
        if not same_city:
            continue
        crm_street = normalize_street(a.get("billing_street"))
        if crm_street and crm_street == site_street and normalize_zip(a.get("billing_zip")) == site_zip:
            found.append(("EXACT ADDRESS", a))
        elif crm_street and fuzz.ratio(crm_street, site_street) >= 85:
            found.append(("SIMILAR ADDRESS", a))
        elif fuzz.token_set_ratio(normalize_text(a["name"]), normalize_text(loc["name"])) >= 90:
            found.append(("NAME ONLY", a))
    # If any account matches on address, name-only lookalikes are ignored
    if any(level != "NAME ONLY" for level, _ in found):
        found = [(l, a) for l, a in found if l != "NAME ONLY"]
    return found


REASONS = ["has billing history", "is already under Bellhaven",
           "has the street written exactly like the website", "has no parent"]


def survivor_rank(loc, a):
    """Tie-breaker ladder for duplicates (higher wins, compared step by step)."""
    return (
        has_billing(a),                                                                    # 1
        a.get("parent_id") == BELLHAVEN_PARENT_ID,                                         # 2
        (a.get("billing_street") or "").strip().lower() == loc["street"].strip().lower(),  # 3
        not a.get("parent_id"),                                                            # 4
    )


def pick_survivor(loc, accounts):
    return max(accounts, key=lambda a: survivor_rank(loc, a))


def why_beats(loc, survivor, loser):
    """The first step of the ladder where the survivor beats this particular duplicate."""
    for step, (s, l) in enumerate(zip(survivor_rank(loc, survivor), survivor_rank(loc, loser))):
        if s != l:
            return f"step {step + 1}: the survivor {REASONS[step]}"
    return "all steps tied, so the first account was kept"


# ---------- proposal builders ----------

def proposal(key, kind, title, account, reason, evidence, actions):
    return {"key": key, "type": kind, "title": title,
            "account_id": account["account_id"] if account else None,
            "account_name": account["name"] if account else None,
            "reason": reason, "evidence": evidence, "actions": actions}


def new_account_fields(loc, parent_id, note, fallback_care_type=None):
    return {
        "name": loc["name"], "parent_id": parent_id,
        "billing_street": loc["street"], "billing_city": loc["city"],
        "billing_state": loc["state"], "billing_zip": loc["zip"],
        "care_type": care_type_from_site(loc) or fallback_care_type,
        "phone": loc.get("phone") or None, "status": "Active", "note": note,
    }


def build_proposals(site, crm):
    proposals = []
    matched = set()

    for loc in site:
        evidence_site = f'Website: {loc["name"]} | {site_address(loc)} | {", ".join(loc["care_offerings"])} | {loc["url"]}'
        candidates = find_candidates(loc, crm)

        # 1) Not in the CRM -> create
        if not candidates:
            fields = new_account_fields(loc, BELLHAVEN_PARENT_ID,
                                        "Created from the Bellhaven website; no CRM account found at this address.")
            proposals.append(proposal(
                f'CREATE:{loc["slug"]}', "CREATE", f'Create account "{loc["name"]}" under Bellhaven', None,
                "Listed on the Bellhaven website, but no CRM account exists at this address (same city/state).",
                [evidence_site, "CRM: no account at this address"],
                [{"method": "POST", "fields": fields}]))
            continue

        accounts = [a for _, a in candidates]
        matched.update(a["account_id"] for a in accounts)
        levels = {a["account_id"]: level for level, a in candidates}
        survivor = pick_survivor(loc, accounts)

        # 2) Duplicates -> mark losers
        for loser in accounts:
            if loser is survivor:
                continue
            ev = [evidence_site, "Duplicate: " + describe(loser), "Survivor: " + describe(survivor),
                  f"Tie-breaker ({why_beats(loc, survivor, loser)})."]
            if has_billing(loser):
                ev.append("WARNING: this duplicate has billing history - check with billing before approving.")
            proposals.append(proposal(
                f'DUPLICATE:{loser["account_id"]}->{survivor["account_id"]}', "DUPLICATE",
                f'Mark "{loser["name"]}" as duplicate of "{survivor["name"]}"', loser,
                f"Same facility as {survivor['name']} ({levels[loser['account_id']].lower()} match).",
                ev,
                [{"method": "PATCH", "account_id": loser["account_id"], "fields": {
                    "duplicate_of_account": survivor["account_id"], "status": "Inactive",
                    "note": f'Duplicate of {survivor["name"]} ({survivor["account_id"]}), same address: {site_address(loc)}.'}}]))

        # 3) Survivor: wrong parent? (SOP)  outdated name? wrong ZIP?
        ev = [evidence_site, f'CRM ({levels[survivor["account_id"]].lower()} match): ' + describe(survivor)]
        if len(accounts) > 1:
            ev.append(f"Kept as survivor among {len(accounts)} accounts at this address (tie-breaker ladder: "
                      "billing history > already under Bellhaven > street written like the website > no parent).")
        wrong_parent = survivor.get("parent_id") != BELLHAVEN_PARENT_ID

        if wrong_parent and needs_chow(survivor):
            fields = new_account_fields(
                loc, BELLHAVEN_PARENT_ID,
                f'Change of ownership: replaces {survivor["name"]} ({survivor["account_id"]}), kept under its previous parent for billing.',
                survivor.get("care_type"))
            proposals.append(proposal(
                f'CHOW:{survivor["account_id"]}->{BELLHAVEN_PARENT_ID}', "CHOW",
                f'CHOW: new "{loc["name"]}" under Bellhaven; keep old account for billing', survivor,
                "Website shows Bellhaven owns it, but the CRM parent is "
                f'{survivor.get("parent_name") or "empty"}. Revenue > 0 AND open AR > 0, so per SOP the old '
                "account stays untouched and a new account is created under Bellhaven.",
                ev,
                [{"method": "POST", "fields": fields, "save_id_as": "new_id"},
                 {"method": "PATCH", "account_id": survivor["account_id"],
                  "fields": {"chow_current_account": "$new_id"}}]))
            continue

        changes, notes = {}, []
        if wrong_parent:
            changes["parent_id"] = BELLHAVEN_PARENT_ID
            notes.append(f'Re-parent from {survivor.get("parent_name") or "no parent"} to Bellhaven '
                         f'(revenue ${money(survivor.get("lifetime_revenue")):,.0f}, '
                         f'AR ${money(survivor.get("outstanding_ar")):,.0f}: not both > 0, so direct re-parent per SOP)')
        if survivor["name"].strip() != loc["name"].strip():
            changes["name"] = loc["name"]
            notes.append(f'Rename "{survivor["name"]}" -> "{loc["name"]}" (website name)')
        if (normalize_street(survivor.get("billing_street")) == normalize_street(loc["street"])
                and normalize_zip(survivor.get("billing_zip")) != normalize_zip(loc["zip"])):
            changes["billing_zip"] = loc["zip"]
            notes.append(f'Fix ZIP {survivor.get("billing_zip")} -> {loc["zip"]} (street matches; ZIP differs)')
        # Name-only match: the street does not match the website. We never change a billing
        # address automatically, but we surface it as a LOW CONFIDENCE proposal so a person decides
        # (e.g. a PO Box may be the correct billing address on purpose).
        if levels[survivor["account_id"]] == "NAME ONLY" and survivor.get("billing_street"):
            is_po_box = "po box" in normalize_text(survivor["billing_street"])
            proposals.append(proposal(
                f'ADDRESS:{survivor["account_id"]}:{loc["street"]}', "LOW CONFIDENCE",
                f'Replace billing street of "{survivor["name"]}" with the website address', survivor,
                f'Matched on name only: CRM billing street "{survivor["billing_street"]}" differs from the '
                f'website address "{loc["street"]}". Review before changing billing data.',
                ev + (["CRM billing street is a PO Box - it may be the intended billing address."]
                      if is_po_box else []),
                [{"method": "PATCH", "account_id": survivor["account_id"],
                  "fields": {"billing_street": loc["street"]}}]))

        if changes:
            kind = "REPARENT" if wrong_parent else "UPDATE"
            proposals.append(proposal(
                f'{kind}:{survivor["account_id"]}:' + json.dumps(changes, sort_keys=True), kind,
                f'{"Re-parent" if wrong_parent else "Update"} "{survivor["name"]}"', survivor,
                "; ".join(notes) + ".", ev,
                [{"method": "PATCH", "account_id": survivor["account_id"], "fields": changes}]))

    # 4) Orphans: under Bellhaven in the CRM, not on the website
    for a in crm:
        if a.get("parent_id") != BELLHAVEN_PARENT_ID or a["account_id"] in matched or not is_open(a):
            continue
        others = [b for b in crm if b["account_id"] != a["account_id"] and b.get("billing_street")
                  and same_address(a, b) and b.get("parent_id") != BELLHAVEN_PARENT_ID and is_open(b)]
        ev = ["Website: not listed on the Bellhaven website", "CRM: " + describe(a)]
        if others:
            new_owner = others[0]
            ev.append("Same address, other parent: " + describe(new_owner))
            if needs_chow(a):
                proposals.append(proposal(
                    f'CHOW_EXISTING:{a["account_id"]}->{new_owner["account_id"]}', "CHOW",
                    f'CHOW: "{a["name"]}" was sold to {new_owner.get("parent_name")}', a,
                    "Not on the Bellhaven website, and an account at the same address already exists under "
                    f'{new_owner.get("parent_name")}. Revenue > 0 AND open AR > 0, so per SOP the old account '
                    "stays untouched. The new-owner account already exists, so chow_current_account points to it "
                    "instead of creating a duplicate.", ev,
                    [{"method": "PATCH", "account_id": a["account_id"],
                      "fields": {"chow_current_account": new_owner["account_id"]}}]))
            else:
                proposals.append(proposal(
                    f'DUPLICATE:{a["account_id"]}->{new_owner["account_id"]}', "DUPLICATE",
                    f'Mark "{a["name"]}" as duplicate of "{new_owner["name"]}" (sold)', a,
                    f'Not on the Bellhaven website; same facility now exists under {new_owner.get("parent_name")}. '
                    "No open billing, so the old Bellhaven copy is retired.", ev,
                    [{"method": "PATCH", "account_id": a["account_id"], "fields": {
                        "duplicate_of_account": new_owner["account_id"], "status": "Inactive",
                        "note": f'Facility sold; now {new_owner["name"]} ({new_owner["account_id"]}).'}}]))
        else:
            ev.append("No other CRM account at this address.")
            proposals.append(proposal(
                f'ORPHAN:{a["account_id"]}', "NEEDS REVIEW",
                f'Flag "{a["name"]}" for review (no longer on website)', a,
                "Under Bellhaven in the CRM but not on the website, with no evidence of a new owner. "
                "Flag for a person to confirm instead of deactivating.", ev,
                [{"method": "PATCH", "account_id": a["account_id"], "fields": {
                    "status": "Needs Review",
                    "note": "No longer listed on the Bellhaven website. No other CRM account at this address, "
                            "so the new owner (if any) is unknown. Needs confirmation before deactivating."}}]))
    return proposals


def load_decisions():
    try:
        return json.load(open(DECISIONS_FILE))
    except FileNotFoundError:
        return {}


def run():
    site = json.load(open("data/site_locations.json"))
    crm = json.load(open("data/crm_accounts.json"))
    decided = load_decisions()
    all_proposals = build_proposals(site, crm)
    pending = [p for p in all_proposals if p["key"] not in decided]
    json.dump(pending, open(PROPOSALS_FILE, "w"), indent=2)
    print(f"   {len(all_proposals)} proposals found, {len(all_proposals) - len(pending)} already decided, "
          f"{len(pending)} pending review -> {PROPOSALS_FILE}")
    return pending


if __name__ == "__main__":
    for p in run():
        print(f'   [{p["type"]}] {p["title"]}')
