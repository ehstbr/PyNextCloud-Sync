#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

export PYTHONPATH="$project_root/src${PYTHONPATH:+:$PYTHONPATH}"
python3 -m compileall -q src tests
python3 -m unittest discover -s tests -v
msgfmt --check --output-file=/tmp/pynextcloud-sync-pt_BR.mo po/pt_BR.po
msgfmt --check --output-file=/tmp/pynextcloud-sync-es.mo po/es.po

