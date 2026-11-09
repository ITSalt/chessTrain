# Offline pilot harness (WP-EVALUATION-02)

This is a standalone manual path for `docs/evaluation.md`, independent of B0,
UI, video extraction, database, credentials and Stockfish installation. The checked-in
fixtures are **invented synthetic data**, synthetic engine records and fake TEST
currency rates. They are not experiments on real authors, measured engine outputs,
provider prices, or evidence for H1–H5. Product acceptance remains inconclusive.

From the repository root, create a virtual environment (Python 3.12), activate it,
and install only this module's development requirements:

```bash
python3 -m venv /tmp/chesstrain-evaluation-venv
. /tmp/chesstrain-evaluation-venv/bin/activate
python -m pip install -r evaluation/requirements-dev.txt
python -m pytest evaluation/tests
python -m evaluation validate evaluation/fixtures/manifest.json
python -m evaluation run evaluation/fixtures/manifest.json evaluation/fixtures/config.json evaluation/fixtures/responses.json evaluation/fixtures/engine.json evaluation/artifacts/private/result.json
python -m evaluation blind evaluation/fixtures/manifest.json evaluation/artifacts/private/result.json evaluation/artifacts/reviewer evaluation/artifacts/key --seed 19
```

Commands refuse output overwrite. Choose a fresh output directory for a repeat and
compare JSON contents: the same versioned inputs and seed yield identical output.
`run` returns exit status 2 for a budget/provider stop and writes the partial result
with its costs. Invalid preflight inputs fail before calling the text adapter.
CI installs these requirements and runs `python -m pytest evaluation/tests` with no
credentials, backend, database or network provider calls.

## Manifest and manual annotation contract

`fixtures/manifest.json` is a complete version-1 example. Set `synthetic: false`
only for actual collected data. Preserve dataset, protocol and prompt revisions;
record source provenance in the private manifest. Increment revisions when correcting
labels, changing protocol thresholds or prompts. SHA-256 of the entire validated
manifest is stored with the result and checked before blind export.

Every case identifies its source/author, `split_group`, split, verified status,
position prefix, thought, context before explanation, private labels and an explicit
`exclusion_reason` (empty when eligible). Slices, repeated streams and duplicate
games must use the **same globally scoped split_group**. The validator rejects any
group present in both splits, even across different authors. Determining which
sources are duplicates is a human intake responsibility. Keep final blind games
separate from prompt-tuning material.

Position format is `root_fen` plus a legal sequence of `prefix_uci` moves **only up
to the evaluation position**. Replay checks the root and every move. The private
`labels` object holds explanation, continuation, considered candidates, source words,
analyst interpretation, claim type, expected assessment, timing uncertainty and
unresolved issues (see fixture). Preserve original author words separately from
analyst interpretation. Label meaningful player thoughts including silence, correct
moves for false reasons and negation errors. A label may remain unresolved: exclude
it with a reason when it cannot be judged. Human annotators must ensure `thought`,
`context_before` and the position prefix do not themselves copy the hidden answer.
Automated field isolation cannot detect a mislabeled free-text field.

Profiles must be verified with nonempty evidence IDs pointing only to eligible,
verified train cases of the same author. Human profile creation must use only those
sources. B retrieves eligible train explanations of the target author (all of them
in this minimal baseline); C adds that author's verified profile; A gets neither.
Holdout labels and continuation never enter requests, retrieval or profile evidence.
The harness cannot prove the provider never saw a public video in pretraining.

## Adapters and identical A/B/C settings

`TextProvider` and `EngineProvider` in `adapters.py` define the integration boundary.
The CLI uses only `RecordedText` and `RecordedEngine`. Record the **exact** model ID,
parameters (including output-token cap), config version, prompt revision, engine
budget and tariff snapshot. `latest` aliases are rejected. All three variants receive
the same model/parameters, replayed position, player thought and one reused engine
analysis. Engine records are keyed by full FEN, must match the configured budget,
and contain depth/nodes/time plus legally replayable UCI lines. The fixture engine
is synthetic; real records must be created and verified externally with the chosen
engine and budget. No claim of measured engine quality follows from legal replay.

The ordered response tape contains one record per attempt in holdout manifest order,
then A/B/C order. Each record has `text`, all usage counters and `latency_seconds`,
or `timeout: true` to simulate an unknown billed outcome. Recordings are trusted
manual inputs: record the actual provider model/settings in the config, and do not
present replay timing as a fresh API latency measurement. Request contexts and
settings are copied so adapter mutation cannot change later variants.

