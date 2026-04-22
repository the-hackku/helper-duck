#!/bin/sh
set -e

DB_FILE="${DB_FILE:-/home/bot/data/database.db}"

# Ensure db exists
if [ ! -f "$DB_FILE" ]; then
    echo "Initializing database at $DB_FILE"
    sqlite3 "$DB_FILE" < /home/bot/db_init.sql
fi

exec python main.py
