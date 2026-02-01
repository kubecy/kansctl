#!/usr/bin/env bash
set -e

response=$(echo ruok | nc 127.0.0.1 2181 2>/dev/null | tr -d '\r')

if [ "$response" = "imok" ]; then
  exit 0
else
  exit 1
fi

