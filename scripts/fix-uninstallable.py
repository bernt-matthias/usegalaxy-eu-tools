# Check all revisions in the lockfile if they are installable.
# Remove if not and add the next installable revision.
#
# Only updates the lock file and does not install
# or uninstall any tools from a Galaxy instance.
#
# Backgroud: for each tool version there can be only one revision installed
# (multiple revisions with the same version happen e.g. if the version
# is not bumped but some files are updated)
#
# Revisions that became not-installable are treated as a safe update
# because the author claims the tool did not change its behavior from
# the reproducibility perspective.
#
# The script queries the TS to get_ordered_installable_revisions
# and clones (to /tmp/) the mercurial repos to get all revisions
# (the later is only done for tools with revisions that are not
# installable).

import argparse
import subprocess
import os.path
import yaml

from bioblend import toolshed
from galaxy.tool_util.loader_directory import load_tool_sources_from_path


def clone(toolshed_url, name, owner, repo_path):
    if not os.path.exists(repo_path):
        print(f"Cloning {toolshed_url} {owner} {name} {repo_path}")
        cmd = [
            "hg",
            "clone",
            f"{toolshed_url}/repos/{owner}/{name}",
            repo_path,
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def get_all_revisions(toolshed_url, name, owner):
    repo_path = f"/tmp/toolshed-{owner}-{name}"
    clone(toolshed_url, name, owner, repo_path)
    cmd = ["hg", "log", "--template", "{node|short}\n"]
    result = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True)
    return list(reversed(result.stdout.splitlines()))


def fix_uninstallable(lockfile_name, toolshed_url):
    ts = toolshed.ToolShedInstance(url=toolshed_url)

    with open(lockfile_name) as f:
        lockfile = yaml.safe_load(f)
        tools = lockfile["tools"]

    for i, tool in enumerate(tools):
        name = tool["name"]
        owner = tool["owner"]
        print(f"Checking {toolshed_url} {owner} {name} ")
        # get ordered_installable_revisions from oldest to newest
        ordered_installable_revisions = (
            ts.repositories.get_ordered_installable_revisions(name, owner)
        )

        if len(set(tool["revisions"]) - set(ordered_installable_revisions)):
            all_revisions = get_all_revisions(toolshed_url, name, owner)

        to_remove = []
        to_append = []
        for cur in tool["revisions"]:
            if cur in ordered_installable_revisions:
                continue
            if cur not in all_revisions:
                print(f"Removing {cur} -- it is not a valid revision of {name} {owner}")
                to_remove.append(cur)
                continue
            start = all_revisions.index(cur)
            nxt = None
            for i in range(start, len(all_revisions)):
                if all_revisions[i] in ordered_installable_revisions:
                    nxt = all_revisions[i]
                    break
            if nxt:
                print(f"Removing {cur} in favor of {nxt} {name} {owner}")
                to_remove.append(cur)
                if nxt not in tool["revisions"]:
                    print(f"Adding {nxt} which was absent so far {name} {owner}")
                    to_append.append(nxt)
            else:
                print(f"Could not determine the next revision for {cur} {name} {owner}")

        for r in to_remove:
            tool["revisions"].remove(r)
        tool["revisions"].extend(to_append)

        # maintaing unified sorting standard
        tool["revisions"] = sorted(list(set(map(str, tool['revisions']))))

    with open(lockfile_name, "w") as handle:
        yaml.dump(lockfile, handle, default_flow_style=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "lockfile", type=argparse.FileType("r"), help="Tool.yaml.lock file"
    )
    parser.add_argument(
        "--toolshed",
        default="https://toolshed.g2.bx.psu.edu",
        help="Toolshed to test against",
    )
    args = parser.parse_args()
    fix_uninstallable(args.lockfile.name, args.toolshed)
