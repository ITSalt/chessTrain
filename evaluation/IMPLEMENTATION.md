# WP-EVALUATION-02 implementation evidence

Assignment: 910ba01e-ead2-4d47-aa46-95d49385e211.
Baseline: dbe8873. Branch: codex/wp-evaluation-02-pilot-harness.

Scope: evaluation/** and .github/workflows/evaluation.yml only. The coordinator
status showed app:.github/** held by this WP before workflow edits. No fixed ports,
paid API calls, database writes, merge, deploy or program-workspace changes.

Both AGENTS.md and CLAUDE.md, including case variants and applicable nested files,
were searched for and absent. Read-only `orch.py instructions status/check` reported
missing/unmanaged pairs (synchronized=false). This advisory is preserved; instructions
were not created or synchronized. Preparation and approved plan were confirmed from
the coordinator's existing read-only status/lock evidence.

Validation commands (activate the isolated venv described in README first):

```bash
python -m pip install -r evaluation/requirements-dev.txt
python -m pytest evaluation/tests
```

Behavioral coverage includes leakage rejection, train-only profile evidence,
hidden-answer prompt isolation, legal replay, equal A/B/C model/engine settings,
adapter mutation isolation, seeded blind exports, deterministic synthetic execution,
pre-call spend stops, charged timeouts/retries, malformed usage and overrun handling,
versioned unit costs, separate manual/server costs, human rating exclusions,
comparison integrity, ASR semantic counts and the full offline CLI flow.

Deviations/limits: Python is named python3 on this host, so tests use an isolated
/tmp venv whose executable supplies the required `python -m pytest` command. The
engine/text adapters replay trusted manual records; no backend or paid-provider
integration is claimed. Human annotation, source deduplication, profile provenance,
indirect blind clues and real-corpus statistical coverage need human verification.
All fixture data/prices/latencies are synthetic. No measured author experiment or
H1–H5 product success is claimed. Exact commit, test result and CI evidence are in
the PR body to avoid a self-referential commit hash in this tracked report.

## Review revision 1

Addressed the P2 finding on reviewed head
45d66773530226962b4d15dc2fa264b801eb2bb8: valid usage above a reservation is now
retained as known expenditure, including all usage counters and actual unit costs.
The original reservation is recorded as reserved_bound, with explicit bound_exceeded
and budget_exceeded flags. The runner stops with bound_violated before any retry or
later variant, and does not misclassify the known expenditure as uncertain.

Regression evidence: two new parameterized cases failed before the implementation
change. The reported reproduction now preserves 100.008 TEST, 100000 input tokens,
zero uncertain cost and a batch-budget violation. A second case costing 1.508 TEST
exceeds the per-call reservation while remaining within the batch budget; it also
stops immediately and reports only the bound violation. Full suite: 37 passed.
No paid calls or changes outside the evaluation module in this revision. Exact
resubmission SHA and CI evidence are recorded in the PR body.
