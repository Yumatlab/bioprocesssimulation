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
#   1. Never write to the remote's main or master. Our history goes to its
#      own branch; bringing the two together is a decision made in a pull
#      request with both sides visible, not a side effect of a push.
#   2. Never delete a remote branch.
#   3. Never overwrite a remote branch with something that is not a
#      continuation of it. This is what a forced push does, and it is the
#      only way to actually lose someone else's commits.
#
# To push somewhere this hook forbids, edit the branch list below or remove
# the hook. Refusing to be overridden by a flag is the point; refusing to be
# removed would just be theatre.

PROTECTED="refs/heads/main refs/heads/master"
ZERO="0000000000000000000000000000000000000000"

status=0

# stdin: <local ref> <local sha> <remote ref> <remote sha>, one line per ref.
while read -r local_ref local_sha remote_ref remote_sha; do
    [ -z "$remote_ref" ] && continue

    for protected in $PROTECTED; do
        if [ "$remote_ref" = "$protected" ]; then
            echo "pre-push: refusing to push to $remote_ref on the remote." >&2
            echo "          That branch holds the MATLAB application. Push to a" >&2
            echo "          branch of its own and merge through a pull request:" >&2
            echo "          git push origin main:python-port" >&2
            status=1
        fi
    done

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
