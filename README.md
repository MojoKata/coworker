# coworker

How projects that share one development machine share its big, slow-to-make things (installer
ISOs and other large downloads, virtual machines) without stepping on each other, and say what the
machine must have installed and reachable for them. The shared thing
records who uses it, so no project's documents need to name another.

This repository is the source. The commands are **installed** from it into the machine's coworker
home, which also holds the shared things; the checkout itself never holds them.

| Where | What |
|---|---|
| a checkout of this repository | the source: `bin/`, `install.sh`, `tests/`, this README |
| `$COWORKER_HOME` (`~/coworker` unless set) | the installed commands and the shared things |
| `$COWORKER_HOME/bin/downloads` | shares large downloads ([Downloads](#downloads)) |
| `$COWORKER_HOME/bin/vms` | shares virtual machines ([VMs](#vms)) |
| `$COWORKER_HOME/bin/deps` | checks what the projects need installed and reachable ([Dependencies](#dependencies)) |
| `$COWORKER_HOME/.coworker/deps.json` | coworker's own needs, installed from this checkout's |
| `$COWORKER_HOME/projects/` | each project `deps` has seen: `<project>` holds its checkout's path |
| `$COWORKER_HOME/downloads/` | the downloads, with their checksums and claims |
| `$COWORKER_HOME/vms/` | the VMs' folders, with their claims (each project's needs of the VM) and locks |
| `$COWORKER_HOME/VERSION` | what's installed (`git describe` of the checkout it came from) |

`COWORKER_HOME` is the only setting. The commands use `${COWORKER_HOME:-$HOME/coworker}` whether
they run installed or from a checkout.

## Installing

    git clone https://github.com/MojoKata/coworker.git && coworker/install.sh

`install.sh` copies `bin/downloads`, `bin/vms` and `bin/deps` into `$COWORKER_HOME/bin` (copies, not
links) and `.coworker/deps.json` into `$COWORKER_HOME/.coworker/`, writes `VERSION`, and creates `downloads/` and `vms/` if they're missing. It never touches what's in
them, so updating is `git pull` and `install.sh` again. Versions are this repository's tags.
(Versions 1 and 2 of the protocol lived as a `coworker/` folder copied into each project; version 2
made a run that starts a VM stop it; version 3 added `deps` and a project's `.coworker/deps.json`.)

## In a project

- **Its name.** A project claims things under one name: letters, digits, `-` and `_`.
- **Calling the commands.** A project's scripts call the installed copies, and say how to get them
  when they're missing:

      CW=${COWORKER_HOME:-$HOME/coworker}
      [ -x "$CW/bin/vms" ] || { echo "coworker isn't installed: run install.sh from a checkout of MojoKata/coworker" >&2; exit 1; }

- **What it needs of the machine.** `.coworker/deps.json` in the project's checkout, version-controlled
  with the project ([Dependencies](#dependencies)).
- **Where it's written down.** The project's own documents say what it claims and why. Nothing here
  names a project.

## Downloads

One folder, `$COWORKER_HOME/downloads`, for every large download the projects need (installer ISOs
above all), so each is downloaded once, checked once, and deleted only when no project needs it any
more.

| File | What it is |
|---|---|
| `<file>` | the download, complete and checked |
| `<file>.sha256` | its SHA-256, as `<hash>  <file>` (what `sha256sum -c` reads) |
| `<file>.<project>` | an empty file: that project needs it (a *claim*) |
| `<file>.part` | a download in progress or stopped; `fetch` resumes it |
| `<file>.lock` | held while `fetch` downloads that file, so a second one waits |
| `<file>.bad` | a copy that failed its SHA-256 and was set aside; delete it once looked at |

A project isn't named `sha256`, `sha256sum`, `part`, `lock` or `bad`.

    downloads fetch   FILE PROJECT URL SHA_URL
    downloads claim   FILE PROJECT
    downloads release FILE PROJECT
    downloads list    [--verify]

- **`fetch`** downloads `URL` as `FILE.part`, checks its SHA-256 against `SHA_URL`, renames it into
  place and claims it for `PROJECT`. `SHA_URL` may be the one hash or a mirror's list that names the
  file (a `sha256sum.txt`); the hash is kept as `FILE.sha256`. Run the same command again after a
  failure and it resumes from the `.part`. A file already there and matching is only claimed; one
  that doesn't match is set aside as `.bad` and fetched again. A host the machine can't reach
  directly is fetched through a container (`curlimages/curl`), when Docker is there.
- **`claim`** records that a project needs a file already there (or about to be).
- **`release`** removes a project's claim; with the last claim gone it removes the file and its
  `.sha256`, `.part`, `.bad` and `.lock`.
- **`list`** lists every file, there or claimed and still on its way, with its size and claims;
  `--verify` checks each against its SHA-256 (it reads every file: a minute or two).

Rules:

- **Never** download into a project's own folders, and never delete a file a project still claims:
  `release` is the only way a download leaves.
- A project checks a file's SHA-256 before using it (`sha256sum -c --status <file>.sha256` in the
  folder); `fetch` does on every download.
- A project claims what it uses when it starts using it (its scripts can run `claim` each time: it's
  idempotent), and releases it when it's done with it for good, not after each run.

Maintenance:

- **What's there and who needs it:** `downloads list`. A file listed *unclaimed* is needed by no
  project: ask the machine's owner, then delete it (or `claim` it for the project that does need it).
- **Leftovers:** a `.part` no download is running for can be resumed (`fetch`, same arguments) or
  deleted; a `.bad` can be deleted once looked at; a `.lock` with no file is harmless.
- **Replacing a file with a newer release:** fetch the new one under its own name, move each
  project's claim to it as that project moves (`claim` the new, `release` the old), and the old one
  goes with its last claim.
- **A file a VM boots from** belongs to the VM's folder; a hard link to it in `downloads/`, claimed
  like any other, shares the space instead of keeping two copies.

## VMs

A VM that more than one project tests on (a Windows VM, say) is kept in `$COWORKER_HOME/vms`,
described once, and used by one project at a time. A VM only one project uses stays in that
project's own folders; this is for the shared ones.

| File | What it is |
|---|---|
| `<vm>/` | the VM's folder: its disks, its `README.md` and its `vm.env` |
| `<vm>/README.md` | what the VM is, how it was built, how to rebuild it, and what it keeps for everyone |
| `<vm>/vm.env` | how a project reaches it (below) |
| `<vm>.<project>` | an empty file: that project needs the VM (a *claim*) |
| `<vm>.lock` | held while a project uses the VM; while held, it names the holder |

A VM's name is letters, digits, `-`, `_` and `.`; a project isn't named `lock`.

A VM that runs in a Docker container has the container named `coworker-<vm>` (the VM `win10`
runs as `coworker-win10`), so `docker ps` says which containers are the shared VMs. Its `vm.env`
names it as `VM_CONTAINER`, and scripts use that rather than the name itself.

### `vm.env`

Shell assignments; paths are relative to the VM's folder.

| Setting | What it is |
|---|---|
| `VM_OS` | what runs in it, e.g. `Windows 10 Pro 22H2` |
| `VM_CONTAINER` | the Docker container that runs it, if one does: `coworker-<vm>` (`docker start` starts it) |
| `VM_SSH_HOST` | where its SSH server is reached (default `127.0.0.1`) |
| `VM_SSH_PORT` | that port (required) |
| `VM_SSH_USER` | the account a project's scripts sign in as (required) |
| `VM_SSH_KEY` | the private key for it (required) |
| `VM_KNOWN_HOSTS` | the VM's host key, as `ssh` keeps it (default `known_hosts`) |

The account, password, key and ports are the VM's, not a project's: every project uses the same
ones, and a rebuild keeps them.

### The command

    vms run     VM DIR [--keep-vm] [--no-wait] -- COMMAND [ARG...]
    vms claim   VM PROJECT
    vms release VM PROJECT
    vms lock    VM PROJECT [--no-wait] -- COMMAND [ARG...]
    vms env     VM
    vms list

- **`run`** is the one call a project's script makes: `DIR` is the project's checkout. It
  1. claims the VM for the project (its `deps.json` names it) with what the project needs of the VM
     (its `"vms"` entry, [below](#what-a-project-needs-of-a-vm)) written into the claim;
  2. merges every claimant's needs, and stops (exit **65**) if they can't all hold;
  3. checks that the host has what using the VM takes (exit **1**: `deps install`); the project's
     other needs are only mentioned;
  4. takes the lock (waiting for another project's run; `--no-wait`: exit **75**);
  5. starts the VM's container if it's down, waits for SSH (`COWORKER_VM_BOOT_WAIT`, 900 s), and
     checks the guest against the merged needs (exit **69** if it falls short);
  6. runs `COMMAND` with `COWORKER_VM_LOCKED=<vm>` and every `vms env` setting exported;
  7. stops the VM if this run started it, pass or fail (or Ctrl-C), unless `--keep-vm`.

  The exit is `COMMAND`'s otherwise. A script re-runs itself under it:

      [ -n "${COWORKER_VM_LOCKED:-}" ] || exec "$CW/bin/vms" run win10 "$HERE" -- sh "$0" "$@"

- **`claim`** records that a project needs the VM. A script can run it each time: it's idempotent.
- **`release`** removes a project's claim. It never deletes a VM: with the last claim gone it says
  so, and the machine's owner decides.
- **`lock`** runs a command holding the VM's lock. A second project's run waits, after saying whose
  run it waits for (`--no-wait`: exits 75 instead). `COMMAND` sees `COWORKER_VM_LOCKED=<vm>`, so a
  script can re-run itself under it:

      [ -n "${COWORKER_VM_LOCKED:-}" ] || exec "$CW/bin/vms" lock win10 myproject -- "$0" "$@"

- **`env`** prints how to reach the VM, for a script to `eval "$("$CW/bin/vms" env win10)"`:
  `VM_HOME` (the VM's folder) and each `vm.env` setting, with the key and known-hosts paths made
  absolute.
- **`list`** lists each VM, what it is, its claims, and who holds it now.

Rules:

- **One project at a time.** Hold the lock for the whole use, from starting the VM to the last file
  copied back. The projects share its ports, its desktop and its signed-in session.
- **Leave it as you found it.** A setting changed for a run (the screen's size, say) is put back or
  not saved. A project's files go in folders named after the project (on Windows,
  `C:\Users\Public\<project>-…`). What a project installs, it uninstalls, unless the VM's
  `README.md` lists it as kept for everyone.
- **A run that starts the VM stops it.** `vms run` starts the VM if it isn't running, and then
  stops it when the run ends, pass or fail, still holding the lock: an idle VM holds its memory for
  nothing. A run that found it running leaves it running. `--keep-vm` keeps it running (for runs back
  to back); a VM left running that way is that project's to stop.
- **Needs are merged, and a clash stops the run.** Each project says what it needs of a VM in its
  own `deps.json`; `vms run` combines them all and refuses (65, 69, 1) rather than run on a VM some
  project can't use. The agent working at the time sorts it out: in coworker, the project, the VM or
  the system, with the machine's owner where it's theirs.
- **The VM itself is everyone's.** Its account, password, key, ports, operating-system version and
  update policy change only by the machine's owner, through its `README.md`, and a rebuild keeps
  what `vm.env` says.

Maintenance:

- **What's there, who needs it, who's using it:** `vms list`. A VM listed *unclaimed* is needed by
  no project: ask the machine's owner before deleting it.
- **A held lock with no run behind it** can't happen: the lock is a `flock` on `<vm>.lock`, and it
  goes with the process that holds it. The file's text is only the last holder's name.
- **Adding a VM:** its folder in `vms/`, with `README.md` and `vm.env` (and, if a container runs
  it, the container named `coworker-<vm>`); then each project that needs it claims it.

## Dependencies

Each project says in its own `.coworker/deps.json` what the machine must have for it: host packages,
pips in the system Python, tools from their own installers, and network hosts it reaches. `deps` reads those files, and coworker's
own, and says what's missing, installs it, and lists the hosts for the machine's firewall. The
install has two halves: what the user can install (the pips), which an agent runs, and the host
packages, which need root and which the machine's owner runs with `sudo`.

    deps check   [--no-network] [DIR...]
    deps install [--dry-run] [DIR...]                 as the user, never root
    sudo ~/coworker/bin/deps install --sudo [--dry-run] [DIR...]   as root only
    deps hosts   [DIR...]
    deps register DIR

- **`check`** lists every need with what's installed and whether it's met, and whether each host
  answers. Exit 1 if anything is missing, out of range or unreachable; 2 if a `deps.json` is wrong or
  two projects' needs clash.
- **`install`** (as the user; it refuses to run as root) installs the missing pips into the user's
  site (`pip install --user`, after `ensurepip --user` when the Python has no pip), checks again, and
  says which host packages are left for the `--sudo` run. Exit 0 only when nothing is left.
- **`install --sudo`** (as root; it refuses otherwise, except with `--dry-run`, which says so on
  stderr and prints the commands anyway) installs the missing host packages with one
  `dnf install` (or `apt-get install`), checks them again, and writes nothing in the user's home.
  An installed `deps` uses the home it's installed in (`<home>/bin/deps` beside `<home>/VERSION`), so
  root sees the same projects whether it comes by `sudo` or a root login:
  `/home/<user>/coworker/bin/deps install --sudo`. (A copy run from a checkout falls back to
  `SUDO_USER`'s `~/coworker` under `sudo`.)
- **`--dry-run`** (`-n`) prints the commands that half would run, one per line on stdout, and runs
  nothing; what's left for the other half (and the tools' installers) goes to stderr as `#` lines.
  Each half stops at the first command that fails.
- **`hosts`** lists every network host the projects need, whether it answers, and why it's needed:
  what to open on a firewall. `BLOCKED` is no answer (or not as far as the probe goes);
  `CERTIFICATE` is an answer with a certificate the system doesn't accept for that name, which a
  firewall rule doesn't fix.

- **`register`** is for the first line of a project's scripts: it remembers the checkout and, if the
  host lacks any of the project's needs, says so in one line on stderr. It never fails the script
  (exit 2 only for a broken `deps.json`): a script that uses a shared VM gets its real check from
  `vms run`, and a project's other needs are for whoever runs `deps check`.

      CW=${COWORKER_HOME:-$HOME/coworker}
      [ -x "$CW/bin/deps" ] && "$CW/bin/deps" register "$HERE"

A `DIR` is a project's checkout. Coworker's own `deps.json` (installed with the commands) always
counts too. Each `DIR` is remembered in `$COWORKER_HOME/projects/<project>` (a file holding the
checkout's path), so with no `DIR` every project the machine has seen counts: setting up a machine
is installing coworker, one `deps check` in each project, `deps install`, and the owner's
`sudo ~/coworker/bin/deps install --sudo` (or, as root, the full path). A remembered
checkout that's gone is skipped and said; delete its file when the project is.

### `.coworker/deps.json`

```json
{
  "project": "myproject",
  "host": [
    { "package": "libglvnd-glx", "platform": "rocky-10*", "min": "1.7.0", "why": "Qt's libGL, for the tests" },
    { "package": "libgl1", "platform": "ubuntu*", "why": "Qt's libGL, for the tests" }
  ],
  "pips": [
    { "pip": "pillow", "min": "13.0.0", "why": "screenshots: its PNGs measured the best size and quality" }
  ],
  "network": [
    { "host": "github.com", "why": "the project's releases" },
    { "host": "deb.debian.org", "port": 80, "why": "apt in the containers, over plain HTTP" },
    { "host": "internal.example", "port": 22, "probe": "tcp", "why": "an SSH service" }
  ]
}
```

| Key | What it is |
|---|---|
| `project` | the project's name (as it claims things); labels its needs in the output |
| `host` | host packages: `package` is the distribution's name for it (`dnf`/`apt`) |
| `pips` | pips in the system Python (`python3`): `pip` is the distribution name (`pillow`, not `PIL`) |
| `tools` | what comes from its own installer, not the package manager (an SDK, Nix): `tool`, found by `command` (on `PATH`) or `path` (`~` allowed), and `how` to install it, which `deps install` prints and never runs |
| `network` | hosts it reaches: `host`, `port` (443), `probe` (how it's tried: `tls`, or `http` on port 80; `tcp` for anything else) |
| `platform` | which machines an entry is for: a glob over `ID-VERSION_ID` from `/etc/os-release` (`rocky-10.2`, `ubuntu-24.04`); every machine if left out |
| `min`, `max` | the versions it accepts, inclusive; `pin`, exactly one (not with `min` or `max`) |
| `why` | required: what needs it, so nobody has to rediscover the reason |

Rules:

- **First match.** In a file, the first entry whose `platform` matches the machine wins for its
  name; later entries with that name are not read. A name with no matching entry isn't needed there.
  So a list can go from the most specific platform to `*`.
- **Projects combine.** The same name in two projects needs both: the highest `min`, the lowest `max`.
  Two different pins, or a `min` above a `max`, is a clash: `deps` reports which projects and stops
  (exit 2). The agent working at the time sorts it out with the machine's owner.
- **Versions** compare as the package manager does (rpm's or dpkg's rules), without the packaging
  revision (`2.15.0-7.el10` meets a pin of `2.15.0`); pips by their release numbers.
- **A host answers** when it gets as far as its real client would: `tls`, a TLS handshake naming
  it finishes; `http`, a request naming it gets a status line back; `tcp`, the connection opens. A
  firewall that filters by name lets the connection open and then never answers, so a connection
  alone proves nothing for HTTPS or HTTP.
- **`sudo` is the owner's.** An agent runs `deps install` and never the `--sudo` half; when host
  packages are missing it asks the owner to run `sudo ~/coworker/bin/deps install --sudo` (or, as root, the full path).

### What a project needs of a VM

A project's `deps.json` says, under `"vms"`, what it needs of each shared VM it uses:

```json
"vms": {
  "win10": {
    "os": { "family": "windows", "name": "Windows 10 Pro", "version": "22H2", "min": "10.0.19045",
            "why": "the Windows the project supports" },
    "pips": [ { "pip": "pillow", "min": "13.0.0", "why": "shot.sh: its PNGs measured the best size and quality" } ]
  }
}
```

| Key | What it is |
|---|---|
| `os` | what the guest must be: `family` (`windows` or `linux`: how it's asked), `name` (contained in the guest's product name), `version` (the version people call it: `22H2`, `24.04`), and `min`, `max` or `pin` of its build (`10.0.19045.6456` on Windows, `VERSION_ID` on Linux); `why` |
| `host`, `pips`, `network` | what the host needs to use the VM (as at the top level of `deps.json`) |

`vms run` writes the project's entry into its claim (`<vm>.<project>`, beside the VM's folder), so
the merge sees every project that uses the VM without knowing where their checkouts are. Merging:
the same `family` and `version` (else a clash), names one inside the other (`Windows 10` and
`Windows 10 Pro`: the longer counts), the highest `min` and the lowest `max` of
the build, one `pin`; the host needs as at the top level.

## Tests

    python3 -m unittest discover -s tests

Standard library only; they need `sh`, `flock` (util-linux), for `fetch`, `curl`, and for the
network checks, `openssl` (a throwaway certificate). Each test
uses a throwaway `COWORKER_HOME`, so they never touch the machine's.
