# ============================================================
# REVIEW APP - a reviewer approves or rejects each proposed change
# Run with:  streamlit run app.py
# ============================================================
# Golden rule: NOTHING is written to the CRM unless a reviewer clicks Approve.
# Every decision (approved / rejected) is saved to data/decisions.json, so the
# daily pipeline never proposes the same change again.
# ============================================================

import json
from datetime import datetime, timezone
import streamlit as st
import crm_client
from config import BASE_URL, TOKEN
from propose import DECISIONS_FILE, PROPOSALS_FILE, load_decisions

CRM_BROWSER = f"{BASE_URL}/crm/{TOKEN}/accounts"
TYPE_COLORS = {"CHOW": "red", "REPARENT": "orange", "DUPLICATE": "violet",
               "UPDATE": "blue", "CREATE": "green", "NEEDS REVIEW": "gray", "LOW CONFIDENCE": "yellow"}

st.set_page_config(page_title="Bellhaven CRM review", layout="wide")


def load_proposals():
    try:
        return json.load(open(PROPOSALS_FILE))
    except FileNotFoundError:
        return []


def save_decision(p, decision, comment, result=None):
    decisions = load_decisions()
    decisions[p["key"]] = {
        "decision": decision, "comment": comment, "result": result,
        "type": p["type"], "title": p["title"], "account_id": p["account_id"],
        "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    json.dump(decisions, open(DECISIONS_FILE, "w"), indent=2)


def apply_actions(p):
    """Run the proposal's API calls in order. A CHOW creates the new account first,
    then writes its id into chow_current_account on the old account."""
    saved, log = {}, []
    for action in p["actions"]:
        fields = {k: (saved.get(v[1:], v) if isinstance(v, str) and v.startswith("$") else v)
                  for k, v in action["fields"].items()}
        if action["method"] == "POST":
            created = crm_client.create_account(fields)
            new_id = created.get("account_id") or created.get("data", {}).get("account_id")
            if action.get("save_id_as"):
                saved[action["save_id_as"]] = new_id
            log.append(f"Created account {new_id}")
        else:
            crm_client.update_account(action["account_id"], fields)
            log.append(f"Updated {action['account_id']}: {', '.join(fields)}")
    return log


# ---------------- page ----------------
st.title("Bellhaven CRM review queue")
st.caption("Each card is a proposed CRM change with its evidence. Approve writes it to the CRM through the API; "
           "Reject records the decision so it is not proposed again.")

decisions = load_decisions()
pending = [p for p in load_proposals() if p["key"] not in decisions]

c1, c2, c3 = st.columns(3)
c1.metric("Pending", len(pending))
c2.metric("Approved", sum(d["decision"] == "approved" for d in decisions.values()))
c3.metric("Rejected", sum(d["decision"] == "rejected" for d in decisions.values()))
st.markdown(f"[Open the CRM browser]({CRM_BROWSER})")

# Show the result of the last click (kept across the page reload)
if "flash" in st.session_state:
    kind, text = st.session_state.pop("flash")
    (st.success if kind == "ok" else st.info)(text)

types = sorted({p["type"] for p in pending})
chosen = st.multiselect("Filter by type", types, default=types)

for p in [p for p in pending if p["type"] in chosen]:
    with st.container(border=True):
        st.markdown(f':{TYPE_COLORS.get(p["type"], "gray")}-background[**{p["type"]}**] &nbsp; **{p["title"]}**')
        st.write(p["reason"])
        st.markdown("**Evidence**")
        for line in p["evidence"]:
            st.markdown(f"- {line}")
        with st.expander("API calls that will run if approved"):
            st.json(p["actions"])
        if p["account_id"]:
            st.markdown(f"[View account in CRM]({BASE_URL}/crm/{TOKEN}/accounts/{p['account_id']})")
        comment = st.text_input("Reviewer comment (optional)", key="c_" + p["key"])
        b1, b2, _ = st.columns([1, 1, 6])
        if b1.button("Approve", key="a_" + p["key"], type="primary"):
            try:
                log = apply_actions(p)
                save_decision(p, "approved", comment, log)
                st.session_state["flash"] = ("ok", f'Approved "{p["title"]}". Written to CRM: ' + "; ".join(log))
            except crm_client.CRMError as e:
                st.error(f"The CRM rejected the change, nothing recorded as approved: {e}")
                st.stop()
            st.rerun()
        if b2.button("Reject", key="r_" + p["key"]):
            save_decision(p, "rejected", comment)
            st.session_state["flash"] = ("info", f'Rejected "{p["title"]}". Nothing was written to the CRM.')
            st.rerun()

with st.expander(f"Decision history ({len(decisions)})"):
    for key, d in sorted(decisions.items(), key=lambda kv: kv[1]["decided_at"], reverse=True):
        st.markdown(f'- **{d["decision"].upper()}** · {d["type"]} · {d["title"]} · {d["decided_at"]}'
                    + (f' · _{d["comment"]}_' if d.get("comment") else "")
                    + (f' · {"; ".join(d["result"])}' if d.get("result") else ""))
