---
name: test
description: Run the DJI Mission Planner plugin's checks (Ruff, ESLint, Jest, Django tests in the dev container) before committing or merging.
---

# Tests and checks

From the repo root, with the dev stack up (`dev/webodm.sh ps`; start it with `dev/webodm.sh up`). The stack
is WebODM 4.0.0 (`mp-webapp`, :8009).

1. **Ruff** (Python 3.14, WebODM 4.0.0's, and lint): `.venv/bin/ruff check .`
2. **ESLint** (the ES5 scripts in `mission_planner/public`): `npm run lint -- mission_planner`
3. **Jest**: `npm test` (add a path or `-t "<name>"` to run fewer).
4. **Django**, the test modules by name (discovery does not find them: WebODM's `coreplugins` is no package):
   `labels=$(ls mission_planner/tests/test_*.py | sed 's|mission_planner/tests/\(.*\)\.py|coreplugins.mission_planner.tests.\1|')`, then
   `docker exec -w /webodm mp-webapp python manage.py test --noinput $labels`.
   Before a merge, also WebODM's plugin tests: `app.tests.test_plugins`. Never two Django runs at once: they share
   the test database.
   Work in a worktree: `mp-webapp` mounts the main checkout, so run the worktree's tests with
   `.claude/skills/test/worktree_test.sh <worktree> <modules...>` (a throwaway `mp-test-worktree` container from the
   same image, environment, network and volumes, the worktree's `mission_planner` mounted instead).
   A test run starts WebODM in test mode, which adds a `test` plugin row to the dev database; until the webapp
   restarts, Administration > Plugins fails (500). Remove the row afterwards:
   `docker exec -w /webodm mp-webapp python manage.py shell -c "from app.plugins.functions import sync_plugin_db; sync_plugin_db()"`.

A failure is reported with its output. Before calling one pre-existing, check whether it also fails on `main`.
