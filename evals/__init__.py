"""Evaluation harness (SPEC-09): does memory make Recon's suggestions better over time?

    python -m evals.run --conditions on,off --seed 42     # runs, then writes the report
    python -m evals.report evals/results/<run_id>         # re-scores saved results

`harness` replays the dataset through the real pipeline and records every
suggestion; `metrics` scores the records against the ground truth (pure, no
I/O); `report` writes metrics.json, learning_curve.json, the chart and report.md.
"""
