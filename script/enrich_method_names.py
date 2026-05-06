#!/usr/bin/env python3
"""
enrich_method_names.py

Memperkaya warning Checkstyle dan SonarQube dengan method_name
menggunakan scan ke atas dari line_number di file Java sumber.

Pendekatan STREAMING (tidak load semua rows ke memory):
  - Baca input CSV baris per baris
  - Proses dan langsung tulis ke file temp
  - Rename temp file ke output file saat selesai
  - File cache (filepath -> lines) tetap di memory karena hanya ~2000 file unik

Optimasi:
  - File Java di-cache in memory (baca max 1x per file)
  - Progress print setiap 100,000 baris
  - Memory footprint: hanya file cache + 1 baris CSV aktif
"""

import os
import csv
import re
import tempfile
import shutil

# ── Configuration ─────────────────────────────────────────────────────────────

BASE_DIR   = os.path.expanduser("~")
INPUT_CSV  = os.path.join(BASE_DIR, "csv-results", "all_warnings.csv")
OUTPUT_CSV = INPUT_CSV   # overwrite in-place via temp file

MAX_SCAN   = 300
PROGRESS_N = 100_000

TOOLS_TO_ENRICH = {"checkstyle", "sonarqube"}

# ── Regex Patterns (copy exact dari extract_ground_truth.py) ──────────────────

THROW_SKIP_RE = re.compile(r'^\s*(?:throw\s+new|throw\b|return\b)')

FLOW_SKIP_RE = re.compile(
    r'^\s*(?:if|else(?:\s+if)?|while|for|do|switch|catch|finally)\s*[\(\{]?'
)

REGULAR_METHOD_RE = re.compile(
    r'^\s*'
    r'(?:public|private|protected)'
    r'(?:\s+(?:static|final|synchronized|abstract|native|default|strictfp))*'
    r'\s+[\w<>\[\],?]+\s+'
    r'(\w+)'
    r'\s*\('
)

CONSTRUCTOR_RE = re.compile(
    r'^\s*'
    r'(?:public|private|protected)\s+'
    r'([A-Z]\w*)'
    r'\s*\('
)

PACKAGE_PRIVATE_RE = re.compile(
    r'^\s*'
    r'(?:(?:static|final|synchronized|abstract|native|strictfp)\s+)+'
    r'[\w<>\[\],?\s]+?\s+'
    r'(\w+)'
    r'\s*\('
)

BARE_METHOD_RETURN_TYPES = (
    'void', 'boolean', 'int', 'long', 'double', 'float',
    'char', 'byte', 'short', 'String', 'Node', 'List',
    'Map', 'Set', 'Collection', 'Iterator', 'Object',
)

BARE_METHOD_RE = re.compile(
    r'^\s{1,2}'
    r'(?:' + '|'.join(BARE_METHOD_RETURN_TYPES) + r'|[\w<>\[\]]+)'
    r'\s+'
    r'(\w+)'
    r'\s*\('
)

JAVA_KEYWORDS = {
    'if', 'else', 'for', 'while', 'do', 'switch', 'case', 'try', 'catch',
    'finally', 'return', 'new', 'import', 'package', 'throws', 'throw',
    'super', 'this', 'instanceof', 'class', 'interface', 'enum',
    'void', 'boolean', 'int', 'long', 'double', 'float', 'char', 'byte', 'short',
}

# ── Method Extractor ──────────────────────────────────────────────────────────

def extract_method_name(line):
    stripped = line.strip()
    if THROW_SKIP_RE.match(stripped):
        return None
    if FLOW_SKIP_RE.match(stripped):
        return None
    m = REGULAR_METHOD_RE.match(line)
    if m:
        return m.group(1)
    m = CONSTRUCTOR_RE.match(line)
    if m:
        return m.group(1)
    m = PACKAGE_PRIVATE_RE.match(line)
    if m:
        name = m.group(1)
        if name not in JAVA_KEYWORDS and len(name) > 1:
            return name
    m = BARE_METHOD_RE.match(line)
    if m:
        name = m.group(1)
        if name not in JAVA_KEYWORDS and len(name) > 1:
            return name
    return None


def scan_upward_for_method(lines, line_number, max_scan=MAX_SCAN):
    """Scan ke atas dari line_number di list of lines."""
    start = min(line_number - 1, len(lines) - 1)
    for i in range(start, max(start - max_scan, -1), -1):
        name = extract_method_name(lines[i])
        if name:
            return name
    return None

