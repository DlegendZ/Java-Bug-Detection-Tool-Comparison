#!/usr/bin/env python3
"""
extract_ground_truth.py

Mengekstrak ground truth (method yang buggy) dari dua sumber resmi Defects4J:
  1. modified_classes/{bug_id}.src  → class yang dimodifikasi (100% akurat)
  2. patches/{bug_id}.src.patch     → git/svn diff untuk ekstrak method name

Strategi ekstraksi method name (prioritas berurutan per hunk):
  1. Scan baris +/- dalam hunk untuk cari method declaration
  2. Scan ke atas di file buggy dari line number hunk (fallback, max 300 baris)

Regex menangani 4 jenis method declaration Java:
  1. Regular method    : public/private/protected + return type + name(
  2. Constructor       : public/private/protected + NamaKelas(
  3. Package-private   : static/abstract/final + return type + name(
  4. Bare method       : return_type + name( (tanpa modifier apapun, indent 1-2 spasi)

False positive di-skip:
  - throw/return/if/for/while/do/switch/catch/finally

Diff format yang didukung:
  - Git diff : diff --git a/path b/path
  - SVN diff : Index: path

Bug yang tidak bisa diekstrak (bukan method change, atau deprecated):
  - Lang_25, Lang_48 : bukan perubahan method
  - Math_12, Math_104: bukan perubahan method
  - Closure_63, Closure_93, Lang_2, Lang_18, Time_21: deprecated

Output: ~/ground_truth.csv
Kolom : project, bug_id, classname, method_name, file_path
"""

import os
import csv
import re
import subprocess

# ── Configuration ─────────────────────────────────────────────────────────────

BASE_DIR     = os.path.expanduser("~")
D4J_HOME     = os.path.join(BASE_DIR, "defects4j")
PROJECTS_DIR = os.path.join(BASE_DIR, "defects4j-projects")
OUTPUT_FILE  = os.path.join(BASE_DIR, "ground_truth.csv")

PROJECT_COUNTS = {
    "Chart":   26,
    "Closure": 174,
    "Lang":    61,
    "Math":    106,
    "Time":    26,
}

CSV_COLUMNS = ["project", "bug_id", "classname", "method_name", "file_path"]

# Max baris scan ke atas di file buggy
MAX_SCAN = 300

# ── Regex Patterns ────────────────────────────────────────────────────────────

# Skip: throw, return
THROW_SKIP_RE = re.compile(r'^\s*(?:throw\s+new|throw\b|return\b)')

# Skip: flow control
FLOW_SKIP_RE = re.compile(
    r'^\s*(?:if|else(?:\s+if)?|while|for|do|switch|catch|finally)\s*[\(\{]?'
)

# 1. Regular method: wajib access modifier + return type + name(
#    public LegendItemCollection getLegendItems() {
#    private static int compute(int x) throws E {
REGULAR_METHOD_RE = re.compile(
    r'^\s*'
    r'(?:public|private|protected)'
    r'(?:\s+(?:static|final|synchronized|abstract|native|default|strictfp))*'
    r'\s+[\w<>\[\],?]+\s+'
    r'(\w+)'
    r'\s*\('
)

# 2. Constructor: access modifier + NamaKelas( (huruf kapital)
#    public Week(Date time, TimeZone zone) {
CONSTRUCTOR_RE = re.compile(
    r'^\s*'
    r'(?:public|private|protected)\s+'
    r'([A-Z]\w*)'
    r'\s*\('
)

# 3. Package-private dengan modifier: static/abstract/final + return type + name(
#    static Map<Object, Object> getRegistry() {
#    static boolean isRegistered(Object value) {
#    abstract void doSomething() {
PACKAGE_PRIVATE_RE = re.compile(
    r'^\s*'
    r'(?:(?:static|final|synchronized|abstract|native|strictfp)\s+)+'
    r'[\w<>\[\],?\s]+?\s+'
    r'(\w+)'
    r'\s*\('
)

# 4. Bare method: tanpa modifier apapun, indent 1-2 spasi (top-level method)
#    void tryFoldStringJoin(NodeTraversal t, Node n, ...) {
#    Gunakan whitelist return type untuk hindari false positive
BARE_METHOD_RETURN_TYPES = (
    'void', 'boolean', 'int', 'long', 'double', 'float',
    'char', 'byte', 'short', 'String', 'Node', 'List',
    'Map', 'Set', 'Collection', 'Iterator', 'Object',
)
BARE_METHOD_RE = re.compile(
    r'^\s{1,2}'              # indent 1-2 spasi (top-level class method)
    r'(' + '|'.join(BARE_METHOD_RETURN_TYPES) + r'|[\w<>\[\]]+)'
    r'\s+'
    r'(\w+)'                 # method name
    r'\s*\('
)

# Git diff file header
GIT_FILE_HEADER_RE = re.compile(r'^diff --git a/(.+?) b/(.+?)$')

