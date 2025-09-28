#!/usr/bin/env python3
"""
tools/eval_compare.py

Compare LLM judge outputs to human labels and produce simple metrics.

It reads `judge_logs` and `human_labels` from `data/agent.db`, joins them on `audit_id`, and computes
precision/recall for approve vs non-approve, confusion matrix, and a short CSV export.

Usage:
  .venv/bin/python tools/eval_compare.py --db data/agent.db --out report.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import sqlite3
import sys
import typing as t

HERE = os.path.abspath(os.path.dirname(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, ".."))
DB_PATH_DEFAULT = os.path.join(REPO_ROOT, "data", "agent.db")


def load_pairs(db_path: str) -> t.List[t.Tuple[int, str, str]]:
    """Load pairs of (audit_id, judge_label, human_label).

    Returns list of tuples. If multiple judge or human labels exist per audit_id, picks the most recent.
    """
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    # get latest judge per audit_id
    cur.execute(
        """
        SELECT jl.audit_id, jl.label, hl.label
        FROM (
            SELECT audit_id, label, max(created_at) as ma FROM judge_logs GROUP BY audit_id
        ) jl
        LEFT JOIN (
            SELECT audit_id, label, max(created_at) as mh FROM human_labels GROUP BY audit_id
        ) hl ON jl.audit_id = hl.audit_id
        WHERE hl.label IS NOT NULL
        """
    )
    rows = cur.fetchall()
    conn.close()
    return [(int(r[0]), r[1], r[2]) for r in rows]


def confusion_matrix(pairs: t.List[t.Tuple[int, str, str]]) -> dict:
    labels = sorted(list({p[1] for p in pairs} | {p[2] for p in pairs}))
    mat = {l: {m: 0 for m in labels} for l in labels}
    for _, judge, human in pairs:
        mat[judge][human] += 1
    return {"labels": labels, "matrix": mat}


def precision_recall(pairs: t.List[t.Tuple[int, str, str]], positive_label: str = "approve") -> dict:
    tp = sum(1 for _, j, h in pairs if j == positive_label and h == positive_label)
    fp = sum(1 for _, j, h in pairs if j == positive_label and h != positive_label)
    fn = sum(1 for _, j, h in pairs if j != positive_label and h == positive_label)
    prec = tp / (tp + fp) if (tp + fp) > 0 else None
    rec = tp / (tp + fn) if (tp + fn) > 0 else None
    return {"tp": tp, "fp": fp, "fn": fn, "precision": prec, "recall": rec}


def write_csv(pairs: t.List[t.Tuple[int, str, str]], out_path: str) -> None:
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["audit_id", "judge_label", "human_label"])

        for aid, j, h in pairs:
            w.writerow([aid, j, h])


def cli() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=DB_PATH_DEFAULT)
    p.add_argument("--out", default=None)
    p.add_argument("--positive", default="approve")
    args = p.parse_args()
    if not os.path.exists(args.db):
        print("DB not found:", args.db)
        sys.exit(2)
    pairs = load_pairs(args.db)
    if not pairs:
        print("No paired judge/human labels found in DB")
        sys.exit(0)
    cm = confusion_matrix(pairs)
    pr = precision_recall(pairs, positive_label=args.positive)
    print("Labels:", cm["labels"])
    print("Confusion matrix:")
    for j in cm["labels"]:
        row = cm["matrix"][j]
        print(j, [row[l] for l in cm["labels"]])
    print("Precision/Recall (positive=%s): %s" % (args.positive, pr))
    if args.out:
        write_csv(pairs, args.out)
        print("Wrote CSV to", args.out)


if __name__ == "__main__":
    cli()
