#!/usr/bin/env python3
"""
compute_metrics.py

Menghitung 5 metrik evaluasi untuk setiap static analysis tool:
  1. Precision    = TP / (TP + FP)
  2. Recall       = TP / (TP + FN)
  3. F1-Score     = 2 * (P * R) / (P + R)
  4. FPR          = FP / (FP + TN)
  5. Execution Time = rata-rata dari 3 run (detik dan format jam:menit:detik)

Input files:
  - ~/csv-results/summary_per_tool.csv   : TP, FP, FN per tool
  - ~/all_methods.csv                    : semua method dari versi buggy
  - ~/ground_truth.csv                   : buggy methods (untuk hitung TN)

TN per tool:
  TN = total unique methods - buggy methods - methods yang dapat FP warning
     = (all_methods - gt_methods) - methods_with_fp_only
  Disederhanakan: TN = total_methods_no_warning - buggy_methods_no_tp

Output:
  - ~/csv-results/metrics_per_tool.csv   : 5 metrik lengkap per tool
  - ~/csv-results/metrics_summary.txt    : ringkasan human-readable
"""

import os
import csv
from collections import defaultdict

# ── Configuration ─────────────────────────────────────────────────────────────

BASE_DIR         = os.path.expanduser("~")
SUMMARY_CSV      = os.path.join(BASE_DIR, "csv-results", "summary_per_tool.csv")
ALL_METHODS_CSV  = os.path.join(BASE_DIR, "all_methods.csv")
GROUND_TRUTH_CSV = os.path.join(BASE_DIR, "ground_truth.csv")
TP_FP_CSV        = os.path.join(BASE_DIR, "csv-results", "tp_fp_warnings.csv")
OUTPUT_DIR       = os.path.join(BASE_DIR, "csv-results")

# ── Execution Time dari log (detik) ───────────────────────────────────────────
# Diambil langsung dari timing_summary files yang sudah diupload
EXECUTION_TIMES = {
    "spotbugs":   {"run1": 5868,  "run2": 6420,  "run3": 5629},
    "pmd":        {"run1": 3316,  "run2": 3307,  "run3": 3314},
    "checkstyle": {"run1": 6696,  "run2": 6671,  "run3": 6648},
    "sonarqube":  {"run1": 44937, "run2": 35778, "run3": 33524},
}

# ── Helpers ───────────────────────────────────────────────────────────────────

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


