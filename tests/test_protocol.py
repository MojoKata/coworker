"""Protocol 4 (README.md, "Protocol"): a project calls coworker through its submodule's launcher, which
checks the installed coworker (the handshake) and hands the call over; installing is a human's call,
or COWORKER_UNATTENDED=1's. Run here against a project folder holding a copy of this checkout as its
coworker/, and a throwaway COWORKER_HOME."""

import os
import shutil
import subprocess
import unittest
from pathlib import Path

from test_deps import Case

ROOT = Path(__file__).resolve().parent.parent
MINE = (ROOT / "PROTOCOL").read_text().strip()
MAJOR = MINE.split(".")[0]


def bump(v, major=0, minor=0):
    a, b = (int(x) for x in v.split("."))
    return f"{a + major}.{b + minor}" if not major else f"{a + major}.0"


@unittest.skipUnless(shutil.which("flock"), "the commands need flock (util-linux)")
class Launcher(Case):
    def setUp(self):
        super().setUp()
        self.env.pop("COWORKER_CLIENT_PROTOCOL")            # set by the launcher, never by a project
        self.env["FAKE_RPMS"] = "curl=8-1 openssh-clients=9-1 python3=3.12-1 util-linux=2-1"   # coworker's own needs
        self.proj = Path(self.project("Proj", {"project": "Proj"}))
        self.sub = self.proj / "coworker"
        shutil.copytree(ROOT, self.sub, symlinks=True,
                        ignore=shutil.ignore_patterns(".git", "__pycache__", "tests", "docs", ".github"))

    def call(self, *args, rc=None, name="coworker", sub=None, **env):
        res = subprocess.run([str((sub or self.sub) / "bin" / name), *args], capture_output=True, text=True,
                             timeout=60, env={**self.env, **env})
        if rc is not None:
            self.assertEqual(res.returncode, rc, res.stdout + res.stderr)
        return res

    def install(self, protocol=None, change=False):
        if protocol:
            (self.sub / "PROTOCOL").write_text(protocol + "\n")
        self.call("install", *(["--change"] if change else []), rc=0)
        (self.sub / "PROTOCOL").write_text(MINE + "\n")

    # -- the handshake --------------------------------------------------------------------------

    def test_not_installed_register_says_so_and_never_fails_the_script(self):
        res = self.call("register", str(self.proj), name="deps", rc=0)
        self.assertIn("not installed", res.stderr)
        self.assertIn("bin/coworker status", res.stderr)
        self.assertFalse(self.home.exists())

    def test_not_installed_anything_else_waits_on_a_human(self):
        res = self.call("list", name="vms", rc=3)
        self.assertIn(f"{self.sub}/bin/coworker install", res.stderr)
        self.assertFalse(self.home.exists())                # nothing installed by itself

    def test_installed_it_hands_over_under_each_name(self):
        self.install()
        self.assertEqual((self.home / "PROTOCOL").read_text().strip(), MINE)
        self.assertIn("Proj claims win", self.call("claim", "win", "Proj", name="vms", rc=0).stdout)
        self.assertIn("Proj claims x.iso", self.call("downloads", "claim", "x.iso", "Proj", rc=0).stdout)
        self.call("register", str(self.proj), name="deps", rc=0)
        self.assertEqual((self.home / "projects" / "Proj").read_text().strip(), str(self.proj))

    def test_a_newer_minor_installed_serves_this_project(self):
        self.install(bump(MINE, minor=2), change=True)
        self.call("claim", "win", "Proj", name="vms", rc=0)

    def test_an_older_minor_installed_waits_and_names_the_projects(self):
        self.install()
        self.call("register", str(self.proj), name="deps", rc=0)
        (self.sub / "PROTOCOL").write_text(bump(MINE, minor=1))
        res = self.call("claim", "win", "Proj", name="vms", rc=3)
        self.assertIn(f"protocol {bump(MINE, minor=1)}", res.stderr)
        self.assertIn("(Proj)", res.stderr)
        self.assertIn("coworker install --change", res.stderr)
        self.assertFalse((self.home / "vms" / "win.Proj").exists())

    def test_another_major_installed_waits(self):
        self.install(bump(MINE, major=1), change=True)
        self.call("list", name="vms", rc=3)

    def test_a_protocol_3_install_waits(self):
        (self.home / "bin").mkdir(parents=True)
        shutil.copy(ROOT / "libexec" / "deps", self.home / "bin" / "deps")    # protocol 3 wrote no PROTOCOL
        res = self.call("list", name="vms", rc=3)
        self.assertIn("in", res.stderr)
        self.assertIn(" is 3.", res.stderr)

    def test_the_launcher_reads_only_protocol_and_the_command_of_an_install(self):
        """Frozen for every protocol: an install with a later minor and different commands still gets
        the call, with this project's protocol and the home."""
        (self.home / "bin").mkdir(parents=True)
        (self.home / "PROTOCOL").write_text(bump(MINE, minor=7))
        (self.home / "bin" / "vms").write_text('#!/bin/sh\necho "$COWORKER_CLIENT_PROTOCOL $COWORKER_HOME $*"\n')
        (self.home / "bin" / "vms").chmod(0o755)
        self.assertEqual(self.call("a", "b", name="vms", rc=0).stdout.strip(), f"{MINE} {self.home} a b")

    # -- the installed half ---------------------------------------------------------------------

    def test_installed_commands_called_directly_refuse_to_change_shared_state(self):
        self.install()
        for argv in (["vms", "claim", "win", "Proj"], ["downloads", "claim", "x.iso", "Proj"],
                     ["deps", "register", str(self.proj)]):
            res = subprocess.run([str(self.home / "bin" / argv[0]), *argv[1:]], capture_output=True, text=True,
                                 env=self.env, timeout=60)
            self.assertEqual(res.returncode, 3, argv)
            self.assertIn("not through a project's coworker submodule", res.stderr)
        self.assertFalse((self.home / "vms" / "win.Proj").exists())
        for argv in (["vms", "list"], ["downloads", "list"]):           # looking is anyone's
            self.assertEqual(subprocess.run([str(self.home / "bin" / argv[0]), *argv[1:]], capture_output=True,
                                            env=self.env, timeout=60).returncode, 0, argv)

    def test_installed_commands_refuse_a_project_of_another_protocol(self):
        self.install()
        for theirs in (bump(MINE, major=1), bump(MINE, minor=1)):
            res = subprocess.run([str(self.home / "bin" / "vms"), "claim", "win", "Proj"], capture_output=True,
                                 text=True, env={**self.env, "COWORKER_CLIENT_PROTOCOL": theirs}, timeout=60)
            self.assertEqual(res.returncode, 3, theirs)

    # -- install --------------------------------------------------------------------------------

    def test_install_over_another_protocol_needs_change(self):
        self.install(bump(MINE, minor=1), change=True)
        before = (self.home / "bin" / "vms").read_bytes()
        (self.home / "bin" / "vms").write_bytes(b"#!/bin/sh\n# the old one\n")
        res = self.call("install", rc=3)
        self.assertIn(f"protocol {bump(MINE, minor=1)}; this is {MINE}", res.stderr)
        self.assertEqual((self.home / "bin" / "vms").read_bytes(), b"#!/bin/sh\n# the old one\n")
        self.assertEqual((self.home / "PROTOCOL").read_text().strip(), bump(MINE, minor=1))
        self.call("install", "--change", rc=0)
        self.assertEqual((self.home / "PROTOCOL").read_text().strip(), MINE)
        self.assertEqual((self.home / "bin" / "vms").read_bytes(), before)

    def test_install_of_the_same_protocol_again_needs_no_flag(self):
        self.install()
        (self.home / "downloads" / "x.iso").write_text("data")
        self.call("install", rc=0)
        self.assertEqual((self.home / "downloads" / "x.iso").read_text(), "data")

    # -- unattended (CI) ------------------------------------------------------------------------

    def test_unattended_installs_instead_of_waiting(self):
        self.assertIn("Proj claims win", self.call("claim", "win", "Proj", name="vms", rc=0,
                                                   COWORKER_UNATTENDED="1").stdout)
        self.assertEqual((self.home / "PROTOCOL").read_text().strip(), MINE)

    def test_unattended_changes_another_protocol(self):
        self.install(bump(MINE, major=1), change=True)
        self.call("list", name="vms", rc=0, COWORKER_UNATTENDED="1")
        self.assertEqual((self.home / "PROTOCOL").read_text().strip(), MINE)

    # -- status ---------------------------------------------------------------------------------

    def test_status_not_installed_waits(self):
        self.assertIn("coworker install", self.call("status", rc=3).stderr)

    def test_status_finds_its_project_registers_it_and_says_ready(self):
        self.install()
        out = self.call("status", "--no-network", rc=0).stdout
        self.assertIn(f"Proj at {self.proj}", out)
        self.assertIn("ready", out)
        self.assertEqual((self.home / "projects" / "Proj").read_text().strip(), str(self.proj))

    def test_status_lists_what_waits_on_a_human_with_its_command(self):
        self.install()
        self.project("Proj", {"project": "Proj", "host": [{"package": "a", "why": "w"}],
                              "pips": [{"pip": "p", "why": "w"}],
                              "tools": [{"tool": "t", "command": "no-such-tool", "how": "echo installing t", "why": "w"}]})
        out = self.call("status", "--no-network", rc=3).stdout
        self.assertIn(f"sudo {self.home}/bin/deps install --sudo {self.proj}", out)
        self.assertIn(f"{self.home}/bin/deps install {self.proj}", out)
        self.assertIn("echo installing t", out)
        self.assertFalse(Path(self.env["FAKE_LOG"]).exists())       # nothing installed by itself

    def test_status_unattended_installs_what_it_can_and_fails_on_the_rest(self):
        self.project("Proj", {"project": "Proj", "pips": [{"pip": "p", "why": "w"}],
                              "tools": [{"tool": "t", "path": str(self.tmp / "t"), "how": f"touch {self.tmp / 't'}", "why": "w"}]})
        out = self.call("status", "--no-network", rc=0, COWORKER_UNATTENDED="1").stdout
        self.assertIn("ready", out)
        self.assertTrue((self.tmp / "t").exists())
        self.assertIn("pip install --user p", Path(self.env["FAKE_LOG"]).read_text())
        self.project("Proj", {"project": "Proj", "tools": [{"tool": "u", "command": "no-such-tool", "how": "true", "why": "w"}]})
        self.assertIn("still missing", self.call("status", "--no-network", rc=1, COWORKER_UNATTENDED="1").stdout)


if __name__ == "__main__":
    unittest.main()
