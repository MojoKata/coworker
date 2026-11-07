"""VM recipes (README.md, "VM recipes"): vms create builds a VM from $COWORKER_HOME/recipes/<vm>, vms
update runs Windows Update until nothing is left, and a project can need the VM updated within so
many days. Against stand-ins for docker, ssh, scp and ssh-keyscan, as the other VM tests are."""

import datetime
import hashlib
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

from test_deps import Case, WIN

ROOT = Path(__file__).resolve().parent.parent
VMS = str(ROOT / "libexec" / "vms")

DOCKER = """#!/bin/sh
echo "docker $*" >> "$FAKE_LOG"
case $1 in
  inspect) [ -f "$FAKE_UP" ] && echo true || { [ -f "$FAKE_EXISTS" ] || exit 1; echo false; } ;;
  start|run) touch "$FAKE_UP" "$FAKE_EXISTS" ;;
  stop) rm -f "$FAKE_UP" ;;
  rm) rm -f "$FAKE_EXISTS" ;;
esac
"""
# ssh ... COMMAND: answers while FAKE_UP exists, as the Windows guest would
SSH = """#!/bin/sh
for last; do :; done
[ -f "$FAKE_UP" ] || { echo "ssh: connect to host: Connection refused" >&2; exit 255; }
echo "ssh $last" >> "$FAKE_LOG"
case $last in
  "echo up") echo up ;;
  *ssh_host_*) printf 'ssh-ed25519 AAAAguestkey\\r\\n' ;;
  *Get-Content*update.result*)
    if [ -f "$FAKE_RESULTS" ] && [ -s "$FAKE_RESULTS" ]; then
      head -1 "$FAKE_RESULTS"; sed -i 1d "$FAKE_RESULTS"
    fi ;;
  *CurrentBuild*) printf '10.0.19045.6456\\r\\n' ;;
  *-Command\ -) cat > /dev/null; printf '%s\\r\\n' "$FAKE_GUEST" ;;
  *) ;;
esac
"""
KEYSCAN = """#!/bin/sh
echo "[127.0.0.1]:2222 ssh-ed25519 AAAAguestkey"
echo "[127.0.0.1]:2222 ssh-rsa AAAAnotnamedbytheguest"
"""
SCP = """#!/bin/sh
echo "scp $*" >> "$FAKE_LOG"
"""