No paid adapter is supplied or invoked. Future live adapters must set `live=True`,
obey `Request.max_cost`/`currency`, enforce token/audio/frame and transport limits,
record actual usage, and have an externally approved positive `spend_limit` with
`budget_approval_reference`. A reference records approval; this code does not grant
it. Adapters must not hide retries. Maximum transport retries is three, every
attempt reserves the bound, and only timeout failures retry. Other failures stop.
The engine adapter is an offline record reader; any cost of externally preparing
those records belongs in the supplied usage, not an unaccounted live engine call.

## Costs and partial runs

Tariffs snapshot version, currency, rate **per single named unit**, and cost category
for input tokens (uncached), output tokens, cache tokens (exclusive of uncached
input), audio minutes, frames, retry requests, CPU seconds and manual minutes.
Every response must contain every counter, including explicit zeros. Rates in the
fixture are fake. Enter CPU/server and manual rates separately from API rates;
never substitute a chat subscription price for API usage. Avoid charging the same
unit twice. Upstream preparation costs can be included in the manual tape once;
provenance should explain their allocation across answers.

Before a call, the ledger reserves its conservative upper bound against the batch
limit. Successful usage releases the unused reservation. Timeout, malformed usage,
invalid answer or adapter failure retains the full uncertain reservation and records
the reason. Missing units never silently count as zero. The next attempt stops when
known spend plus uncertain reservations plus its bound would exceed the limit.
The bound must be a genuine upper bound enforced by any future live adapter; an
adapter that violates it stops with an uncertain cost and needs reconciliation.

Reports include known costs, uncertain upper bounds, per-category costs, unit totals,
per-answer/per-verified-episode/per-game/per-source-video-hour denominators and unit
costs. Zero denominators have null prices. Unknown costs remain separate from known
prices; these are not promises of absolute exactly-once API execution. Conservative
reservation can stop a run before all A/B/C answers exist; reports remain partial.

## Blind human review and scoring

Distribute only `reviewer/answers.json` and `reviewer/ratings.json`. Keep the manifest,
original result, seed, response tape, engine records and key private. The CLI requires
separate, non-nested public/private output directories, creates artifacts with mode
0600 and refuses overwrite. It anonymizes case IDs, shuffles answers, removes listed
author IDs/aliases (case insensitive) from answers/context and removes explicit
`config A`/`variant C` style tags. List all known names, initials and transliterations
in `authors`. The organizer must inspect the export for indirect identity clues,
self-identification and recognizable phrases before distribution. Redaction is not
a semantic anonymization guarantee.

Review all four independent dimensions on integer scales 1–5: accuracy, usefulness,
principle applicability and explanation character. Fill `critical_error` boolean,
optional `error_example` and an exclusion reason when a rating cannot be completed.
Leave no inferred score for excluded cases. An unfilled template is rejected; missing
answer ratings are explicitly listed. Use owner/human review and engine checks for
chess claims; an LLM judge alone cannot establish acceptance.

For a paired A/C preference, the organizer can use the private key to add this entry
to the public ratings template **before** distribution (randomize the pair order):

```json
{"answer_ids": ["answer-0002", "answer-0003"], "winner": "answer-0003"}
```

Add it to the `comparisons` array. The reviewer sets `winner` to one anonymous answer
ID or `tie`, without seeing the configurations. Score accepts only rated A/C answers
of the same case and rejects duplicate comparisons. Pair IDs in this example are
illustrative: resolve the actual IDs using the key. Never send the key to reviewers.

```bash
python -m evaluation score evaluation/artifacts/private/result.json evaluation/artifacts/key/key.json evaluation/artifacts/reviewer/ratings.json evaluation/artifacts/private/report.json --asr evaluation/fixtures/asr.json
```

ASR annotations include reference/hypothesis, counts of square/piece/negation errors,
remaining known semantic distortions after review and explicit exclusions. WER uses
case-sensitive whitespace tokenization and Levenshtein word edit counts. Semantic
counts are human labels per included utterance, can exceed one per utterance and
are reported independently of WER. This path does not run ASR or claim automatic
detection of semantic errors.

Reports retain versions/hash/config, input and rating exclusions, unrated IDs,
score sums/counts/histograms, critical errors, raw latency distribution and nearest-rank
p95, preference wins/non-ties, ties/losses, ASR numerators/denominators and costs.
H2 remains inconclusive for synthetic or incomplete runs, missing/excluded ratings
or fewer than 30 non-tie A/C comparisons. Otherwise the specified 60% preference and
non-decreasing factual accuracy thresholds determine H2 only. A synthetic run never
passes a product gate. H1/H3/H4/H5, minimum real-corpus coverage, per-author transfer,
profile construction quality and overall product acceptance still require the later
real pilot and human decision in WP-EVALUATION-03; no automatic corpus expansion.
