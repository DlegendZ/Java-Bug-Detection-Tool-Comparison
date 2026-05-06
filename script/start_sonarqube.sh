#!/bin/bash

echo "============================================"
echo "  SonarQube Server - Startup Script"
echo "============================================"
echo ""

# Step 1: Set vm.max_map_count (required for Elasticsearch)
echo "  [CONFIG] Setting vm.max_map_count to 262144..."
sudo sysctl -w vm.max_map_count=262144 > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "  [OK] vm.max_map_count set successfully"
else
    echo "  [WARNING] Failed to set vm.max_map_count (may need sudo)"
fi

# Step 2: Clean temp files from previous session
echo "  [CLEAN] Removing stale temp files..."
sudo rm -rf /opt/sonarqube/temp/*
sudo rm -f /opt/sonarqube/bin/linux-x86-64/SonarQube.pid
echo "  [OK] Temp files cleaned"

# Step 3: Fix ownership
echo "  [PERM] Fixing ownership for sonarqube user..."
sudo chown -R sonarqube:sonarqube /opt/sonarqube > /dev/null 2>&1
echo "  [OK] Ownership fixed"

# Step 4: Start SonarQube
echo ""
echo "  [START] Starting SonarQube server..."
sudo -u sonarqube /opt/sonarqube/bin/linux-x86-64/sonar.sh start > /dev/null 2>&1
echo "  [OK] Start command issued"
echo ""

# Step 5: Wait for SonarQube to be fully operational
echo "  [WAIT] Waiting for SonarQube to be ready..."
echo ""

success=false
for i in $(seq 1 36); do
    STATUS=$(curl -s http://localhost:9000/api/system/status 2>/dev/null)
    if echo "$STATUS" | grep -q '"status":"UP"'; then
        success=true
        break
    fi
    echo "  [${i}/36] Not ready yet, retrying in 5 seconds..."
    sleep 5
done

echo ""
echo "============================================"
if [ "$success" = true ]; then
    echo "  RESULT: SonarQube is UP and operational"
    echo "============================================"
    echo "  URL     : http://localhost:9000"
    echo "  Login   : admin / admin (change on first login)"
    echo "============================================"
else
    echo "  RESULT: SonarQube failed to start in time"
    echo "============================================"
    echo "  Check logs with:"
    echo "  tail -f /opt/sonarqube/logs/sonar.log"
    echo "  tail -f /opt/sonarqube/logs/es.log"
    echo "============================================"
    exit 1
fi
