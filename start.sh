#!/bin/bash
export DB_PATH=/data/crm_v5.db
exec gunicorn app:app --bind 0.0.0.0:$PORT --workers 1
