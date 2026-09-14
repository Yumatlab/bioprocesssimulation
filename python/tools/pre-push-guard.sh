#!/bin/sh
# A pre-push hook that refuses to touch anything that is already on the remote.
#
# Why this exists: this repository has no history in common with what already
# lies in the GitHub repository — that is the MATLAB application, years of
# work, and it must not be mixed into this one or replaced by it. Git will
# normally refuse a non-fast-forward push on its own, but "normally" leaves
# three ways through: `--force`, `--force-with-lease`, and pushing a branch
# that happens to be empty on the other side and then merging carelessly.
# This hook closes the first two and makes the third deliberate.
#
# Install it with: tools/install-hooks.sh
#
# Three rules, and each one names what it is protecting:
#
#   1. Never delete a remote branch.
#   2. Never overwrite a remote branch with something that is not a
#      continuation of it. This is what a forced push does, and it is the
#      only way to actually lose someone else's commits. It also catches the
#      case this repository was built for: two histories with no common
#      root, where nothing on the remote is an ancestor of anything here.
#   3. Not to main or master unless it is said out loud. Adding to the
#      MATLAB history is a legitimate thing to do; doing it by accident is
#      not. Rule 2 already makes it impossible to lose anything, so this is
#      about intent, not about safety:
#
#          BIOFERM_PUSH_MAIN=1 git push origin matlab-main:main
#
# There is no flag for rules 1 and 2, and no flag is planned. Refusing to be
# overridden is their whole purpose.

PROTECTED="refs/heads/main refs/heads/master"
ZERO="0000000000000000000000000000000000000000"

status=0

# stdin: <local ref> <local sha> <remote ref> <remote sha>, one line per ref.
while read -r local_ref local_sha remote_ref remote_sha; do
    [ -z "$remote_ref" ] && continue

    if [ -z "$BIOFERM_PUSH_MAIN" ]; then
        for protected in $PROTECTED; do
            if [ "$remote_ref" = "$protected" ]; then
                echo "pre-push: refusing to push to $remote_ref without being asked to." >&2
                echo "          That branch holds the MATLAB application. Either push" >&2
                echo "          to a branch of its own," >&2
                echo "              git push origin main:python-port" >&2
                echo "          or say that main is really meant:" >&2
                echo "              BIOFERM_PUSH_MAIN=1 git push origin <local>:main" >&2
                status=1
            fi
        done
    fi

    if [ "$local_sha" = "$ZERO" ]; then
        echo "pre-push: refusing to delete $remote_ref on the remote." >&2
        status=1
        continue
    fi

    # An empty remote side is a new branch: nothing there to lose.
    [ "$remote_sha" = "$ZERO" ] && continue

    # Everything the remote has must still be reachable from what we send.
    # If it is not, this push would drop commits that exist only there.
    if ! git merge-base --is-ancestor "$remote_sha" "$local_sha" 2>/dev/null; then
        echo "pre-push: refusing to overwrite $remote_ref." >&2
        echo "          The remote has commits that would be lost —" >&2
        echo "          ${remote_sha%"${remote_sha#???????}"}… is not an ancestor of what is being pushed." >&2
        echo "          Fetch and look at them before deciding anything." >&2
        status=1
    fi
done

if [ "$status" -ne 0 ]; then
    echo "pre-push: nothing was pushed." >&2
fi
exit "$status"
