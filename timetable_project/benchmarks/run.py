"""Run all registered benchmark adapters on one parsed instance."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Sequence

from algorithms import CpSatAlgorithm, CspAlgorithm, RunConfig
from parser import parse_instance, validate_instance
from benchmarks.synthetic import (
    make_synthetic_instance,
    make_synthetic_objective_instance,
)


def _format_table(results: list[dict]) -> str:
    headers = ("Algorithm", "Status", "Runtime (s)", "Coverage", "Validated")
    rows = [
        (
            result["algorithm"],
            result["status"],
            f'{result["runtime_s"]:.3f}',
            f'{result["assignment_coverage"]:.1%}',
            "yes" if result["successful"] else "no",
        )
        for result in results
    ]
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(len(headers))
    ]
    header = " | ".join(
        value.ljust(widths[index]) for index, value in enumerate(headers)
    )
    separator = "-+-".join("-" * width for width in widths)
    body = [
        " | ".join(value.ljust(widths[index]) for index, value in enumerate(row))
        for row in rows
    ]
    return "\n".join([header, separator, *body])


def run_benchmark(
    instance_path: Path | None,
    config: RunConfig,
    output_path: Path,
    *,
    synthetic_objective: bool = False,
) -> dict:
    instance = (
        (
            make_synthetic_objective_instance()
            if synthetic_objective
            else make_synthetic_instance()
        )
        if instance_path is None
        else parse_instance(instance_path)
    )
    validate_instance(instance)
    results = [
        algorithm.run(instance, config)
        for algorithm in (CspAlgorithm(), CpSatAlgorithm())
    ]
    payload = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "instance": {
            "name": instance.name,
            "path": (
                "synthetic:positive-objective"
                if synthetic_objective
                else "synthetic:feasible"
            ) if instance_path is None else str(instance_path),
            "synthetic": instance_path is None,
            "classes": len(instance.classes),
            "rooms": len(instance.rooms),
            "courses": len(instance.courses),
            "students": len(instance.students),
        },
        "shared_configuration": {
            "time_limit_s": config.time_limit_s,
            "node_limit": config.node_limit,
            "random_seed": config.random_seed,
            "workers": config.workers,
        },
        "comparison_scope": (
            "Comparable only if both adapters modeled every required constraint "
            "and both independent validation reports have complete coverage."
        ),
        "results": [result.to_dict() for result in results],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f'Instance: {instance.name} ({len(instance.classes)} classes)')
    print(_format_table(payload["results"]))
    print(f"Raw results: {output_path}")
    for result in payload["results"]:
        if result["error"]:
            print(f'{result["algorithm"]}: {result["error"]}')
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare the CSP and OR-Tools CP-SAT scheduling adapters."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--instance", type=Path)
    source.add_argument(
        "--synthetic",
        action="store_true",
        help="benchmark a tiny, explicitly synthetic feasible instance",
    )
    source.add_argument(
        "--synthetic-objective",
        action="store_true",
        help="benchmark a tiny feasible instance with a known positive soft cost",
    )
    parser.add_argument("--time-limit", type=float, default=60.0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.time_limit < 0:
        parser.error("--time-limit must be non-negative")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_path = args.output or Path("results") / f"benchmark-{stamp}.json"
    config = RunConfig(
        time_limit_s=args.time_limit,
        random_seed=args.seed,
        workers=args.workers,
    )
    run_benchmark(
        None if args.synthetic else args.instance,
        config,
        output_path,
        synthetic_objective=args.synthetic_objective,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
