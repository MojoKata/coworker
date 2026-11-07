#!/bin/sh
# repo-admin.sh: this repository's GitHub settings, as code. Needs gh, logged in; apply needs an admin
# of the repository (the owner's own account).
#
#   repo-admin.sh check    read each setting back: exit 1 when one differs, 3 when the rest are right
#                          but some couldn't be read (GitHub shows some only to admins), else 0
#   repo-admin.sh apply    set what differs, then check; a second run changes nothing
#
# Options: --repo OWNER/NAME (another repository, a fork, to try it); --yes (no questions from the
# release settings' script, below).
#
# What it sets, the same in each MojoKata repository apart from the block below:
# - a ruleset named after the default branch, on it: no deletion, no force push, a pull request to
#   merge (no approvals needed; squash the only method), the status checks below, and repository
#   admins may bypass it;
# - merging: squash only, and a pull request's branch deleted once it's merged;
# - Actions: the workflow token only reads, and can't approve pull requests; a pull request from
#   anyone outside the organization runs only after an admin approves it; every action is pinned to
#   a full-length commit SHA;
# - private vulnerability reporting on.
# --- this repository ----------------------------------------------------------------------------
REPO=MojoKata/coworker
CHECKS="test"                   # the status checks the branch ruleset requires ("": no CI)
RELEASE=                        # the release's own settings, set and checked by that script ("": none)
# ------------------------------------------------------------------------------------------------
set -eu
HERE=$(cd "$(dirname "$0")" && git rev-parse --show-toplevel)
YES=
while [ $# -gt 0 ]; do
    case $1 in
        --repo) REPO=$2; shift 2 ;;
        --yes) YES=--yes; shift ;;
        *) break ;;
    esac