# ── Path Resolution ───────────────────────────────────────────────────────────

def resolve_filepath(tool, file_path):
    """
    Resolve file_path ke absolute path.
    Checkstyle: path absolut → pakai langsung
    SonarQube : path relatif → prepend ~/
    """
    if not file_path:
        return None
    if tool == "checkstyle":
        return file_path if os.path.isfile(file_path) else None
    elif tool == "sonarqube":
        candidate = os.path.join(BASE_DIR, file_path.lstrip("/"))
        return candidate if os.path.isfile(candidate) else None
    return None

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("============================================")
    print("  Method Name Enricher (Streaming Mode)")
    print("  Tools: checkstyle, sonarqube")
    print("============================================\n")

    # File cache: abs_path -> list of lines
    # Hanya ~2000 file unik — aman di memory
    file_cache    = {}
    not_found     = set()   # path yang sudah diketahui tidak ada

    enriched      = 0
    skipped_file  = 0
    skipped_line  = 0
    total_rows    = 0

    # Tulis ke temp file dulu, baru rename ke output
    tmp_path = OUTPUT_CSV + ".tmp"

    print(f"[STREAM] Processing {INPUT_CSV} ...")
    print(f"         Writing to  {tmp_path}")
    print()

    with open(INPUT_CSV, "r", encoding="utf-8", newline="") as fin, \
         open(tmp_path,  "w", encoding="utf-8", newline="") as fout:

        reader  = csv.DictReader(fin)
        columns = reader.fieldnames
        writer  = csv.DictWriter(fout, fieldnames=columns)
        writer.writeheader()

        for row in reader:
            total_rows += 1
            tool = row.get("tool", "")

            if tool in TOOLS_TO_ENRICH:
                file_path = (row.get("file_path") or "").strip()
                line_str  = (row.get("line_number") or "").strip()

                # Resolve absolute path
                abs_path = resolve_filepath(tool, file_path)

                if abs_path is None or abs_path in not_found:
                    skipped_file += 1

                elif not line_str:
                    skipped_line += 1

                else:
                    # Load file ke cache jika belum ada
                    if abs_path not in file_cache:
                        try:
                            with open(abs_path, "r",
                                      encoding="utf-8", errors="replace") as jf:
                                file_cache[abs_path] = jf.readlines()
                        except OSError:
                            not_found.add(abs_path)
                            skipped_file += 1
                            writer.writerow(row)
                            if total_rows % PROGRESS_N == 0:
                                print(f"  Progress: {total_rows:>9} rows | "
                                      f"enriched={enriched} "
                                      f"skipped={skipped_file+skipped_line} "
                                      f"cached_files={len(file_cache)}")
                            continue

                    lines = file_cache[abs_path]

                    try:
                        line_number = int(line_str)
                    except ValueError:
                        skipped_line += 1
                        writer.writerow(row)
                        if total_rows % PROGRESS_N == 0:
                            print(f"  Progress: {total_rows:>9} rows | "
                                  f"enriched={enriched} "
                                  f"skipped={skipped_file+skipped_line} "
                                  f"cached_files={len(file_cache)}")
                        continue

                    method_name = scan_upward_for_method(lines, line_number)
                    if method_name:
                        row["method_name"] = method_name
                        enriched += 1
                    else:
                        skipped_line += 1

            # Tulis baris (diubah atau tidak) langsung ke file output
            writer.writerow(row)

            if total_rows % PROGRESS_N == 0:
                print(f"  Progress: {total_rows:>9} rows | "
                      f"enriched={enriched} "
                      f"skipped={skipped_file+skipped_line} "
                      f"cached_files={len(file_cache)}")

    # Atomic replace: rename temp ke output
    print(f"\n[RENAME] Replacing {OUTPUT_CSV} ...")
    shutil.move(tmp_path, OUTPUT_CSV)

    print("\n============================================")
    print("  COMPLETED - Enrichment Summary")
    print("============================================")
    print(f"  Total rows processed      : {total_rows}")
    print(f"  Method names enriched     : {enriched}")
    print(f"  Skipped (file not found)  : {skipped_file}")
    print(f"  Skipped (no line/method)  : {skipped_line}")
    print(f"  Files cached in memory    : {len(file_cache)}")
    print(f"  Output                    : {OUTPUT_CSV}")
    print("============================================")


if __name__ == "__main__":
    main()