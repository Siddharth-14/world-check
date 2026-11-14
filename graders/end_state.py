"""Grader A: end-state comparison.

Replays the task's golden actions through the *same simulator build* the agent
ran on (so a persistent simulator bug, such as a dropped user write, applies to
the golden run too), then compares the agent's final world to that expected
world: every user balance, every order status and payment list.

Transient faults (a timeout, a stale read) are not replayed. The golden run is
one clean call per action.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "world"))
from tools import Env  # noqa: E402


def _index(world):
    return ({u["user_id"]: u for u in world["users"]}, {o["order_id"]: o for o in world["orders"]})


def expected_world(trace):
    users, orders = _index(trace["initial_world"])
    env = Env(users, orders, persist_user=trace["simulator"]["persist_user"],
              guard_duplicates=trace["simulator"]["guard_duplicates"])
    for a in trace["task"]["golden_actions"]:
        env.call(a["tool"], **a["args"])
    return env.store


def grade(trace):
    exp = expected_world(trace)
    users, orders = _index(trace["final_world"])
    diffs = []
    for uid, u in users.items():
        if abs(u["gift_card_balance"] - exp["users"][uid]["gift_card_balance"]) > 0.005:
            diffs.append(f"user {uid} balance {u['gift_card_balance']:.2f}, expected {exp['users'][uid]['gift_card_balance']:.2f}")
    for oid, o in orders.items():
        e = exp["orders"][oid]
        if o["status"] != e["status"] or o["payments"] != e["payments"]:
            diffs.append(f"order {oid} is {o['status']} {o['payments']}, expected {e['status']} {e['payments']}")
    return {"verdict": "pass" if not diffs else "fail", "diffs": diffs}


if __name__ == "__main__":
    for t in json.loads((ROOT / "traces" / "traces.json").read_text()):
        g = grade(t)
        print(t["trace_id"], g["verdict"], "; ".join(g["diffs"]))
