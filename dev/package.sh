#!/usr/bin/env bash
# Builds the release zip, dist/mission_planner-<version>.zip (the version from mission_planner/manifest.json), from the committed
# files of mission_planner/ with LICENSE added and without the tests, and prints its sha256 (for the GitHub
# release's notes: WebODM's Administration > Plugins upload does not check one). Commit first: uncommitted changes are not in the zip.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo"

version="$(python3 -c 'import json; print(json.load(open("mission_planner/manifest.json"))["version"])')"
zip="dist/mission_planner-$version.zip"
if [ -n "$(git status --porcelain -- mission_planner LICENSE)" ]; then
    echo "mission_planner/ or LICENSE has uncommitted changes: commit them first" >&2
    exit 1
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
# The single root folder WebODM expects; the tests stay out (public/ is served to browsers)
git archive HEAD mission_planner LICENSE | tar -x -C "$work"
mv "$work/LICENSE" "$work/mission_planner/LICENSE"
rm -rf "$work/mission_planner/tests" "$work/mission_planner/public/__tests__"

mkdir -p dist
rm -f "$zip"
# Python's zipfile, so that no zip tool is needed; folders first, sorted, as unzip lists them. Reproducible: every entry
# has the time of the last commit that changed mission_planner/ or LICENSE and fixed permissions, so a commit that
# changes neither (docs, the plan) builds the same zip, with the same sha256.
stamp="$(git log -1 --format=%ct -- mission_planner LICENSE)"
python3 - "$work" "$repo/$zip" "$stamp" <<'PY'
import os, sys, time, zipfile
root, out, stamp = sys.argv[1], sys.argv[2], int(sys.argv[3])
date_time = time.gmtime(stamp)[:6]


def entry(name, mode):
    info = zipfile.ZipInfo(name, date_time)
    info.external_attr = mode << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


with zipfile.ZipFile(out, "w") as z:
    for folder, dirs, files in sorted(os.walk(os.path.join(root, "mission_planner"))):
        dirs.sort()
        z.writestr(entry(os.path.relpath(folder, root) + "/", 0o40755), b"")
        for name in sorted(files):
            path = os.path.join(folder, name)
            with open(path, "rb") as f:
                z.writestr(entry(os.path.relpath(path, root), 0o100644), f.read())
PY
echo "$zip"
unzip -l "$zip" | tail -n +4 | head -n -2 | awk '{print "  " $4}'
echo "sha256: $(sha256sum "$zip" | cut -d' ' -f1)"
