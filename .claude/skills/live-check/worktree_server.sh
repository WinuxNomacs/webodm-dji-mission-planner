#!/bin/bash
# A throwaway WebODM serving a worktree's plugin on 127.0.0.1:<port> (default 8011), to check unmerged code live without
# touching the user's server (mp-webapp serves the main checkout). It shares the dev stack's database, media and
# broker, and runs worker jobs inline (Celery eager), so a job never reaches mp-worker, which runs main's code. Nothing
# is written into the worktree (no bytecode; main's node_modules mounted read-only).
#   .claude/skills/live-check/worktree_server.sh start <worktree> [port]   (answers on /login/ after about 20 s)
#   .claude/skills/live-check/worktree_server.sh stop [port]
set -euo pipefail
cmd="${1:?start or stop}"
if [ "$cmd" = stop ]; then docker stop "mp-wt-${2:-8011}" >/dev/null && echo "stopped mp-wt-${2:-8011}"; exit; fi
WT="$(cd "${2:?worktree}" && pwd)"; PORT="${3:-8011}"
REPO="$(dirname "$(git -C "$WT" rev-parse --path-format=absolute --git-common-dir)")"   # the main checkout: WebODM, node_modules
venv=$(docker inspect mp-webapp --format '{{range .Mounts}}{{if eq .Destination "/webodm/venv"}}{{.Name}}{{end}}{{end}}')
docker run -d --rm --name "mp-wt-$PORT" --network webodm-mission-planner_default -p "127.0.0.1:$PORT:$PORT" \
  --env-file <(docker inspect mp-webapp --format '{{range .Config.Env}}{{println .}}{{end}}') \
  -v "$REPO/ignored/WebODM:/webodm" -v "$venv:/webodm/venv" \
  -v webodm-mission-planner_appmedia:/webodm/app/media -v "$WT/mission_planner:/webodm/coreplugins/mission_planner" \
  -v "$REPO/mission_planner/public/node_modules:/webodm/coreplugins/mission_planner/public/node_modules:ro" \
  -e PYTHONDONTWRITEBYTECODE=1 -w /webodm --entrypoint "" "$(docker inspect mp-webapp --format '{{.Config.Image}}')" \
  python -c "
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'webodm.settings')
django.setup()
from worker.celery import app
app.conf.task_always_eager = True
from django.core.management import call_command
call_command('runserver', '0.0.0.0:$PORT', '--noreload')
" >/dev/null
echo "mp-wt-$PORT started: http://localhost:$PORT"
