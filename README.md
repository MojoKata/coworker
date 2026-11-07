# coworker

How projects that share one development machine share its big, slow-to-make things (installer
ISOs and other large downloads, virtual machines) without stepping on each other. The shared thing
records who uses it, so no project's documents need to name another.

This repository is the source. The commands are **installed** from it into the machine's coworker
home, which also holds the shared things; the checkout itself never holds them.

| Where | What |
|---|---|
| a checkout of this repository | the source: `bin/`, `install.sh`, `tests/`, this README |
| `$COWORKER_HOME` (`~/coworker` unless set) | the installed commands and the shared things |
| `$COWORKER_HOME/bin/downloads` | shares large downloads ([Downloads](#downloads)) |
| `$COWORKER_HOME/bin/vms` | shares virtual machines ([VMs](#vms)) |
| `$COWORKER_HOME/downloads/` | the downloads, with their checksums and claims |
| `$COWORKER_HOME/vms/` | the VMs' folders, with their claims and locks |
| `$COWORKER_HOME/VERSION` | what's installed (`git describe` of the checkout it came from) |

`COWORKER_HOME` is the only setting. The commands use `${COWORKER_HOME:-$HOME/coworker}` whether
they run installed or from a checkout.

## Installing

    git clone https://github.com/MojoKata/coworker.git && coworker/install.sh

`install.sh` copies `bin/downloads` and `bin/vms` into `$COWORKER_HOME/bin` (copies, not links),
writes `VERSION`, and creates `downloads/` and `vms/` if they're missing. It never touches what's in
them, so updating is `git pull` and `install.sh` again. Versions are this repository's tags.
(Versions 1 and 2 of the protocol lived as a `coworker/` folder copied into each project; version 2
made a run that starts a VM stop it.)

## In a project

- **Its name.** A project claims things under one name: letters, digits, `-` and `_`.
- **Calling the commands.** A project's scripts call the installed copies, and say how to get them
  when they're missing:

      CW=${COWORKER_HOME:-$HOME/coworker}
      [ -x "$CW/bin/vms" ] || { echo "coworker isn't installed: run install.sh from a checkout of MojoKata/coworker" >&2; exit 1; }

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

    vms claim   VM PROJECT
    vms release VM PROJECT
    vms lock    VM PROJECT [--no-wait] -- COMMAND [ARG...]
    vms env     VM
    vms list

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
- **A run that starts the VM stops it.** A project starts the VM if it isn't running, and then
  stops it when the run ends, pass or fail, still holding the lock: an idle VM holds its memory for
  nothing. A run that found it running leaves it running. A project may offer a way to keep it
  running (for runs back to back); a VM left running that way is that project's to stop.
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

## Tests

    python3 -m unittest discover -s tests

Standard library only; they need `sh`, `flock` (util-linux) and, for `fetch`, `curl`. Each test
uses a throwaway `COWORKER_HOME`, so they never touch the machine's.
