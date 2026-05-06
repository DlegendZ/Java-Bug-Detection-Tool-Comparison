#!/bin/bash

PROJECTS_DIR=~/defects4j-projects
OUTPUT_DIR=~/spotbugs-results
mkdir -p $OUTPUT_DIR

declare -A PROJECT_COUNTS
PROJECT_COUNTS=( ["Chart"]=26 ["Closure"]=174 ["Lang"]=61 ["Math"]=106 ["Time"]=26 )
IDENTIFIERS=("Chart" "Closure" "Lang" "Math" "Time")

total_processed=0
total_skipped=0
total_warning=0
total_bugs_all=0

echo "============================================"
echo "  SpotBugs Automation - Defects4J Dataset"
echo "============================================"
echo ""

for identifier in "${IDENTIFIERS[@]}"; do
    max=${PROJECT_COUNTS[$identifier]}
    echo "############################################"
    echo "  START: $identifier (1 - $max)"
    echo "############################################"

    identifier_bugs=0
    identifier_processed=0
    identifier_skipped=0
    identifier_warning=0

    for i in $(seq 1 $max); do
        project_name="${identifier}_${i}_buggy"
        project_dir="$PROJECTS_DIR/$project_name"
        output_xml="$OUTPUT_DIR/${project_name}.xml"

        if [ ! -d "$project_dir" ]; then
            echo "  [WARNING] Project folder not found: $project_name"
            ((identifier_warning++)); ((total_warning++))
            continue
        fi

        if [ -f "$output_xml" ]; then
            bug_count=$(grep -c "<BugInstance" "$output_xml" 2>/dev/null || echo 0)
            echo "  [SKIP] $project_name (already exists: $bug_count bugs)"
            ((identifier_skipped++)); ((total_skipped++))
            ((identifier_bugs+=bug_count)); ((total_bugs_all+=bug_count))
            continue
        fi

        echo "  [RUN] $project_name ..."

        cd "$project_dir"
        defects4j compile > /dev/null 2>&1
        if [ $? -ne 0 ]; then
            echo "  [WARNING] Compilation failed: $project_name"
            ((identifier_warning++)); ((total_warning++))
            continue
        fi

        CLASS_DIR=$(defects4j export -p dir.bin.classes 2>/dev/null)
        if [ -z "$CLASS_DIR" ] || [ ! -d "$project_dir/$CLASS_DIR" ]; then
            echo "  [WARNING] No .class directory found: $project_name (CLASS_DIR='$CLASS_DIR')"
            ((identifier_warning++)); ((total_warning++))
            continue
        fi

        spotbugs -textui \
            -xml:withMessages \
            -output "$output_xml" \
            "$project_dir/$CLASS_DIR" > /dev/null 2>&1

        if [ ! -f "$output_xml" ]; then
            echo "  [WARNING] Output XML not created: $project_name"
            ((identifier_warning++)); ((total_warning++))
            continue
        fi

        bug_count=$(grep -c "<BugInstance" "$output_xml" 2>/dev/null || echo 0)
        echo "  [DONE] $project_name -> $bug_count bugs found"

        ((identifier_bugs+=bug_count)); ((total_bugs_all+=bug_count))
        ((identifier_processed++)); ((total_processed++))
    done

    echo ""
    echo "  --- Summary: $identifier ---"
    echo "  Processed : $identifier_processed"
    echo "  Skipped   : $identifier_skipped"
    echo "  Warnings  : $identifier_warning"
    echo "  Total bugs: $identifier_bugs"
    echo ""
done

echo "============================================"
echo "  COMPLETED - Overall Summary"
echo "============================================"
echo "  Total processed : $total_processed projects"
echo "  Total skipped   : $total_skipped projects"
echo "  Total warnings  : $total_warning projects"
echo "  Total bugs      : $total_bugs_all bugs"
echo "  Total XML files : $(ls $OUTPUT_DIR/*.xml 2>/dev/null | wc -l) files"
echo "============================================"