# SVN diff file header: Index: source/org/jfree/.../Foo.java
SVN_FILE_HEADER_RE = re.compile(r'^Index:\s+(.+)$')

# Hunk header: @@ -START,COUNT +START,COUNT @@ context
HUNK_RE = re.compile(r'^@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@\s*(.*)')

# Keywords Java yang bukan nama method
JAVA_KEYWORDS = {
    'if', 'else', 'for', 'while', 'do', 'switch', 'case', 'try', 'catch',
    'finally', 'return', 'new', 'import', 'package', 'throws', 'throw',
    'super', 'this', 'instanceof', 'class', 'interface', 'enum',
    'void', 'boolean', 'int', 'long', 'double', 'float', 'char', 'byte', 'short',
}

# ── Method Name Extractor ─────────────────────────────────────────────────────

def extract_method_name(line):
    """
    Ekstrak nama method dari satu baris Java.
    Urutan pengecekan:
      1. Skip throw/return
      2. Skip flow control
      3. Regular method (dengan access modifier)
      4. Constructor (huruf kapital)
      5. Package-private dengan modifier (static/abstract/final)
      6. Bare method (tanpa modifier, indent 1-2 spasi, return type dari whitelist)
    Return None jika bukan method/constructor declaration.
    """
    stripped = line.strip()

    if THROW_SKIP_RE.match(stripped):
        return None
    if FLOW_SKIP_RE.match(stripped):
        return None

    # 1. Regular method
    m = REGULAR_METHOD_RE.match(line)
    if m:
        return m.group(1)

    # 2. Constructor
    m = CONSTRUCTOR_RE.match(line)
    if m:
        return m.group(1)

    # 3. Package-private dengan modifier
    m = PACKAGE_PRIVATE_RE.match(line)
    if m:
        name = m.group(1)
        if name not in JAVA_KEYWORDS and len(name) > 1:
            return name

    # 4. Bare method (tanpa modifier apapun)
    m = BARE_METHOD_RE.match(line)
    if m:
        name = m.group(2)
        if name not in JAVA_KEYWORDS and len(name) > 1:
            return name

    return None

# ── File Scanner ──────────────────────────────────────────────────────────────

def scan_upward_for_method(filepath, line_number, max_scan=MAX_SCAN):
    """
    Scan ke atas dari line_number untuk menemukan deklarasi method terdekat.
    """
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return None

    start = min(line_number - 1, len(lines) - 1)
    for i in range(start, max(start - max_scan, -1), -1):
        name = extract_method_name(lines[i])
        if name:
            return name
    return None

# ── Helpers ───────────────────────────────────────────────────────────────────

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


def get_modified_classes(d4j_home, project, bug_id):
    filepath = os.path.join(
        d4j_home, "framework", "projects", project,
        "modified_classes", f"{bug_id}.src"
    )
    if not os.path.isfile(filepath):
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def classname_to_relpath(classname, src_dir):
    return os.path.join(src_dir, classname.replace(".", "/") + ".java")


def find_buggy_file(buggy_dir, classname, src_dir):
    """Cari file .java di folder buggy, coba beberapa path alternatif."""
    rel = classname_to_relpath(classname, src_dir)
    path = os.path.join(buggy_dir, rel)
    if os.path.isfile(path):
        return path, rel

    rel2 = classname.replace(".", "/") + ".java"
    for prefix in ["source/", "src/main/java/", "src/java/", "src/"]:
        path2 = os.path.join(buggy_dir, prefix + rel2)
        if os.path.isfile(path2):
            return path2, prefix + rel2

    try:
        filename = classname.split(".")[-1] + ".java"
        result = subprocess.run(
            ["find", buggy_dir, "-name", filename, "-type", "f"],
            capture_output=True, text=True, timeout=15
        )
        found = result.stdout.strip().splitlines()
        if found:
            abs_path = found[0]
            rel_path = os.path.relpath(abs_path, buggy_dir)
            return abs_path, rel_path
    except Exception:
        pass

    return None, None


def classname_from_path(file_path, src_dir):
    rel = file_path
    for prefix in [src_dir + "/", src_dir + "\\"]:
        if rel.startswith(prefix):
            rel = rel[len(prefix):]
            break
    for prefix in ["source/", "src/main/java/", "src/java/", "src/"]:
        if rel.startswith(prefix):
            rel = rel[len(prefix):]
            break
    classname = rel.replace("/", ".").replace("\\", ".")
    if classname.endswith(".java"):
        classname = classname[:-5]
    return classname

# ── Patch Parser ──────────────────────────────────────────────────────────────