done
[ $# = 1 ] || { sed -n '2,/^set -eu/p' "$0" | sed -e '$d' -e 's/^# \{0,1\}//'; exit 2; }

say() { printf '%s\n' "$*" >&2; }
die() { say "repo-admin.sh: $*"; exit 1; }
CANT="(can't read)"
# GitHub's answer, or (can't read): a refused read prints its error on stdout, which isn't the answer
api() { _a=$(gh api "repos/$REPO$1" --jq "$2" 2>/dev/null) && printf '%s\n' "$_a" || echo "$CANT"; }
ruleset_id() {  # NAME: its id, nothing when there's none, (can't read) when the rulesets can't be read
    gh api "repos/$REPO/rulesets" --jq ".[] | select(.name == \"$1\") | .id" 2>/dev/null || echo "$CANT"
}

# --- what each setting reads now, and what it should read ------------------------------------------
BRANCH=$(api "" .default_branch)
[ "$BRANCH" != "$CANT" ] || die "can't read $REPO"
RULES="deletion non_fast_forward pull_request${CHECKS:+ required_status_checks}"
want_ruleset="active branch ~DEFAULT_BRANCH; $RULES; 0 approvals, squash; checks: $(printf '%s\n' ${CHECKS:-none} | sort | paste -sd, -)"
ruleset_now() {     # ID
    api "/rulesets/$1" '"\(.enforcement) \(.target) \(.conditions.ref_name.include | join(",")); \([.rules[].type] | sort | join(" ")); \(.rules[] | select(.type == "pull_request") | .parameters | "\(.required_approving_review_count) approvals, \(.allowed_merge_methods | join(","))"); checks: \([.rules[] | select(.type == "required_status_checks") | .parameters.required_status_checks[].context] | sort | join(",") | if . == "" then "none" else . end)"'
}
bypass_now() {      # ID: how many admin bypass entries (hidden from non-admins)
    api "/rulesets/$1" 'if has("bypass_actors") then [.bypass_actors[] | select(.actor_type == "RepositoryRole" and .actor_id == 5)] | length else "(can'"'"'t read)" end'
}
merging_now() { api "" 'if .allow_squash_merge == null then "(can'"'"'t read)" else "squash \(.allow_squash_merge), merge \(.allow_merge_commit), rebase \(.allow_rebase_merge), delete branch \(.delete_branch_on_merge)" end'; }
want_merging="squash true, merge false, rebase false, delete branch true"
token_now() { api /actions/permissions/workflow '"\(.default_workflow_permissions), approves PRs: \(.can_approve_pull_request_reviews)"'; }
want_token="read, approves PRs: false"
forks_now() { api /actions/permissions/fork-pr-contributor-approval .approval_policy; }
want_forks=all_external_contributors
pinned_now() { api /actions/permissions .sha_pinning_required; }
pvr_now() { api /private-vulnerability-reporting .enabled; }

check() {
    DRIFT=0 UNREAD=0
    is() {      # WHAT NOW WANT
        if [ "$2" = "$3" ]; then say "ok       $1: $2"
        elif [ "$2" = "$CANT" ]; then say "unread   $1 (GitHub shows it to admins)"; UNREAD=1
        else say "DIFFERS  $1: $2 (want $3)"; DRIFT=1; fi
    }
    say "== $REPO (default branch $BRANCH)"
    id=$(ruleset_id "$BRANCH")
    if [ "$id" = "$CANT" ]; then is "$BRANCH ruleset" "$CANT" there
    elif [ -z "$id" ]; then is "$BRANCH ruleset" missing there
    else
        is "$BRANCH ruleset" "$(ruleset_now "$id")" "$want_ruleset"
        is "$BRANCH ruleset: admins bypass" "$(bypass_now "$id")" 1
    fi
    is "merging" "$(merging_now)" "$want_merging"
    is "workflow token" "$(token_now)" "$want_token"
    is "fork PR runs wait for approval" "$(forks_now)" "$want_forks"
    is "actions pinned by SHA" "$(pinned_now)" true
    is "private vulnerability reporting" "$(pvr_now)" true
    if [ -n "$RELEASE" ]; then
        say "== the release's settings: $RELEASE check"
        sh "$HERE/$RELEASE" --repo "$REPO" check || DRIFT=1
    fi
    [ "$DRIFT" = 0 ] || exit 1
    [ "$UNREAD" = 0 ] || exit 3
}

ruleset_json() {
    checks=""
    for c in $CHECKS; do checks="$checks${checks:+,}{\"context\": \"$c\", \"integration_id\": 15368}"; done
    printf '{"name": "%s", "target": "branch", "enforcement": "active",\n' "$BRANCH"
    printf ' "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},\n'
    printf ' "rules": [{"type": "deletion"}, {"type": "non_fast_forward"},\n'
    printf '  {"type": "pull_request", "parameters": {"required_approving_review_count": 0, "dismiss_stale_reviews_on_push": false,\n'
    printf '   "require_code_owner_review": false, "require_last_push_approval": false, "required_review_thread_resolution": false,\n'
    printf '   "allowed_merge_methods": ["squash"]}}'
    [ -z "$checks" ] || printf ',\n  {"type": "required_status_checks", "parameters": {"strict_required_status_checks_policy": false,\n   "required_status_checks": [%s]}}' "$checks"
    printf '],\n "bypass_actors": [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}]}\n'
}

apply() {
    [ "$(gh api "repos/$REPO" --jq .permissions.admin)" = true ] || die "apply needs an admin of $REPO (gh is logged in as $(gh api user --jq .login))"
    changed() { say "set      $1"; }
    say "== $REPO (default branch $BRANCH)"
    id=$(ruleset_id "$BRANCH")
    if [ -z "$id" ]; then
        ruleset_json | gh api -X POST "repos/$REPO/rulesets" --input - >/dev/null; changed "$BRANCH ruleset (made)"
    elif [ "$(ruleset_now "$id")" != "$want_ruleset" ] || [ "$(bypass_now "$id")" != 1 ]; then
        ruleset_json | gh api -X PUT "repos/$REPO/rulesets/$id" --input - >/dev/null; changed "$BRANCH ruleset"
    fi
    if [ "$(merging_now)" != "$want_merging" ]; then
        gh api -X PATCH "repos/$REPO" -F allow_squash_merge=true -F allow_merge_commit=false -F allow_rebase_merge=false \
            -F delete_branch_on_merge=true >/dev/null; changed merging
    fi
    if [ "$(token_now)" != "$want_token" ]; then
        gh api -X PUT "repos/$REPO/actions/permissions/workflow" -f default_workflow_permissions=read \
            -F can_approve_pull_request_reviews=false >/dev/null; changed "workflow token"
    fi
    if [ "$(forks_now)" != "$want_forks" ]; then
        gh api -X PUT "repos/$REPO/actions/permissions/fork-pr-contributor-approval" -f approval_policy="$want_forks" >/dev/null
        changed "fork PR runs wait for approval"
    fi
    if [ "$(pinned_now)" != true ]; then
        gh api "repos/$REPO/actions/permissions" --jq '{enabled, allowed_actions, sha_pinning_required: true}' |
            gh api -X PUT "repos/$REPO/actions/permissions" --input - >/dev/null; changed "actions pinned by SHA"
    fi
    if [ "$(pvr_now)" != true ]; then
        gh api -X PUT "repos/$REPO/private-vulnerability-reporting" >/dev/null; changed "private vulnerability reporting"
    fi
    if [ -n "$RELEASE" ]; then
        say "== the release's settings: $RELEASE setup"
        sh "$HERE/$RELEASE" --repo "$REPO" $YES setup
    fi
    check
}

case $1 in
    check|apply) "$1" ;;
    *) die "no command $1 (check or apply)" ;;
esac
