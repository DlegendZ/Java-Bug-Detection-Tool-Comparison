# Java-Bug-Detection-Tool-Comparison

A research project that evaluates four Java static analysis tools — **SpotBugs**, **PMD**, **Checkstyle**, and **SonarQube** — on the [Defects4J](https://github.com/rjust/defects4j) benchmark dataset using five statistical metrics.

---

## What This Project Does

This project runs four tools on real Java bugs from Defects4J, then measures how good each tool is at finding those bugs. Five metrics are computed: **Precision**, **Recall**, **F1-Score**, **FPR**, and **Execution Time**. The results are compiled into a Weighted Decision Matrix to rank the tools.

---

## Project Status

| Step | Task                                      | Status  |
| ---- | ----------------------------------------- | ------- |
| 1    | Run all 4 tools on Defects4J (3x each)    | ✅ Done |
| 2    | Parse XML/JSON outputs into CSV           | ✅ Done |
| 3    | Extract ground truth from Defects4J       | ✅ Done |
| 4    | Enrich warnings with method names         | ✅ Done |
| 5    | Map warnings → TP / FP / FN               | ✅ Done |
| 6    | Enumerate all methods for TN              | ✅ Done |
| 7    | Compute 5 metrics per tool                | ✅ Done |
| 8    | Weighted Decision Matrix + visualizations | ✅ Done |

---

## Files Overview

### Python Scripts

| File                      | What it does                                                                                                                                                  |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `parse_warnings.py`       | Reads XML/JSON outputs from all 4 tools and combines them into `all_warnings.csv`                                                                             |
| `extract_ground_truth.py` | Reads Defects4J patches to find which methods are actually buggy → `ground_truth.csv`                                                                         |
| `enrich_method_names.py`  | Checkstyle and SonarQube don't include method names — this script scans the Java source files to fill them in. Run this on `all_warnings.csv` before mapping. |
| `map_warnings.py`         | Compares each warning against ground truth and labels it TP, FP, or FN → `summary_per_tool.csv`                                                               |
| `enumerate_methods.py`    | Collects all unique methods from all buggy project versions → `all_methods.csv` (used to compute TN)                                                          |
| `compute_metrics.py`      | Uses all the CSVs above to compute Precision, Recall, F1, FPR, Execution Time → `metrics_per_tool.csv`                                                        |

### Bash Scripts

| File                 | What it does                                                        |
| -------------------- | ------------------------------------------------------------------- |
| `run_all_tools.sh`   | Master script — runs all 4 tools 3 times each and saves timing logs |
| `run_spotbugs.sh`    | Runs SpotBugs on all Defects4J projects                             |
| `run_pmd.sh`         | Runs PMD on all Defects4J projects                                  |
| `run_checkstyle.sh`  | Runs Checkstyle on all Defects4J projects                           |
| `run_sonarqube.sh`   | Runs SonarQube on all Defects4J projects                            |
| `start_sonarqube.sh` | Starts the SonarQube server (must run before `run_sonarqube.sh`)    |

### csv-results/ folder

| File                           | What it contains                                                           |
| ------------------------------ | -------------------------------------------------------------------------- |
| `all_methods.csv`              | All unique methods extracted from all buggy project versions (used for TN) |
| `ground_truth.csv`             | 640 confirmed buggy methods across 384 bugs                                |
| `fn_warnings.csv`              | Buggy methods that no tool detected (False Negatives)                      |
| `summary_per_tool.csv`         | TP / FP / FN count per tool                                                |
| `summary_per_tool_project.csv` | TP / FP / FN per tool per project (Chart, Closure, Lang, Math, Time)       |
| `metrics_per_tool.csv`         | Final 5 metrics per tool                                                   |
| `metrics_summary.txt`          | Human-readable summary of all metrics                                      |

### analysis-logs/ folder

Contains timing logs from the 3-run benchmark for each tool:

- `SpotBugs_run1/2/3_....log`
- `PMD_run1/2/3_....log`
- `Checkstyle_run1/2/3_....log`
- `SonarQube_run1/2/3_....log`
- `timing_summary_sb_pmd_cs.txt` — average execution times for SpotBugs, PMD, Checkstyle
- `timing_summary_sonarqube.txt` — average execution time for SonarQube

---

## How to Run (Full Pipeline)

> **Requirements:** Ubuntu or WSL, Java 11, Java 17, Perl, Defects4J installed at `~/defects4j/`
> All Defects4J projects must be checked out at `~/defects4j-projects/` with naming: `{Project}_{BugID}_buggy/`

### 1. Run all tools

```bash
bash start_sonarqube.sh        # Start SonarQube server first
bash run_all_tools.sh          # Runs all 4 tools 3x each (~several days)
```

### 2. Parse tool outputs

```bash
python3 parse_warnings.py
```

Produces `csv-results/all_warnings.csv`

### 3. Extract ground truth

```bash
python3 extract_ground_truth.py
```

Produces `ground_truth.csv`

### 4. Enrich method names (Checkstyle + SonarQube)

```bash
# Back up first!
cp ~/csv-results/all_warnings.csv ~/csv-results/all_warnings_backup.csv

python3 enrich_method_names.py
```

> ⚠️ This takes ~30–60 minutes (processes 12.6 million warnings)

### 5. Map warnings to ground truth

```bash
python3 map_warnings.py
```

Produces `csv-results/summary_per_tool.csv` and `csv-results/tp_fp_warnings.csv`

### 6. Enumerate all methods

```bash
python3 enumerate_methods.py
```

Produces `csv-results/all_methods.csv`

> ⚠️ This also takes a while (processes all 393 bug versions)

### 7. Compute final metrics

```bash
python3 compute_metrics.py
```

> ⚠️ Before running, open `compute_metrics.py` and update `EXECUTION_TIMES` with the actual timing values from `analysis-logs/timing_summary_*.txt`

Produces `csv-results/metrics_per_tool.csv` and `csv-results/metrics_summary.txt`

---

## Final Results

| Tool       | Precision | Recall | F1     | FPR    | Avg Time |
| ---------- | --------- | ------ | ------ | ------ | -------- |
| SpotBugs   | 0.0003    | 0.0781 | 0.0006 | 0.8284 | 1h 39m   |
| PMD        | 0.0004    | 0.2969 | 0.0007 | 0.9467 | 0h 55m   |
| Checkstyle | 0.0000    | 0.8438 | 0.0001 | 0.9969 | 1h 51m   |
| SonarQube  | 0.0005    | 0.6344 | 0.0009 | 0.9621 | 10h 34m  |

### Weighted Decision Matrix Ranking

Weights: Precision 0.30, Recall 0.30, F1-Score 0.20, FPR 0.15, Exec Time 0.05

| Rank   | Tool       | Composite Score |
| ------ | ---------- | --------------- |
| 🥇 1st | SonarQube  | 0.749           |
| 🥈 2nd | PMD        | 0.570           |
| 🥉 3rd | SpotBugs   | 0.501           |
| 4th    | Checkstyle | 0.345           |

---

## Important Notes

**Why does Checkstyle have high Recall (0.84)?**
Checkstyle is a style checker — it flags almost every line of code for formatting issues. Because it produces so many warnings (11 million), it incidentally overlaps with many buggy methods. This high Recall is not because Checkstyle is good at detecting bugs — it's because it flags almost everything. Its Precision (0.0000) and FPR (0.9969) confirm this.

**Why is Checkstyle/SonarQube Precision so low?**
Both tools are not designed purely for bug detection. They also flag code smells, style violations, and security issues. Running them with default settings produces a huge number of warnings, most of which are not actual bugs.

**What files are too large to push to GitHub?**
These files are large and can be regenerated by running the pipeline:

- `all_warnings.csv` (~2 GB)
- `tp_fp_warnings.csv` (~2 GB)
- `checkstyle_warnings.csv` (~1.9 GB)
- `pmd_warnings.csv` (~115 MB)
- `sonarqube_warnings.csv` (~130 MB)
- `spotbugs_warnings.csv` (~24 MB)
- `spotbugs-results/`, `pmd-results/`, `checkstyle-results/`, `sonarqube-results/` folders

---

## Authors

Bina Nusantara University — Computer Science Department

- Andrew Frederick Iskandar (Student)
- Raynald Arvan Lim (Student)
- Yohannes Adrian (Student)
- Andry Chowanda (Lecturer)
- Anderies (Lecturer)
