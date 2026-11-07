"""bin/deps (README.md, "Dependencies"), against a throwaway COWORKER_HOME, a stated platform, and
stand-ins for rpm, dpkg-query and the Python whose pips are checked. Standard library only."""

import importlib.machinery
import importlib.util
import json
import os
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEPS = str(ROOT / "bin" / "deps")

RPM = """#!/bin/sh
# rpm -q --qf FORMAT NAME, answered from FAKE_RPMS ("name=version-release ...") and the file FAKE_RPMDB
for kv in $FAKE_RPMS $(cat "$FAKE_RPMDB" 2>/dev/null); do [ "${kv%%=*}" = "$4" ] && { echo "${kv#*=}"; exit 0; }; done
echo "package $4 is not installed"; exit 1
"""
DPKG_QUERY = """#!/bin/sh
# dpkg-query -W -f FORMAT NAME, answered from FAKE_DEBS
for kv in $FAKE_DEBS; do [ "${kv%%=*}" = "$4" ] && { printf 'installed %s' "${kv#*=}"; exit 0; }; done
exit 1
"""
DNF = """#!/bin/sh
# dnf install -y SPEC... (or apt-get): logs the command and "installs" each spec's name at 9.9 into FAKE_RPMDB
echo "$(basename "$0") $*" >> "$FAKE_LOG"
shift 2
for spec in "$@"; do set -- $spec; n=${1%%-[0-9]*}; echo "${n%%=*}=9.9-1" >> "$FAKE_RPMDB"; done
"""
PYTHON = """#!/bin/sh
# python -m pip --version | python -c CODE NAME, answered from FAKE_HAS_PIP and FAKE_PIPS
if [ "$1 $2 $3" = "-m pip install" ]; then
  echo "python $*" >> "$FAKE_LOG"; shift 4
  for spec in "$@"; do echo "${spec%%[<>=]*}=99.0" >> "$FAKE_PIPDB"; done; exit 0
fi
if [ "$1 $2" = "-m ensurepip" ]; then echo "python $*" >> "$FAKE_LOG"; exit 0; fi
if [ "$1" = -m ]; then [ -n "$FAKE_HAS_PIP" ]; exit $?; fi
for kv in $FAKE_PIPS $(cat "$FAKE_PIPDB" 2>/dev/null); do [ "${kv%%=*}" = "$3" ] && { echo "${kv#*=}"; exit 0; }; done
exit 3
"""


