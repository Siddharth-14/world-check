"""Grader B: end-state plus two invariants.

1. Write-persistence audit: every record a tool says it changed must appear in
   the persisted write set.
2. Balance conservation: total gift-card money must be conserved. Sum of user
   balances plus gift-card payments recorded on orders is the same before and
   after.

B passes only if the end-state check (grader A) and both invariants pass.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "graders"))
import end_state  # noqa: E402


def write_persistence_audit(trace):
    changed = {c["record"] for c in trace["tool_changes"]}
    persisted = set(trace["persisted_writes"])
    missing = sorted(changed - persisted)
    return {"ok": not missing, "missing": missing}


def _gc_money(world):
    bal = sum(u["gift_card_balance"] for u in world["users"])
    paid = sum(p["amount"] for o in world["orders"] for p in o["payments"] if p["method"] == "gift_card")
    return round(bal + paid, 2)


def balance_conservation(trace):
    before, after = _gc_money(trace["initial_world"]), _gc_money(trace["final_world"])
    return {"ok": abs(before - after) < 0.005, "before": before, "after": after,
            "drift": round(after - before, 2)}


def grade(trace):
    a = end_state.grade(trace)
    w = write_persistence_audit(trace)
    c = balance_conservation(trace)
    reasons = list(a["diffs"])
    if not w["ok"]:
        reasons.append("tool changed " + ", ".join(w["missing"]) + " but it was never persisted")
    if not c["ok"]:
        reasons.append(f"gift-card money not conserved (drift {c['drift']:+.2f})")
    ok = a["verdict"] == "pass" and w["ok"] and c["ok"]
    return {"verdict": "pass" if ok else "fail", "end_state": a["verdict"], "persistence": w,
            "conservation": c, "reasons": reasons}


if __name__ == "__main__":
    for t in json.loads((ROOT / "traces" / "traces.json").read_text()):
        g = grade(t)
        print(t["trace_id"], g["verdict"], "; ".join(g["reasons"]))
