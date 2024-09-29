import logging
import os
import sys

import requests
from git import GitCommandError

from . import sensitive_env

LOGGER = logging.getLogger(__name__)


def get_gha_run_link():
    """Get the link to the GHA run."""
    run_id = os.environ["GITHUB_RUN_ID"]
    return f"https://github.com/conda-forge-webservices/actions/runs/{run_id}"


def comment_and_push_if_changed(
    *,
    action,
    changed,
    error,
    git_repo,
    pull,
    pr_branch,
    pr_owner,
    pr_repo,
    repo_name,
    close_pr_if_no_changes_or_errors,
    help_message,
    info_message,
):
    with sensitive_env():
        token = os.environ["GH_TOKEN"]
    actor = "x-access-token"

    LOGGER.info(
        "pushing and commenting: branch|owner|repo = %s|%s|%s",
        pr_branch,
        pr_owner,
        pr_repo,
    )

    run_link = get_gha_run_link()

    push_error = False
    message = None
    if changed:
        try:
            git_repo.remotes.origin.set_url(
                f"https://{actor}:{token}@github.com/{pr_owner}/{pr_repo}.git",
                push=True,
            )
            git_repo.remotes.origin.push()
        except GitCommandError as e:
            push_error = True
            LOGGER.critical(repr(e))
            message = f"""\
Hi! This is the friendly automated conda-forge-webservice.

I tried to {action} for you, but it looks like I wasn't \
able to push to the `{pr_branch}` \
branch of `{pr_owner}`/`{pr_repo}`. Did you check the "Allow edits from \
maintainers" box?

**NOTE**: Our webservices cannot push to PRs from organization accounts \
or PRs from forks made from \
organization forks because of GitHub \
permissions. Please fork the feedstock directly from conda-forge \
into your personal GitHub account.
"""
        finally:
            git_repo.remotes.origin.set_url(
                f"https://github.com/{pr_owner}/{pr_repo}.git",
                push=True,
            )
    else:
        if error:
            message = f"""\
Hi! This is the friendly automated conda-forge-webservice.

I tried to {action} for you but ran into some issues. \
Please check the output logs of the GitHub actions workflow below for more details. \
You can also ping conda-forge/core for further assistance{help_message}.
"""
        else:
            message = f"""\
Hi! This is the friendly automated conda-forge-webservice.

I tried to {action} for you, but it looks like there was nothing to do.
"""
            if close_pr_if_no_changes_or_errors:
                message += "\nI'm closing this PR!"

    if info_message:
        if message is None:
            message = f"""\
Hi! This is the friendly automated conda-forge-webservice.

{info_message}
"""
        else:
            message += "\n" + info_message

    if message is not None:
        if run_link is not None:
            message += (
                "\n\n<sub>This message was generated by "
                f"GitHub actions workflow run [{run_link}]({run_link}).</sub>\n"
            )

        pull.create_issue_comment(message)

    if close_pr_if_no_changes_or_errors and not changed and not error:
        pull.edit(state="closed")

    return push_error


def mark_pr_as_ready_for_review(pr):
    # based on this post: https://github.com/orgs/community/discussions/70061
    if not pr.draft:
        return True

    mutation = f"""\
mutation {{
    markPullRequestReadyForReview(input:{{pullRequestId: "{pr.node_id:s}"}}) {{
        pullRequest{{id, isDraft}}
    }}
}}
"""

    with sensitive_env():
        token = os.environ["GH_TOKEN"]
    headers = {"Authorization": f"bearer {token}"}
    req = requests.post(
        "https://api.github.com/graphql",
        json={"query": mutation},
        headers=headers,
    )
    if "errors" in req.json():
        LOGGER.error(req.json()["errors"])
        return False
    else:
        return True


def flush_logger(logger):
    for handler in logger.handlers:
        try:
            # bypass locks for threading
            handler.stream.flush()
        except Exception:
            pass
    sys.stdout.flush()
    sys.stderr.flush()
    sys.__stderr__.flush()
    sys.__stdout__.flush()