def load_module():
    loader = importlib.machinery.SourceFileLoader("deps", DEPS)
    spec = importlib.util.spec_from_loader("deps", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.home = self.tmp / "coworker"
        stubs = self.tmp / "stubs"
        stubs.mkdir()
        for name, text in (("rpm", RPM), ("dpkg-query", DPKG_QUERY), ("python", PYTHON), ("dnf", DNF), ("apt-get", DNF)):
            (stubs / name).write_text(text)
            (stubs / name).chmod(0o755)
        self.env = {**os.environ, "COWORKER_HOME": str(self.home), "COWORKER_PLATFORM": "rocky-10.2",
                    "COWORKER_FAMILY": "rpm", "COWORKER_PYTHON": str(stubs / "python"),
                    "PATH": f"{stubs}:{os.environ['PATH']}", "FAKE_RPMS": "", "FAKE_PIPS": "", "FAKE_HAS_PIP": "1",
                    "FAKE_LOG": str(self.tmp / "log"), "FAKE_RPMDB": str(self.tmp / "rpmdb"),
                    "FAKE_PIPDB": str(self.tmp / "pipdb"), "COWORKER_EUID": "1000"}

    def project(self, name, deps, folder=None):
        d = self.tmp / (folder or name)
        (d / ".coworker").mkdir(parents=True, exist_ok=True)
        (d / ".coworker" / "deps.json").write_text(json.dumps(deps))
        return str(d)

    def deps(self, *args, rc=None, **env):
        res = subprocess.run(["python3", DEPS, *args], capture_output=True, text=True, timeout=60,
                             env={**self.env, **env})
        if rc is not None:
            self.assertEqual(res.returncode, rc, res.stdout + res.stderr)
        return res

    def line(self, out, name):
        hits = [l for l in out.splitlines() if f" {name} " in f" {l} " or l.split()[1:2] == [name]]
        self.assertTrue(hits, f"{name} not in:\n{out}")
        return hits[0]


class Versions(unittest.TestCase):
    def test_rpm_versions_compare_as_rpm_does(self):
        m = load_module()
        for a, b, want in (("1.10", "1.9", 1), ("1.0", "1.0", 0), ("1.0~rc1", "1.0", -1), ("2.15.0", "2.15", 1),
                           ("1.0a", "1.0", 1), ("0.10.0", "0.9", 1), ("5.2.26", "5.2.3", 1)):
            self.assertEqual(m.rpmvercmp(a, b), want, (a, b))
            self.assertEqual(m.rpmvercmp(b, a), -want, (b, a))

    def test_pip_versions_compare_by_release(self):
        m = load_module()
        self.assertEqual(m.pipvercmp("13.0.0", "13"), 0)
        self.assertEqual(m.pipvercmp("12.3.0", "13.0.0"), -1)
        self.assertEqual(m.pipvercmp("13.1", "13.0.9"), 1)

    @unittest.skipUnless(shutil.which("dpkg"), "needs dpkg (CI's Ubuntu runner has it)")
    def test_deb_versions_compare_as_dpkg_does(self):
        m = load_module()
        self.assertEqual(m.debvercmp("1.2.3-1ubuntu2", "1.2.10-1"), -1)
        self.assertEqual(m.debvercmp("2:1.0-1", "1:9.9-1"), 1)
        self.assertEqual(m.debvercmp("1.0-1", "1.0-1"), 0)

    def test_the_packaging_revision_is_not_the_version(self):
        self.assertEqual(load_module().upstream("1:2.15.0-7.el10"), "2.15.0")


class Check(Case):
    def test_the_first_entry_whose_platform_matches_wins_for_a_name(self):
        p = self.project("one", {"host": [
            {"package": "bash", "platform": "debian*", "min": "99", "why": "not this machine"},
            {"package": "bash", "platform": "rocky-10*", "min": "5.0", "why": "this one"},
            {"package": "bash", "min": "98", "why": "never reached: an entry above matched"},
            {"package": "zsh", "platform": "debian*", "why": "not needed here"}]})
        out = self.deps("check", "--no-network", p, rc=0, FAKE_RPMS="bash=5.2.26-6.el10").stdout
        self.assertIn(">=5.0", self.line(out, "bash"))
        self.assertNotIn("zsh", out)

    def test_missing_below_above_and_off_pin_are_each_reported(self):
        p = self.project("one", {"host": [
            {"package": "a", "why": "w"}, {"package": "b", "min": "2.0", "why": "w"},
            {"package": "c", "max": "1.5", "why": "w"}, {"package": "d", "pin": "3.1", "why": "w"}]})
        out = self.deps("check", "--no-network", p, rc=1, FAKE_RPMS="b=1.9-1 c=1.6-2 d=3.1.1-1").stdout
        self.assertIn("MISSING", self.line(out, "a"))
        self.assertIn("below 2.0", self.line(out, "b"))
        self.assertIn("above 1.5", self.line(out, "c"))
        self.assertIn("pinned to 3.1", self.line(out, "d"))
        self.assertIn("4 to fix", out)

    def test_a_pin_matches_the_version_without_its_packaging_revision(self):
        p = self.project("one", {"host": [{"package": "fontconfig", "pin": "2.15.0", "why": "w"}]})
        self.deps("check", "--no-network", p, rc=0, FAKE_RPMS="fontconfig=2.15.0-7.el10")

    def test_pips_are_checked_in_the_python_named(self):
        p = self.project("one", {"pips": [{"pip": "pillow", "min": "13.0.0", "why": "shot.sh"},
                                          {"pip": "absent", "why": "w"}]})
        out = self.deps("check", "--no-network", p, rc=1, FAKE_PIPS="pillow=13.0.0").stdout
        self.assertIn("ok", self.line(out, "pillow"))
        self.assertIn("MISSING", self.line(out, "absent"))

    def test_every_entry_says_why_and_typos_are_refused(self):
        for bad, said in (({"host": [{"package": "a"}]}, "needs a 'why'"),
                          ({"host": [{"package": "a", "why": "w", "mni": "1"}]}, "unknown key 'mni'"),
                          ({"hosts": []}, "unknown key 'hosts'"),
                          ({"host": [{"package": "a", "why": "w", "pin": "1", "min": "1"}]}, "a pin with a min"),
                          ({"network": [{"host": "x", "why": "w", "min": "1"}]}, "a host has no version"),
                          ({"pips": [{"pip": "x", "why": "w", "port": 1}]}, "only a network host"),
                          ({"network": [{"host": "x", "why": "w", "probe": "ping"}]}, "probe is tls, http or tcp")):
            p = self.project("bad", bad)
            self.assertIn(said, self.deps("check", "--no-network", p, rc=2).stderr, bad)

    def test_two_projects_ranges_combine_and_a_clash_is_refused(self):
        a = self.project("a", {"host": [{"package": "x", "min": "1.2", "max": "3", "why": "a's"}]})
        b = self.project("b", {"host": [{"package": "x", "min": "1.10", "why": "b's"}]})
        out = self.deps("check", "--no-network", a, b, rc=1, FAKE_RPMS="x=1.9-1").stdout
        self.assertIn(">=1.10,<=3", self.line(out, "x"))
        self.assertIn("[a, b]", self.line(out, "x"))
        c = self.project("c", {"host": [{"package": "x", "pin": "1.0", "why": "c's"}]})
        d = self.project("d", {"host": [{"package": "x", "pin": "2.0", "why": "d's"}]})
        self.assertIn("pinned to 1.0 and to 2.0", self.deps("check", "--no-network", c, d, rc=65).stderr)
        e = self.project("e", {"host": [{"package": "x", "max": "1.0", "why": "e's"}]})
        self.assertIn("at least 1.10 and at most 1.0", self.deps("check", "--no-network", b, e, rc=65).stderr)

    def test_a_projects_name_labels_its_needs(self):
        p = self.project("checkout-dir", {"project": "one", "host": [{"package": "a", "why": "w"}]})
        self.assertIn("[one]", self.line(self.deps("check", "--no-network", p, rc=0, FAKE_RPMS="a=1-1").stdout, "a"))

    def test_the_coworker_homes_own_needs_always_count(self):
        self.project("home", {"host": [{"package": "curl", "why": "downloads fetch"}]}, folder="coworker")
        p = self.project("one", {})
        self.assertIn("[coworker]", self.line(self.deps("check", "--no-network", p, rc=1).stdout, "curl"))

    def test_an_unknown_command_shows_the_usage(self):
        self.assertIn("usage: deps", self.deps("frob", rc=2).stderr)


class Install(Case):
    ROOT = {"COWORKER_EUID": "0"}

    def log(self):
        f = self.tmp / "log"
        return f.read_text().splitlines() if f.exists() else []

    def test_as_the_user_it_installs_the_pips_and_leaves_host_packages_to_root(self):
        p = self.project("one", {"host": [{"package": "a", "why": "w"}],
                                 "pips": [{"pip": "pillow", "min": "13.0.0", "why": "w"}]})
        res = self.deps("install", p, rc=1)
        py = self.env["COWORKER_PYTHON"]
        self.assertEqual(self.log(), ["python -m pip install --user pillow>=13.0.0"])
        self.assertIn("1 host package(s) need root", res.stdout)
        self.assertIn("sudo ~/coworker/bin/deps install --sudo", res.stdout)

    def test_pip_comes_first_when_the_python_has_none(self):
        p = self.project("one", {"pips": [{"pip": "pillow", "why": "w"}]})
        res = self.deps("install", p, rc=0, FAKE_HAS_PIP="")
        self.assertEqual(self.log(), ["python -m ensurepip --user", "python -m pip install --user pillow"])
        self.assertIn("everything installed", res.stdout)

    def test_as_root_without_sudo_it_refuses(self):
        p = self.project("one", {"pips": [{"pip": "pillow", "why": "w"}]})
        self.assertIn("as root, use --sudo", self.deps("install", p, rc=2, **self.ROOT).stderr)
        self.assertEqual(self.log(), [])

    def test_sudo_mode_refuses_unless_root(self):
        p = self.project("one", {"host": [{"package": "a", "why": "w"}]})
        self.assertIn("must run as root", self.deps("install", "--sudo", p, rc=2).stderr)
        self.assertEqual(self.log(), [])

    def test_sudo_mode_installs_host_packages_with_ranges_and_pins_then_checks(self):
        p = self.project("one", {"host": [{"package": "a", "min": "1.2", "why": "w"}, {"package": "b", "pin": "9.9", "why": "w"},
                                          {"package": "c", "max": "10", "why": "w"}, {"package": "ok", "why": "there"}],
                                 "pips": [{"pip": "pillow", "why": "the user's, not root's"}]})
        res = self.deps("install", "--sudo", p, rc=0, FAKE_RPMS="ok=1-1", **self.ROOT)
        self.assertEqual(self.log(), ["dnf install -y a >= 1.2 b-9.9 c <= 10"])
        self.assertIn("host packages installed", res.stdout)
        self.assertFalse((self.home / "projects").exists(), "root wrote in the user's coworker home")

    def test_sudo_mode_says_what_is_still_wrong_after(self):
        p = self.project("one", {"host": [{"package": "a", "min": "10", "why": "w"}]})
        res = self.deps("install", "--sudo", p, rc=1, **self.ROOT)      # the stand-in installs 9.9
        self.assertIn("still to fix", res.stdout)
        self.assertIn("below 10", res.stdout)

    def test_a_failing_command_stops_the_run(self):
        p = self.project("one", {"host": [{"package": "a", "why": "w"}]})
        (self.tmp / "stubs" / "dnf").write_text("#!/bin/sh\nexit 7\n")
        res = self.deps("install", "--sudo", p, rc=1, **self.ROOT)
        self.assertIn("exit 7", res.stderr)
        self.assertIn("nothing after it was run", res.stderr)

    def test_dry_run_prints_both_parts_and_runs_nothing(self):
        p = self.project("one", {"host": [{"package": "a", "min": "1.2", "why": "w"}],
                                 "pips": [{"pip": "pillow", "min": "13.0.0", "why": "w"}]})
        out = self.deps("install", "-n", p, rc=0).stdout.splitlines()
        py = self.env["COWORKER_PYTHON"]
        self.assertEqual(out, [f"{py} -m pip install --user 'pillow>=13.0.0'",
                               "# as root (sudo ~/coworker/bin/deps install --sudo): dnf install -y 'a >= 1.2'"])
        self.assertEqual(self.deps("install", "--sudo", "-n", p, rc=0, **self.ROOT).stdout.strip(), "dnf install -y 'a >= 1.2'")
        self.assertEqual(self.log(), [])

    def test_apt_gets_names_and_pins(self):
        p = self.project("one", {"host": [{"package": "libgl1", "why": "w"}, {"package": "b", "pin": "2.0", "why": "w"}]})
        out = self.deps("install", "--sudo", "-n", p, rc=0, COWORKER_FAMILY="deb", COWORKER_PLATFORM="ubuntu-24.04",
                        FAKE_DEBS="", **self.ROOT).stdout
        self.assertEqual(out.strip(), "apt-get install -y b=2.0 libgl1")

    def test_nothing_missing_says_so(self):
        p = self.project("one", {"host": [{"package": "a", "why": "w"}]})
        self.assertIn("everything installed", self.deps("install", p, rc=0, FAKE_RPMS="a=1-1").stdout)
        self.assertIn("no host packages", self.deps("install", "--sudo", p, rc=0, FAKE_RPMS="a=1-1", **self.ROOT).stdout)

    def test_under_sudo_the_home_is_the_invoking_users(self):
        import pwd
        me = pwd.getpwuid(os.getuid())
        env = {k: v for k, v in self.env.items() if k != "COWORKER_HOME"}
        code = ("import importlib.machinery as m, importlib.util as u; l = m.SourceFileLoader('d', %r); "
                "s = u.spec_from_loader('d', l); d = u.module_from_spec(s); l.exec_module(d); print(d.HOME)") % DEPS
        out = subprocess.run(["python3", "-c", code], capture_output=True, text=True,
                             env={**env, "COWORKER_EUID": "0", "SUDO_USER": me.pw_name, "HOME": "/root"}).stdout.strip()
        self.assertEqual(out, os.path.join(me.pw_dir, "coworker"))


class Remembered(Case):
    def test_a_dir_is_remembered_and_a_run_with_none_covers_it(self):
        p = self.project("checkout", {"project": "one", "host": [{"package": "a", "why": "w"}]})
        self.deps("check", "--no-network", p, rc=1)
        self.assertEqual((self.home / "projects" / "one").read_text().strip(), p)
        self.assertIn("dnf install -y a", self.deps("install", "-n", rc=0).stdout)

    def test_a_remembered_checkout_that_is_gone_is_skipped_and_said(self):
        p = self.project("checkout", {"project": "one", "host": [{"package": "a", "why": "w"}]})
        self.deps("check", "--no-network", p, rc=1)
        shutil.rmtree(p)
        res = self.deps("install", rc=0)
        self.assertIn("everything installed", res.stdout)
        self.assertIn("one:", res.stderr)


class Register(Case):
    def test_register_remembers_and_only_mentions_what_is_missing(self):
        p = self.project("checkout", {"project": "one", "host": [{"package": "a", "why": "w"}, {"package": "b", "why": "w"}]})
        res = self.deps("register", p, rc=0, FAKE_RPMS="b=1-1")
        self.assertEqual(res.stdout, "")
        self.assertIn("lacks 1 of one's needs (a)", res.stderr)
        self.assertEqual((self.home / "projects" / "one").read_text().strip(), p)
        self.assertEqual(self.deps("register", p, rc=0, FAKE_RPMS="a=1-1 b=1-1").stderr, "")

    def test_a_broken_deps_json_still_fails(self):
        p = self.project("checkout", {"host": [{"package": "a"}]})
        self.assertIn("needs a 'why'", self.deps("register", p, rc=2).stderr)


class Network(Case):
    """Local servers: one that speaks TLS, one that answers HTTP, one that accepts and never answers
    (what a firewall that filters by name looks like), and a closed port."""

    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp())
        key, cert = cls.dir / "key.pem", cls.dir / "cert.pem"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=localhost",
                        "-addext", "subjectAltName=DNS:localhost", "-keyout", key, "-out", cert],
                       check=True, capture_output=True)
        cls.cert = cert
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        cls.socks, cls.held = [], []

        def serve(kind):
            s = socket.socket()
            s.bind(("127.0.0.1", 0))
            s.listen(8)
            cls.socks.append(s)

            def loop():
                while True:
                    try:
                        c, _ = s.accept()
                    except OSError:
                        return
                    if kind == "tls":
                        try:
                            ctx.wrap_socket(c, server_side=True).close()
                        except (ssl.SSLError, OSError):
                            c.close()
                    elif kind == "http":
                        try:
                            c.recv(1024)
                            c.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
                        finally:
                            c.close()
                    else:
                        cls.held.append(c)      # silent: keep it open and say nothing
            threading.Thread(target=loop, daemon=True).start()
            return s.getsockname()[1]

        cls.tls_port, cls.silent_port, cls.http_port = serve("tls"), serve("silent"), serve("http")
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        cls.closed_port = s.getsockname()[1]
        s.close()

    @classmethod
    def tearDownClass(cls):
        for s in cls.socks + cls.held:
            s.close()
        shutil.rmtree(cls.dir)

    def test_a_host_answers_only_if_its_tls_handshake_finishes(self):
        p = self.project("one", {"network": [
            {"host": "localhost", "port": self.tls_port, "why": "speaks TLS"},
            {"host": "localhost", "port": self.silent_port, "why": "accepts, then silence"},
            {"host": "localhost", "port": self.closed_port, "why": "closed"},
            {"host": "localhost", "port": self.silent_port, "probe": "tcp", "why": "never read: same host:port"}]})
        res = self.deps("hosts", p, rc=1, COWORKER_TLS_CA=str(self.cert), COWORKER_NET_TIMEOUT="1")
        lines = {l.split()[0]: l for l in res.stdout.splitlines()}
        self.assertIn(" ok ", lines[f"localhost:{self.tls_port}"])
        self.assertIn("no answer to the TLS handshake", lines[f"localhost:{self.silent_port}"])
        self.assertIn("BLOCKED", lines[f"localhost:{self.closed_port}"])

    def test_an_http_host_answers_only_if_a_request_gets_a_status_line(self):
        p = self.project("one", {"network": [{"host": "localhost", "port": self.silent_port, "probe": "http", "why": "silent"},
                                             {"host": "localhost", "port": self.http_port, "probe": "http", "why": "answers"}]})
        lines = {l.split()[0]: l for l in self.deps("hosts", p, rc=1, COWORKER_NET_TIMEOUT="1").stdout.splitlines()}
        self.assertIn("no answer to an HTTP request", lines[f"localhost:{self.silent_port}"])
        self.assertIn(" ok ", lines[f"localhost:{self.http_port}"])

    def test_port_80_is_probed_with_http_unless_it_says_otherwise(self):
        self.assertEqual(load_module().default_probe(80), "http")
        self.assertEqual(load_module().default_probe(443), "tls")

    def test_a_plain_tcp_service_says_probe_tcp(self):
        p = self.project("one", {"network": [{"host": "localhost", "port": self.silent_port, "probe": "tcp", "why": "not TLS"}]})
        self.deps("hosts", p, rc=0, COWORKER_NET_TIMEOUT="1")

    def test_two_projects_probing_one_host_two_ways_is_a_clash(self):
        a = self.project("a", {"network": [{"host": "h", "port": 8080, "probe": "http", "why": "a"}]})
        b = self.project("b", {"network": [{"host": "h", "port": 8080, "probe": "tcp", "why": "b"}]})
        self.assertIn("probed as http and as tcp", self.deps("hosts", a, b, rc=65).stderr)

    def test_a_certificate_that_doesnt_verify_is_a_problem(self):
        p = self.project("one", {"network": [{"host": "localhost", "port": self.tls_port, "why": "self-signed"}]})
        out = self.deps("hosts", p, rc=1, COWORKER_NET_TIMEOUT="1").stdout
        self.assertIn("CERTIFICATE", out)
        self.assertIn("TLS certificate", out)


