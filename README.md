# World Check

**Live demo:** https://world-check-demo.netlify.app

When a simulated tool silently drops a write, the world a grader inspects at the end can look correct even though the customer's money is wrong. This repo builds a small synthetic retail world, scripts 24 agent traces over it, and measures how three kinds of grader handle the 12 traces that contain a planted error.

It is a static web demo plus the Python that produced it. It is not a reproduction of anyone's product or bug.

## What it does

- **World.** 6 users with gift-card balances and 8 orders, generated from a fixed seed (`world/seed_world.py`). Three tools: `get_user`, `pay_with_gift_card`, `modify_order_payment` (`world/tools.py`). A flag, `persist_user`, decides whether a changed user record is written back.
- **Traces.** 24 scripted traces (`traces/make_traces.py`): 12 correct, and 12 with one planted error each (4 dropped writes, 4 double spends from a retry after a timeout, 4 stale reads). The agent's words are scripted. Every tool result, final world and diff is computed by running the real tool code.
- **Labels.** One label per trace (`traces/labels.json`): did the customer end up with the right outcome, `ok` or `wrong`. Written by hand from the customer's request, the starting records and the final world diff, before any grader ran.
- **Graders.**
  - **A, end-state check** (`graders/end_state.py`). Replays the task's golden actions through the same simulator build, then compares the whole final world to that expected world.
  - **B, end-state plus invariants** (`graders/invariants.py`). A, plus a write-persistence audit (every record a tool changed must be in the persisted write set) and a balance-conservation check (balances plus gift-card payments on orders must not change).
  - **C, LLM judge** (`graders/run_judge.py`). Reads the transcript only. 5 seeds at temperature 0.7, majority verdict.
- **Page.** `site/` reads static JSON and renders a summary, a trace list with a red mark where a grader was wrong, and for each trace the transcript, the world diff, the label and the three verdicts.

## How it runs for $0

| Part | What it uses | Cost |
|---|---|---|
| World, traces, graders A and B | Python standard library, no packages | $0 |
| Judge C | `qwen2.5:7b-instruct` (7.6B, Q4_K_M) through Ollama on a laptop, run once. No API key, no paid API | $0 |
| Page | Static HTML, CSS, JS and 3 JSON files. No model call and no network call after load. No API key in client code | $0 |
| Repo | Public GitHub repo | $0 |
| Hosting | Netlify Free plan. On 2026-11-14 its pricing page listed Free as "$0 forever" with hard monthly limits that cannot be exceeded or incur costs | $0 |

To reproduce:

```bash
python3 world/seed_world.py            # users.json, orders.json
python3 traces/make_traces.py          # traces/traces.json
# labels.json is hand-written and checked in
ollama serve &                         # in another terminal, with qwen2.5:7b-instruct pulled
python3 graders/run_judge.py           # results/judge_runs.json (about 20 minutes on a laptop)
python3 graders/compute_metrics.py     # validates, writes results/metrics.json, copies data to site/data/
python3 -m http.server -d site 8000    # open http://localhost:8000
```

The judge run was done once on 2026-11-14 (Ollama 0.40.15, model digest `845dbda0ea48`). Re-running it will not give identical verdicts, so `results/judge_runs.json` is checked in and is what the page shows. If Ollama is unavailable, `run_judge.py --scripted` uses a deterministic rule-based judge, and the output file and the page then say so.

## The eval table

Each grader against the hand labels. 24 traces: 11 labelled wrong, 13 labelled ok. A false pass is a grader passing a trace labelled wrong. A false fail is a grader failing a trace labelled ok. Intervals are Wilson 95%.

| Grader | Agrees with label | False passes (of 11 wrong) | False fails (of 13 ok) |
|---|---|---|---|
| A. End-state check | 20/24, 83% (64–93%) | 4/11, 36% (15–65%) | 0/13, 0% (0–23%) |
| B. End-state + invariants | 24/24, 100% (86–100%) | 0/11, 0% (0–26%) | 0/13, 0% (0–23%) |
| C. LLM judge, transcript only | 13/24, 54% (35–72%) | 9/11, 82% (52–95%) | 2/13, 15% (4–42%) |

Where each grader was wrong, by planted error:

| Planted error | Traces | Labelled wrong | A wrong | B wrong | C wrong |
|---|---|---|---|---|---|
| Dropped write | 4 | 4 | 4 | 0 | 3 |
| Double spend | 4 | 4 | 0 | 0 | 4 |
| Stale read | 4 | 3 | 0 | 0 | 3 |
| None (correct run) | 12 | 0 | 0 | 0 | 1 |

What the table shows, and what it does not:

- **A passed all four dropped-write traces.** The golden run goes through the same simulator, which drops the same write, so the expected world is missing it too. A did catch the double spends and the stale reads.
- **B caught all four, but that is by construction.** I wrote the two invariants for these failure types, so 24/24 says the checks do what they were written to do. It says nothing about failures I did not think of.
- **C was stable and mostly wrong.** Across 5 seeds the judge never changed its verdict on any trace (0 of 24 traces, 0 of 120 verdicts), yet its written reasons differed between seeds (about 4.1 distinct reasons out of 5 per trace), so sampling was live. It reads the transcript, and in most traces the transcript looks fine: the tool reported success and the agent said so. It passed 9 of the 11 wrong outcomes. Its two false fails were the correct credit-card fallbacks.
- **Stable is not correct.** A flip rate of zero is a statement about this model and prompt, not about LLM judges in general.
- **n is small.** With 24 traces the intervals are wide and overlap. Differences between graders are suggestive, not established.

## Limits

- **One labeller.** A single labeller wrote every label, and the same author wrote the traces and the graders. The labels were drafted with Claude Code reading each trace's request, starting records and diff, and have not been independently reviewed. A second labeller could disagree, most plausibly on whether an unwarranted refusal counts as `wrong`.
- **Scripted traces.** No real agent produced these transcripts. They are plausible, but real agents fail in ways a script does not.
- **Small n.** 24 traces, 11 wrong. One of the 12 planted errors (T05, a stale read the agent recovered from) did no harm, so it is labelled `ok`.
- **Narrow graders.** A and B are mine, built for this world. A different end-state design would behave differently. The judge is one 7B model with one prompt, not tuned, run once.
- **Issue #104 is unverified and AI-filed.** The scenario was prompted by a reported issue, #104. I have not verified it and it was filed by an AI. This demo does not depend on it and does not claim to reproduce it.
- **Synthetic everything.** The world, the customers and the amounts are invented. Nothing was copied from any other project's code or data.

## Layout

```
world/    seed_world.py, tools.py, users.json, orders.json
traces/   make_traces.py, traces.json (24), labels.json (hand labels)
graders/  end_state.py, invariants.py, judge_prompt.txt, run_judge.py, compute_metrics.py
results/  judge_runs.json (5 seeds), metrics.json
site/     index.html, app.js, style.css, data/ (copies of the JSON the page reads)
```
