"""Grader C: an LLM judge that reads the transcript only.

Run ONCE, locally, through Ollama (http://localhost:11434). No API key, no paid
service. 24 traces x 5 seeds at temperature 0.7. Output: results/judge_runs.json.
The page never calls a model; it only reads that file.

    ollama serve &                      # if not already running
    python3 graders/run_judge.py [--model qwen2.5:7b-instruct]

If Ollama is unreachable, pass --scripted to use a deterministic rule-based
judge instead. The output file then says so in `judge.kind`.
"""
import argparse
import datetime
import hashlib
import json
import pathlib
import re
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
OLLAMA = "http://localhost:11434"
SEEDS = [1, 2, 3, 4, 5]
TEMPERATURE = 0.7


def render(trace):
    lines = []
    for m in trace["transcript"]:
        if m["role"] == "user":
            lines.append(f"CUSTOMER: {m['text']}")
        elif m["role"] == "assistant" and "tool_call" in m:
            c = m["tool_call"]
            lines.append(f"AGENT CALLS {c['name']}({json.dumps(c['args'])})")
        elif m["role"] == "assistant":
            lines.append(f"AGENT: {m['text']}")
        else:
            lines.append(f"TOOL RESULT ({m['name']}): {json.dumps(m['result'])}")
    return "\n".join(lines)


def http(path, payload=None, timeout=300):
    req = urllib.request.Request(OLLAMA + path, data=None if payload is None else json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def parse_verdict(text):
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return None, None
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None, None
    v = str(obj.get("verdict", "")).strip().lower()
    return (v if v in ("pass", "fail") else None), str(obj.get("reason", ""))[:300]


def ollama_judge(model, prompt, seed):
    last = ""
    for attempt in range(1, 4):  # re-ask on malformed output; attempts are recorded
        out = http("/api/generate", {"model": model, "prompt": prompt, "stream": False, "format": "json",
                                     "options": {"temperature": TEMPERATURE, "seed": seed + (attempt - 1) * 1000,
                                                 "num_predict": 160}})
        last = out["response"]
        verdict, reason = parse_verdict(last)
        if verdict:
            return {"verdict": verdict, "reason": reason, "attempts": attempt}
    return {"verdict": None, "reason": last[:200], "attempts": 3}


def scripted_judge(trace, seed):
    """Deterministic fallback: fail if the agent ended on a tool error or reported a failure it did not
    resolve; otherwise pass. `seed` is ignored. Used only when Ollama is unavailable."""
    results = [m for m in trace["transcript"] if m["role"] == "tool"]
    last_write = [m for m in results if m["name"] != "get_user"]
    if last_write and not last_write[-1]["result"].get("ok", False):
        return {"verdict": "fail", "reason": "last write call returned an error", "attempts": 1}
    return {"verdict": "pass", "reason": "no unresolved tool error", "attempts": 1}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen2.5:7b-instruct")
    ap.add_argument("--scripted", action="store_true")
    args = ap.parse_args()

    traces = json.loads((ROOT / "traces" / "traces.json").read_text())
    template = (ROOT / "graders" / "judge_prompt.txt").read_text()

    if args.scripted:
        judge = {"kind": "scripted", "model": None, "note": "deterministic rule-based judge; no LLM was used"}
    else:
        tags = {m["name"]: m for m in http("/api/tags")["models"]}
        if args.model not in tags:
            sys.exit(f"model {args.model} not installed; have: {sorted(tags)}")
        show = http("/api/show", {"model": args.model})
        judge = {"kind": "ollama", "model": args.model, "digest": tags[args.model]["digest"],
                 "parameter_size": show.get("details", {}).get("parameter_size"),
                 "quantization": show.get("details", {}).get("quantization_level"),
                 "ollama_version": http("/api/version")["version"]}
    judge.update({"temperature": TEMPERATURE, "seeds": SEEDS, "sees": "transcript only",
                  "prompt_sha256": hashlib.sha256(template.encode()).hexdigest()[:16],
                  "run_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")})

    runs = []
    t0 = time.time()
    for t in traces:
        prompt = template.replace("{transcript}", render(t))
        verdicts = []
        for seed in SEEDS:
            r = scripted_judge(t, seed) if args.scripted else ollama_judge(args.model, prompt, seed)
            verdicts.append({"seed": seed, **r})
        runs.append({"trace_id": t["trace_id"], "verdicts": verdicts})
        print(t["trace_id"], "".join("P" if v["verdict"] == "pass" else "F" if v["verdict"] == "fail" else "?" for v in verdicts),
              f"{time.time() - t0:.0f}s", flush=True)

    (ROOT / "results" / "judge_runs.json").write_text(json.dumps({"judge": judge, "runs": runs}, indent=1) + "\n")
    print("wrote results/judge_runs.json")


if __name__ == "__main__":
    main()
