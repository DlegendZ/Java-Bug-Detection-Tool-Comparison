#!/bin/bash

PROJECTS_DIR="$HOME/defects4j-projects"
OUTPUT_DIR="$HOME/sonarqube-results"
SONAR_URL="http://localhost:9000"
SONAR_TOKEN="${SONAR_TOKEN}"
SONAR_ADMIN_PASSWORD="${SONAR_ADMIN_PASSWORD:-admin}"

# Java 11 is required by Defects4J
JAVA11_HOME=$(update-alternatives --list java 2>/dev/null | grep "java-11" | head -1 | sed 's|/bin/java||')
if [ -z "$JAVA11_HOME" ]; then
    echo "  [ERROR] Java 11 not found. Install it: sudo apt install openjdk-11-jdk -y"
    exit 1
fi

mkdir -p $OUTPUT_DIR

declare -A PROJECT_COUNTS
PROJECT_COUNTS=( ["Chart"]=26 ["Closure"]=174 ["Lang"]=61 ["Math"]=106 ["Time"]=26 )
IDENTIFIERS=("Chart" "Closure" "Lang" "Math" "Time")

total_processed=0
total_skipped=0
total_warning=0
total_issues_all=0

echo "============================================"
echo "  SonarQube Automation - Defects4J Dataset"
echo "============================================"
echo ""

