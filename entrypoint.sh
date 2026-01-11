#!/bin/bash
set -e
# Database is on external server, connection will be handled by Django
# No need to wait for local database service
exec "$@"