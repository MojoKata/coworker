"""The coworker commands (README.md), run against a throwaway COWORKER_HOME as the README says they
behave, and install.sh into one. Standard library only: python3 -m unittest discover -s tests"""

import fcntl
import hashlib
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOWNLOADS = str(ROOT / "libexec" / "downloads")
VMS = str(ROOT / "libexec" / "vms")
PROTOCOL = (ROOT / "PROTOCOL").read_text().strip()   # the commands are called as a project's submodule calls them


def run(cmd, *args, env, check=True):
    res = subprocess.run(["sh", cmd, *args], capture_output=True, text=True, env=env, timeout=60)
    if check:
        assert res.returncode == 0, res.stderr + res.stdout
    return res


@unittest.skipUnless(shutil.which("flock"), "the commands need flock (util-linux)")
class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.home = self.tmp / "coworker"
        self.env = {**os.environ, "COWORKER_HOME": str(self.home), "COWORKER_CLIENT_PROTOCOL": PROTOCOL}


class Home(Case):
    def test_the_home_is_coworker_in_the_users_home_unless_set(self):
        env = {**self.env, "HOME": str(self.tmp)}
        env.pop("COWORKER_HOME", None)
        run(DOWNLOADS, "claim", "x.iso", "one", env=env)
        run(VMS, "claim", "win", "one", env=env)
        self.assertTrue((self.tmp / "coworker" / "downloads" / "x.iso.one").exists())
        self.assertTrue((self.tmp / "coworker" / "vms" / "win.one").exists())

    def test_install_copies_the_commands_and_keeps_the_data(self):
        out = subprocess.run(["sh", str(ROOT / "install.sh")], capture_output=True, text=True, env=self.env, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        for f in ("downloads", "vms", "deps"):
            p = self.home / "bin" / f
            self.assertTrue(p.is_file() and not p.is_symlink() and os.access(p, os.X_OK), f)
            self.assertEqual(p.read_bytes(), (ROOT / "libexec" / f).read_bytes())
        self.assertTrue((self.home / "VERSION").read_text().strip())
        (self.home / "downloads" / "x.iso").write_text("data")
        (self.home / "vms" / "win").mkdir()
        (self.home / "bin" / "vms").write_text("old")
        subprocess.run(["sh", str(ROOT / "install.sh")], check=True, capture_output=True, env=self.env, timeout=60)
        self.assertEqual((self.home / "bin" / "vms").read_bytes(), (ROOT / "libexec" / "vms").read_bytes())
        self.assertEqual((self.home / "downloads" / "x.iso").read_text(), "data")
        self.assertTrue((self.home / "vms" / "win").is_dir())
        self.assertEqual(sorted(os.listdir(self.home / "bin")), ["deps", "downloads", "vms"])

    def test_an_unknown_subcommand_shows_the_usage(self):
        for cmd in (DOWNLOADS, VMS):
            res = run(cmd, "nonsense", env=self.env, check=False)
            self.assertEqual(res.returncode, 2)
            self.assertIn("usage:", res.stderr)


class Downloads(Case):
    def setUp(self):
        super().setUp()
        self.d = self.home / "downloads"

    def test_claims_keep_a_file_until_the_last_is_released(self):
        run(DOWNLOADS, "claim", "x.iso", "one", env=self.env)
        run(DOWNLOADS, "claim", "x.iso", "two", env=self.env)
        for f in ("x.iso", "x.iso.sha256", "x.iso.part", "x.iso.bad", "x.iso.lock"):
            (self.d / f).write_text("data")
        out = run(DOWNLOADS, "release", "x.iso", "one", env=self.env).stdout
        self.assertIn("kept, claimed by two", out)
        self.assertTrue((self.d / "x.iso").exists())
        self.assertFalse((self.d / "x.iso.one").exists())
        out = run(DOWNLOADS, "release", "x.iso", "two", env=self.env).stdout
        self.assertIn("removed", out)
        self.assertEqual(os.listdir(self.d), [])

    def test_project_names_are_checked(self):
        for bad in ("a b", "x/y", "lock", "sha256", "part", "bad", ""):
            res = run(DOWNLOADS, "claim", "x.iso", bad, env=self.env, check=False)
            self.assertEqual(res.returncode, 2, repr(bad))

    def test_list_shows_claims_and_verifies(self):
        self.d.mkdir(parents=True)
        (self.d / "a.iso").write_bytes(b"A")
        (self.d / "a.iso.sha256").write_text(hashlib.sha256(b"A").hexdigest() + "  a.iso\n")
        (self.d / "a.iso.one").touch()
        (self.d / "b.iso").write_bytes(b"B")
        (self.d / "b.iso.sha256").write_text("0" * 64 + "  b.iso\n")
        (self.d / "c.iso.two").touch()                                    # claimed, not here yet
        (self.d / "tool.tar.gz").write_bytes(b"T")                        # any big file, not only ISOs
        (self.d / "tool.tar.gz.one").touch()
        out = run(DOWNLOADS, "list", "--verify", env=self.env).stdout.splitlines()
        self.assertEqual(len(out), 4, out)
        self.assertTrue(out[0].startswith("a.iso |") and out[0].endswith("claimed by one | SHA-256 ok"), out[0])
        self.assertTrue(out[1].startswith("b.iso |") and "unclaimed" in out[1] and "doesn't match" in out[1], out[1])
        self.assertEqual(out[2], "c.iso | not here yet | claimed by two")
        self.assertTrue(out[3].startswith("tool.tar.gz |") and "claimed by one" in out[3], out[3])

    @unittest.skipUnless(shutil.which("curl"), "fetch needs curl")
    def test_fetch_checks_resumes_and_claims(self):
        src = self.tmp / "src"
        src.mkdir()
        (src / "x.iso").write_bytes(b"x" * 100_000)
        good = hashlib.sha256(b"x" * 100_000).hexdigest()
        (src / "sha256sum.txt").write_text(f"{'1' * 64}  other.iso\n{good} *x.iso\n")   # a mirror's list
        (src / "wrong.txt").write_text("2" * 64 + "\n")
        args = ("fetch", "x.iso", "one", f"file://{src}/x.iso")
        res = run(DOWNLOADS, *args, f"file://{src}/wrong.txt", env=self.env, check=False)
        self.assertEqual(res.returncode, 1)
        self.assertIn("doesn't match", res.stderr)
        self.assertFalse((self.d / "x.iso").exists())
        os.remove(self.d / "x.iso.part")
        (self.d / "x.iso.part").write_bytes(b"x" * 40_000)                     # stopped part-way: resumed
        out = run(DOWNLOADS, *args, f"file://{src}/sha256sum.txt", env=self.env).stdout
        for s in ("resuming", "SHA-256 matches", "one claims x.iso"):
            self.assertIn(s, out)
        self.assertEqual((self.d / "x.iso").read_bytes(), b"x" * 100_000)
        self.assertTrue((self.d / "x.iso.one").exists())
        self.assertEqual((self.d / "x.iso.sha256").read_text(), f"{good}  x.iso\n")
        out = run(DOWNLOADS, "fetch", "x.iso", "two", f"file://{src}/x.iso", f"file://{src}/sha256sum.txt",
                  env=self.env).stdout
        self.assertNotIn("downloading", out)                                    # already here: only claimed
        self.assertIn("two claims x.iso", out)
        (self.d / "x.iso").write_bytes(b"corrupt")
        out = run(DOWNLOADS, *args, f"file://{src}/sha256sum.txt", env=self.env).stdout
        self.assertIn("doesn't match", out)
        self.assertEqual((self.d / "x.iso.bad").read_bytes(), b"corrupt")
        self.assertEqual((self.d / "x.iso").read_bytes(), b"x" * 100_000)


class Vms(Case):
    def setUp(self):
        super().setUp()
        self.d = self.home / "vms"
        (self.d / "win").mkdir(parents=True)
        (self.d / "win" / "vm.env").write_text('VM_OS="Windows 10 Pro 22H2"\nVM_CONTAINER=box\nVM_SSH_PORT=2222\n'
                                               'VM_SSH_USER=tester\nVM_SSH_KEY=vm_key\n')

    def test_release_never_deletes_a_vm(self):
        run(VMS, "claim", "win", "one", env=self.env)
        run(VMS, "claim", "win", "two", env=self.env)
        self.assertIn("kept, claimed by two", run(VMS, "release", "win", "one", env=self.env).stdout)
        out = run(VMS, "release", "win", "two", env=self.env).stdout
        self.assertIn("no project claims it now", out)
        self.assertTrue((self.d / "win" / "vm.env").exists())
        self.assertEqual(run(VMS, "claim", "win", "lock", env=self.env, check=False).returncode, 2)

    def test_env_resolves_the_vms_paths(self):
        out = run(VMS, "env", "win", env=self.env).stdout
        got = dict(line.split("=", 1) for line in out.splitlines())
        home = os.path.realpath(self.d / "win")
        self.assertEqual(got["VM_HOME"], f"'{home}'")
        self.assertEqual(got["VM_SSH_KEY"], f"'{home}/vm_key'")
        self.assertEqual(got["VM_KNOWN_HOSTS"], f"'{home}/known_hosts'")
        self.assertEqual(got["VM_SSH_HOST"], "'127.0.0.1'")
        self.assertEqual(got["VM_OS"], "'Windows 10 Pro 22H2'")
        self.assertEqual(got["VM_CONTAINER"], "'box'")
        shell = subprocess.run(["sh", "-c", f'eval "$(sh {VMS} env win)"; echo "$VM_SSH_USER@$VM_SSH_HOST:$VM_SSH_PORT"'],
                               capture_output=True, text=True, env=self.env)
        self.assertEqual(shell.stdout.strip(), "tester@127.0.0.1:2222")
        (self.d / "win" / "vm.env").write_text("VM_SSH_PORT=22\n")
        res = run(VMS, "env", "win", env=self.env, check=False)
        self.assertEqual(res.returncode, 1)
        self.assertIn("sets no VM_SSH_USER", res.stderr)

    def test_lock_runs_one_project_at_a_time(self):
        out = run(VMS, "lock", "win", "one", "--", "sh", "-c", f'echo "$COWORKER_VM_LOCKED"; cat {self.d}/win.lock',
                  env=self.env).stdout
        self.assertTrue(out.startswith("win\none, pid "), out)                  # the command sees the lock and its holder
        self.assertEqual((self.d / "win.lock").read_text(), "")                 # cleared after
        self.assertEqual(run(VMS, "lock", "win", "one", "--", "sh", "-c", "exit 3", env=self.env, check=False).returncode, 3)
        with open(self.d / "win.lock", "a") as held:                            # another run holds it
            fcntl.flock(held, fcntl.LOCK_EX)
            (self.d / "win.lock").write_text("two, pid 1, since then\n")
            res = run(VMS, "lock", "win", "one", "--no-wait", "--", "true", env=self.env, check=False)
            self.assertEqual(res.returncode, 75)
            self.assertIn("in use: two, pid 1", res.stderr)
            self.assertIn("in use: two", run(VMS, "list", env=self.env).stdout)
            mark = self.tmp / "ran"
            waiting = subprocess.Popen(["sh", VMS, "lock", "win", "one", "--", "touch", str(mark)], env=self.env,
                                       stdout=subprocess.PIPE, text=True)
            time.sleep(1)
            self.assertFalse(mark.exists())                                     # waits for the holder
            fcntl.flock(held, fcntl.LOCK_UN)
        self.assertEqual(waiting.wait(timeout=20), 0)
        self.assertTrue(mark.exists())
        self.assertIn("waiting for it", waiting.stdout.read())
        waiting.stdout.close()
        self.assertEqual(run(VMS, "lock", "nowhere", "one", "--", "true", env=self.env, check=False).returncode, 1)

    def test_list_shows_what_claims_and_who_holds(self):
        (self.d / "win.one").touch()
        (self.d / "other.two").touch()                                          # claimed, not set up yet
        out = run(VMS, "list", env=self.env).stdout.splitlines()
        self.assertEqual(out, ["other | not set up yet (no other/vm.env) | claimed by two | free",
                               "win | Windows 10 Pro 22H2 | claimed by one | free"])


if __name__ == "__main__":
    unittest.main()
