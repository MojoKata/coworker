# Protocol 4: coworker as a submodule that negotiates with the installed coworker

A plan, for review before any code. It comes from the owner's walk thru on 2026-11-07. Protocol 3,
the current one, is in the [README](../README.md).

## What changes

Each client project carries coworker as a **git submodule** at `coworker/`, and its scripts always
call coworker **through the submodule**. The submodule's commands are a launcher. Each call
negotiates with the **installed** coworker (`$COWORKER_HOME`, `~/coworker` unless set) and then
hands the call to it. Installing and upgrading are the only things the submodule does itself, and
only when a human says so.

The installed coworker stays the only thing that does the work, and it holds the shared state as
before: the projects, the claims, the locks, downloads and VMs. So every project on a machine goes
through one set of code and one set of state, and compatibility is decided in coworker's code,
tested in coworker's tests, not in each project's scripts or in an agent's reasoning.

With the submodule in place, no separate clone of coworker is needed. A clone on its own is only
for working on coworker.

## Decisions (owner, 2026-11-07)

| # | Decision |
|---|---|
| 1 | The check is "installed is compatible with the pin", not "installed equals the pin": projects bump their submodules at different times |
| 2 | Compatibility goes by a **protocol number**, not by commit ancestry (CI's checkouts are shallow, and `VERSION` is a bare commit ID). The commit stays, for information |
| 3 | A run inside a project's own container, where coworker isn't installed, has a defined behaviour |
| 4 | **No automatic change** to the installed coworker, up or down. A mismatch stops and says what to do; a human decides |
| 5 | Project scripts **always call the submodule**. It negotiates with the installed coworker and hands over everything it can, so install and upgrade are the only things run from the submodule's own code, and only on a human's say-so. It never does a shared-state command itself (its claims and locks would be private to one project, so two projects could boot one VM) |
| 6 | **The first step on any machine is getting coworker installed.** After that, "not installed" doesn't come up on the host |

## Design

**Protocol number.** `PROTOCOL` at the repository root holds `MAJOR.MINOR` (this plan starts at
`4.0`). A minor bump adds something and keeps every earlier 4.x client working. A major bump
changes the shared state or a command's meaning. `install.sh` copies it to
`$COWORKER_HOME/PROTOCOL`, beside `VERSION`.

**The launcher.** `bin/coworker` is one POSIX `sh` file, so it runs before anything else is
installed. `bin/deps`, `bin/vms` and `bin/downloads` are the same file under those names, so a
project calls `"$HERE/coworker/bin/vms" run ...` as before, only from its submodule. The real
commands move to `libexec/`, and `install.sh` installs them as `$COWORKER_HOME/bin/*`, as now.
The launcher does this:

1. Finds the install (`${COWORKER_HOME:-$HOME/coworker}`) and reads its `PROTOCOL`. It reads
   nothing else of the install's. This much is frozen for every version, because an old launcher will
   meet a new install and the reverse.
2. Compares the two numbers (the table below).
3. When they're compatible, runs `exec "$COWORKER_HOME/bin/<command>" "$@"` with
   `COWORKER_CLIENT_PROTOCOL` set to its own number. The installed command checks that from its
   side too, so the negotiation is two-way: an install can refuse a client it no longer serves.

| Installed vs this submodule | Result |
|---|---|
| same major, installed minor ≥ the submodule's | hand over |
| same major, installed minor < the submodule's | stop, exit 3: "this project needs coworker 4.N; installed is 4.M", the upgrade command, and the projects registered on the machine (an upgrade changes what they run) |
| different major | stop, exit 3, naming both numbers. Nothing is changed |
| no install | `register`: one line on stderr, exit 0 (decision 3). Anything else: stop, exit 3, "coworker isn't installed: `coworker/bin/coworker install`" |

**Install and upgrade.** `coworker/bin/coworker install` runs the submodule's `install.sh`. It's run
by a human, or by an agent only on the human's say-so. When there's no install, it installs. When
there is one with a different protocol number, it installs only with `--change`: without the flag it
prints old → new and the registered projects, and does nothing. The same number installed again (a
repair) needs no flag.

**Status.** `coworker/bin/coworker status` is the first step on a machine (decision 6). It runs the
handshake and `deps check`, does what's automated (the table below), and prints what's waiting on a
human, each item with its exact command. It exits 3 when something is waiting. An agent runs it,
passes on what it prints, and stops there.

**In a container.** A project script that runs itself again inside its own container finds no
install there. `register` is the first line of every script, and it never fails a script (protocol
3's rule), so the container's run carries on. The shared-state commands belong on the host. No
project needs its own `if`: on 2026-11-07 one client's build script failed in its container because
its scripts made the check fail hard.

**Project scripts.** The first line becomes:

    "$HERE/coworker/bin/deps" register "$HERE"

and the other calls are `"$HERE/coworker/bin/vms" ...` and `"$HERE/coworker/bin/downloads" ...`.
No `COWORKER_HOME` handling and no installed check stay in project scripts.

**CI.** `actions/checkout` with `submodules: true`, then `coworker/bin/coworker install`: the same
path as on a machine, and the copied commit IDs leave the workflows. On a fresh CI machine, CI is the
human's say-so, given once in the workflow.

## A client project on a new machine: what's automated, what's asked

The rule: anything that changes what other projects use, needs root, or is costly to undo is the
human's call. What's read-only, or touches only this project, is automated. `status` says which is
which.

| Step | Who |
|---|---|
| `git clone --recurse-submodules`, or `git submodule update --init coworker` | automated (inside the project's folder) |
| `coworker/bin/coworker status` (handshake, `deps check`) | automated (read-only) |
| First install of coworker on the machine | **asked**: the machine joins the protocol, and where `COWORKER_HOME` goes is a machine-level choice |
| Any change to the installed coworker, up or down | **asked** (decision 4) |
| `deps register` with a compatible install | automated (adds this project and changes nothing for the others) |
| The project's own `.venv`, build caches, images | automated |
| Tools in shared user space (`~/.local/bin`, Nix, a JDK) | **asked**: other projects use them too |
| Host packages (`deps install --sudo`, as root) | **the human runs it**, as now |
| Claiming an existing VM or download, `vms run` under the lock | automated (claims are additive; the lock rules already cover sharing) |
| Downloading a missing ISO | automated (claimed, and removed with its last claim) |
| Creating a VM (`vms create`, step 4) | **asked**: hours of work and large disks, and the VM is shared |
| A protocol mismatch | **asked**: stop and name both numbers and the projects |

Exit 3 means "waiting on a human". It's free: the commands use 1 and 2 for errors and 75 for "in
use".

## Moving over

1. Coworker: `PROTOCOL`, the launcher (`bin/`) and the commands moved to `libexec/`, the two-way
   check, `install --change`, `status`, exit 3, tests (each row of the handshake table, an old
   launcher against a new install and the reverse, install refusing a change without the flag), and
   the README. Released as `4.0`.
2. Each client project, one PR each: add the submodule at the 4.0 commit, call coworker through it,
   switch CI to `submodules: true` + `coworker/bin/coworker install`, and make the docs' first step
   `coworker/bin/coworker status`. One project first, as the proof, then the rest.
3. The installed coworker moves to 4.0 once, by the owner (decision 4), after step 1 merges.
   Projects not moved yet call `$COWORKER_HOME/bin/*` directly with no `COWORKER_CLIENT_PROTOCOL`.
   A 4.0 install treats that as protocol 3 and serves it, with one line saying the project isn't on
   protocol 4 yet, until every client project has moved. Then a 4.x minor release drops it.

## Open questions

- **Protocol 3 clients after the move.** The plan serves them until every client has moved, then
  drops them. Or should an install keep serving the previous major for good?
- **CI's say-so.** Is installing coworker in CI covered once by the workflow, as above, or should CI
  need an explicit setting such as `COWORKER_INSTALL=yes`?
