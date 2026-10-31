#!/usr/bin/env python3
"""Run the gold question set through retrieval and report pass/fail per question (Doc/step-9-requirements.md Q-1).

  scripts/run_gold_set.py                         # real index, config/gold_questions.yaml
  scripts/run_gold_set.py --demo                  # synthetic dataset, config/gold_questions.example.yaml
  scripts/run_gold_set.py --set relevance_min_hits=2          # what would a settings change break? (nothing is written)
  scripts/run_gold_set.py --query-config scratch.yaml         # same, with a scratch config file
  scripts/run_gold_set.py --save-baseline        # remember this run; later runs report regressions against it

Read-only: it reads the index and calls the embedding model; it writes only the report file (logs/gold_report.json),
and only with --save-report/--save-baseline. Exit status: 0 all pass (and no regression), 1 otherwise, 2 usage error."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from console import gold  # noqa: E402
from console.config import ConsoleConfig  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(ROOT / "config" / "console_config.yaml"), help="console config (default config/console_config.yaml, else the example)")
    ap.add_argument("--demo", action="store_true", help="use the synthetic demo dataset")
    ap.add_argument("--questions", help="question file (default config/gold_questions.yaml; with --demo the .example.yaml)")
    ap.add_argument("--query-config", help="query config to use instead of config/query_config.yaml (e.g. a scratch copy)")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="override one query setting for this run")
    ap.add_argument("--json", dest="as_json", action="store_true", help="print the report as JSON")
    ap.add_argument("--baseline", help="report file to compare with (default logs/gold_baseline.json when it exists)")
    ap.add_argument("--save-report", action="store_true", help="write logs/gold_report.json (the console shows it)")
    ap.add_argument("--save-baseline", action="store_true", help="also save this run as logs/gold_baseline.json")
    a = ap.parse_args(argv)

    cfg_path = Path(a.config)
    if not cfg_path.exists():
        cfg_path = ROOT / "config" / "console_config.example.yaml"
    cfg = ConsoleConfig.load(cfg_path, demo=a.demo)
    qpath = Path(a.questions) if a.questions else ROOT / "config" / ("gold_questions.example.yaml" if a.demo else "gold_questions.yaml")
    if not qpath.exists():
        print(f"no question file at {qpath}. Copy config/gold_questions.example.yaml to config/gold_questions.yaml and put your own questions in it.", file=sys.stderr)
        return 2
    try:
        questions = gold.load_questions(qpath)
    except ValueError as e:
        print(f"{qpath}: {e}", file=sys.stderr)
        return 2

    from console.explorer import build_query_config
    if a.query_config:
        cfg.query_config = Path(a.query_config)
    qcfg = build_query_config(cfg)
    for item in a.set:
        key, _, value = item.partition("=")
        if not hasattr(qcfg, key):
            print(f"unknown query setting {key!r}", file=sys.stderr)
            return 2
        old = getattr(qcfg, key)
        setattr(qcfg, key, type(old)(value) if not isinstance(old, bool) else value.lower() in ("1", "true", "yes"))

    embed = None
    if cfg.demo:
        from console.demo_embed import embed_batch as embed
    report = gold.run(questions, qcfg, embed=embed)
    report["questions_file"] = str(qpath)
    report["overrides"] = a.set

    base_path = Path(a.baseline) if a.baseline else cfg.logs_dir / "gold_baseline.json"
    diff = None
    if base_path.exists():
        diff = gold.compare(report, json.loads(base_path.read_text()))
        report["compared_with"] = {"file": str(base_path), **diff}

    if a.save_report or a.save_baseline:
        cfg.logs_dir.mkdir(parents=True, exist_ok=True)
        (cfg.logs_dir / gold.REPORT_NAME).write_text(json.dumps(report, indent=1) + "\n")
    if a.save_baseline:
        (cfg.logs_dir / "gold_baseline.json").write_text(json.dumps(report, indent=1) + "\n")

    if a.as_json:
        print(json.dumps(report, indent=1))
    else:
        s = report["settings"]
        print(f"Gold set: {report['passed']}/{report['total']} passed in {report['seconds']} s "
              f"(distance_threshold={s['distance_threshold']}, min_hits={s['min_hits']}, top_k_fused={s['top_k_fused']})")
        for r in report["results"]:
            mark = "PASS" if r["passed"] else "FAIL"
            why = "" if r["passed"] else "  <- " + "; ".join(r["problems"])
            print(f"  [{mark}] {r['id']:<6} {r['question'][:60]:<60} {r['verdict']:<11} hits={r['hits']} rank={r['first_expected_rank']}{why}")
        if diff:
            print(f"Compared with {base_path.name}: regressions {diff['regressions'] or 'none'}; newly passing {diff['fixed'] or 'none'}; new {diff['new'] or 'none'}")
    return 0 if report["failed"] == 0 and not (diff and diff["regressions"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
