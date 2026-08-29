# Mandate Step-up Recovery Agent

Buildathon prototype for detecting failed recurring-payment revenue, diagnosing the failure, and executing a bounded recovery workflow.

This repository does **not** patch Razorpay or reproduce bank-side failures through Razorpay test mode. Failure events are synthetic. Any future Razorpay test-mode integration will demonstrate supported API plumbing only.

## Current status

Checkpoint 1 implements a deterministic synthetic failed-payment generator:

- 100–300 labeled records per batch;
- configurable category distribution;
- integer-paise monetary values;
- card and UPI rails modeled separately;
- ground-truth labels kept separate from runtime-visible fields;
- schema and business-invariant validation;
- reproducible output from a fixed seed.

Checkpoint 2 adds a deterministic root-cause classifier:

- named, ordered rules rather than model scoring;
- structured evidence and a human-readable reason for every prediction;
- runtime-only inputs with evaluation labels stripped first;
- per-category accuracy, confusion matrix, and full mismatch reporting.

Checkpoint 3 adds the bounded recovery agent and paired baseline comparison:

- a fixed seven-tool registry with schema validation;
- category- and state-specific tool permissions;
- hard same-mandate, RuPay, retry-cap, recovery-window, and payment-evidence checks;
- provider-neutral clients for Groq, Ollama, and deterministic simulation/replay;
- compliant agent flow versus an intentionally broken new-mandate baseline;
- paired seeded outcomes, so both strategies face the same latent customer response.

## Generate the checkpoint dataset

Python 3.11 or newer is recommended. Checkpoint 1 uses only the Python standard library.

```bash
python scripts/generate_dataset.py --seed 42 --count 200
```

The command writes a JSONL dataset and prints an inspection summary. To choose a path:

```bash
python scripts/generate_dataset.py --seed 42 --count 200 --output data/generated/my_batch.jsonl
```

## Run tests

```bash
python -m unittest discover -s tests -v
```

## Classify the generated batch

```bash
python scripts/classify_batch.py --run-id checkpoint-2
```

Inspect the resulting files under `data/runs/checkpoint-2/`:

- `classified_transactions.jsonl` contains the runtime transaction, prediction, rule ID, evidence, and evaluation result;
- `classification_metrics.json` contains overall/per-category accuracy, a confusion matrix, and every mismatch.

## Compare compliant and naive recovery flows

The reproducible offline comparison uses the explicitly labeled scripted provider:

```bash
python scripts/compare_flows.py --run-id checkpoint-3 --seed 42 --provider scripted
```

With a Groq free-tier key in `GROQ_API_KEY`, the same bounded agent can use live model tool selection:

```bash
python scripts/compare_flows.py --run-id checkpoint-3-groq --seed 42 --provider groq
```

Use `--provider ollama` for the configured local Ollama endpoint. Provider selection changes who chooses among permitted tools; it does not change tool capabilities or enforcement.

Checkpoint-3 artifacts are written under `data/runs/<run-id>/`:

- `agent_traces.jsonl` — context, tools offered, decision summary, selected tool, validation, and result;
- `compliant_results.jsonl` and `naive_results.jsonl` — paired transaction outcomes;
- `comparison_metrics.json` — recovery count/rate, recovered paise, time, and delta.

All recovery outcomes and headline numbers in this prototype are generated from documented synthetic probabilities. They are demonstration measurements, not claims about production recovery performance.

## Evaluation-label boundary

Each stored synthetic record contains answer-key fields such as `failure_category`, `correct_action`, and `ground_truth_recoverable`. They exist only to evaluate later checkpoints. `SyntheticTransaction.to_runtime_dict()` strips these fields before classification or orchestration.

The classifier and recovery agent must infer their decisions from observable fields such as amount, mandate ceiling, payment rail, card network, decline code, and prior attempts. Reading the answer-key fields at runtime would be label leakage and would invalidate the evaluation.

See [Checkpoint 1 assumptions](docs/assumptions.md) for the schema decisions made from the brief.
