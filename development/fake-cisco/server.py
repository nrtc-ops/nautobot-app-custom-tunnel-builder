#!/usr/bin/env python3
"""Fake Cisco IOS-XE SSH server for integration testing.

Accepts any SSH credentials, simulates enough IOS-XE prompt behavior to
satisfy Netmiko's cisco_xe driver, and records every config command it
receives to /output/commands.txt (one command per line).

Also prints all received commands to stdout so `docker logs` works.

Session flow that Netmiko expects:
  connect  → router#
  enable   → Password: → (any password) → router#
  conf t   → router(config)#
  <cmds>   → router(config)#
  end      → router#
  write memory → Building configuration...[OK] → router#
"""

import socket
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import paramiko

HOST_KEY_PATH = "/var/fake-cisco/host_key"
OUTPUT_FILE = "/output/commands.txt"
LISTEN_PORT = 22
HOSTNAME = "fake-router"


class _ServerInterface(paramiko.ServerInterface):
    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED if kind == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_auth_password(self, username, password):
        return paramiko.AUTH_SUCCESSFUL

    def check_auth_publickey(self, username, key):
        return paramiko.AUTH_SUCCESSFUL

    def get_allowed_auths(self, username):
        return "password,publickey"

    def check_channel_shell_request(self, channel):
        return True

    def check_channel_pty_request(self, channel, term, width, height, pixelwidth, pixelheight, modes):
        return True


def _append_to_file(lines: list[str]) -> None:
    Path(OUTPUT_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "a") as f:
        for line in lines:
            f.write(line + "\n")
        f.flush()


class _Session:
    """One SSH shell session."""

    def __init__(self, channel: paramiko.Channel) -> None:
        self.channel = channel
        self.state = "privileged"   # start privileged — no need to 'enable' in tests
        self.config_commands: list[str] = []
        self._buf = b""

    # ------------------------------------------------------------------ #
    # I/O helpers                                                          #
    # ------------------------------------------------------------------ #

    def _send(self, text: str) -> None:
        self.channel.send(text.encode("utf-8"))

    def _prompt(self) -> str:
        if self.state == "config":
            return f"{HOSTNAME}(config)# "
        return f"{HOSTNAME}# "

    # ------------------------------------------------------------------ #
    # Command handling                                                     #
    # ------------------------------------------------------------------ #

    def _handle_line(self, line: str) -> None:
        """Process one complete input line and send the appropriate response."""
        cmd = line.strip()

        # Skip blank lines — just re-emit prompt
        if not cmd:
            self._send(f"\r\n{self._prompt()}")
            return

        cmd_lower = cmd.lower()

        if self.state == "privileged":
            if cmd_lower == "enable":
                # Already privileged; ask for password anyway so enable() doesn't hang
                self._send("\r\nPassword: ")
                return
            if cmd_lower in ("terminal length 0", "terminal width 511", "terminal width 0",
                              "terminal no monitor"):
                self._send(f"\r\n{self._prompt()}")
                return
            if cmd_lower in ("configure terminal", "conf t", "conf terminal"):
                self.state = "config"
                self._send(
                    "\r\nEnter configuration commands, one per line.  End with CNTL/Z.\r\n"
                    f"{self._prompt()}"
                )
                return
            if cmd_lower in ("write memory", "write mem", "wr mem", "wr"):
                self._send(f"\r\nBuilding configuration...\r\n[OK]\r\n{self._prompt()}")
                return
            if cmd_lower.startswith("copy running-config"):
                self._send(f"\r\nBuilding configuration...\r\n[OK]\r\n{self._prompt()}")
                return
            if cmd_lower in ("exit", "logout", "quit"):
                self._send("\r\nGoodbye.\r\n")
                return
            # Unrecognised exec command — just echo the prompt
            self._send(f"\r\n{self._prompt()}")
            return

        if self.state == "config":
            if cmd_lower == "end":
                self.state = "privileged"
                self._send(f"\r\n{self._prompt()}")
                return
            if cmd_lower == "exit":
                self.state = "privileged"
                self._send(f"\r\n{self._prompt()}")
                return
            # A real config command — record it
            self.config_commands.append(cmd)
            self._send(f"\r\n{self._prompt()}")
            return

    def _handle_enable_password(self, line: str) -> None:
        """Called after 'enable' → 'Password:' to consume the secret."""
        # Ignore actual value; grant access unconditionally
        self.state = "privileged"
        self._send(f"\r\n{self._prompt()}")

    # ------------------------------------------------------------------ #
    # Session loop                                                         #
    # ------------------------------------------------------------------ #

    def run(self) -> None:
        """Read from channel until closed, process line by line."""
        waiting_for_enable_secret = False
        self._send(f"\r\n{self._prompt()}")

        try:
            while True:
                data = self.channel.recv(4096)
                if not data:
                    break
                self._buf += data

                # Process every complete line in the buffer
                while True:
                    for sep in (b"\r\n", b"\n", b"\r"):
                        if sep in self._buf:
                            raw, self._buf = self._buf.split(sep, 1)
                            line = raw.decode("utf-8", errors="replace")
                            if waiting_for_enable_secret:
                                self._handle_enable_password(line)
                                waiting_for_enable_secret = False
                            else:
                                # Peek: is this the "enable" command?
                                if line.strip().lower() == "enable":
                                    waiting_for_enable_secret = True
                                self._handle_line(line)
                            break
                    else:
                        break  # no more complete lines

        finally:
            self._flush_output()
            self.channel.close()

    def _flush_output(self) -> None:
        if not self.config_commands:
            return
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        header = f"# === Session {ts} ==="
        print(header, flush=True)
        for cmd in self.config_commands:
            print(cmd, flush=True)
        _append_to_file([header] + self.config_commands)


# ------------------------------------------------------------------ #
# Server bootstrap                                                     #
# ------------------------------------------------------------------ #


def _load_or_generate_host_key() -> paramiko.RSAKey:
    path = Path(HOST_KEY_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return paramiko.RSAKey(filename=str(path))
    key = paramiko.RSAKey.generate(2048)
    key.write_private_key_file(str(path))
    return key


def _accept_loop(sock: socket.socket, host_key: paramiko.RSAKey) -> None:
    while True:
        conn, addr = sock.accept()
        print(f"Connection from {addr[0]}:{addr[1]}", flush=True)

        transport = paramiko.Transport(conn)
        transport.add_server_key(host_key)

        server_interface = _ServerInterface()
        try:
            transport.start_server(server=server_interface)
        except paramiko.SSHException as exc:
            print(f"SSH negotiation failed: {exc}", flush=True)
            continue

        channel = transport.accept(timeout=20)
        if channel is None:
            print("Client never opened a channel.", flush=True)
            continue

        session = _Session(channel)
        t = threading.Thread(target=session.run, daemon=True)
        t.start()


def main() -> None:
    host_key = _load_or_generate_host_key()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", LISTEN_PORT))
    sock.listen(50)
    print(f"Fake Cisco IOS-XE SSH server listening on :{LISTEN_PORT}", flush=True)

    _accept_loop(sock, host_key)


if __name__ == "__main__":
    main()
