# coworker

How projects that share one development machine share its big, slow-to-make things (installer
ISOs and other large downloads, virtual machines) without stepping on each other, and say what the
machine must have installed and reachable for them. The shared thing
records who uses it, so no project's documents need to name another.

This repository is the source. Each project carries it as a **git submodule** at `coworker/`, and
the commands are **installed** from there into the machine's coworker home, which also holds the
shared things. A project calls coworker through its submodule, which checks the installed coworker
and hands the call to it ([Protocol](#protocol)).

| Where | What |
|---|---|
| a project's `coworker/` (a submodule of this repository) | the launcher (`bin/coworker`, and `bin/deps`, `bin/vms`, `bin/downloads` linked to it), what it installs (`libexec/`, `install.sh`), and `PROTOCOL` |
| `$COWORKER_HOME` (`~/coworker` unless set) | the installed commands and the shared things |
| `$COWORKER_HOME/bin/downloads` | shares large downloads ([Downloads](#downloads)) |
| `$COWORKER_HOME/bin/vms` | shares virtual machines ([VMs](#vms)) |
| `$COWORKER_HOME/bin/deps` | checks what the projects need installed and reachable ([Dependencies](#dependencies)) |
| `$COWORKER_HOME/bin/containers` | the container images the projects declare, and the ones no project claims ([Container images](#container-images)) |
| `$COWORKER_HOME/.coworker/deps.json` | coworker's own needs, installed from this checkout's |
| `$COWORKER_HOME/projects/` | each project `deps` has seen: `<project>` holds its checkout's path |
| `$COWORKER_HOME/downloads/` | the downloads, with their checksums and claims |
| `$COWORKER_HOME/vms/` | the VMs' folders, with their claims (each project's needs of the VM) and locks |
| `$COWORKER_HOME/VERSION` | what's installed (`git describe` of the checkout it came from) |
| `$COWORKER_HOME/PROTOCOL` | the installed protocol, `MAJOR.MINOR` ([Protocol](#protocol)) |

`COWORKER_HOME` is the one setting a machine needs; the commands use `${COWORKER_HOME:-$HOME/coworker}`.
`COWORKER_UNATTENDED=1` is for CI, where there's no human ([A new machine](#a-new-machine)).

## Installing

From any project that carries coworker, and only as a human's call (or on their say-so):

    coworker/bin/coworker install [--change]

It runs the submodule's `install.sh`, which copies `libexec/downloads`, `libexec/vms` and
`libexec/deps` into `$COWORKER_HOME/bin` (copies, not links), `.coworker/deps.json` into
`$COWORKER_HOME/.coworker/` and `PROTOCOL` beside it, writes `VERSION`, and creates `downloads/` and
`vms/` if they're missing. It never touches what's in them. Over an install of another protocol it
needs `--change` ([Protocol](#protocol)); without it, it says what would change for which projects
and exits 3. No separate clone of coworker is needed; one is only for working on coworker. Versions
are this repository's tags.

(Versions 1 and 2 of the protocol lived as a `coworker/` folder copied into each project; version 2
made a run that starts a VM stop it; version 3 added `deps` and a project's `.coworker/deps.json`;
version 4 made `coworker/` a submodule that checks the install and hands over.)

## In a project

- **Its name.** A project's name is its checkout directory's name (`~/MyProject` claims as
  `MyProject`): letters, digits, `-` and `_`. `deps` and `vms run` take it from the directory; a script
  that calls `downloads` or `vms claim` itself passes the same (`"$(basename "$HERE")"`).
- **Carrying coworker.** `git submodule add https://github.com/MojoKata/coworker.git coworker`, and
  a bump is `git -C coworker checkout <tag>` and a commit. The machine's projects move to a new
  protocol together ([Protocol](#protocol)).
- **Calling the commands.** Always through the submodule; never the installed copies directly (they
  refuse to change shared state for a caller that doesn't say its protocol). The first line of each
  script:

      "$HERE/coworker/bin/deps" register "$HERE"

  then `"$HERE/coworker/bin/vms" ...` and `"$HERE/coworker/bin/downloads" ...`. Nothing else: the
  submodule finds the install, checks it and says what to do when it's missing or doesn't match.
  `register` never fails a script, even with nothing installed (a project's own container), so a
  script that runs itself again in a container needs no check of its own.
- **Its first step on a machine** is `coworker/bin/coworker status` ([A new machine](#a-new-machine)).

- **What it needs of the machine.** `.coworker/deps.json` in the project's checkout, version-controlled
  with the project ([Dependencies](#dependencies)).
- **Where it's written down.** The project's own documents say what it claims and why. Nothing here
  names a project.

## Protocol

`PROTOCOL` holds `MAJOR.MINOR`. A minor adds something and keeps every earlier client of the same
major working; a major changes the shared state or what a command means.

**The handshake.** Every call through a project's submodule reads the installed `PROTOCOL` and:

| Installed vs the project's submodule | Result |
|---|---|
| same major, installed minor ≥ the submodule's | hands the call to `$COWORKER_HOME/bin/<command>`, with `COWORKER_CLIENT_PROTOCOL` (the submodule's) and `COWORKER_HOME` |
| older minor, or another major (or protocol 3, which wrote no `PROTOCOL`) | exit 3: both numbers, the machine's projects, and `coworker/bin/coworker install --change` |
| nothing installed | `deps register`: one line on stderr, exit 0. Anything else: exit 3 and `coworker/bin/coworker install` |

The installed commands check from their side too: `vms run`, `claim`, `release`, `lock`, `downloads
fetch`, `claim`, `release`, and `deps register`, `status` refuse (exit 3) a call that doesn't carry a
protocol they serve. Looking (`list`, `env`, `check`, `hosts`, `install`) is anyone's.

What the launcher reads of an install, `${COWORKER_HOME:-~/coworker}`, its `bin/<command>` and its
`PROTOCOL`, stays the same in every version, so any launcher can talk to any install.

**Moving to a new protocol.** All the machine's projects move together, with the install, and
nothing changes the install by itself: the machine's owner bumps each project's submodule, then runs
`coworker/bin/coworker install --change` once. A project that was missed gets exit 3 and what to do.

**Exit 3** always means "waiting on a human", with the command to run. The commands' other codes:
1 and 2 for errors, 65, 69 and 75 for VMs ([The command](#the-command)).

## A new machine

    coworker/bin/coworker status [--no-network] [DIR]

is a project's first step on any machine (`DIR`: the project the submodule is in). It does the
handshake, registers the project, does what needs no human, and lists what's waiting on one, each
with its command (exit 3; 0 when nothing waits). The rule: what changes what other projects use,
needs root, or is costly to undo is a human's call; what's read-only or the project's own is
automated.

| Step | Who |
|---|---|
| `git clone --recurse-submodules`, or `git submodule update --init coworker` | automated (the project's own folder) |
| `coworker status`: the handshake, `deps check` | automated (read-only) |
| Installing coworker on the machine for the first time | **asked**: the machine joins, and `COWORKER_HOME` is a machine-wide choice |
| Any change to the installed coworker | **asked** ([Protocol](#protocol)) |
| `deps register` | automated (adds this project, changes nothing for others) |
| The project's own `.venv`, build caches, images | automated |
| Pips (the user's site) and tools (`~/.local/bin`, an SDK, Nix) | **asked**: the machine's projects share them |
| Host packages (`deps install --sudo`, root) | **the human runs it** |
| Claiming a VM or download, `vms run` under the lock | automated |
| Downloading a missing ISO | automated (claimed, and removed with its last claim) |
| Creating a VM | **asked**: hours and big disks, and the VM is shared |
| A protocol mismatch | **asked** |

**Unattended (CI).** With `COWORKER_UNATTENDED=1`, set explicitly (never inferred from `CI`), every
**asked** step is done instead: the launcher installs coworker (with `--change`) rather than exit 3,
and `status` runs `deps install`, each missing tool's `how`, and the host packages through `sudo -n`
(which fails rather than prompts). Nothing waits: what still can't be done exits 1. A client's CI:

    - uses: actions/checkout@<sha>
      with: { submodules: true }
    - run: COWORKER_UNATTENDED=1 coworker/bin/coworker status

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
    vms create  VM [--yes]
    vms update  VM

- **`run`** is the one call a project's script makes: `DIR` is the project's checkout. It
  1. claims the VM for the project (named after its checkout directory) with what the project needs of the VM
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

      [ -n "${COWORKER_VM_LOCKED:-}" ] || exec "$HERE/coworker/bin/vms" run win10 "$HERE" -- sh "$0" "$@"

- **`claim`** records that a project needs the VM. A script can run it each time: it's idempotent.
- **`release`** removes a project's claim. It never deletes a VM: with the last claim gone it says
  so, and the machine's owner decides.
- **`lock`** runs a command holding the VM's lock. A second project's run waits, after saying whose
  run it waits for (`--no-wait`: exits 75 instead). `COMMAND` sees `COWORKER_VM_LOCKED=<vm>`, so a
  script can re-run itself under it:

      [ -n "${COWORKER_VM_LOCKED:-}" ] || exec "$HERE/coworker/bin/vms" lock win10 myproject -- "$0" "$@"

- **`env`** prints how to reach the VM, for a script to `eval "$("$HERE/coworker/bin/vms" env win10)"`:
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
    deps status  [--no-network] DIR                   through coworker status

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

      "$HERE/coworker/bin/deps" register "$HERE"

- **`status`** is what `coworker status` runs after the handshake ([A new machine](#a-new-machine)).

A `DIR` is a project's checkout. Coworker's own `deps.json` (installed with the commands) always
counts too. Each `DIR` is remembered in `$COWORKER_HOME/projects/<project>` (a file holding the
checkout's path), so with no `DIR` every project the machine has seen counts: setting up a machine
is `coworker/bin/coworker status` in each project, and what it lists ([A new machine](#a-new-machine)). A remembered
checkout that's gone is skipped and said; delete its file when the project is.

### `.coworker/deps.json`

```json
{
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
| `project` | optional: if present, it must be the checkout directory's name (a project's name is its directory's) |
| `host` | host packages: `package` is the distribution's name for it (`dnf`/`apt`) |
| `pips` | pips in the system Python (`python3`): `pip` is the distribution name (`pillow`, not `PIL`) |
| `tools` | what comes from its own installer, not the package manager (an SDK, Nix): `tool`, found by `command` (on `PATH`) or `path` (`~` allowed), and `how` to install it, which `deps install` prints and never runs (`status` runs it only unattended) |
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
| `os` | what the guest must be: `family` (`windows` or `linux`: how it's asked), `name` (contained in the guest's product name), `version` (the version people call it: `22H2`, `24.04`), and `min`, `max` or `pin` of its build (`10.0.19045.6456` on Windows, `VERSION_ID` on Linux); `updated_within_days`, a whole number: `vms update` must have left it with nothing to install within that many days (protocol 4.1); `why` |
| `host`, `pips`, `network` | what the host needs to use the VM (as at the top level of `deps.json`) |

`vms run` writes the project's entry into its claim (`<vm>.<project>`, beside the VM's folder), so
the merge sees every project that uses the VM without knowing where their checkouts are. Merging:
the same `family` and `version` (else a clash), names one inside the other (`Windows 10` and
`Windows 10 Pro`: the longer counts), the highest `min` and the lowest `max` of
the build, one `pin`, the smallest `updated_within_days`; the host needs as at the top level.

## VM recipes

A shared VM that coworker can build has a **recipe** in this repository, `vms/<vm>/`, installed as
`$COWORKER_HOME/recipes/<vm>/` (protocol 4.1). A recipe is everything the VM is made from, pinned:
`recipe.env` (the image by its digest, the Windows version, size, account and ports, and the
OpenSSH zip by its SHA-256), `oem/` (what runs at the end of setup), `update.ps1`, and the helpers
copied into the VM's folder (`ssh.sh`, `scp.sh`, `shot.sh`, `keys.sh`). A change to a recipe is a
change to every project's test machine: the machine's owner's call, through a PR here.

    vms create VM [--yes]
    vms update VM

- **`create`** builds the VM from its recipe, replacing the one in `vms/<vm>/`, under the VM's
  lock. Without `--yes` it says what it would replace and for which projects, and exits 3: it's a
  human's call (`COWORKER_UNATTENDED=1` counts as yes). It keeps the folder's `password.txt` and
  `vm_key` (or makes them), checks the OpenSSH zip, writes `vm.env`, keeps the old disk as
  `storage-<date>-old` (delete it once the new VM works), starts the container and waits for SSH
  (`COWORKER_VM_INSTALL_WAIT`, 2 h). It then writes `known_hosts` from the host keys the guest says
  it has, as they answer on the port, runs `update`, notes the build in `history`, and stops the VM.
  The VM's own files that aren't in the recipe (a project's helper scripts, its `README.md`) stay.
- **`update`** brings the guest up to date, under the VM's lock: it starts the VM if it's down (and
  stops it after). When the recipe pins a last cumulative update (`LCU_URL`, `LCU_SHA256`,
  `LCU_BUILD`) and the guest is older, it fetches it (kept in `<vm>/updates/`), installs it with
  `wusa` as SYSTEM and restarts: Windows 10 is past its end of support, and Windows Update offers its
  cumulative updates only to machines with Extended Security Updates. Then it runs `update.ps1` as SYSTEM through a scheduled
  task (the update API refuses an SSH session), restarts the guest when an update asks, and goes
  round again (at most 8 rounds; each may take up to 3 h, `COWORKER_VM_UPDATE_WAIT`). When a round
  finds nothing to install, and the build is at least `LCU_BUILD`, it writes `<vm>/updated` (the
  day and the build), which a project's
  `updated_within_days` need reads. Exit 1 when updates keep failing (`C:\coworker\update.log` in
  the guest says which).

Both reach Microsoft (`deps hosts` lists the hosts): `create` for the ISO, unless
`downloads/<ISO>` holds it, and `update` for Windows Update.

## Container images

A project declares the container images it uses in its `deps.json` (protocol 4.2); declaring is
claiming, so nothing else records who needs an image:

```json
"container_images": [
  { "image": "ubuntu:22.04@sha256:b8b6ee6a…", "why": "builds the AppImage (glibc 2.35)" },
  { "image": "myproject-tier1", "built": "scripts/test-tier1.sh", "from": ["ubuntu:24.04@sha256:00817…"],
    "why": "tier 1: the release's Python on Ubuntu 24.04" }
]
```

| Key | What it is |
|---|---|
| `image` | an image a project pulls, by its tag and, best, its digest (a bare name is refused: it means whatever `:latest` is); or, with `built`, the repository of one a project builds, without a tag (its tag changes as its recipe does) |
| `built` | the script that builds it |
| `from` | the images it's built from, each by tag or digest: claimed too |
| `platform`, `why` | as for the other lists |

`"containers"` is kept for long-lived named containers, should a project have one; the containers
a project runs and removes (`docker run --rm`) aren't declared. A VM's own image is its recipe's
(`IMAGE` in `recipe.env`), claimed by the VM.

- **`deps check`** lists each declared image and whether it's here. One that isn't is no problem:
  docker pulls a pulled image when a script first runs it, and a built one's script builds it
  (a built image named as another's base is that one, never pulled). Only no docker is a problem.
  `deps install` pulls the missing ones ahead, say before going offline. `coworker status` doesn't:
  CI runs it in every job, and pulling every declared image there would cost gigabytes each time.

      containers list
      containers remove [--yes]

- **`list`** reads the declarations of every project the machine has seen, coworker's own and the
  VM recipes', and shows each image here with its size and who claims it, or why no one does:
  *superseded* (an older build of a built image: the newest counts), *near miss* (the repository of
  a declared image, at another tag or digest: a pin that moved on), *undeclared*, or *dangling* (no
  tag). Then the declared images that aren't here, the build cache and volumes, and what
  `remove` would free.
- **`remove`** deletes the images no project claims (superseded, near misses, undeclared,
  dangling), never a claimed one, never the build cache or volumes. It's a human's call: without
  `--yes` it lists them and exits 3 (`COWORKER_UNATTENDED=1` counts as yes). An image a container
  still uses is kept and said.

## Tests

    python3 -m unittest discover -s tests

Standard library only; they need `sh`, `flock` (util-linux), for `fetch`, `curl`, and for the
network checks, `openssl` (a throwaway certificate). Each test
uses a throwaway `COWORKER_HOME`, so they never touch the machine's. `tests/test_protocol.py` runs the
launcher from a project holding a copy of this checkout as its `coworker/`.

## Repository settings

`repo-admin.sh check` reads this repository's GitHub settings back (exit 1 when one differs); `repo-admin.sh
apply`, run by an admin with `gh` logged in, sets them: a ruleset on `main` (a pull request to
merge, squash only, no force push or deletion, the `test` check), squash merging only with the branch deleted once merged, the Actions token
read-only, actions pinned by SHA, fork pull requests' runs approved first, and private vulnerability
reporting. Each MojoKata repository has the same script; only its settings block differs.