def seconds_to_hms(seconds):
    """Konversi detik ke format jam:menit:detik."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h}h {m:02d}m {s:02d}s"


def compute_execution_time(tool):
    """Hitung rata-rata execution time dari 3 run."""
    times = EXECUTION_TIMES.get(tool)
    if not times:
        return None, None
    avg_sec = sum(times.values()) / len(times)
    return avg_sec, seconds_to_hms(avg_sec)


def compute_metrics(tp, fp, fn, tn):
    """Hitung semua 5 metrik."""
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1        = (2 * precision * recall / (precision + recall)
                 if (precision + recall) > 0 else 0.0)
    fpr       = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    return (
        round(precision, 4),
        round(recall, 4),
        round(f1, 4),
        round(fpr, 4),
    )

# ── TN Computation ────────────────────────────────────────────────────────────

def compute_tn_per_tool(all_methods, ground_truth, tp_fp_warnings):
    """
    Hitung TN per tool.

    all_methods tidak punya bug_id (satu representasi per project).
    Matching dilakukan di level (project, classname, method_name).

    TN = method yang:
      1. Ada di all_methods (exist di codebase, bukan test)
      2. TIDAK ada di ground truth (bukan buggy method)
      3. TIDAK mendapat warning dari tool tersebut

    Pendekatan:
      - Buat set (project, classname, method_name) dari all_methods
      - Buat set buggy methods dari ground_truth (tanpa bug_id)
      - Untuk setiap tool, buat set methods yang mendapat warning
      - TN = clean_methods - warned_clean_methods_by_tool
    """

    print("\n[TN] Building method sets ...")

    # Set semua method di codebase: (project, classname, method_name)
    # all_methods tidak punya bug_id — satu representasi per project
    all_method_keys = set()
    for row in all_methods:
        key = (row["project"],
               row["classname"].strip(),
               row["method_name"].strip())
        all_method_keys.add(key)
    print(f"  Total unique methods in codebase: {len(all_method_keys)}")

    # Set buggy methods dari ground truth (tanpa bug_id untuk matching)
    buggy_method_keys = set()
    for row in ground_truth:
        key = (row["project"],
               row["classname"].strip(),
               row["method_name"].strip())
        buggy_method_keys.add(key)
    print(f"  Total buggy method signatures (GT): {len(buggy_method_keys)}")

    # Clean methods = all_methods - buggy_methods
    clean_method_keys = all_method_keys - buggy_method_keys
    print(f"  Total clean methods: {len(clean_method_keys)}")

    # Helper: normalisasi file path ke bentuk relative dari package root
    # Menangani format path yang berbeda antara all_methods.csv dan tp_fp_warnings.csv:
    #   all_methods    : org/jfree/chart/ChartFactory.java  (sudah relative)
    #   checkstyle     : /home/user/.../source/org/jfree/chart/ChartFactory.java (absolute)
    #   sonarqube      : src/main/java/org/apache/... (relative dengan prefix)
    SRC_PREFIXES = ["source/", "src/main/java/", "src/java/", "src/"]

    def normalize_path(path):
        p = path.replace("\\", "/").strip()
        # Strip absolute path: cari src prefix di dalam path dan ambil dari situ
        for prefix in SRC_PREFIXES:
            idx = p.find("/" + prefix)
            if idx != -1:
                return p[idx + 1 + len(prefix):]
            if p.startswith(prefix):
                return p[len(prefix):]
        return p

    # Build index: (project, normalized_file_path) -> set of (classname, method_name)
    # Normalisasi path di sisi all_methods agar konsisten dengan warning paths
    # Digunakan oleh Checkstyle/SonarQube untuk file-level matching
    file_to_methods = defaultdict(set)
    basename_to_methods = defaultdict(set)  # fallback: (project, basename) -> methods
    for row in all_methods:
        norm_path  = normalize_path(row["file_path"].strip())
        file_key   = (row["project"], norm_path)
        base_key   = (row["project"], os.path.basename(norm_path))
        method_key = (row["classname"].strip(), row["method_name"].strip())
        file_to_methods[file_key].add(method_key)
        basename_to_methods[base_key].add(method_key)

    # Untuk setiap tool, hitung clean methods yang mendapat warning
    tools = sorted(set(r["tool"] for r in tp_fp_warnings))
    warned_clean_per_tool = defaultdict(set)

    # Tools dengan method_name: match per (project, classname, method_name)
    TOOLS_WITH_METHOD = {"spotbugs", "pmd", "checkstyle", "sonarqube"}
    # Tools tanpa method_name: match per (project, file_path) →
    # semua method dalam file yang di-flag dianggap warned

    print("  Building warned-method sets per tool ...")
    for row in tp_fp_warnings:
        tool    = row["tool"]
        project = row["project"]

        if tool in TOOLS_WITH_METHOD:
            # Match per method: (project, classname, method_name)
            method_name = (row.get("method_name") or "").strip()
            classname   = (row.get("classname") or "").strip()
            if not method_name:
                continue
            key = (project, classname, method_name)
            if key in clean_method_keys:
                warned_clean_per_tool[tool].add(key)

        elif tool in TOOLS_FILE_LEVEL:
            # Match per file: semua method dalam file yang di-flag → warned
            # Normalisasi kedua sisi path sebelum matching
            raw_path = (row.get("file_path") or "").strip()
            if not raw_path:
                continue

            norm_path = normalize_path(raw_path)
            base_path = os.path.basename(norm_path)

            # Coba 3 variasi path: normalized, raw (stripped), lalu basename
            matched = False
            for fp_variant, index in [
                (norm_path, file_to_methods),
                (raw_path.lstrip("/"), file_to_methods),
                (base_path, basename_to_methods),
            ]:
                file_key = (project, fp_variant)
                if file_key in index:
                    for (classname, method_name) in index[file_key]:
                        method_key = (project, classname, method_name)
                        if method_key in clean_method_keys:
                            warned_clean_per_tool[tool].add(method_key)
                    matched = True
                    break

    # TN per tool = clean methods yang TIDAK mendapat warning dari tool tersebut
    tn_per_tool = {}
    for tool in tools:
        warned = warned_clean_per_tool.get(tool, set())
        tn     = len(clean_method_keys) - len(warned)
        tn_per_tool[tool] = tn
        print(f"  TN {tool:<12}: {tn:>10} "
              f"(clean={len(clean_method_keys)}, warned_clean={len(warned)})")

    return tn_per_tool

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("============================================")
    print("  Metrics Computation - 5 Metrics per Tool")
    print("============================================\n")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Load data
    print("[LOAD] Loading data ...")
    summary      = load_csv(SUMMARY_CSV)
    all_methods  = load_csv(ALL_METHODS_CSV)
    ground_truth = load_csv(GROUND_TRUTH_CSV)
    tp_fp        = load_csv(TP_FP_CSV)

    if not summary or not all_methods or not ground_truth or not tp_fp:
        print("[ERROR] One or more input files missing. Exiting.")
        return

    print(f"  Summary rows      : {len(summary)}")
    print(f"  All methods       : {len(all_methods)}")
    print(f"  Ground truth      : {len(ground_truth)}")
    print(f"  TP/FP warnings    : {len(tp_fp)}")

    # Hitung TN per tool
    tn_per_tool = compute_tn_per_tool(all_methods, ground_truth, tp_fp)

    # Hitung 5 metrics per tool
    print("\n[METRICS] Computing 5 metrics per tool ...")
    results = []

    for row in summary:
        tool = row["tool"]
        tp   = int(row["TP"])
        fp   = int(row["FP"])
        fn   = int(row["FN"])
        tn   = tn_per_tool.get(tool, 0)

        precision, recall, f1, fpr = compute_metrics(tp, fp, fn, tn)
        avg_sec, avg_hms           = compute_execution_time(tool)

        results.append({
            "tool":           tool,
            "TP":             tp,
            "FP":             fp,
            "FN":             fn,
            "TN":             tn,
            "precision":      precision,
            "recall":         recall,
            "f1_score":       f1,
            "fpr":            fpr,
            "exec_time_sec":  round(avg_sec, 1) if avg_sec else "N/A",
            "exec_time_hms":  avg_hms if avg_hms else "N/A",
        })

    # Tulis CSV
    out_csv = os.path.join(OUTPUT_DIR, "metrics_per_tool.csv")
    write_csv(out_csv, results, [
        "tool", "TP", "FP", "FN", "TN",
        "precision", "recall", "f1_score", "fpr",
        "exec_time_sec", "exec_time_hms"
    ])

    # Tulis ringkasan txt
    out_txt = os.path.join(OUTPUT_DIR, "metrics_summary.txt")
    lines = []
    lines.append("=" * 72)
    lines.append("  METRICS SUMMARY - Static Analysis Tools on Defects4J")
    lines.append("=" * 72)
    lines.append(f"  {'Tool':<12} {'TP':>6} {'FP':>9} {'FN':>6} {'TN':>10} "
                 f"{'Prec':>7} {'Recall':>7} {'F1':>7} {'FPR':>7} {'Avg Time'}")
    lines.append("  " + "─" * 70)
    for r in results:
        lines.append(
            f"  {r['tool']:<12} {r['TP']:>6} {r['FP']:>9} {r['FN']:>6} "
            f"{r['TN']:>10} {r['precision']:>7} {r['recall']:>7} "
            f"{r['f1_score']:>7} {r['fpr']:>7} {r['exec_time_hms']}"
        )
    lines.append("=" * 72)
    lines.append("\nNotes:")
    lines.append("  - Precision = TP / (TP + FP)")
    lines.append("  - Recall    = TP / (TP + FN)")
    lines.append("  - F1-Score  = 2 * (Precision * Recall) / (Precision + Recall)")
    lines.append("  - FPR       = FP / (FP + TN)")
    lines.append("  - Exec Time = average of 3 runs")
    lines.append("  - Checkstyle/SonarQube: no method-level info → Precision/Recall/F1 = 0")
    lines.append("  - TN computed from all methods in buggy versions minus buggy methods")
    lines.append("    minus methods that received warnings from that tool")

    with open(out_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    # Print hasil
    print("\n============================================")
    print("  COMPLETED - 5 Metrics per Tool")
    print("============================================")
    header = (f"  {'Tool':<12} {'TP':>6} {'FP':>9} {'FN':>6} {'TN':>10} "
              f"{'Prec':>7} {'Recall':>7} {'F1':>7} {'FPR':>7} Avg Time")
    print(header)
    print("  " + "─" * 72)
    for r in results:
        print(f"  {r['tool']:<12} {r['TP']:>6} {r['FP']:>9} {r['FN']:>6} "
              f"{r['TN']:>10} {r['precision']:>7} {r['recall']:>7} "
              f"{r['f1_score']:>7} {r['fpr']:>7} {r['exec_time_hms']}")

    print(f"\n  Output files:")
    print(f"    - {out_csv}")
    print(f"    - {out_txt}")
    print("============================================")


if __name__ == "__main__":
    main()