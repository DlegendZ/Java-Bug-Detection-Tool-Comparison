#!/bin/bash

PROJECTS_DIR=~/defects4j-projects
OUTPUT_DIR=~/pmd-results
PMD=~/pmd-bin-6.55.0/bin/run.sh
mkdir -p $OUTPUT_DIR

declare -A PROJECT_COUNTS
PROJECT_COUNTS=( ["Chart"]=26 ["Closure"]=174 ["Lang"]=61 ["Math"]=106 ["Time"]=26 )
IDENTIFIERS=("Chart" "Closure" "Lang" "Math" "Time")

total_processed=0
total_skipped=0
total_warning=0
total_violations_all=0

echo "============================================"
echo "  PMD Automation - Defects4J Dataset"
echo "============================================"
echo ""

for identifier in "${IDENTIFIERS[@]}"; do
    max=${PROJECT_COUNTS[$identifier]}
    echo "############################################"
    echo "  START: $identifier (1 - $max)"
    echo "############################################"

    identifier_violations=0
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
            violation_count=$(grep -c "<violation" "$output_xml" 2>/dev/null || echo 0)
            echo "  [SKIP] $project_name (already exists: $violation_count violations)"
            ((identifier_skipped++)); ((total_skipped++))
            ((identifier_violations+=violation_count)); ((total_violations_all+=violation_count))
            continue
        fi

        echo "  [RUN] $project_name ..."

        cd "$project_dir"
        SRC_DIR=$(defects4j export -p dir.src.classes 2>/dev/null)
        if [ -z "$SRC_DIR" ] || [ ! -d "$project_dir/$SRC_DIR" ]; then
            echo "  [WARNING] No source directory found: $project_name (SRC_DIR='$SRC_DIR')"
            ((identifier_warning++)); ((total_warning++))
            continue
        fi

        $PMD pmd \
            -d "$project_dir/$SRC_DIR" \
            -R rulesets/java/quickstart.xml \
            -f xml \
            -r "$output_xml" > /dev/null 2>&1
        exit_code=$?

        if [ $exit_code -ne 0 ] && [ $exit_code -ne 4 ]; then
            echo "  [WARNING] PMD failed (exit code $exit_code): $project_name"
            ((identifier_warning++)); ((total_warning++))
            continue
        fi

        if [ ! -f "$output_xml" ]; then
            echo "  [WARNING] Output XML not created: $project_name"
            ((identifier_warning++)); ((total_warning++))
            continue
        fi

        violation_count=$(grep -c "<violation" "$output_xml" 2>/dev/null || echo 0)
        echo "  [DONE] $project_name -> $violation_count violations found"

        ((identifier_violations+=violation_count)); ((total_violations_all+=violation_count))
        ((identifier_processed++)); ((total_processed++))
    done

    echo ""
    echo "  --- Summary: $identifier ---"
    echo "  Processed  : $identifier_processed"
    echo "  Skipped    : $identifier_skipped"
    echo "  Warnings   : $identifier_warning"
    echo "  Total violations: $identifier_violations"
    echo ""
done

echo "============================================"
echo "  COMPLETED - Overall Summary"
echo "============================================"
echo "  Total processed  : $total_processed projects"
echo "  Total skipped    : $total_skipped projects"
echo "  Total warnings   : $total_warning projects"
echo "  Total violations : $total_violations_all violations"
echo "  Total XML files  : $(ls $OUTPUT_DIR/*.xml 2>/dev/null | wc -l) files"
echo "============================================"