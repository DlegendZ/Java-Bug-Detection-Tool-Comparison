#!/bin/bash

PROJECTS_DIR=~/defects4j-projects
OUTPUT_DIR=~/checkstyle-results
CHECKSTYLE="java -jar $HOME/checkstyle-10.13.0-all.jar"
CONFIG="/google_checks.xml"

mkdir -p $OUTPUT_DIR

declare -A PROJECT_COUNTS
PROJECT_COUNTS=( ["Chart"]=26 ["Closure"]=174 ["Lang"]=61 ["Math"]=106 ["Time"]=26 )
IDENTIFIERS=("Chart" "Closure" "Lang" "Math" "Time")

total_processed=0
total_skipped=0
total_warning=0
total_errors_all=0

echo "============================================"
echo "  Checkstyle Automation - Defects4J Dataset"
echo "============================================"
echo ""

for identifier in "${IDENTIFIERS[@]}"; do
    max=${PROJECT_COUNTS[$identifier]}
    echo "############################################"
    echo "  START: $identifier (1 - $max)"
    echo "############################################"

    identifier_errors=0
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
            error_count=$(grep -c "<error " "$output_xml" 2>/dev/null || echo 0)
            echo "  [SKIP] $project_name (already exists: $error_count errors)"
            ((identifier_skipped++)); ((total_skipped++))
            ((identifier_errors+=error_count)); ((total_errors_all+=error_count))
            continue
        fi

        echo "  [RUN] $project_name ..."

        # Use subshell for cd to avoid working directory side effects
        SRC_DIR=$(cd "$project_dir" && defects4j export -p dir.src.classes 2>/dev/null)
        if [ -z "$SRC_DIR" ] || [ ! -d "$project_dir/$SRC_DIR" ]; then
            echo "  [WARNING] No source directory found: $project_name (SRC_DIR='$SRC_DIR')"
            ((identifier_warning++)); ((total_warning++))
            continue
        fi

        $CHECKSTYLE \
            -c $CONFIG \
            -f xml \
            -o "$output_xml" \
            "$project_dir/$SRC_DIR" > /dev/null 2>&1
        exit_code=$?

        if [ $exit_code -ne 0 ] && [ $exit_code -ne 1 ]; then
            echo "  [WARNING] Checkstyle failed (exit code $exit_code): $project_name"
            ((identifier_warning++)); ((total_warning++))
            continue
        fi

        if [ ! -f "$output_xml" ]; then
            echo "  [WARNING] Output XML not created: $project_name"
            ((identifier_warning++)); ((total_warning++))
            continue
        fi

        error_count=$(grep -c "<error " "$output_xml" 2>/dev/null || echo 0)
        echo "  [DONE] $project_name -> $error_count errors found"

        ((identifier_errors+=error_count)); ((total_errors_all+=error_count))
        ((identifier_processed++)); ((total_processed++))
    done

    echo ""
    echo "  --- Summary: $identifier ---"
    echo "  Processed  : $identifier_processed"
    echo "  Skipped    : $identifier_skipped"
    echo "  Warnings   : $identifier_warning"
    echo "  Total errors: $identifier_errors"
    echo ""
done

echo "============================================"
echo "  COMPLETED - Overall Summary"
echo "============================================"
echo "  Total processed  : $total_processed projects"
echo "  Total skipped    : $total_skipped projects"
echo "  Total warnings   : $total_warning projects"
echo "  Total errors     : $total_errors_all errors"
echo "  Total XML files  : $(ls $OUTPUT_DIR/*.xml 2>/dev/null | wc -l) files"
echo "============================================"