@unittest.skipUnless(shutil.which("flock") and shutil.which("ssh-keygen"), "needs flock and ssh-keygen")
class Recipes(Case):
    def setUp(self):
        super().setUp()
        stubs = self.tmp / "stubs"
        for name, text in (("docker", DOCKER), ("ssh", SSH), ("ssh-keyscan", KEYSCAN), ("scp", SCP)):
            (stubs / name).write_text(text)
            (stubs / name).chmod(0o755)
        self.env.update(COWORKER_SSH=str(stubs / "ssh"), COWORKER_SCP=str(stubs / "scp"),
                        COWORKER_SSH_KEYSCAN=str(stubs / "ssh-keyscan"), FAKE_UP=str(self.tmp / "up"),
                        FAKE_EXISTS=str(self.tmp / "exists"), FAKE_RESULTS=str(self.tmp / "results"),
                        FAKE_GUEST="10.0.19045.6456|22H2|Windows 10 Pro", COWORKER_VM_POLL="0.05", COWORKER_VM_UPDATE_WAIT="5",
                        COWORKER_VM_REBOOT_PAUSE="0", COWORKER_VM_BOOT_WAIT="5", COWORKER_VM_INSTALL_WAIT="5")
        shutil.copytree(ROOT / "vms", self.home / "recipes")
        zipfile = self.tmp / "OpenSSH-Win64.zip"
        zipfile.write_bytes(b"not really a zip")
        recipe = self.home / "recipes" / "win10" / "recipe.env"
        text = recipe.read_text()
        text = text.replace(text.split("OPENSSH_URL=")[1].split("\n")[0], f"file://{zipfile}")
        text = text.replace(text.split("OPENSSH_SHA256=")[1].split("\n")[0], hashlib.sha256(b"not really a zip").hexdigest())
        recipe.write_text(text)
        self.vm = self.home / "vms" / "win10"

    def vms(self, *args, rc=None, **env):
        res = subprocess.run(["sh", VMS, *args], capture_output=True, text=True, timeout=120, env={**self.env, **env})
        if rc is not None:
            self.assertEqual(res.returncode, rc, res.stdout + res.stderr)
        return res

    def log(self):
        p = Path(self.env["FAKE_LOG"])
        return p.read_text() if p.exists() else ""

    # -- vms create -----------------------------------------------------------------------------

    def test_create_is_a_human_call(self):
        res = self.vms("create", "win10", rc=3)
        self.assertIn("vms create win10 --yes", res.stderr)
        self.assertFalse(self.vm.exists())
        self.assertNotIn("docker", self.log())

    def test_create_without_a_recipe_says_so(self):
        self.assertIn("no recipe for nosuch", self.vms("create", "nosuch", "--yes", rc=1).stderr)

    def test_create_builds_the_vm_from_the_recipe(self):
        (self.vm / "storage").mkdir(parents=True)
        (self.vm / "storage" / "data.img").write_text("the old disk")
        (self.vm / "password.txt").write_text("kept\n")
        Path(self.env["FAKE_RESULTS"]).write_text("DONE installed=0 failed=0 reboot=0\n")
        out = self.vms("create", "win10", "--yes", rc=0).stdout
        self.assertIn("up to date, build 10.0.19045.6456", out)
        env = (self.vm / "vm.env").read_text()
        self.assertIn("VM_SSH_USER=tester", env)
        self.assertIn("VM_CONTAINER=coworker-win10", env)
        self.assertEqual((self.vm / "password.txt").read_text(), "kept\n")
        self.assertEqual((self.vm / "oem" / "authorized_key.pub").read_text(), (self.vm / "vm_key.pub").read_text())
        self.assertEqual((self.vm / "known_hosts").read_text().strip(), "[127.0.0.1]:2222 ssh-ed25519 AAAAguestkey")
        olds = [p for p in self.vm.iterdir() if p.name.startswith("storage-") and p.name.endswith("-old")]
        self.assertEqual(len(olds), 1)
        self.assertEqual((olds[0] / "data.img").read_text(), "the old disk")
        self.assertTrue((self.vm / "storage" / "vmctl.py").exists())
        self.assertEqual((self.vm / "updated").read_text().split()[1], "10.0.19045.6456")
        self.assertIn("built from the recipe", (self.vm / "history").read_text())
        log = self.log()
        self.assertIn("docker run -d --name coworker-win10", log)
        self.assertIn("dockurr/windows@sha256:", log)
        self.assertIn("-e USERNAME=tester", log)
        self.assertIn("docker stop -t 120 coworker-win10", log)
        self.assertFalse(Path(self.env["FAKE_UP"]).exists())              # left stopped
        self.assertEqual((self.home / "vms" / "win10.lock").read_text(), "")    # the lock is let go

    def test_create_refuses_an_openssh_zip_the_recipe_doesnt_pin(self):
        recipe = self.home / "recipes" / "win10" / "recipe.env"
        recipe.write_text(recipe.read_text().replace("OPENSSH_SHA256=", "OPENSSH_SHA256=0" * 1 + "0" * 63 + "#"))
        res = self.vms("create", "win10", "--yes")
        self.assertNotEqual(res.returncode, 0)
        self.assertNotIn("docker run", self.log())

    # -- vms update -----------------------------------------------------------------------------

    def built(self):
        Path(self.env["FAKE_RESULTS"]).write_text("DONE installed=0 failed=0 reboot=0\n")
        self.vms("create", "win10", "--yes", rc=0)
        Path(self.env["FAKE_LOG"]).write_text("")
        (self.vm / "updated").unlink()

    def test_update_installs_restarts_and_rounds_again_until_nothing_is_left(self):
        self.built()
        Path(self.env["FAKE_RESULTS"]).write_text("DONE installed=3 failed=0 reboot=1\nDONE installed=1 failed=0 reboot=0\n"
                                                  "DONE installed=0 failed=0 reboot=0\n")
        out = self.vms("update", "win10", rc=0).stdout
        self.assertIn("round 3", out)
        self.assertIn("restarting", out)
        log = self.log()
        self.assertIn("docker start coworker-win10", log)
        self.assertEqual(log.count("schtasks /run /tn coworker-update"), 3)
        self.assertIn("/ru SYSTEM", log)
        self.assertIn("shutdown /r", log)
        self.assertIn("docker stop", log)                                   # it started it, so it stops it
        self.assertEqual((self.vm / "updated").read_text().split(), [str(datetime.date.today()), "10.0.19045.6456"])

    def test_update_fails_on_updates_that_keep_failing(self):
        self.built()
        Path(self.env["FAKE_RESULTS"]).write_text("DONE installed=0 failed=2 reboot=0\n")
        self.assertIn("keep failing", self.vms("update", "win10", rc=1).stderr)
        self.assertFalse((self.vm / "updated").exists())

    def test_update_reports_a_failed_round(self):
        self.built()
        Path(self.env["FAKE_RESULTS"]).write_text("FAILED 0x8024402c\n")
        self.vms("update", "win10", rc=1)

    # -- a project's need: updated within so many days -------------------------------------------

    def run_vm(self, d, rc):
        return subprocess.run(["sh", VMS, "run", "win10", d, "--", "true"], capture_output=True, text=True,
                              timeout=60, env=self.env)

    def test_vms_run_holds_the_vm_to_its_projects_freshness(self):
        self.built()
        a = self.project("one", {"vms": {"win10": {"os": {**WIN, "updated_within_days": 30}}}})
        b = self.project("two", {"vms": {"win10": {"os": {**WIN, "updated_within_days": 5}}}})
        res = self.run_vm(a, 69)
        self.assertEqual(res.returncode, 69, res.stdout + res.stderr)
        self.assertIn("never fully updated", res.stderr)
        today = datetime.date.today()
        (self.vm / "updated").write_text(f"{today - datetime.timedelta(days=10)} 10.0.19045.6456\n")
        self.assertEqual(self.run_vm(a, 0).returncode, 0)
        res = self.run_vm(b, 69)                                 # the stricter claim now holds for both
        self.assertEqual(res.returncode, 69, res.stdout + res.stderr)
        self.assertIn("last fully updated 10 days ago, not within 5 (vms update win10)", res.stderr)
        (self.vm / "updated").write_text(f"{today} 10.0.19045.6456\n")
        self.assertEqual(self.run_vm(a, 0).returncode, 0)

    def test_updated_within_days_is_a_whole_number(self):
        for bad in (0, "7", 1.5, True):
            d = self.project("one", {"vms": {"win10": {"os": {**WIN, "updated_within_days": bad}}}})
            self.deps("check", "--no-network", d, rc=2)


if __name__ == "__main__":
    unittest.main()
