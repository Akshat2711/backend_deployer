from __future__ import annotations

import random
import socket


def port_is_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def random_available_port(start: int, end: int, attempts: int = 100) -> int:
    for _ in range(attempts):
        port = random.randint(start, end)
        if port_is_available(port):
            return port
    raise RuntimeError("No available host ports in configured range")
