#!/usr/bin/env python3
"""
parse_warnings.py

Parses static analysis tool outputs (SpotBugs, PMD, Checkstyle, SonarQube)
from the Defects4J benchmark and extracts warning data at the method level.

Output:
  - ~/csv-results/spotbugs_warnings.csv
  - ~/csv-results/pmd_warnings.csv
  - ~/csv-results/checkstyle_warnings.csv
  - ~/csv-results/sonarqube_warnings.csv
  - ~/csv-results/all_warnings.csv  (combined, sorted by project -> bug_id -> tool)
"""

import os
import csv
import json
import re
import xml.etree.ElementTree as ET

# ── Configuration ─────────────────────────────────────────────────────────────

BASE_DIR       = os.path.expanduser("~")
SPOTBUGS_DIR   = os.path.join(BASE_DIR, "spotbugs-results")
PMD_DIR        = os.path.join(BASE_DIR, "pmd-results")
CHECKSTYLE_DIR = os.path.join(BASE_DIR, "checkstyle-results")
SONARQUBE_DIR  = os.path.join(BASE_DIR, "sonarqube-results")
OUTPUT_DIR     = os.path.join(BASE_DIR, "csv-results")

CSV_COLUMNS = [
    "project", "bug_id", "tool",
    "classname", "method_name", "warning_type",
    "file_path", "line_number"
]

# Sort key: project name -> bug_id (numeric) -> tool name
SORT_KEY = lambda r: (r["project"], int(r["bug_id"]), r["tool"])

# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_filename(filename):
    """
    Extract project and bug_id from filename.
    Format: {Project}_{BugID}_buggy.{ext}  e.g. Chart_1_buggy.xml -> ("Chart", "1")
    Returns (None, None) if pattern does not match.
    """
    match = re.match(r"^([A-Za-z]+)_(\d+)_buggy\.", filename)
    if match:
        return match.group(1), match.group(2)
    return None, None


def strip_xml_namespaces(content):
    """
    Remove all XML namespace declarations and xsi attributes from raw XML text
    so ElementTree can parse tags with plain local names.
    Required for PMD which uses xmlns="http://pmd.sourceforge.net/report/2.0.0".
    """
    content = re.sub(r'\s+xmlns(?::\w+)?="[^"]*"', '', content)
    content = re.sub(r'\s+xsi:\w+="[^"]*"', '', content)
    return content


def parse_xml_file(filepath):
    """
    Parse an XML file with namespace stripping.
    Returns (root, error_message). On failure root is None.
    """
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        content = strip_xml_namespaces(content)
        root = ET.fromstring(content)
        return root, None
    except ET.ParseError as e:
        return None, str(e)


def natural_sort_key(filename):
    """Sort key for filenames: by (project_name, bug_id_as_int)."""
    project, bug_id = parse_filename(filename)
    if project is None:
        return ("", 0)
    return (project, int(bug_id))


def write_csv(filepath, rows):
    """Write rows to a CSV file with standard columns."""
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

# ── SpotBugs Parser ───────────────────────────────────────────────────────────

def parse_spotbugs(filepath, project, bug_id):
    """
    Parse SpotBugs XML output.

    Structure:
      <BugCollection>
        <BugInstance type="...">
          <Method classname="..." name="...">
            <SourceLine sourcepath="..." start="..."/>
          </Method>
          <SourceLine primary="true" sourcepath="..." start="..."/>
        </BugInstance>
      </BugCollection>

    Priority for file_path / line_number:
      1. <SourceLine primary="true"> directly under <BugInstance>
      2. <SourceLine> inside <Method>
    """
    rows = []
    root, err = parse_xml_file(filepath)
    if root is None:
        print(f"  [WARNING] SpotBugs XML parse error in {filepath}: {err}")
        return rows

    for bug in root.iter("BugInstance"):
        warning_type = bug.get("type", "")

        method_el   = bug.find("Method")
        classname   = method_el.get("classname", "") if method_el is not None else ""
        method_name = method_el.get("name", "")      if method_el is not None else None

        # Prefer primary SourceLine on BugInstance, fallback to Method's SourceLine
        file_path   = ""
        line_number = ""

        for sl in bug.findall("SourceLine"):
            if sl.get("primary") == "true" or not file_path:
                file_path   = sl.get("sourcepath", "") or file_path
                line_number = sl.get("start", "")      or line_number

        if not file_path and method_el is not None:
            method_sl = method_el.find("SourceLine")
            if method_sl is not None:
                file_path   = method_sl.get("sourcepath", "")
                line_number = method_sl.get("start", "")

        rows.append({
            "project":      project,
            "bug_id":       bug_id,
            "tool":         "spotbugs",
            "classname":    classname,
            "method_name":  method_name if method_name else None,
            "warning_type": warning_type,
            "file_path":    file_path,
            "line_number":  line_number,
        })

    return rows

