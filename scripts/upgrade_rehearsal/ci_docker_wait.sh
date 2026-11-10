#!/bin/bash
# Wait for the compose stack's app container to answer /health/ (CI only).
set -euo pipefail
for _ in $(seq 1 120); do
    if curl -fsS http://127.0.0.1:8000/health/ >/dev/null 2>&1; then
        echo "app is up"
        exit 0
    fi
    if [ "$(docker inspect -f '{{.State.Status}}' clientst0r-app 2>/dev/null)" = "exited" ]; then
        docker logs --tail 200 clientst0r-app || true
        echo "app container exited"
        exit 1
    fi
    sleep 5
done
docker logs --tail 200 clientst0r-app || true
echo "app did not come up"
exit 1
