#!/usr/bin/env python3
"""
map_warnings.py

Cross-reference all_warnings.csv dengan ground_truth.csv untuk
mengklasifikasikan setiap warning sebagai TP, FP, atau FN.

Definisi:
  TP (True Positive)  : buggy method yang berhasil dideteksi tool (per unique method)
  FP (False Positive) : warning menunjuk ke method yang bersih
  FN (False Negative) : method buggy yang tidak ada warning-nya

Strategi matching (prioritas berurutan):
  1. Exact match   : project + bug_id + classname + method_name sama persis
  2. Partial match : project + bug_id + method_name sama,
                     classname warning adalah suffix dari classname GT

Output (semua di ~/csv-results/):
  - tp_fp_warnings.csv          : semua warning + label TP/FP per baris
  - fn_warnings.csv             : method buggy tanpa warning
  - summary_per_tool.csv        : TP/FP/FN + Precision/Recall/F1 per tool
  - summary_per_tool_project.csv: TP/FP/FN per tool per project
  - spotbugs_warnings.csv       : warning SpotBugs + label
  - pmd_warnings.csv            : warning PMD + label
  - checkstyle_warnings.csv     : warning Checkstyle + label
  - sonarqube_warnings.csv      : warning SonarQube + label
"""

import os
import csv
from collections import defaultdict

# ── Configuration ─────────────────────────────────────────────────────────────

BASE_DIR         = os.path.expanduser("~")
WARNINGS_CSV     = os.path.join(BASE_DIR, "csv-results", "all_warnings.csv")
GROUND_TRUTH_CSV = os.path.join(BASE_DIR, "ground_truth.csv")
OUTPUT_DIR       = os.path.join(BASE_DIR, "csv-results")

TOOL_CSVS = {
    "spotbugs":   os.path.join(OUTPUT_DIR, "spotbugs_warnings.csv"),
    "pmd":        os.path.join(OUTPUT_DIR, "pmd_warnings.csv"),
    "checkstyle": os.path.join(OUTPUT_DIR, "checkstyle_warnings.csv"),
    "sonarqube":  os.path.join(OUTPUT_DIR, "sonarqube_warnings.csv"),
}

# ── Load Data ─────────────────────────────────────────────────────────────────

def load_csv(filepath):
    if not os.path.isfile(filepath):
        print(f"  [ERROR] File not found: {filepath}")
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(filepath, rows, columns):
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

# ── Ground Truth Index ────────────────────────────────────────────────────────

def build_gt_indexes(gt_rows):
    exact_index   = set()
    partial_index = defaultdict(set)
    gt_per_bug    = defaultdict(set)

    for row in gt_rows:
        project     = row["project"]
        bug_id      = row["bug_id"]
        classname   = row["classname"].strip()
        method_name = row["method_name"].strip()

        exact_index.add((project, bug_id, classname, method_name))
        partial_index[(project, bug_id, method_name)].add(classname)
        gt_per_bug[(project, bug_id)].add((classname, method_name))

    return exact_index, partial_index, gt_per_bug

# ── Matching Logic ────────────────────────────────────────────────────────────

def match_warning(warning, exact_index, partial_index):
    method_name = (warning.get("method_name") or "").strip()

    if not method_name:
        return "FP", "no_method"

    project   = warning["project"]
    bug_id    = warning["bug_id"]
    classname = (warning.get("classname") or "").strip()

    # 1. Exact match
    if (project, bug_id, classname, method_name) in exact_index:
        return "TP", "exact"

    # 2. Partial match
    partial_key = (project, bug_id, method_name)
    if partial_key in partial_index:
        for gt_cls in partial_index[partial_key]:
            if (classname == gt_cls or
                gt_cls.endswith(classname) or
                (classname and gt_cls.endswith("." + classname.split(".")[-1]))):
                return "TP", "partial"

    return "FP", "no_match"


def find_false_negatives(gt_per_bug, tp_covered):
    fn_rows = []
    for (project, bug_id), buggy_methods in sorted(gt_per_bug.items()):
        covered = tp_covered.get((project, bug_id), set())
        for (classname, method_name) in sorted(buggy_methods):
            if (classname, method_name) not in covered:
                fn_rows.append({
                    "project":     project,
                    "bug_id":      bug_id,
                    "classname":   classname,
                    "method_name": method_name,
                    "label":       "FN",
                })
    return fn_rows

# ── Summary Computation ───────────────────────────────────────────────────────

def compute_metrics(tp, fp, fn):
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1        = (2 * precision * recall / (precision + recall)
                 if (precision + recall) > 0 else 0.0)
    return round(precision, 4), round(recall, 4), round(f1, 4)


