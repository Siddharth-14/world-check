"""Validate the judge output, run graders A and B, and compute metrics.

    python3 graders/compute_metrics.py

Reads  traces/traces.json, traces/labels.json, results/judge_runs.json
Writes results/metrics.json and copies the three JSON files the page needs into
site/data/ (the page is deployed from site/ alone). The per-seed verdicts and
reasons the page shows are embedded in metrics.json.

Graders:  A = end-state comparison   B = end-state + invariants   C = LLM judge (transcript only)
Grader C's verdict for a trace is the majority of its 5 seed verdicts.
Verdict "pass" means the grader thinks the customer outcome is ok.
  false pass = grader says pass, label says wrong
  false fail = grader says fail, label says ok
Intervals are Wilson 95% (z = 1.96). n is 24, so they are wide on purpose.
"""
import json
import math
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "graders"))
import end_state  # noqa: E402
import invariants  # noqa: E402

Z = 1.96


def wilson(k, n, z=Z):
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3)]


def stat(k, n):
    return {"k": k, "n": n, "rate": round(k / n, 3) if n else None, "ci95": wilson(k, n)}


def validate(traces, labels, judge):
    """Checks listed in the brief, plus a few sanity checks. Raises on any failure."""
    tids = [t["trace_id"] for t in traces]
    lids = [l["trace_id"] for l in labels]
    rids = [r["trace_id"] for r in judge["runs"]]
    checks = {}

    def check(name, ok, detail=""):
        checks[name] = {"ok": bool(ok), "detail": detail}
        if not ok:
            raise SystemExit(f"VALIDATION FAILED: {name} {detail}")

    check("24 traces", len(tids) == 24, len(tids))
    check("trace ids unique", len(set(tids)) == 24)
    check("label ids match trace ids", sorted(lids) == sorted(tids))
    check("judge ids match trace ids", sorted(rids) == sorted(tids))
    check("label values valid", all(l["customer_outcome"] in ("ok", "wrong") for l in labels))
    check("12 correct, 12 planted-error traces", sum(t["planted_error"] == "none" for t in traces) == 12)
    nverd = {r["trace_id"]: len(r["verdicts"]) for r in judge["runs"]}
    check("every trace has 5 verdicts", all(v == 5 for v in nverd.values()), nverd)
    check("seeds are 1..5 on every trace", all([v["seed"] for v in r["verdicts"]] == [1, 2, 3, 4, 5] for r in judge["runs"]))
    allv = [v for r in judge["runs"] for v in r["verdicts"]]
    check("no null verdicts", all(v["verdict"] in ("pass", "fail") for v in allv),
          f"{sum(v['verdict'] is None for v in allv)} null")
    check("no empty reasons", all(v["reason"] for v in allv))
    retried = sum(v["attempts"] > 1 for v in allv)
    checks["re-asks needed (malformed JSON)"] = {"ok": True, "detail": f"{retried} of {len(allv)} verdicts"}
    # the judge must not have been shown anything beyond the transcript
    prompt = (ROOT / "graders" / "judge_prompt.txt").read_text()
    leak = [w for w in ("planted", "dropped", "persist", "label", "customer_outcome", "stale", "double spend") if w in prompt.lower()]
    check("judge prompt has no leaked grading terms", not leak, leak)
    return checks, retried


