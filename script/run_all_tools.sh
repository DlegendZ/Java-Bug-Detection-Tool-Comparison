#!/bin/bash

# ============================================================
#  Master Wrapper - Static Analysis Monitoring Dashboard
#  Tools: SpotBugs, PMD, Checkstyle, SonarQube
#  Runs each tool 3x for execution time averaging
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$HOME/analysis-logs"
TIMING_LOG="$LOG_DIR/timing_summary.txt"

TOTAL_PROJECTS=393  # effective total after deprecated entries

# Output directories per tool
SPOTBUGS_OUT="$HOME/spotbugs-results"
PMD_OUT="$HOME/pmd-results"
CHECKSTYLE_OUT="$HOME/checkstyle-results"
SONARQUBE_OUT="$HOME/sonarqube-results"

TOTAL_RUNS=3

mkdir -p "$LOG_DIR"

# ============================================================
#  HELPER: Format seconds into Hh Mm Ss
# ============================================================
format_duration() {
    local secs=$1
    local h=$((secs / 3600))
    local m=$(((secs % 3600) / 60))
    local s=$((secs % 60))
    if [ $h -gt 0 ]; then
        printf "%dh %02dm %02ds" $h $m $s
    else
        printf "%dm %02ds" $m $s
    fi
}

# ============================================================
#  HELPER: Print section divider
# ============================================================
print_divider() {
    echo "============================================================"
}

print_sub_divider() {
    echo "------------------------------------------------------------"
}