def is_method_covered(covered_set, classname, method_name):
    """
    Cek apakah (classname, method_name) ter-cover di covered_set.
    Jika covered_set berisi entries dengan classname kosong (""),
    maka cocokkan hanya berdasarkan method_name saja.
    (Terjadi untuk Checkstyle/SonarQube yang tidak punya classname)
    """
    if (classname, method_name) in covered_set:
        return True
    # Fallback: cek apakah method_name ter-cover tanpa classname
    covered_methods_only = {m for (c, m) in covered_set if c == ""}
    if method_name in covered_methods_only:
        return True
    return False


def compute_summary_per_tool(classified, gt_per_bug, tp_covered_per_tool):
    """
    TP per tool = jumlah unique buggy methods yang ter-cover oleh tool tersebut.
    FP per tool = jumlah warning rows yang mengenai method bersih.
    FN per tool = jumlah buggy methods yang TIDAK ter-cover oleh tool tersebut.
    """
    tools   = sorted(set(w["tool"] for w in classified))
    summary = []

    for tool in tools:
        tool_warnings = [w for w in classified if w["tool"] == tool]

        # FP = jumlah warning rows berlabel FP
        fp = sum(1 for w in tool_warnings if w["label"] == "FP")

        # TP = jumlah unique buggy methods yang ter-cover oleh tool ini
        tool_covered = tp_covered_per_tool.get(tool, {})

        # Hitung TP dan FN dengan mempertimbangkan classname kosong
        tp = 0
        fn = 0
        for (project, bug_id), buggy_methods in gt_per_bug.items():
            covered = tool_covered.get((project, bug_id), set())
            for (classname, method_name) in buggy_methods:
                if is_method_covered(covered, classname, method_name):
                    tp += 1
                else:
                    fn += 1

        precision, recall, f1 = compute_metrics(tp, fp, fn)
        summary.append({
            "tool":      tool,
            "TP":        tp,
            "FP":        fp,
            "FN":        fn,
            "precision": precision,
            "recall":    recall,
            "f1_score":  f1,
        })

    return summary


