#!/bin/sh
# Put the tracked hooks into .git/hooks, where git looks for them.
#
# .git/hooks is not part of the repository, so a hook that matters has to be
# tracked somewhere a person can read it and installed from there. Run this
# after cloning.
set -e

root=$(git rev-parse --show-toplevel)
cp "$root/tools/pre-push-guard.sh" "$root/.git/hooks/pre-push"
chmod +x "$root/.git/hooks/pre-push"
echo "installed .git/hooks/pre-push  (from tools/pre-push-guard.sh)"
