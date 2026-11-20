#!/bin/bash
# Django tests of a worktree's plugin, in a throwaway container like mp-webapp (whose mount is the main checkout),
# leaving nothing in the worktree (no bytecode; the main checkout's node_modules mounted read-only, so WebODM installs none):
#   .claude/skills/test/worktree_test.sh <worktree> <test module>... (e.g. test_air; app.tests... labels as they are)
WT="${1:?worktree}"; shift
labels=""; for m in "$@"; do case "$m" in *.*) labels="$labels $m";; *) labels="$labels coreplugins.mission_planner.tests.$m";; esac; done
venv=$(docker inspect mp-webapp --format '{{range .Mounts}}{{if eq .Destination "/webodm/venv"}}{{.Name}}{{end}}{{end}}')
docker run --rm --name mp-test-worktree --network webodm-mission-planner_default \
  --env-file <(docker inspect mp-webapp --format '{{range .Config.Env}}{{println .}}{{end}}') \
  -v /home/winux/gitrepos/web/webodm-mission-planner/ignored/WebODM:/webodm -v "$venv":/webodm/venv \
  -v webodm-mission-planner_appmedia:/webodm/app/media -v "$WT/mission_planner":/webodm/coreplugins/mission_planner \
  -v /home/winux/gitrepos/web/webodm-mission-planner/mission_planner/public/node_modules:/webodm/coreplugins/mission_planner/public/node_modules:ro \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -w /webodm --entrypoint "" "$(docker inspect mp-webapp --format '{{.Config.Image}}')" python manage.py test --noinput $labels
