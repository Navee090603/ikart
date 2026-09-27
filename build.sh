#!/usr/bin/env bash
set -o errexit
pip install -r requirements.txt
./scripts/build_css.sh
python manage.py collectstatic --no-input
python manage.py migrate
