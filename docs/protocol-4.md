# Protocol 4: coworker as a submodule, with the handshake in coworker

A plan, for review before any code. It comes from the owner's walk thru on 2026-11-07. Protocol 3,
the current one, is in the [README](../README.md).

## What changes

Each client project carries coworker as a **git submodule** at `coworker/`. The submodule is the
project's pin: the coworker it's written against, recorded by git. It is also where coworker gets
installed from. It is **never run** for anything else.

The **installed** coworker (`$COWORKER_HOME`, `~/coworker` unless set) stays the only thing that
runs, and it holds the shared state as before: the projects, the claims, the locks, downloads and
VMs. It checks itself against each project's pin (the **handshake**), so compatibility is decided
in coworker's code and tested in coworker's tests, not in each project's scripts or in an agent's
reasoning.

With a submodule in place, no separate clone of coworker is needed. A clone of coworker on its own
is only for working on coworker.

## Decisions (owner, 2026-11-07)

| # | Decision |
|---|---|
| 1 | The check is "installed is compatible with the pin", not "installed equals the pin": projects bump their submodules at different times |
| 2 | Compatibility goes by a **protocol number**, not by commit ancestry (CI's checkouts are shallow, and `VERSION` is a bare commit ID). The commit stays, for information |
| 3 | A run inside a project's own container, where coworker isn't installed, has a defined behaviour: the shared-state calls are made on the host |
| 4 | **No automatic change** to the installed coworker, up or down. A mismatch stops and says what to do; a human decides |
| 5 | The submodule is never run except `coworker/install.sh`, and that only when the human says so. With no install, coworker refuses; it never falls back to the submodule's copy (its claims and locks would be private to that project, so two projects could boot one VM) |

## Design

**Protocol number.** `PROTOCOL` at the repository root holds `MAJOR.MINOR` (this plan starts at
`4.0`). A minor bump adds something and keeps every earlier 4.x client working. A major bump
changes the shared state or a command's meaning. `install.sh` copies `PROTOCOL` into
`$COWORKER_HOME/PROTOCOL`, beside `VERSION`.

**Handshake.** Every installed command that touches shared state (`vms run`, `vms claim`, `vms lock`,
`downloads`) and `deps register` reads the calling project's `coworker/PROTOCOL` (the submodule's
work tree) and compares it with its own:

| Installed vs pin | Result |
|---|---|
| same major, installed minor ≥ pin's | go on |
| same major, installed minor < pin's | stop: "this project needs coworker 4.N; installed is 4.M" and the command to update, listing the projects registered on the machine (an update changes what they run) |
| different major | stop, naming both numbers. Nothing is changed |
| no submodule work tree | stop: "run `git submodule update --init coworker`" (project-local, an agent may run it) |
| no `coworker/` at all (a protocol 3 project) | go on as protocol 3 does, with one line saying the project isn't on protocol 4 yet, until every client project has moved |

`deps register` keeps its rule of never failing a script: on a mismatch it says so on stderr, and
the shared-state commands are what refuse.

**`install.sh`.** It's run from the submodule, by a human or on the human's say-so. It installs
when there's no install. When there is one, it installs a different protocol number only with
`--change`: it prints old → new and the projects registered on the machine, and does nothing
without the flag. The same commit installed again (a repair) needs no flag.

**Project scripts.** The first line stays protocol 3's non-failing one:

    CW=${COWORKER_HOME:-$HOME/coworker}
    [ -x "$CW/bin/deps" ] && "$CW/bin/deps" register "$HERE"

A script that needs a shared thing calls `$CW/bin/vms run` (or `downloads`) and lets that command's
handshake decide. Inside a project's own container there's no install. The non-failing line skips
itself there, and the shared-state calls are made from the host run, so no project needs its own
`if`. On 2026-11-07 one client's build script failed in its container because its scripts made the
check fail hard; the README's line wouldn't have.

**CI.** `actions/checkout` with `submodules: true`, then `coworker/install.sh`: the same path as on
a machine, and the copied commit IDs leave the workflows.

## A client project on a new machine: what's automated, what's asked

The rule: anything that changes what other projects use, needs root, or is costly to undo is the
human's call. What's read-only, or touches only this project, is automated. Coworker's handshake
output says which is which, so an agent relays it rather than working it out.

| Step | Who |
|---|---|
| `git submodule update --init coworker` | automated (inside the project's folder) |
| Handshake, `deps check` | automated (read-only) |
| First install of coworker on the machine (`coworker/install.sh`) | **asked**: the machine joins the protocol, and where `COWORKER_HOME` goes is a machine-level choice |
| Any change to the installed coworker, up or down | **asked** (decision 4) |
| `deps register` with a compatible install | automated (adds this project and changes nothing for the others) |
| The project's own `.venv`, build caches, images | automated |
| Tools in shared user space (`~/.local/bin`, Nix, a JDK) | **asked**: other projects use them too |
| Host packages (`deps install --sudo`, as root) | **the human runs it**, as now |
| Claiming an existing VM or download, `vms run` under the lock | automated (claims are additive; the lock rules already cover sharing) |
| Downloading a missing ISO | automated (claimed, and removed with its last claim) |
| Creating a VM (`vms create`, step 4) | **asked**: hours of work and large disks, and the VM is shared |
| A protocol mismatch | **asked**: stop and name both numbers and the projects |

When something is waiting on a human, the command exits with a distinct code, 3, and
prints each waiting item with its exact command. 3 is free: the commands use 1 and 2 for errors
and 75 for "in use". An agent passes that on and stops there.

## Moving over

1. Coworker: `PROTOCOL`, the handshake, `install.sh --change`, the exit code, tests (each row of the
   handshake table; install refusing a change without the flag; the no-install refusal), README.
   Released as `4.0`.
2. Each client project, one PR each: add the submodule at the 4.0 commit, switch CI to
   `submodules: true` + `coworker/install.sh`, go back to the README's non-failing first line, and
   update the docs to say "install from `coworker/`". One project first, as the proof, then the rest.
3. The installed coworker on the machine moves to 4.0 once, by the owner (decision 4), after step 1
   merges. Until a project's PR lands, it runs as protocol 3 (the last row of the handshake table).

## Open questions

- **Where the handshake runs.** This plan has the installed coworker do it by reading the
  project's submodule, so nothing from the submodule ever runs except `install.sh`. The other
  reading of "the submodule handshake" was a small launcher in the submodule that checks and then
  hands off to the install. That runs submodule code on every call, so this plan leaves it out.
  Confirm.
- **The message when coworker isn't installed at all.** With the non-failing first line, a script
  that needs `vms` finds no `$CW/bin/vms`. The script needs one line to say "coworker isn't installed:
  ask the human, then `coworker/install.sh`". That's the only check left outside coworker. Is
  that acceptable, or should it be a tiny shared snippet?
