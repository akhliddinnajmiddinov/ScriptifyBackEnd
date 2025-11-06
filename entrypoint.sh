#!/bin/bash
set -e
until nc -z db 5432; do
    echo "Waiting for PostgreSQL..."
    sleep 2
done
echo "PostgreSQL is up!"
exec "$@"