# ── PMD Parser ────────────────────────────────────────────────────────────────

def parse_pmd(filepath, project, bug_id):
    """
    Parse PMD XML output.

    PMD uses an XML namespace (xmlns="http://pmd.sourceforge.net/report/2.0.0")
    which is stripped before parsing so tag names are plain local names.

    Structure:
      <pmd>
        <file name="...">
          <violation beginline="..." class="..." method="..." rule="..." package="...">
            message text
          </violation>
        </file>
      </pmd>

    classname = package + "." + class (reconstructed).
    method_name is optional — null for class-level violations.
    """
    rows = []
    root, err = parse_xml_file(filepath)
    if root is None:
        print(f"  [WARNING] PMD XML parse error in {filepath}: {err}")
        return rows

    for file_el in root.iter("file"):
        file_path = file_el.get("name", "")

        for violation in file_el.iter("violation"):
            pkg          = violation.get("package", "")
            cls          = violation.get("class", "")
            method_name  = violation.get("method", None)
            warning_type = violation.get("rule", "")
            line_number  = violation.get("beginline", "")

            if pkg and cls:
                classname = f"{pkg}.{cls}"
            else:
                classname = cls or pkg

            rows.append({
                "project":      project,
                "bug_id":       bug_id,
                "tool":         "pmd",
                "classname":    classname,
                "method_name":  method_name if method_name else None,
                "warning_type": warning_type,
                "file_path":    file_path,
                "line_number":  line_number,
            })

    return rows

# ── Checkstyle Parser ─────────────────────────────────────────────────────────

def parse_checkstyle(filepath, project, bug_id):
    """
    Parse Checkstyle XML output.

    Structure:
      <checkstyle>
        <file name="...">
          <error line="..." message="..." source="..."/>
        </file>
      </checkstyle>

    No method or classname info available.
    warning_type = last segment of 'source' (e.g. "JavadocMethodCheck").
    """
    rows = []
    root, err = parse_xml_file(filepath)
    if root is None:
        print(f"  [WARNING] Checkstyle XML parse error in {filepath}: {err}")
        return rows

    for file_el in root.iter("file"):
        file_path = file_el.get("name", "")

        for error in file_el.iter("error"):
            line_number  = error.get("line", "")
            source       = error.get("source", "")
            warning_type = source.split(".")[-1] if source else ""

            rows.append({
                "project":      project,
                "bug_id":       bug_id,
                "tool":         "checkstyle",
                "classname":    None,
                "method_name":  None,
                "warning_type": warning_type,
                "file_path":    file_path,
                "line_number":  line_number,
            })

    return rows

# ── SonarQube Parser ──────────────────────────────────────────────────────────

def parse_sonarqube(filepath, project, bug_id):
    """
    Parse SonarQube JSON output produced by run_sonarqube.sh.

    Structure:
      {
        "total_accurate": N,     <- real total from API
        "issues_fetched": M,     <- rows in "issues" (capped at 500 per request)
        "issues": [ { "component": "key:path/File.java", "line": N, "rule": "..." } ]
      }

    file_path extracted from 'component' by stripping project-key prefix.
    No method or classname available from SonarQube API.

    Prints a note if total_accurate > issues_fetched (data truncation).
    """
    rows = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"  [WARNING] SonarQube JSON parse error in {filepath}: {e}")
        return rows

    issues         = data.get("issues", [])
    total_accurate = data.get("total_accurate", len(issues))
    issues_fetched = data.get("issues_fetched", len(issues))

    if total_accurate > issues_fetched:
        print(f"  [NOTE] {os.path.basename(filepath)}: "
              f"total={total_accurate} but only {issues_fetched} fetched "
              f"(API pagination limit — consider re-running with full pagination)")

    for issue in issues:
        component    = issue.get("component", "")
        line_number  = issue.get("line", "")
        warning_type = issue.get("rule", "")

        # Strip project-key prefix: "chart-1-buggy:src/Foo.java" -> "src/Foo.java"
        file_path = component.split(":", 1)[1] if ":" in component else component

        rows.append({
            "project":      project,
            "bug_id":       bug_id,
            "tool":         "sonarqube",
            "classname":    None,
            "method_name":  None,
            "warning_type": warning_type,
            "file_path":    file_path,
            "line_number":  str(line_number) if line_number != "" else "",
        })

    return rows

