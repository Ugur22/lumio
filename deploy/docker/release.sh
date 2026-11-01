#!/bin/sh
# Runs on the server (via `make deploy` / `make rollback`): switches the stack to an image tag, or to the
# previous one with "previous". The tags live in .env next to this script.
set -eu
cd "$(dirname "$0")"

get() { sed -n "s/^$1=//p" .env; }
set_var() {
	if grep -q "^$1=" .env; then sed -i "s/^$1=.*/$1=$2/" .env; else echo "$1=$2" >> .env; fi
}

new=${1:?usage: release.sh <tag|previous>}
cur=$(get TAG)
if [ "$new" = previous ]; then new=$(get PREVIOUS_TAG); fi
[ -n "$new" ] || { echo "no previous tag recorded"; exit 1; }
# The tag goes into sed below.
case $new in *[!a-zA-Z0-9._-]*) echo "bad tag: $new"; exit 1 ;; esac

# Pull before touching .env, so a tag CI has not built yet changes nothing. Only the app image: Caddy is pinned in the compose file.
TAG=$new docker compose pull app || { echo "could not pull image $new: wait for the image workflow on main to finish, and check the package is public"; exit 1; }
if [ "$new" != "$cur" ]; then
	set_var PREVIOUS_TAG "$cur"
	set_var TAG "$new"
fi
docker compose up -d --wait --wait-timeout 90 || { echo "release of $new failed: run 'make rollback' (or see the cutover section of deploy/README.md if there is no previous tag)"; exit 1; }
# Old tags are re-pulled by a rollback, so only unused images older than two weeks are dropped.
docker image prune -af --filter until=336h > /dev/null
docker compose ps
