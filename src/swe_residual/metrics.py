"""Aggregate already selected attempts; unscored instances stay explicit."""

import argparse
import json
from collections import defaultdict
from pathlib import Path


def summarize(records):
    grouped = defaultdict(list)
    seen = set()
    for r in records:
        key = (r["model"], r.get("effort"), r["benchmark"], r["condition"])
        identity = (key, r["instance"])
        if identity in seen:
            raise ValueError(
                "Multiple attempts for one instance; select attempts explicitly"
            )
        seen.add(identity)
        grouped[key].append(r)
    output = []
    for key, rows in sorted(grouped.items(), key=lambda item: str(item[0])):
        valid = [r for r in rows if r.get("reward") in [0, 1]]
        per_task = defaultdict(list)
        for r in valid:
            per_task[r["task"]].append(r["reward"])
        missing = len(rows) - len(valid)
        output.append(
            {
                "model": key[0],
                "effort": key[1],
                "benchmark": key[2],
                "condition": key[3],
                "instances": len(rows),
                "scored": len(valid),
                "unscored": missing,
                "passed": sum(r["reward"] == 1 for r in valid),
                "instance_pass_rate": sum(r["reward"] for r in valid) / len(valid)
                if valid
                else None,
                "task_equal_pass_rate": sum(sum(v) / len(v) for v in per_task.values())
                / len(per_task)
                if per_task and not missing
                else None,
            }
        )
    return output


def load_records(root):
    root = Path(root)
    rows = [json.loads(path.read_text()) for path in sorted(root.rglob("score.json"))]
    summarize(rows)  # Reject duplicate selected attempts before merging with plans.

    def identity(row):
        return (
            row["model"],
            row.get("effort"),
            row["benchmark"],
            row["condition"],
            row["instance"],
        )

    scored = {identity(row): row for row in rows}
    planned = {}
    for path in sorted(root.rglob("selection.json")):
        plan = json.loads(path.read_text())
        for entry in plan["instances"]:
            row = {
                key: plan.get(key)
                for key in ["model", "effort", "benchmark", "condition"]
            }
            row.update(entry, reward=None)
            key = identity(row)
            if key in planned:
                raise ValueError(
                    "Duplicate planned instance; select one attempt explicitly"
                )
            planned[key] = scored.get(key, row)
    if planned:
        if set(scored) - set(planned):
            raise ValueError("Score records do not match the recorded selection")
        return list(planned.values())
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run", type=Path)
    args = p.parse_args()
    rows = load_records(args.run)
    if not rows:
        p.error("No score.json records found")
    print(json.dumps(summarize(rows), indent=2))


if __name__ == "__main__":
    main()
