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

## Evaluation-label boundary

Each stored synthetic record contains answer-key fields such as `failure_category`, `correct_action`, and `ground_truth_recoverable`. They exist only to evaluate later checkpoints. `SyntheticTransaction.to_runtime_dict()` strips these fields before classification or orchestration.

The classifier and recovery agent must infer their decisions from observable fields such as amount, mandate ceiling, payment rail, card network, decline code, and prior attempts. Reading the answer-key fields at runtime would be label leakage and would invalidate the evaluation.

See [Checkpoint 1 assumptions](docs/assumptions.md) for the schema decisions made from the brief.