server_status=$(curl -s "$SONAR_URL/api/system/status" \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','DOWN'))" 2>/dev/null)

if [ "$server_status" != "UP" ]; then
    echo "  [ERROR] SonarQube server is not running at $SONAR_URL"
    echo "  Start it first: ~/start_sonarqube.sh"
    exit 1
fi

echo "  [INFO] SonarQube server is UP at $SONAR_URL"
echo ""

for identifier in "${IDENTIFIERS[@]}"; do
    max=${PROJECT_COUNTS[$identifier]}
    echo "############################################"
    echo "  START: $identifier (1 - $max)"
    echo "############################################"

    identifier_issues=0
    identifier_processed=0
    identifier_skipped=0
    identifier_warning=0

    for i in $(seq 1 $max); do
        project_name="${identifier}_${i}_buggy"
        project_dir="$PROJECTS_DIR/$project_name"
        output_json="$OUTPUT_DIR/${project_name}.json"
        project_key=$(echo "$project_name" | tr '[:upper:]' '[:lower:]' | tr '_' '-')

        if [ ! -d "$project_dir" ]; then
            echo "  [WARNING] Project folder not found: $project_name"
            ((identifier_warning++)); ((total_warning++))
            continue
        fi

        if [ -f "$output_json" ]; then
            issue_count=$(python3 -c "
import json
with open('$output_json') as f:
    data = json.load(f)
print(data.get('total_accurate', data.get('total', 0)))
" 2>/dev/null || echo 0)
            echo "  [SKIP] $project_name (already exists: $issue_count issues)"
            ((identifier_skipped++)); ((total_skipped++))
            ((identifier_issues+=issue_count)); ((total_issues_all+=issue_count))
            continue
        fi

        echo "  [RUN] $project_name ..."

        SRC_DIR=$(cd "$project_dir" && JAVA_HOME="$JAVA11_HOME" defects4j export -p dir.src.classes 2>/dev/null)
        if [ -z "$SRC_DIR" ] || [ ! -d "$project_dir/$SRC_DIR" ]; then
            echo "  [WARNING] No source directory found: $project_name"
            ((identifier_warning++)); ((total_warning++))
            continue
        fi

        echo "  [COMPILE] Compiling $project_name..."
        (cd "$project_dir" && JAVA_HOME="$JAVA11_HOME" defects4j compile > /dev/null 2>&1)
        if [ $? -ne 0 ]; then
            echo "  [WARNING] Compilation failed: $project_name"
            ((identifier_warning++)); ((total_warning++))
            continue
        fi

        CLASS_DIR=$(cd "$project_dir" && JAVA_HOME="$JAVA11_HOME" defects4j export -p dir.bin.classes 2>/dev/null)
        if [ -z "$CLASS_DIR" ] || [ ! -d "$project_dir/$CLASS_DIR" ]; then
            echo "  [WARNING] No .class directory found: $project_name"
            ((identifier_warning++)); ((total_warning++))
            continue
        fi

        curl -s -X POST -u "admin:$SONAR_ADMIN_PASSWORD" \
            "$SONAR_URL/api/projects/delete?project=$project_key" > /dev/null 2>&1
        rm -rf "$project_dir/.scannerwork"
        sleep 5

        sonar-scanner \
            -Dsonar.projectKey="$project_key" \
            -Dsonar.projectName="$project_name" \
            -Dsonar.sources="$project_dir/$SRC_DIR" \
            -Dsonar.java.binaries="$project_dir/$CLASS_DIR" \
            -Dsonar.host.url="$SONAR_URL" \
            -Dsonar.login="$SONAR_TOKEN" \
            -Dsonar.language=java \
            -Dsonar.sourceEncoding=UTF-8 \
            -Dsonar.scm.disabled=true > /dev/null 2>&1

        if [ $? -ne 0 ]; then
            echo "  [WARNING] SonarScanner failed: $project_name"
            ((identifier_warning++)); ((total_warning++))
            continue
        fi

        elapsed=0
        while [ $elapsed -lt 120 ]; do
            status=$(curl -s -u "$SONAR_TOKEN:" \
                "$SONAR_URL/api/ce/component?component=$project_key" \
                | python3 -c "
import sys, json
data = json.load(sys.stdin)
queue = data.get('queue', [])
current = data.get('current', {})
if queue or current.get('status') in ('IN_PROGRESS', 'PENDING'):
    print('IN_PROGRESS')
else:
    print(current.get('status', 'SUCCESS'))
" 2>/dev/null)
            if [ "$status" = "SUCCESS" ] || [ "$status" = "FAILED" ] || [ "$status" = "CANCELED" ]; then
                break
            fi
            sleep 5
            ((elapsed+=5))
        done
        sleep 20

        issue_count=0
        for retry in $(seq 1 5); do
            issue_count=$(curl -s -u "$SONAR_TOKEN:" \
                "$SONAR_URL/api/issues/search?componentKeys=$project_key&ps=1&resolved=false" \
                | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(data.get('total', 0))
" 2>/dev/null || echo 0)
            if [ "$issue_count" -gt 0 ]; then break; fi
            sleep 10
        done

        python3 - <<PYEOF > "$output_json" 2>/dev/null
import urllib.request, urllib.parse, json, math, base64

token = "$SONAR_TOKEN"
base_url = "$SONAR_URL/api/issues/search"
total = $issue_count
total_pages = math.ceil(total / 500) if total > 0 else 1
auth = base64.b64encode(f"{token}:".encode()).decode()
headers = {"Authorization": f"Basic {auth}"}

all_issues = []
for page in range(1, total_pages + 1):
    params = urllib.parse.urlencode({
        "componentKeys": "$project_key",
        "ps": 500,
        "p": page,
        "resolved": "false",
        "types": "BUG,VULNERABILITY,CODE_SMELL"
    })
    req = urllib.request.Request(f"{base_url}?{params}", headers=headers)
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    issues = data.get("issues", [])
    if not issues:
        break
    all_issues.extend(issues)

output = {
    "total_accurate": total,
    "issues_fetched": len(all_issues),
    "issues": all_issues
}
print(json.dumps(output, indent=2))
PYEOF

        if [ ! -f "$output_json" ]; then
            echo "  [WARNING] Output JSON not created: $project_name"
            ((identifier_warning++)); ((total_warning++))
            continue
        fi

        echo "  [DONE] $project_name -> $issue_count issues found"
        ((identifier_issues+=issue_count)); ((total_issues_all+=issue_count))
        ((identifier_processed++)); ((total_processed++))
    done

    echo ""
    echo "  --- Summary: $identifier ---"
    echo "  Processed   : $identifier_processed"
    echo "  Skipped     : $identifier_skipped"
    echo "  Warnings    : $identifier_warning"
    echo "  Total issues: $identifier_issues"
    echo ""
done

echo "============================================"
echo "  COMPLETED - Overall Summary"
echo "============================================"
echo "  Total processed   : $total_processed projects"
echo "  Total skipped     : $total_skipped projects"
echo "  Total warnings    : $total_warning projects"
echo "  Total issues      : $total_issues_all issues"
echo "  Total JSON files  : $(ls $OUTPUT_DIR/*.json 2>/dev/null | wc -l) files"
echo "============================================"