def main():
    traces = json.loads((ROOT / "traces" / "traces.json").read_text())
    labels = {l["trace_id"]: l for l in json.loads((ROOT / "traces" / "labels.json").read_text())}
    judge = json.loads((ROOT / "results" / "judge_runs.json").read_text())
    checks, retried = validate(traces, list(labels.values()), judge)
    runs = {r["trace_id"]: r["verdicts"] for r in judge["runs"]}

    # Zero flips could mean the judge is confident, or that seed/temperature were ignored. Tell them apart:
    # if sampling is live, the five written reasons per trace should differ.
    distinct = sum(len({v["reason"] for v in vs}) for vs in runs.values()) / len(runs)
    if judge["judge"]["kind"] == "ollama" and distinct <= 1.0:
        raise SystemExit("VALIDATION FAILED: all 5 seeds gave identical text, so seed/temperature were probably ignored")
    checks["seeds change the written reason"] = {"ok": True, "detail": f"{distinct:.2f} distinct reasons per trace out of 5"}

    per_trace, verdicts = {}, {"A": {}, "B": {}, "C": {}}
    for t in traces:
        tid = t["trace_id"]
        a, b = end_state.grade(t), invariants.grade(t)
        seeds = [v["verdict"] for v in runs[tid]]
        npass = seeds.count("pass")
        c = "pass" if npass >= 3 else "fail"
        verdicts["A"][tid], verdicts["B"][tid], verdicts["C"][tid] = a["verdict"], b["verdict"], c
        want = "pass" if labels[tid]["customer_outcome"] == "ok" else "fail"
        per_trace[tid] = {
            "label": labels[tid]["customer_outcome"],
            "A": {"verdict": a["verdict"], "diffs": a["diffs"]},
            "B": {"verdict": b["verdict"], "reasons": b["reasons"], "persistence_ok": b["persistence"]["ok"],
                  "conservation_ok": b["conservation"]["ok"], "drift": b["conservation"]["drift"]},
            "C": {"verdict": c, "votes": {"pass": npass, "fail": 5 - npass}, "unanimous": npass in (0, 5),
                  "seeds": [{"seed": v["seed"], "verdict": v["verdict"], "reason": v["reason"]} for v in runs[tid]]},
            "grader_wrong": [g for g in "ABC" if verdicts[g][tid] != want],
        }

    n_wrong = sum(l["customer_outcome"] == "wrong" for l in labels.values())
    n_ok = len(labels) - n_wrong
    graders = {}
    for g, name, desc in [
        ("A", "End-state check", "Replays the golden actions through the same simulator and compares the whole final world."),
        ("B", "End-state + invariants", "A, plus a write-persistence audit and a balance-conservation check."),
        ("C", "LLM judge (transcript only)", "Local open model, 5 seeds at temperature 0.7, majority verdict."),
    ]:
        v = verdicts[g]
        agree = sum((v[t] == "pass") == (labels[t]["customer_outcome"] == "ok") for t in v)
        fp = sum(v[t] == "pass" and labels[t]["customer_outcome"] == "wrong" for t in v)
        ff = sum(v[t] == "fail" and labels[t]["customer_outcome"] == "ok" for t in v)
        graders[g] = {"name": name, "description": desc, "agreement": stat(agree, len(v)),
                      "false_pass": {**stat(fp, n_wrong), "of": "traces labelled wrong"},
                      "false_fail": {**stat(ff, n_ok), "of": "traces labelled ok"}}

    # Judge variability across seeds (single-run view of grader C)
    per_seed = []
    for s in range(5):
        acc = sum((runs[t][s]["verdict"] == "pass") == (labels[t]["customer_outcome"] == "ok") for t in runs)
        per_seed.append(acc)
    flipped = sum(not per_trace[t]["C"]["unanimous"] for t in per_trace)
    minority = sum(min(per_trace[t]["C"]["votes"].values()) for t in per_trace)
    graders["C"]["seed_variability"] = {
        "flip_rate_traces": {**stat(flipped, len(runs)), "meaning": "traces where the 5 seeds did not all agree"},
        "minority_votes": {**stat(minority, 5 * len(runs)), "meaning": "individual verdicts that disagree with their trace's majority"},
        "single_run_agreement": {"per_seed_correct": per_seed, "n": len(runs),
                                 "min": round(min(per_seed) / len(runs), 3), "max": round(max(per_seed) / len(runs), 3),
                                 "mean": round(sum(per_seed) / (5 * len(runs)), 3)},
        "unanimous_but_wrong": sum(per_trace[t]["C"]["unanimous"] and "C" in per_trace[t]["grader_wrong"] for t in per_trace),
        "distinct_reasons_per_trace": round(distinct, 2),
    }

    by_type = {}
    for t in traces:
        row = by_type.setdefault(t["planted_error"], {"n": 0, "A_wrong": 0, "B_wrong": 0, "C_wrong": 0, "label_wrong": 0})
        row["n"] += 1
        row["label_wrong"] += labels[t["trace_id"]]["customer_outcome"] == "wrong"
        for g in "ABC":
            row[f"{g}_wrong"] += g in per_trace[t["trace_id"]]["grader_wrong"]

    out = {"n_traces": len(traces), "n_label_wrong": n_wrong, "n_label_ok": n_ok,
           "ci_method": "Wilson score, 95%", "judge": judge["judge"], "graders": graders,
           "by_planted_error": by_type, "per_trace": per_trace,
           "validation": {"checks": checks},
           "caution": "n = 24 traces, one labeller, scripted traces. Intervals are wide; do not read these as general accuracy."}
    (ROOT / "results" / "metrics.json").write_text(json.dumps(out, indent=1) + "\n")

    data = ROOT / "site" / "data"
    data.mkdir(parents=True, exist_ok=True)
    for src in ["traces/traces.json", "traces/labels.json", "results/metrics.json"]:
        shutil.copy(ROOT / src, data / pathlib.Path(src).name)

    for g in "ABC":
        x = graders[g]
        print(f"{g} {x['name']:<30} agree {x['agreement']['k']}/24 {x['agreement']['ci95']}  "
              f"false-pass {x['false_pass']['k']}/{n_wrong} {x['false_pass']['ci95']}  "
              f"false-fail {x['false_fail']['k']}/{n_ok} {x['false_fail']['ci95']}")
    sv = graders["C"]["seed_variability"]
    print("judge flip traces", sv["flip_rate_traces"], "\nsingle-run agreement", sv["single_run_agreement"])
    print("re-asks:", retried, "| by type:", json.dumps(by_type))


if __name__ == "__main__":
    main()
