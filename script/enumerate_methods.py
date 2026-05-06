#!/usr/bin/env python3
"""
enumerate_methods.py

Mengekstrak semua method unik dari source code versi buggy Defects4J
untuk menghitung TN (True Negative) dalam metrik FPR.

Strategi:
  - Proses SEMUA bug ID per project (bukan hanya bug_id=1)
  - Deduplikasi per (project, classname, method_name) di level project
  - Setiap method hanya dihitung SATU KALI per project, tidak peduli
    di berapa bug ID dia muncul
  - Skip test directories secara menyeluruh

Kenapa proses semua bug ID?
  Antar bug ID dalam satu project bisa ada perbedaan method karena refactoring.
  Math_1 mungkin punya method yang tidak ada di Math_50, dan sebaliknya.
  Dengan proses semua dan deduplikasi, kita dapat union method pool yang
  paling lengkap untuk representasi TN yang akurat.

Output: ~/all_methods.csv
Kolom : project, classname, method_name, file_path
"""

import os
import csv
import re
import subprocess

# ── Configuration ─────────────────────────────────────────────────────────────

BASE_DIR     = os.path.expanduser("~")
PROJECTS_DIR = os.path.join(BASE_DIR, "defects4j-projects")
OUTPUT_FILE  = os.path.join(BASE_DIR, "all_methods.csv")

PROJECT_COUNTS = {
    "Chart":   26,
    "Closure": 174,
    "Lang":    61,
    "Math":    106,
    "Time":    26,
}

CSV_COLUMNS = ["project", "classname", "method_name", "file_path"]

# ── Test Directory Detection ──────────────────────────────────────────────────

def is_test_path(path):
    """
    Return True jika path mengandung segmen test directory.
    Menangani berbagai struktur: Maven (src/test/java), Ant (test/), dll.
    """
    norm = path.replace("\\", "/").lower()
    # Segment-based check
    segments = set(norm.split("/"))
    if segments & {"test", "tests", "junit", "testcase", "testcases"}:
        return True
    # Substring check untuk path seperti src/test/java
    for pattern in ("src/test", "/test/", "/tests/"):
        if pattern in norm:
            return True
    return False

# ── Regex Patterns (konsisten dengan extract_ground_truth.py) ─────────────────

PACKAGE_RE    = re.compile(r'^\s*package\s+([\w.]+)\s*;')
THROW_SKIP_RE = re.compile(r'^\s*(?:throw\s+new|throw\b|return\b)')
FLOW_SKIP_RE  = re.compile(
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
    """Ekstrak nama method dari satu baris Java."""
    stripped = line.strip()
    if THROW_SKIP_RE.match(stripped) or FLOW_SKIP_RE.match(stripped):
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


def parse_java_file(filepath, src_path):
    """
    Parse satu file .java dan ekstrak semua method.
    Return: list of (classname, method_name, rel_path)
    """
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return []

    # Ekstrak package dari baris awal
    package = ""
    for line in lines[:50]:
        m = PACKAGE_RE.match(line)
        if m:
            package = m.group(1)
            break

    # Classname dari package + nama file
    simple_class = os.path.basename(filepath).replace(".java", "")
    classname    = f"{package}.{simple_class}" if package else simple_class

    # Ekstrak semua method name (deduplikasi per file)
    methods = set()
    for line in lines:
        name = extract_method_name(line)
        if name:
            methods.add(name)

    rel_path = os.path.relpath(filepath, src_path)
    return [(classname, method, rel_path) for method in methods]


def get_src_dir(project_dir):
    try:
        result = subprocess.run(
            ["defects4j", "export", "-p", "dir.src.classes"],
            cwd=project_dir,
            capture_output=True, text=True, timeout=60
        )
        return result.stdout.strip()
    except Exception:
        return None

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("============================================")
    print("  Method Enumerator - Defects4J")
    print("  Strategy: All bug IDs, deduplicated per project")
    print("============================================\n")

    all_rows      = []
    grand_total   = 0

    for project, max_id in PROJECT_COUNTS.items():
        print(f"############################################")
        print(f"  START: {project} (1 - {max_id})")
        print(f"############################################")

        # Set deduplikasi di level PROJECT: (classname, method_name)
        # Setiap method hanya masuk satu kali per project
        seen_project = {}  # (classname, method_name) -> file_path (simpan path pertama)

        bugs_processed = 0
        bugs_skipped   = 0

        for bug_id in range(1, max_id + 1):
            buggy_dir = os.path.join(PROJECTS_DIR, f"{project}_{bug_id}_buggy")

            if not os.path.isdir(buggy_dir):
                bugs_skipped += 1
                continue

            src_dir  = get_src_dir(buggy_dir)
            if not src_dir:
                bugs_skipped += 1
                continue

            src_path = os.path.join(buggy_dir, src_dir)
            if not os.path.isdir(src_path):
                bugs_skipped += 1
                continue

            # Walk src directory, skip test paths
            for root, dirs, files in os.walk(src_path):
                dirs[:] = [
                    d for d in dirs
                    if not is_test_path(os.path.join(root, d))
                ]
                for fname in files:
                    if not fname.endswith(".java"):
                        continue
                    full_path = os.path.join(root, fname)
                    rel_path  = os.path.relpath(full_path, src_path)
                    if is_test_path(rel_path):
                        continue

                    entries = parse_java_file(full_path, src_path)
                    for classname, method_name, file_path in entries:
                        key = (classname, method_name)
                        # Deduplikasi: hanya simpan jika belum pernah muncul
                        if key not in seen_project:
                            seen_project[key] = file_path

            bugs_processed += 1

        # Setelah semua bug ID diproses, tulis hasil deduplikasi project ini
        project_count = len(seen_project)
        for (classname, method_name), file_path in seen_project.items():
            all_rows.append({
                "project":     project,
                "classname":   classname,
                "method_name": method_name,
                "file_path":   file_path,
            })

        grand_total += project_count
        print(f"  Bugs processed : {bugs_processed}")
        print(f"  Bugs skipped   : {bugs_skipped}")
        print(f"  Unique methods : {project_count}\n")

    # Tulis output
    print(f"[OUTPUT] Writing {len(all_rows)} rows to {OUTPUT_FILE} ...")
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(all_rows)

    print("\n============================================")
    print("  COMPLETED - Method Enumeration Summary")
    print("============================================")
    print(f"  Total unique methods (all projects) : {grand_total}")
    print(f"  Output                              : {OUTPUT_FILE}")
    print("============================================")


if __name__ == "__main__":
    main()