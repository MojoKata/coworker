"""Container images (README.md, "Container images"): a project's deps.json declares them under
"container_images" (declaring is claiming), deps check and status pull the missing ones, and
containers list / remove say and delete what no project claims. Against a stand-in docker."""

import json
import os
import subprocess
import unittest
from pathlib import Path

from test_deps import Case

ROOT = Path(__file__).resolve().parent.parent
CONTAINERS = str(ROOT / "libexec" / "containers")

# docker image ls/inspect/pull/rmi and system df over a JSON list of images in $FAKE_IMAGES
DOCKER = r'''#!/usr/bin/env python3
import json, os, sys
db = os.environ["FAKE_IMAGES"]
images = json.load(open(db)) if os.path.exists(db) else []
a = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write("docker " + " ".join(a) + "\n")
if a[:2] == ["image", "ls"]:
    print("\n".join(i["Id"] for i in images))
elif a[:2] == ["image", "inspect"]:
    print(json.dumps([i for i in images if i["Id"] in a[2:]]))
elif a[:2] == ["system", "df"]:
    print(json.dumps({"Type": "Images", "Size": "1GB"}))
    print(json.dumps({"Type": "Build Cache", "Size": "2.7GB"}))
    print(json.dumps({"Type": "Local Volumes", "Size": "0B"}))
elif a[0] == "pull":
    ref = a[1]
    repo, _, digest = ref.partition("@")
    name = repo.rsplit(":", 1)[0] if ":" in repo.rsplit("/", 1)[-1] else repo
    images.append({"Id": "sha256:pulled" + str(len(images)), "RepoTags": [repo] if repo != name else [],
                   "RepoDigests": [f"{name}@{digest}"] if digest else [], "Size": 1000000, "Created": "2026-11-07T00:00:00Z"})
    json.dump(images, open(db, "w"))
elif a[0] == "rmi":
    if a[1] in os.environ.get("FAKE_INUSE", ""):
        print(f"Error response from daemon: conflict: unable to remove {a[1]}: image is being used", file=sys.stderr)
        sys.exit(1)
    json.dump([i for i in images if i["Id"] != a[1]], open(db, "w"))
'''

D1 = "sha256:" + "1" * 64
D2 = "sha256:" + "2" * 64


def img(n, tags=(), digests=(), size=100_000_000, created="2026-11-01T00:00:00Z"):
    return {"Id": f"sha256:{n:064d}", "RepoTags": list(tags), "RepoDigests": list(digests), "Size": size, "Created": created}


