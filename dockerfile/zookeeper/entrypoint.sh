#!/bin/bash
set -e

if [ -z "$MY_ID" ]; then
    HOSTNAME=$(hostname)
    MY_ID=$(echo "$HOSTNAME" | sed 's/.*-//')
    MY_ID=$((MY_ID + 1))
fi

echo "$MY_ID" > "$ZOO_DATA_DIR/myid"
echo "Generated myid: $MY_ID"

if [ "$1" = "start-foreground" ]; then
    exec zkServer.sh start-foreground
else
    exec "$@"
fi