def parse_patch(patch_path, buggy_dir, src_dir, allowed_classes):
    """
    Parse file .src.patch (git atau SVN diff) dan ekstrak method name per hunk.
    Hanya memproses file yang ada di allowed_classes.
    """
    try:
        with open(patch_path, "r", encoding="utf-8", errors="replace") as f:
            raw_lines = f.readlines()
    except OSError:
        return []

    results = []
    seen    = set()

    current_file    = None
    current_class   = None
    current_relpath = None
    current_hunk    = []
    hunk_start      = None

    def flush_hunk():
        nonlocal current_hunk, hunk_start
        if not current_file or not current_hunk or not current_class:
            current_hunk = []
            hunk_start   = None
            return

        method_name = None

        # Prioritas 1: scan baris +/- dalam hunk
        for line in current_hunk:
            if line and line[0] in ('+', '-', ' '):
                name = extract_method_name(line[1:])
                if name:
                    method_name = name
                    break

        # Prioritas 2: scan ke atas di file buggy
        if not method_name and hunk_start and buggy_dir:
            abs_path, _ = find_buggy_file(buggy_dir, current_class, src_dir)
            if abs_path:
                method_name = scan_upward_for_method(abs_path, hunk_start)

        if method_name:
            key = (current_class, method_name)
            if key not in seen:
                seen.add(key)
                results.append({
                    "classname":   current_class,
                    "method_name": method_name,
                    "file_path":   current_relpath or current_file,
                })

        current_hunk = []
        hunk_start   = None

    def match_class_from_path(raw_path):
        for cls in allowed_classes:
            java_rel = cls.replace(".", "/") + ".java"
            if raw_path.endswith(java_rel) or raw_path == java_rel:
                return cls, raw_path
        return None, None

    for line in raw_lines:
        line = line.rstrip("\n")

        # SVN diff header
        svn_match = SVN_FILE_HEADER_RE.match(line)
        if svn_match:
            flush_hunk()
            raw_path = svn_match.group(1).strip()
            current_class, current_relpath = match_class_from_path(raw_path)
            current_file = raw_path
            continue

        # Git diff header
        git_match = GIT_FILE_HEADER_RE.match(line)
        if git_match:
            flush_hunk()
            raw_path = git_match.group(2)
            if raw_path.startswith("b/"):
                raw_path = raw_path[2:]
            current_class, current_relpath = match_class_from_path(raw_path)
            current_file = raw_path
            continue

        # Hunk header
        hm = HUNK_RE.match(line)
        if hm:
            flush_hunk()
            hunk_start   = int(hm.group(1))
            current_hunk = []
            continue

        # Baris dalam hunk
        if current_class and hunk_start is not None:
            if line.startswith(('+', '-', ' ')):
                current_hunk.append(line)

    flush_hunk()
    return results

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("============================================")
    print("  Ground Truth Extractor - Defects4J")
    print("  Source: modified_classes/ + patches/")
    print("  Fixes : SVN diff, package-private,")
    print("          bare method, max_scan=300")
    print("============================================\n")

    all_rows        = []
    total_processed = 0
    total_skipped   = 0
    total_methods   = 0

    for project, max_id in PROJECT_COUNTS.items():
        print(f"############################################")
        print(f"  START: {project} (1 - {max_id})")
        print(f"############################################")

        patches_dir = os.path.join(
            D4J_HOME, "framework", "projects", project, "patches"
        )

        for bug_id in range(1, max_id + 1):
            patch_file = os.path.join(patches_dir, f"{bug_id}.src.patch")
            buggy_dir  = os.path.join(PROJECTS_DIR, f"{project}_{bug_id}_buggy")

            if not os.path.isfile(patch_file):
                print(f"  [SKIP] {project}_{bug_id}: patch not found")
                total_skipped += 1
                continue

            modified_classes = get_modified_classes(D4J_HOME, project, bug_id)
            if not modified_classes:
                print(f"  [WARNING] {project}_{bug_id}: no modified classes")
                total_skipped += 1
                continue

            src_dir = "source"
            if os.path.isdir(buggy_dir):
                sd = get_src_dir(buggy_dir)
                if sd:
                    src_dir = sd

            entries = parse_patch(
                patch_file, buggy_dir, src_dir, modified_classes
            )

            if entries:
                for entry in entries:
                    all_rows.append({
                        "project":     project,
                        "bug_id":      str(bug_id),
                        "classname":   entry["classname"],
                        "method_name": entry["method_name"],
                        "file_path":   entry["file_path"],
                    })
                total_methods   += len(entries)
                total_processed += 1
                methods_str = ", ".join(e["method_name"] for e in entries)
                print(f"  [DONE] {project}_{bug_id} -> "
                      f"{len(entries)} method(s): {methods_str}")
            else:
                print(f"  [WARNING] {project}_{bug_id} -> no methods extracted")
                total_skipped += 1

        print()

    # Tulis output CSV
    print(f"[OUTPUT] Writing {len(all_rows)} rows to {OUTPUT_FILE} ...")
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(all_rows)

    print("\n============================================")
    print("  COMPLETED - Ground Truth Summary")
    print("============================================")
    print(f"  Processed           : {total_processed} bugs")
    print(f"  Skipped/Warning     : {total_skipped} bugs")
    print(f"  Total buggy methods : {total_methods}")
    print(f"  Output              : {OUTPUT_FILE}")
    print("============================================")


if __name__ == "__main__":
    main()