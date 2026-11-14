/* World Check. Loads three static JSON files once, then renders everything locally.
   No model calls, no keys, no other network requests. */
(function () {
  "use strict";

  const GRADERS = ["A", "B", "C"];
  const GNAME = { A: "End-state check", B: "End-state + invariants", C: "LLM judge, transcript only" };
  const FAULT = {
    none: "None. This is a correct run.",
    dropped_write: "Dropped write. The tool reported a new balance but never saved the user record.",
    double_spend: "Double spend. A timeout and a retry charged the customer twice.",
    stale_read: "Stale read. get_user returned an old balance for one call.",
  };
  const FAULT_SHORT = { dropped_write: "dropped write", double_spend: "double spend", stale_read: "stale read" };

  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const money = (n) => "$" + Number(n).toFixed(2);
  const pct = (r) => Math.round(r * 100) + "%";
  const $ = (s) => document.querySelector(s);

  let T = [], M = null, L = {}, byId = {}, current = null;

  Promise.all(["data/traces.json", "data/labels.json", "data/metrics.json"].map((u) =>
    fetch(u).then((r) => { if (!r.ok) throw new Error(u + " returned " + r.status); return r.json(); })
  )).then(([traces, labels, metrics]) => {
    T = traces; M = metrics;
    labels.forEach((l) => (L[l.trace_id] = l));
    T.forEach((t) => (byId[t.trace_id] = t));
    renderSummary();
    renderList();
    const fromHash = location.hash.slice(1);
    const first = T.find((t) => M.per_trace[t.trace_id].grader_wrong.length) || T[0];
    select(byId[fromHash] ? fromHash : first.trace_id, false);
    window.addEventListener("hashchange", () => {
      const h = location.hash.slice(1);
      if (byId[h] && h !== current) select(h, false);
    });
  }).catch((e) => {
    $("#summary").innerHTML = '<p class="err">Could not load the results: ' + esc(e.message) + ". Open the page from a web server, not from a file.</p>";
  });

  const custName = (t) => t.initial_world.users.find((u) => u.user_id === t.user_id).name;
  const pt = (id) => M.per_trace[id];
  const wrongSet = (id) => pt(id).grader_wrong;

  /* ---------------- summary ---------------- */
  function ciBar(s) {
    const [lo, hi] = s.ci95;
    return '<div class="ci" aria-hidden="true"><b style="left:' + lo * 100 + "%;width:" + (hi - lo) * 100 + '%"></b><i style="left:' + s.rate * 100 + '%"></i></div>' +
      '<span class="cinum">95% interval ' + pct(lo) + " to " + pct(hi) + "</span>";
  }
  function cell(s) {
    return '<span class="num">' + s.k + "/" + s.n + '</span><span class="pct">' + pct(s.rate) + "</span>" + ciBar(s);
  }

  function renderSummary() {
    const g = M.graders;
    const aFP = T.filter((t) => pt(t.trace_id).A.verdict === "pass" && L[t.trace_id].customer_outcome === "wrong");
    const types = [...new Set(aFP.map((t) => t.planted_error))];
    const bCaught = aFP.filter((t) => pt(t.trace_id).B.verdict === "fail").length;
    const cAgree = g.C.agreement;
    const sv = g.C.seed_variability;

    let head = "The end-state check passed " + aFP.length + " of " + M.n_label_wrong + " runs where the customer got the wrong outcome.";
    let sub = "";
    if (aFP.length && types.length === 1) {
      sub = "Every one was a " + (FAULT_SHORT[types[0]] || types[0]) + " run. ";
      if (types[0] === "dropped_write") sub += "The simulator dropped the write for the golden run too, so the expected world was missing it as well. ";
    } else if (aFP.length) {
      sub = "They came from: " + types.map((x) => FAULT_SHORT[x] || x).join(", ") + ". ";
    }
    sub += "Adding a write-persistence audit and a balance-conservation check caught " + bCaught + " of " + aFP.length + ". " +
      "The judge, which reads only the transcript, agreed with the hand label on " + cAgree.k + " of " + cAgree.n + " traces. " +
      (sv.flip_rate_traces.k === 0
        ? "Its five seeds gave the same verdict on every trace, so being stable did not make it right: it was unanimously wrong on " + sv.unanimous_but_wrong + "."
        : "Its five seeds disagreed with each other on " + sv.flip_rate_traces.k + " traces.");

    const rows = [
      ["Label", (t) => L[t.trace_id].customer_outcome === "ok", null],
      ["A", (t) => pt(t.trace_id).A.verdict === "pass", "A"],
      ["B", (t) => pt(t.trace_id).B.verdict === "pass", "B"],
      ["C", (t) => pt(t.trace_id).C.verdict === "pass", "C"],
    ];
    let grid = '<div class="vgrid" aria-hidden="true"><span></span>' + T.map((t, i) => '<span class="tick">' + (i + 1) + "</span>").join("");
    rows.forEach(([name, passFn, gk], ri) => {
      grid += '<span class="rl">' + name + "</span>";
      T.forEach((t) => {
        const pass = passFn(t);
        const bad = gk && wrongSet(t.trace_id).includes(gk);
        grid += '<div class="cell' + (bad ? " bad" : "") + '" data-id="' + t.trace_id + '" title="' + t.trace_id + ", " + name + ": " + (name === "Label" ? (pass ? "ok" : "wrong") : (pass ? "pass" : "fail")) + (bad ? ", disagrees with label" : "") + '"><span class="dot' + (pass ? "" : " ring") + '"></span></div>';
      });
      if (ri === 0) grid += '<span class="rsep"></span>';
    });
    grid += "</div>" +
      '<div class="key" aria-hidden="true"><span><i></i>pass, or label ok</span><span><i class="ring"></i>fail, or label wrong</span><span><i class="sq"></i>grader disagrees with label</span></div>';

    const table = '<table class="mtable"><caption class="sum-sub">Each grader against the hand labels (n = ' + M.n_traces + ")</caption><thead><tr><th scope=\"col\">Grader</th><th scope=\"col\">Agrees with label</th><th scope=\"col\">False passes, of " + M.n_label_wrong + " wrong</th><th scope=\"col\">False fails, of " + M.n_label_ok + " ok</th></tr></thead><tbody>" +
      GRADERS.map((k) => '<tr><th scope="row"><span class="letter">' + k + "</span>" + esc(GNAME[k]) + "</th><td>" + cell(g[k].agreement) + "</td><td>" + cell(g[k].false_pass) + "</td><td>" + cell(g[k].false_fail) + "</td></tr>").join("") +
      "</tbody></table>";

    const j = M.judge;
    const jtxt = j.kind === "ollama"
      ? "Judge: " + esc(j.model) + " (" + esc(j.parameter_size) + ", " + esc(j.quantization) + ") through Ollama " + esc(j.ollama_version) + ", temperature " + j.temperature + ", seeds 1 to 5, run once on a laptop on " + esc(j.run_at.slice(0, 10)) + ". Grader C's verdict is the majority of the five seeds."
      : "Judge: a deterministic scripted rule, not a language model. Ollama was not available for this run.";
    const sra = sv.single_run_agreement;
    const notes = '<div class="notes">' +
      "<p><strong>n is small.</strong> " + M.n_traces + " traces: " + M.n_label_wrong + " labelled wrong, " + M.n_label_ok + " labelled ok, one labeller, all scripted. Bars show Wilson 95% intervals. They are wide. Read differences between graders as suggestive, not established.</p>" +
      "<p>" + jtxt + " " + (Math.min.apply(null, sra.per_seed_correct) === Math.max.apply(null, sra.per_seed_correct)
        ? "Every single seed agreed with the label on " + sra.per_seed_correct[0] + " of " + sra.n + " traces, though the written reasons differed from seed to seed."
        : "A single seed agreed with the label on " + Math.min.apply(null, sra.per_seed_correct) + " to " + Math.max.apply(null, sra.per_seed_correct) + " of " + sra.n + " traces.") + "</p></div>";

    $("#summary").innerHTML =
      '<div class="sum-head"><h2>' + esc(head) + "</h2><p>" + esc(sub) + "</p></div>" +
      "<div><p class=\"sum-sub\">Verdict on every trace. Click a column to open it.</p>" + grid + "</div>" +
      "<div>" + table + notes + "</div>";

    $("#summary").addEventListener("click", (e) => {
      const c = e.target.closest(".cell");
      if (c) select(c.dataset.id, true);
    });
  }

  /* ---------------- list ---------------- */
  function renderList() {
    $("#trace-list").innerHTML = T.map((t) => {
      const w = wrongSet(t.trace_id);
      return '<li><button class="item' + (w.length ? " hasbad" : "") + '" data-id="' + t.trace_id + '">' +
        '<span class="id">' + t.trace_id + '</span><span class="who">' + esc(custName(t).split(" ")[0]) + '<span class="ln"> ' + esc(custName(t).split(" ").slice(1).join(" ")) + "</span></span>" +
        (w.length ? '<span class="flag" title="Grader disagreed with the label: ' + w.join(", ") + '"><span class="sr">Disagrees with label: </span>' + w.join(" ") + "</span>" : "") +
        '<span class="goal">' + esc(t.task.goal_text) + "</span></button></li>";
    }).join("");
    $("#trace-list").addEventListener("click", (e) => {
      const b = e.target.closest(".item");
      if (b) select(b.dataset.id, true);
    });
  }

  /* ---------------- detail ---------------- */
  function chipHTML(k, t) {
    const p = pt(t.trace_id), v = p[k], wrong = p.grader_wrong.includes(k);
    let why = "";
    if (k === "A") {
      why = v.verdict === "fail" ? esc(v.diffs.join(" ")) : "The final world matches the expected world." +
        (wrong ? (t.simulator.persist_user === false ? " The expected world comes from the same simulator, which dropped the same write, so the check cannot see it." : " The customer outcome is still wrong.") : "");
    } else if (k === "B") {
      why = v.verdict === "fail" ? esc(v.reasons.join(" ")) : "End state, write persistence and balance conservation all check out.";
    } else {
      const seeds = v.seeds.map((s) => '<i class="' + (s.verdict === "pass" ? "p" : "f") + '" title="seed ' + s.seed + ": " + s.verdict + '"></i>').join("");
      why = v.votes.pass + " of 5 seeds say pass." + (v.unanimous ? "" : " The seeds disagree.") + '<div class="seeds" aria-hidden="true">' + seeds + "</div>" +
        "<details><summary>What each seed said</summary><ul>" + v.seeds.map((s) => "<li><b>Seed " + s.seed + ", " + s.verdict + ".</b> " + esc(s.reason) + "</li>").join("") + "</ul></details>";
    }
    return '<div class="chip' + (wrong ? " wrong" : "") + '"><div class="cn"><span class="letter">' + k + "</span>" + esc(GNAME[k]) + "</div>" +
      '<div class="cv"><span class="word">' + (v.verdict === "pass" ? "Pass" : "Fail") + "</span>" + (wrong ? '<span class="stamp">Wrong</span>' : "") + "</div>" +
      '<div class="why">' + why + "</div></div>";
  }

  function msgHTML(m) {
    if (m.role === "user") return '<div class="msg user"><div class="who">Customer</div><div class="txt">' + esc(m.text) + "</div></div>";
    if (m.role === "assistant" && m.tool_call) return '<div class="msg call"><div class="who">Agent calls a tool</div><code>' + esc(m.tool_call.name + "(" + JSON.stringify(m.tool_call.args) + ")") + "</code></div>";
    if (m.role === "assistant") return '<div class="msg agent"><div class="who">Agent</div><div class="txt">' + esc(m.text) + "</div></div>";
    const err = m.result && m.result.ok === false;
    return '<div class="msg tool' + (err ? " err" : "") + '"><div class="who">Tool result' + (err ? ", error" : "") + "</div><code>" + esc(JSON.stringify(m.result)) + "</code></div>";
  }

  function fmtField(d, v) { return d.field === "gift_card_balance" ? money(v) : String(v); }

  function gcMoney(w) {
    return w.users.reduce((a, u) => a + u.gift_card_balance, 0) +
      w.orders.reduce((a, o) => a + o.payments.filter((p) => p.method === "gift_card").reduce((b, p) => b + p.amount, 0), 0);
  }

  function worldHTML(t) {
    const rows = t.world_diff.length
      ? t.world_diff.map((d) => "<tr><td>" + esc(d.record) + "<br>" + esc(d.field) + "</td><td>" + esc(fmtField(d, d.before)) + "</td><td>" + esc(fmtField(d, d.after)) + "</td></tr>").join("")
      : '<tr class="none"><td colspan="3">No record changed.</td></tr>';
    const changed = [...new Set(t.tool_changes.map((c) => c.record))];
    const saved = new Set(t.persisted_writes);
    const saves = changed.length
      ? "<ul>" + changed.map((r) => "<li><code>" + esc(r) + "</code>" + (saved.has(r) ? '<span class="saved">saved</span>' : '<span class="stamp">not saved</span>') + "</li>").join("") + "</ul>"
      : "<p class=\"sub\">No tool changed any record.</p>";
    const before = gcMoney(t.initial_world), after = gcMoney(t.final_world), drift = Math.round((after - before) * 100) / 100;
    const bal = drift === 0
      ? '<li>Balances plus gift-card payments: ' + money(before) + " before, " + money(after) + ' after. <span class="saved">balanced</span></li>'
      : '<li>Balances plus gift-card payments: ' + money(before) + " before, " + money(after) + ' after. <span class="stamp">off by ' + (drift > 0 ? "+" : "-") + money(Math.abs(drift)) + "</span></li>";
    return "<h3>World after the run</h3>" +
      '<table class="ledger"><thead><tr><th scope="col">Record</th><th scope="col">Before</th><th scope="col">After</th></tr></thead><tbody>' + rows + "</tbody></table>" +
      '<div class="check"><h4>What the tools said they changed</h4>' + saves + '<p class="sub">A tool reporting a change is not the same as the change reaching the store.</p></div>' +
      '<div class="check"><h4>Gift-card money check</h4><ul>' + bal + '</ul><p class="sub">This total should not move, because a payment only transfers value from a balance to an order.</p></div>';
  }

  function select(id, user) {
    const t = byId[id]; if (!t) return;
    current = id;
    document.querySelectorAll(".item").forEach((b) => b.setAttribute("aria-current", b.dataset.id === id ? "true" : "false"));
    document.querySelectorAll(".cell").forEach((c) => c.classList.toggle("sel", c.dataset.id === id));
    const lab = L[id];
    $("#detail").innerHTML =
      '<header class="d-head"><h2><span class="tid">' + id + "</span>" + esc(custName(t)) + "</h2>" +
      '<blockquote class="req"><small>Customer request</small>' + esc(t.task.request) + "</blockquote>" +
      '<p class="fault"><b>Scripted fault:</b> ' + esc(FAULT[t.planted_error]) + "</p></header>" +
      '<section class="verdicts" aria-label="Verdicts">' +
      '<div class="chip' + (lab.customer_outcome === "wrong" ? " wrong" : "") + '"><div class="cn">Hand label</div><div class="cv"><span class="word">' + (lab.customer_outcome === "ok" ? "Ok" : "Wrong") + "</span></div><div class=\"why\">" + esc(lab.reason) + "</div></div>" +
      GRADERS.map((k) => chipHTML(k, t)).join("") + "</section>" +
      '<div class="d-cols"><section class="world">' + worldHTML(t) + "</section>" +
      '<section class="transcript"><h3>Transcript</h3>' + t.transcript.map(msgHTML).join("") + "</section></div>";
    history.replaceState(null, "", "#" + id);
    if (user) {
      const d = $("#detail");
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      d.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
      d.focus({ preventScroll: true });
    }
  }
})();
