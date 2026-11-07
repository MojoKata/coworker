"""Tiny QEMU human-monitor client (runs inside the dockurr container)."""
import socket, sys, time

def _until_prompt(s, timeout=15.0):
    buf, end = b"", time.time() + timeout
    while time.time() < end:
        try:
            chunk = s.recv(65536)
        except socket.timeout:
            continue
        if not chunk:
            break
        buf += chunk
        if buf.rstrip().endswith(b"(qemu)"):
            break
    return buf.decode(errors="replace")

def cmd(line):
    s = socket.socket(socket.AF_UNIX); s.connect("/run/shm/monitor.sock"); s.settimeout(0.5)
    _until_prompt(s)                                   # banner
    s.sendall((line + "\n").encode())
    out = _until_prompt(s)                             # returns once the command has completed
    s.close()
    return out

for line in sys.argv[1:]:
    cmd(line)
