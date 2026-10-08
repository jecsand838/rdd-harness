# Benchmark protocol

> Authoring template for a measurable NFR. The benchmark implementation and evaluator are developed from this frozen protocol during the planned tests work.

## Requirement and metric

State requirement IDs, metric, unit, threshold, percentile/statistic, and whether every operation class/platform must pass separately.

## Environment

Define OS/architecture, CPU, RAM, storage, runtime/toolchain, build mode, power state, relevant background load, and allowed reference-hardware equivalence. Do not average away a slow required platform.

## Dataset and workload

Define record counts, field-length distribution, status distribution, IDs, deterministic seed, content digest, working-set state, network state, and representative versus maximum-capacity distinction.

## Measurement boundaries

Define precisely when timing starts/stops, warm/cold cache policy, warm-ups, measured samples, concurrency, operation sequence, debouncing, persistence acknowledgment, and UI completion.

## Evaluation

Define percentile/statistic calculation, failure treatment, outlier policy, timeout, minimum sample count, permitted retries, pass/fail output, and raw results format. Do not discard failed samples or repeat until a passing run appears.

## Evidence

Record check IDs, command, exact source revision/digest, dataset digest, environment identity, raw samples, evaluator version, evaluated result, and limitations. Missing required hardware is an environment blocker.