def compute_summary_per_tool_project(classified, gt_per_bug, tp_covered_per_tool):
    """
    TP per tool per project = unique buggy methods di project tersebut yang ter-cover.
    FP per tool per project = warning rows berlabel FP di project tersebut.
    FN per tool per project = buggy methods di project tersebut yang tidak ter-cover.
    """
    # Hitung FP per tool per project dari warning rows
    fp_counts = defaultdict(int)
    for w in classified:
        if w["label"] == "FP":
            fp_counts[(w["tool"], w["project"])] += 1

    summary  = []
    tools    = sorted(set(w["tool"] for w in classified))
    projects = sorted(set(w["project"] for w in classified))

    for tool in tools:
        tool_covered = tp_covered_per_tool.get(tool, {})

        for project in projects:
            fp = fp_counts.get((tool, project), 0)

            # TP = unique buggy methods di project ini yang ter-cover
            tp = 0
            for (proj, bug_id), buggy_methods in gt_per_bug.items():
                if proj != project:
                    continue
                covered = tool_covered.get((proj, bug_id), set())
                for (classname, method_name) in buggy_methods:
                    if is_method_covered(covered, classname, method_name):
                        tp += 1

            # FN = buggy methods di project ini yang tidak ter-cover
            fn = 0
            for (proj, bug_id), buggy_methods in gt_per_bug.items():
                if proj != project:
                    continue
                covered = tool_covered.get((proj, bug_id), set())
                for (classname, method_name) in buggy_methods:
                    if not is_method_covered(covered, classname, method_name):
                        fn += 1

            if tp == 0 and fp == 0:
                continue

            precision, recall, f1 = compute_metrics(tp, fp, fn)
            summary.append({
                "tool":      tool,
                "project":   project,
                "TP":        tp,
                "FP":        fp,
                "FN":        fn,
                "precision": precision,
                "recall":    recall,
                "f1_score":  f1,
            })

    return summary

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("============================================")
    print("  Warning Mapper - TP / FP / FN")
    print("============================================\n")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("[LOAD] Loading warnings ...")
    warnings = load_csv(WARNINGS_CSV)
    print(f"  Total warnings: {len(warnings)}")

    print("[LOAD] Loading ground truth ...")
    gt_rows = load_csv(GROUND_TRUTH_CSV)
    print(f"  Total ground truth entries: {len(gt_rows)}")

    if not warnings or not gt_rows:
        print("[ERROR] Missing input files. Exiting.")
        return

    print("\n[INDEX] Building ground truth indexes ...")
    exact_index, partial_index, gt_per_bug = build_gt_indexes(gt_rows)
    print(f"  Exact index entries  : {len(exact_index)}")
    print(f"  Partial index entries: {len(partial_index)}")
    print(f"  Unique bugs in GT    : {len(gt_per_bug)}")

    print("\n[CLASSIFY] Classifying warnings ...")
    classified          = []
    tp_covered          = defaultdict(set)
    tp_covered_per_tool = defaultdict(lambda: defaultdict(set))
    match_stats         = {"exact": 0, "partial": 0, "no_match": 0, "no_method": 0}

    for w in warnings:
        label, match_type = match_warning(w, exact_index, partial_index)
        row = dict(w)
        row["label"]      = label
        row["match_type"] = match_type
        classified.append(row)
        match_stats[match_type] += 1

        if label == "TP":
            tool          = w["tool"]
            key           = (w["project"], w["bug_id"])
            covered_entry = (
                (w.get("classname") or "").strip(),
                (w.get("method_name") or "").strip()
            )
            tp_covered[key].add(covered_entry)
            tp_covered_per_tool[tool][key].add(covered_entry)

    tp_total = sum(1 for w in classified if w["label"] == "TP")
    fp_total = sum(1 for w in classified if w["label"] == "FP")
    print(f"  TP warnings  : {tp_total:>8}  (warning rows)")
    print(f"  FP warnings  : {fp_total:>8}  (warning rows)")
    print(f"  Match - exact  : {match_stats['exact']:>8}")
    print(f"  Match - partial: {match_stats['partial']:>8}")
    print(f"  No method info : {match_stats['no_method']:>8}")

    print("\n[FN] Finding false negatives ...")
    fn_rows = find_false_negatives(gt_per_bug, tp_covered)
    print(f"  FN: {len(fn_rows)}")

    summary_tool         = compute_summary_per_tool(classified, gt_per_bug, tp_covered_per_tool)
    summary_tool_project = compute_summary_per_tool_project(classified, gt_per_bug, tp_covered_per_tool)

    # Write outputs
    tp_fp_cols = list(warnings[0].keys()) + ["label", "match_type"]
    write_csv(os.path.join(OUTPUT_DIR, "tp_fp_warnings.csv"), classified, tp_fp_cols)
    write_csv(os.path.join(OUTPUT_DIR, "fn_warnings.csv"), fn_rows,
              ["project", "bug_id", "classname", "method_name", "label"])
    write_csv(os.path.join(OUTPUT_DIR, "summary_per_tool.csv"), summary_tool,
              ["tool", "TP", "FP", "FN", "precision", "recall", "f1_score"])
    write_csv(os.path.join(OUTPUT_DIR, "summary_per_tool_project.csv"), summary_tool_project,
              ["tool", "project", "TP", "FP", "FN", "precision", "recall", "f1_score"])

    print("\n[OUTPUT] Writing per-tool labeled CSVs ...")
    tool_rows = defaultdict(list)
    for row in classified:
        tool_rows[row["tool"]].append(row)

    for tool, path in TOOL_CSVS.items():
        rows = tool_rows.get(tool, [])
        if rows:
            cols = list(warnings[0].keys()) + ["label", "match_type"]
            write_csv(path, rows, cols)
            print(f"  {tool}_warnings.csv -> {len(rows):>8} rows")

    print("\n============================================")
    print("  COMPLETED - Summary per Tool")
    print("  (TP = unique buggy methods detected)")
    print("============================================")
    header = f"  {'Tool':<12} {'TP':>6} {'FP':>9} {'FN':>7} {'Precision':>10} {'Recall':>8} {'F1':>8}"
    print(header)
    print(f"  {'─' * 66}")
    for s in summary_tool:
        print(f"  {s['tool']:<12} {s['TP']:>6} {s['FP']:>9} {s['FN']:>7} "
              f"{s['precision']:>10} {s['recall']:>8} {s['f1_score']:>8}")

    print(f"\n  Output folder: {OUTPUT_DIR}")
    print(f"  Files written:")
    print(f"    - tp_fp_warnings.csv          ({len(classified)} rows)")
    print(f"    - fn_warnings.csv             ({len(fn_rows)} rows)")
    print(f"    - summary_per_tool.csv        ({len(summary_tool)} rows)")
    print(f"    - summary_per_tool_project.csv({len(summary_tool_project)} rows)")
    for tool in TOOL_CSVS:
        print(f"    - {tool}_warnings.csv (updated with labels)")
    print("============================================")


if __name__ == "__main__":
    main()