# ── Directory Walker ──────────────────────────────────────────────────────────

def process_directory(directory, extension, parser_fn, tool_name):
    """
    Walk a results directory, parse every matching file, and return all rows.
    Files are processed in natural numeric order: Chart_1, Chart_2, ..., Chart_26.
    """
    all_rows = []

    if not os.path.isdir(directory):
        print(f"[WARNING] Directory not found, skipping: {directory}")
        return all_rows

    files = sorted(
        [f for f in os.listdir(directory) if f.endswith(extension)],
        key=natural_sort_key
    )

    print(f"\n[{tool_name.upper()}] Processing {len(files)} files from {directory}")

    for filename in files:
        project, bug_id = parse_filename(filename)
        if project is None:
            print(f"  [WARNING] Skipping unrecognized filename: {filename}")
            continue

        filepath = os.path.join(directory, filename)
        rows     = parser_fn(filepath, project, bug_id)
        all_rows.extend(rows)
        print(f"  [DONE] {filename} -> {len(rows)} warnings extracted")

    print(f"  Subtotal ({tool_name}): {len(all_rows)} warnings")
    return all_rows

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("============================================")
    print("  Warning Parser - Defects4J Dataset")
    print("============================================")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Parse all tools
    spotbugs_rows   = process_directory(SPOTBUGS_DIR,   ".xml",  parse_spotbugs,   "spotbugs")
    pmd_rows        = process_directory(PMD_DIR,         ".xml",  parse_pmd,         "pmd")
    checkstyle_rows = process_directory(CHECKSTYLE_DIR,  ".xml",  parse_checkstyle,  "checkstyle")
    sonarqube_rows  = process_directory(SONARQUBE_DIR,   ".json", parse_sonarqube,   "sonarqube")

    tool_outputs = [
        ("spotbugs",   spotbugs_rows),
        ("pmd",        pmd_rows),
        ("checkstyle", checkstyle_rows),
        ("sonarqube",  sonarqube_rows),
    ]

    # Write per-tool CSVs (already in natural order from process_directory)
    print("\n[OUTPUT] Writing per-tool CSV files ...")
    for tool_name, rows in tool_outputs:
        out_path = os.path.join(OUTPUT_DIR, f"{tool_name}_warnings.csv")
        write_csv(out_path, rows)
        print(f"  {tool_name}_warnings.csv -> {len(rows):>9} rows  ->  {out_path}")

    # Write combined CSV sorted by project -> bug_id (numeric) -> tool
    all_rows_sorted = sorted(
        spotbugs_rows + pmd_rows + checkstyle_rows + sonarqube_rows,
        key=SORT_KEY
    )
    combined_path = os.path.join(OUTPUT_DIR, "all_warnings.csv")
    print(f"\n[OUTPUT] Writing combined CSV ...")
    write_csv(combined_path, all_rows_sorted)
    print(f"  all_warnings.csv        -> {len(all_rows_sorted):>9} rows  ->  {combined_path}")

    # Summary
    total = sum(len(r) for _, r in tool_outputs)
    print("\n============================================")
    print("  COMPLETED - Overall Summary")
    print("============================================")
    for tool_name, rows in tool_outputs:
        print(f"  {tool_name:<12}: {len(rows):>9} warnings")
    print(f"  {'─' * 30}")
    print(f"  {'Total':<12}: {total:>9} warnings")
    print(f"\n  Output folder : {OUTPUT_DIR}")
    print(f"  Files written :")
    for tool_name, _ in tool_outputs:
        print(f"    - {tool_name}_warnings.csv")
    print(f"    - all_warnings.csv")
    print("============================================")


if __name__ == "__main__":
    main()