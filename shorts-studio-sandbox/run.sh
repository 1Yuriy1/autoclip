#!/bin/sh
set -eu
cd "$(dirname "$0")"
export FRAME_LAB_DATA="${FRAME_LAB_DATA:-$PWD/workspace-user}"
exec ../.venv/bin/python server.py