# ============================================================
#  HELPER: Clear output directory before each fresh run
# ============================================================
clear_output_dir() {
    local dir="$1"
    local tool="$2"
    if [ -d "$dir" ]; then
        local count
        count=$(ls "$dir" 2>/dev/null | wc -l)
        echo "  [CLEANUP] Removing $count previous result files from $tool output..."
        rm -f "$dir"/*.xml "$dir"/*.json 2>/dev/null
        echo "  [CLEANUP] Done."
    fi
}

# ============================================================
#  HELPER: Count results in output directory
# ============================================================
count_results() {
    local dir="$1"
    local ext="$2"
    ls "$dir"/*."$ext" 2>/dev/null | wc -l
}

# ============================================================
#  CORE: Run one tool for one run iteration
#  Args: $1=tool_name $2=script_path $3=output_dir $4=ext $5=run_number
# ============================================================
run_tool_once() {
    local tool_name="$1"
    local script_path="$2"
    local output_dir="$3"
    local ext="$4"
    local run_num="$5"
    local tool_log="$LOG_DIR/${tool_name}_run${run_num}_$(date +%Y%m%d_%H%M%S).log"

    # Counter dir uses parent PID ($BASHPID of this function call) — fixed path for this invocation
    local counter_dir="$LOG_DIR/.counters_${tool_name}_${run_num}"
    mkdir -p "$counter_dir"
    echo 0 > "$counter_dir/project_count"
    echo 0 > "$counter_dir/done_count"
    echo 0 > "$counter_dir/skip_count"
    echo 0 > "$counter_dir/warn_count"

    print_divider
    echo "  TOOL     : $tool_name"
    echo "  RUN      : $run_num / $TOTAL_RUNS"
    echo "  STARTED  : $(date '+%Y-%m-%d %H:%M:%S')"
    print_divider

    # Step 1: Clean previous results for a fresh run
    clear_output_dir "$output_dir" "$tool_name"
    echo ""

    # Step 2: Record start time in a file so subshell can read it
    local run_start
    run_start=$(date +%s)
    echo "$run_start" > "$counter_dir/run_start"

    # Step 3: Run the script and monitor output line by line
    echo "  [START] Running $tool_name script..."
    print_sub_divider
    bash "$script_path" 2>&1 | tee "$tool_log" | while IFS= read -r line; do
        local now
        now=$(date +%s)
        local rs
        rs=$(cat "$counter_dir/run_start")
        local elapsed=$(( now - rs ))
        local elapsed_fmt
        elapsed_fmt=$(format_duration $elapsed)

        # Read counters
        local project_count done_count skip_count warn_count
        project_count=$(cat "$counter_dir/project_count")
        done_count=$(cat "$counter_dir/done_count")
        skip_count=$(cat "$counter_dir/skip_count")
        warn_count=$(cat "$counter_dir/warn_count")

        if [[ "$line" == *"[RUN]"* ]]; then
            project_count=$(( project_count + 1 ))
            echo "$project_count" > "$counter_dir/project_count"

            # Extract project name: text after "[RUN] " up to next space
            local tmp="${line#*\[RUN\] }"
            local last_project="${tmp%% *}"

            local pct=0
            [ "$TOTAL_PROJECTS" -gt 0 ] && pct=$(( project_count * 100 / TOTAL_PROJECTS ))

            local eta_str="calculating..."
            if [ "$project_count" -gt 1 ] && [ "$elapsed" -gt 0 ]; then
                local avg_secs=$(( elapsed / project_count ))
                local remaining=$(( TOTAL_PROJECTS - project_count ))
                local eta_secs=$(( avg_secs * remaining ))
                eta_str=$(format_duration $eta_secs)
            fi

            echo ""
            echo "  >>> PROGRESS : $project_count / $TOTAL_PROJECTS ($pct%)"
            echo "  >>> CURRENT  : $last_project"
            echo "  >>> ELAPSED  : $elapsed_fmt"
            echo "  >>> ETA      : $eta_str"
            echo "  >>> DONE/SKIP/WARN: $done_count / $skip_count / $warn_count"
            print_sub_divider

        elif [[ "$line" == *"[DONE]"* ]]; then
            done_count=$(( done_count + 1 ))
            echo "$done_count" > "$counter_dir/done_count"
            echo "  $line"

        elif [[ "$line" == *"[SKIP]"* ]]; then
            skip_count=$(( skip_count + 1 ))
            echo "$skip_count" > "$counter_dir/skip_count"
            echo "  $line"

        elif [[ "$line" == *"[WARNING]"* ]]; then
            warn_count=$(( warn_count + 1 ))
            echo "$warn_count" > "$counter_dir/warn_count"
            echo "  $line"

        elif [[ "$line" == *"--- Summary:"* ]]; then
            print_sub_divider
            echo "  $line"

        elif [[ "$line" == *"COMPLETED - Overall Summary"* ]]; then
            print_divider
            echo "  $line"

        else
            echo "  $line"
        fi
    done

    # Step 4: Calculate run duration
    local run_end
    run_end=$(date +%s)
    local run_duration=$(( run_end - run_start ))
    local run_duration_fmt
    run_duration_fmt=$(format_duration $run_duration)

    # Count actual output files
    local result_count
    result_count=$(count_results "$output_dir" "$ext")

    # Save duration for parent to read
    echo "$run_duration" > "$LOG_DIR/.last_duration"

    # Cleanup counter temp files
    rm -rf "$counter_dir"

    print_divider
    echo "  [RUN $run_num COMPLETE] $tool_name"
    echo "  Duration     : $run_duration_fmt  ($run_duration seconds)"
    echo "  Result files : $result_count files"
    echo "  Log saved to : $tool_log"
    print_divider
    echo ""
}

# ============================================================
#  CORE: Run one tool for all 3 runs with timing summary
# ============================================================
run_tool_all_runs() {
    local tool_name="$1"
    local script_path="$2"
    local output_dir="$3"
    local ext="$4"

    local run_times=()
    local total_tool_start
    total_tool_start=$(date +%s)

    echo ""
    print_divider
    echo "  ██  STARTING: $tool_name  (3 runs)"
    echo "  ██  TIME    : $(date '+%Y-%m-%d %H:%M:%S')"
    print_divider
    echo ""

    local run_num
    for run_num in $(seq 1 $TOTAL_RUNS); do
        run_tool_once "$tool_name" "$script_path" "$output_dir" "$ext" "$run_num"

        # Read duration from temp file written by run_tool_once
        local dur=0
        if [ -f "$LOG_DIR/.last_duration" ]; then
            dur=$(cat "$LOG_DIR/.last_duration")
            rm -f "$LOG_DIR/.last_duration"
        fi
        run_times+=("$dur")

        echo "  [TIMING] $tool_name Run $run_num duration: $(format_duration $dur)  (${dur}s)"

        # Brief pause between runs
        if [ "$run_num" -lt "$TOTAL_RUNS" ]; then
            echo "  [PAUSE] Waiting 10 seconds before next run..."
            sleep 10
        fi
        echo ""
    done

    # Calculate average
    local total_tool_end
    total_tool_end=$(date +%s)
    local total_tool_duration=$(( total_tool_end - total_tool_start ))

    local sum=0
    local t
    for t in "${run_times[@]}"; do
        sum=$(( sum + t ))
    done
    local avg=0
    [ "${#run_times[@]}" -gt 0 ] && avg=$(( sum / ${#run_times[@]} ))

    print_divider
    echo "  ██  COMPLETED: $tool_name"
    echo "  ██  Run 1     : $(format_duration ${run_times[0]:-0})  (${run_times[0]:-0}s)"
    echo "  ██  Run 2     : $(format_duration ${run_times[1]:-0})  (${run_times[1]:-0}s)"
    echo "  ██  Run 3     : $(format_duration ${run_times[2]:-0})  (${run_times[2]:-0}s)"
    echo "  ██  Average   : $(format_duration $avg)  (${avg}s)"
    echo "  ██  Total     : $(format_duration $total_tool_duration)"
    print_divider
    echo ""

    # Append to timing summary log
    {
        echo "Tool          : $tool_name"
        echo "Run 1         : $(format_duration ${run_times[0]:-0}) (${run_times[0]:-0}s)"
        echo "Run 2         : $(format_duration ${run_times[1]:-0}) (${run_times[1]:-0}s)"
        echo "Run 3         : $(format_duration ${run_times[2]:-0}) (${run_times[2]:-0}s)"
        echo "Average       : $(format_duration $avg) (${avg}s)"
        echo "Total elapsed : $(format_duration $total_tool_duration)"
        echo "------------------------------------------------------------"
    } >> "$TIMING_LOG"
}

# ============================================================
#  MAIN
# ============================================================

# ============================================================
#  MAIN
# ============================================================

# Usage help
usage() {
    echo "Usage: $0 [tool1] [tool2] ..."
    echo ""
    echo "Available tools: spotbugs, pmd, checkstyle, sonarqube"
    echo ""
    echo "Examples:"
    echo "  $0                              # run all 4 tools"
    echo "  $0 spotbugs                     # run SpotBugs only"
    echo "  $0 spotbugs pmd                 # run SpotBugs then PMD"
    echo "  $0 spotbugs pmd checkstyle sonarqube  # run all in order"
    exit 0
}

[ "$1" = "--help" ] || [ "$1" = "-h" ] && usage

# Determine which tools to run (default: all)
TOOLS_TO_RUN=()
if [ $# -eq 0 ]; then
    TOOLS_TO_RUN=("spotbugs" "pmd" "checkstyle" "sonarqube")
else
    for arg in "$@"; do
        case "${arg,,}" in
            spotbugs|pmd|checkstyle|sonarqube) TOOLS_TO_RUN+=("${arg,,}") ;;
            *) echo "  [ERROR] Unknown tool: $arg"; echo "  Valid: spotbugs, pmd, checkstyle, sonarqube"; exit 1 ;;
        esac
    done
fi

# Validate scripts exist for selected tools
MISSING=0
for tool in "${TOOLS_TO_RUN[@]}"; do
    script="$SCRIPT_DIR/run_${tool}.sh"
    if [ ! -f "$script" ]; then
        echo "  [ERROR] Script not found: $script"
        MISSING=1
    fi
done
if [ "$MISSING" -eq 1 ]; then
    echo ""
    echo "  Make sure scripts are in the same directory as run_all_tools.sh:"
    echo "  $SCRIPT_DIR"
    exit 1
fi

# Initialize timing log
{
    echo "============================================================"
    echo "  TIMING SUMMARY - Static Analysis 3-Run Benchmark"
    echo "  Started: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "  Tools   : ${TOOLS_TO_RUN[*]}"
    echo "============================================================"
    echo ""
} > "$TIMING_LOG"

MASTER_START=$(date +%s)

print_divider
echo "  STATIC ANALYSIS - MASTER MONITORING DASHBOARD"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "  Tools     : ${TOOLS_TO_RUN[*]}"
echo "  Runs each : $TOTAL_RUNS"
echo "  Projects  : $TOTAL_PROJECTS"
echo "  Logs dir  : $LOG_DIR"
print_divider
echo ""

# Run selected tools in order
for tool in "${TOOLS_TO_RUN[@]}"; do
    case "$tool" in
        spotbugs)  run_tool_all_runs "SpotBugs"   "$SCRIPT_DIR/run_spotbugs.sh"   "$SPOTBUGS_OUT"   "xml" ;;
        pmd)       run_tool_all_runs "PMD"        "$SCRIPT_DIR/run_pmd.sh"        "$PMD_OUT"        "xml" ;;
        checkstyle) run_tool_all_runs "Checkstyle" "$SCRIPT_DIR/run_checkstyle.sh" "$CHECKSTYLE_OUT" "xml" ;;
        sonarqube) run_tool_all_runs "SonarQube"  "$SCRIPT_DIR/run_sonarqube.sh"  "$SONARQUBE_OUT"  "json" ;;
    esac
done

# Final Master Summary
MASTER_END=$(date +%s)
MASTER_DURATION=$(( MASTER_END - MASTER_START ))

{
    echo ""
    echo "============================================================"
    echo "  GRAND TOTAL"
    echo "  Finished : $(date '+%Y-%m-%d %H:%M:%S')"
    echo "  Total wall-clock time: $(format_duration $MASTER_DURATION)"
    echo "============================================================"
} >> "$TIMING_LOG"

print_divider
echo "  ALL TOOLS COMPLETED"
echo "  Finished  : $(date '+%Y-%m-%d %H:%M:%S')"
echo "  Total time: $(format_duration $MASTER_DURATION)"
echo ""
echo "  TIMING SUMMARY saved to:"
echo "  $TIMING_LOG"
print_divider
echo ""
echo "  Per-tool timing breakdown:"
echo ""
cat "$TIMING_LOG"