class Images(Case):
    def setUp(self):
        super().setUp()
        stub = self.tmp / "stubs" / "docker"
        stub.write_text(DOCKER)
        stub.chmod(0o755)
        self.env.update(FAKE_IMAGES=str(self.tmp / "images.json"))
        self.a = self.project("one", {"container_images": [
            {"image": f"ubuntu:22.04@{D1}", "why": "builds it"},
            {"image": "one-build", "built": "scripts/build.sh", "from": [f"ubuntu:24.04@{D2}"], "why": "tier 1"}]})
        self.b = self.project("two", {"container_images": [{"image": f"ubuntu:22.04@{D1}", "why": "also"},
                                                           {"image": "tobix/pywine:3.12", "why": "Wine"}]})

    def images(self, *imgs):
        Path(self.env["FAKE_IMAGES"]).write_text(json.dumps(list(imgs)))

    def containers(self, *args, rc=None, **env):
        res = subprocess.run(["sh", CONTAINERS, *args], capture_output=True, text=True, timeout=60, env={**self.env, **env})
        if rc is not None:
            self.assertEqual(res.returncode, rc, res.stdout + res.stderr)
        return res

    def register(self):
        for d in (self.a, self.b):
            self.deps("register", d, rc=0)

    # -- declaring ------------------------------------------------------------------------------

    def test_a_pulled_image_names_its_tag_or_digest_and_a_built_one_its_repository(self):
        for bad in ({"image": "ubuntu", "why": "w"},
                    {"image": "x:1", "built": "b.sh", "why": "w"},
                    {"image": "x", "built": "b.sh", "from": ["ubuntu"], "why": "w"},
                    {"image": "x:1", "from": ["ubuntu:24.04"], "why": "w"},
                    {"image": "x:1", "min": "1", "why": "w"}):
            d = self.project("bad", {"container_images": [bad]})
            self.deps("check", "--no-network", d, rc=2)
        d = self.project("bad", {"host": [{"package": "a", "built": "x", "why": "w"}]})
        self.assertIn("are a container image's", self.deps("check", "--no-network", d, rc=2).stderr)
        d = self.project("bad", {"vms": {"win10": {"container_images": [{"image": "x:1", "why": "w"}]}}})
        self.deps("check", "--no-network", d, rc=2)

    def test_check_says_a_pulled_image_isnt_here_without_failing_and_install_pulls_it(self):
        self.images(img(1, [f"ubuntu:22.04"], [f"ubuntu@{D1}"]))
        out = self.deps("check", "--no-network", self.b, rc=0).stdout     # docker pulls it on first use
        self.assertIn("not here (pulled on first use)", self.line(out, "tobix/pywine:3.12"))
        self.assertIn("here", self.line(out, f"ubuntu:22.04@{D1}"))
        self.deps("install", self.b)
        self.assertIn("docker pull tobix/pywine:3.12", Path(self.env["FAKE_LOG"]).read_text())
        self.assertNotIn("docker pull ubuntu", Path(self.env["FAKE_LOG"]).read_text())

    def test_no_docker_is_a_problem_when_a_project_declares_images(self):
        res = self.deps("check", "--no-network", self.b, rc=1, COWORKER_DOCKER="no-such-docker")
        self.assertIn("no docker", self.line(res.stdout, "tobix/pywine:3.12"))

    def test_a_built_image_not_built_yet_is_no_problem_and_its_base_is_claimed(self):
        self.images(img(1, [f"ubuntu:22.04"], [f"ubuntu@{D1}"]))
        out = self.deps("check", "--no-network", self.a, rc=0).stdout
        self.assertIn("not built yet (scripts/build.sh)", self.line(out, "one-build"))
        self.assertIn("not here", self.line(out, f"ubuntu:24.04@{D2}"))    # the base, claimed by one

    def test_a_built_image_as_anothers_base_is_never_pulled(self):
        d = self.project("three", {"container_images": [
            {"image": "three-base", "built": "b.sh", "from": [f"ubuntu:24.04@{D2}"], "why": "w"},
            {"image": "three-top", "built": "b.sh", "from": ["three-base:latest"], "why": "w"}]})
        self.images()
        out = self.deps("check", "--no-network", d, rc=0).stdout
        self.assertNotIn("three-base:latest", out)
        self.deps("install", d)
        self.assertNotIn("docker pull three-base", Path(self.env["FAKE_LOG"]).read_text())
        self.deps("register", d, rc=0)
        self.assertNotIn("three-base:latest", self.containers("list", rc=0).stdout)

    def test_status_is_ready_without_pulling(self):
        """CI runs status in every job: pulling every declared image there would cost gigabytes
        each time, and docker pulls what a job runs anyway."""
        self.images()
        res = subprocess.run(["python3", str(ROOT / "libexec" / "deps"), "status", "--no-network", self.b],
                             capture_output=True, text=True, env={**self.env, "FAKE_RPMS": "curl=8-1 openssh-clients=9-1 python3=3.12-1 util-linux=2-1"})
        self.assertIn("ready", res.stdout, res.stdout + res.stderr)
        self.assertNotIn("docker pull", Path(self.env["FAKE_LOG"]).read_text())

    # -- containers list ------------------------------------------------------------------------

    def test_list_names_each_images_claimants_and_what_no_one_claims(self):
        self.register()
        self.images(img(1, ["ubuntu:22.04"], [f"ubuntu@{D1}"]),
                    img(2, ["ubuntu:22.04"], ["ubuntu@sha256:" + "9" * 64]),            # an older pin
                    img(3, ["one-build:aaa"], created="2026-11-05T00:00:00Z"),
                    img(4, ["one-build:bbb"], created="2026-11-06T00:00:00Z"),
                    img(5, ["alpine:latest"], size=12_700_000),
                    img(6))
        out = self.containers("list", rc=0).stdout
        lines = {l.split(" | ")[0]: l for l in out.splitlines() if " | " in l}
        self.assertIn("claimed by one, two", out)
        self.assertIn("one-build:bbb | 100.0 MB | claimed by one", out)
        self.assertIn("one-build:aaa | 100.0 MB | superseded: an older build of one-build (one)", out)
        self.assertIn(f"near miss: declared is ubuntu:22.04@{D1}", out)
        self.assertIn("alpine:latest | 12.7 MB | undeclared", out)
        self.assertIn("dangling (no tag)", out)
        self.assertIn(f"ubuntu:24.04@{D2} | not here | wanted by one", out)
        self.assertIn("tobix/pywine:3.12 | not here | wanted by two", out)
        self.assertIn("(build cache: 2.7GB, never removed by coworker)", out)
        self.assertIn("removable (containers remove): 4 image(s), 312.7 MB", out)

    def test_a_vm_recipes_image_is_claimed_by_the_vm(self):
        r = self.home / "recipes" / "win10"
        r.mkdir(parents=True)
        (r / "recipe.env").write_text(f"IMAGE=dockurr/windows@{D2}   # its image\n")
        self.images(img(1, ["dockurr/windows:latest"], [f"dockurr/windows@{D2}"]))
        self.assertIn("claimed by the VM win10", self.containers("list", rc=0).stdout)

    # -- containers remove ----------------------------------------------------------------------

    def test_remove_is_a_human_call_and_removes_only_what_no_one_claims(self):
        self.register()
        self.images(img(1, ["ubuntu:22.04"], [f"ubuntu@{D1}"]), img(3, ["one-build:aaa"], created="2026-11-05T00:00:00Z"),
                    img(4, ["one-build:bbb"], created="2026-11-06T00:00:00Z"), img(5, ["alpine:latest"]))
        res = self.containers("remove", rc=3)
        self.assertIn("a human's call: containers remove --yes", res.stderr)
        self.assertIn("alpine:latest", res.stderr)
        self.assertNotIn("docker rmi", Path(self.env["FAKE_LOG"]).read_text())
        out = self.containers("remove", "--yes", rc=0).stdout
        self.assertIn("removed alpine:latest", out)
        self.assertIn("removed one-build:aaa", out)
        left = {i["RepoTags"][0] for i in json.loads(Path(self.env["FAKE_IMAGES"]).read_text())}
        self.assertEqual(left, {"ubuntu:22.04", "one-build:bbb"})

    def test_remove_unattended_needs_no_yes_and_keeps_an_image_in_use(self):
        self.register()
        self.images(img(5, ["alpine:latest"]), img(7, ["hello-world:latest"]))
        res = self.containers("remove", rc=1, COWORKER_UNATTENDED="1", FAKE_INUSE=f"sha256:{7:064d}")
        self.assertIn("removed alpine:latest", res.stdout)
        self.assertIn("kept hello-world:latest", res.stderr)

    def test_remove_needs_a_projects_protocol_and_list_does_not(self):
        self.images(img(5, ["alpine:latest"]))
        env = {"COWORKER_CLIENT_PROTOCOL": ""}
        self.assertIn("not through a project's coworker submodule", self.containers("remove", "--yes", rc=3, **env).stderr)
        self.containers("list", rc=0, **env)


if __name__ == "__main__":
    unittest.main()