class InstallScript(Case):
    def test_install_copies_deps_and_the_homes_own_deps_json(self):
        res = subprocess.run(["sh", str(ROOT / "install.sh")], capture_output=True, text=True, env=self.env, timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        p = self.home / "bin" / "deps"
        self.assertTrue(p.is_file() and os.access(p, os.X_OK))
        self.assertEqual(p.read_bytes(), (ROOT / "bin" / "deps").read_bytes())
        self.assertEqual((self.home / ".coworker" / "deps.json").read_bytes(),
                         (ROOT / ".coworker" / "deps.json").read_bytes())


if __name__ == "__main__":
    unittest.main()


DOCKER = """#!/bin/sh
# docker inspect|start|stop for the stand-in VM: running while FAKE_UP exists
case $1 in
  inspect) [ -f "$FAKE_UP" ] && echo true || echo false ;;
  start) echo "docker start $2" >> "$FAKE_LOG"; touch "$FAKE_UP" ;;
  stop) echo "docker stop $4" >> "$FAKE_LOG"; rm -f "$FAKE_UP" ;;
esac
"""
SSH = """#!/bin/sh
# ssh ... COMMAND: answers while FAKE_UP exists; the OS query gets FAKE_GUEST
for last; do :; done
[ -f "$FAKE_UP" ] || { echo "ssh: connect to host: Connection refused" >&2; exit 255; }
case $last in
  "echo up") echo up ;;
  *) cat > /dev/null; printf '%s\\r\\n' "$FAKE_GUEST" ;;
esac
"""
VMS = str(ROOT / "bin" / "vms")
WIN = {"family": "windows", "name": "Windows 10 Pro", "version": "22H2", "min": "10.0.19045", "why": "Setup's MinVersion"}


class VmsRun(Case):
    def setUp(self):
        super().setUp()
        for name, text in (("docker", DOCKER), ("ssh", SSH)):
            (self.tmp / "stubs" / name).write_text(text)
            (self.tmp / "stubs" / name).chmod(0o755)
        vm = self.home / "vms" / "win"
        vm.mkdir(parents=True)
        (vm / "vm.env").write_text("VM_OS=\"Windows 10 Pro 22H2\"\nVM_CONTAINER=box\nVM_SSH_PORT=2222\n"
                                   "VM_SSH_USER=tester\nVM_SSH_KEY=vm_key\n")
        self.env.update(COWORKER_SSH=str(self.tmp / "stubs" / "ssh"), FAKE_UP=str(self.tmp / "up"),
                        FAKE_GUEST="10.0.19045.6456|22H2|Windows 10 Pro", COWORKER_VM_BOOT_WAIT="2")

    def run_vm(self, d, *cmd, opts=(), rc=None, **env):
        res = subprocess.run(["sh", VMS, "run", "win", d, *opts, "--", *cmd], capture_output=True, text=True,
                             timeout=60, env={**self.env, **env})
        if rc is not None:
            self.assertEqual(res.returncode, rc, res.stdout + res.stderr)
        return res

    def log(self):
        f = self.tmp / "log"
        return f.read_text().splitlines() if f.exists() else []

    def test_a_run_starts_the_vm_checks_it_runs_and_stops_it(self):
        p = self.project("one", {"project": "one", "vms": {"win": {"os": WIN}}})
        out = self.tmp / "seen"
        res = self.run_vm(p, "sh", "-c", f'echo "$COWORKER_VM_LOCKED $VM_SSH_PORT $VM_SSH_USER" > {out}', rc=0)
        self.assertEqual(out.read_text().split(), ["win", "2222", "tester"])
        self.assertEqual(self.log(), ["docker start box", "docker stop box"])
        self.assertIn("win runs Windows 10 Pro 22H2 (build 10.0.19045.6456): meets", res.stdout)
        claim = json.loads((self.home / "vms" / "win.one").read_text())
        self.assertEqual((claim["project"], claim["needs"]["os"]["min"]), ("one", "10.0.19045"))

    def test_a_vm_found_running_is_left_running_and_keep_vm_keeps_one_it_started(self):
        p = self.project("one", {"project": "one"})
        (self.tmp / "up").touch()
        self.run_vm(p, "true", rc=0)
        self.assertEqual(self.log(), [])
        (self.tmp / "up").unlink()
        res = self.run_vm(p, "true", opts=["--keep-vm"], rc=0)
        self.assertEqual(self.log(), ["docker start box"])
        self.assertIn("left running (--keep-vm): stopping it is one's", res.stdout)

    def test_the_commands_exit_is_the_runs_and_the_vm_still_stops(self):
        p = self.project("one", {"project": "one"})
        self.run_vm(p, "sh", "-c", "exit 3", rc=3)
        self.assertEqual(self.log(), ["docker start box", "docker stop box"])

    def test_two_projects_needing_different_guests_clash_before_anything_runs(self):
        self.run_vm(self.project("one", {"project": "one", "vms": {"win": {"os": WIN}}}), "true", rc=0)
        eleven = {**WIN, "name": "Windows 11 Pro", "why": "two wants 11"}
        res = self.run_vm(self.project("two", {"project": "two", "vms": {"win": {"os": eleven}}}),
                          "touch", str(self.tmp / "ran"), rc=65)
        self.assertIn("one needs name 'Windows 10 Pro', two needs 'Windows 11 Pro'", res.stderr)
        self.assertFalse((self.tmp / "ran").exists())
        self.assertEqual(self.log(), ["docker start box", "docker stop box"])     # only the first run's

    def test_a_name_inside_anothers_is_no_clash_and_the_longer_counts(self):
        self.run_vm(self.project("one", {"project": "one", "vms": {"win": {"os": WIN}}}), "true", rc=0)
        older = {"family": "windows", "name": "Windows 10", "min": "10.0.17763", "why": "two runs on 1809+"}
        res = self.run_vm(self.project("two", {"project": "two", "vms": {"win": {"os": older}}}), "true", rc=0)
        self.assertIn("Windows 10 Pro 22H2 build >= 10.0.19045  [one, two]", res.stdout)

    def test_builds_combine_across_projects_and_a_guest_below_them_is_refused(self):
        self.project("one", {"project": "one", "vms": {"win": {"os": WIN}}})
        self.run_vm(self.tmp / "one", "true", rc=0)
        newer = {**WIN, "min": "10.0.19045.6000", "why": "two needs the 2025 patches"}
        res = self.run_vm(self.project("two", {"project": "two", "vms": {"win": {"os": newer}}}),
                          "touch", str(self.tmp / "ran"), rc=69, FAKE_GUEST="10.0.19045.3803|22H2|Windows 10 Pro")
        self.assertIn("build 10.0.19045.3803 is below 10.0.19045.6000", res.stderr)
        self.assertIn("[one, two]", res.stderr)
        self.assertFalse((self.tmp / "ran").exists())
        self.assertEqual(self.log()[-1], "docker stop box")          # started for nothing: stopped again

    def test_a_guest_that_never_answers_is_refused(self):
        p = self.project("one", {"project": "one"})
        res = self.run_vm(p, "true", rc=69, COWORKER_SSH="false")
        self.assertIn("no SSH", res.stderr)

    def test_a_host_need_for_the_vm_that_is_missing_stops_the_run(self):
        p = self.project("one", {"project": "one", "vms": {"win": {"pips": [{"pip": "pillow", "why": "shot.sh"}]}}})
        res = self.run_vm(p, "touch", str(self.tmp / "ran"), rc=1)
        self.assertIn("pillow", res.stdout)
        self.assertIn("[one, for win]", res.stdout)
        self.assertFalse((self.tmp / "ran").exists())
        self.assertEqual(self.log(), [])                               # never started

    def test_the_projects_other_needs_are_mentioned_not_required(self):
        p = self.project("one", {"project": "one", "host": [{"package": "qt-libs", "why": "the project's own tests"}]})
        res = self.run_vm(p, "true", rc=0)
        self.assertIn("lacks 1 of one's other needs, which this run doesn't use", res.stdout)

    def test_vms_list_still_reads_claims_that_carry_needs(self):
        self.run_vm(self.project("one", {"project": "one", "vms": {"win": {"os": WIN}}}), "true", rc=0)
        out = subprocess.run(["sh", VMS, "list"], capture_output=True, text=True, env=self.env).stdout
        self.assertIn("win | Windows 10 Pro 22H2 | claimed by one | free", out)

    def test_claiming_needs_a_project_name(self):
        p = self.project("one", {"host": []})
        self.assertIn('needs "project"', self.run_vm(p, "true", rc=2).stderr)
