import json
import queue
import random
import socket
from contextlib import contextmanager
from time import sleep

from zeroconf import (
    IPVersion,
    ServiceInfo,
    Zeroconf,
    ServiceBrowser,
    ServiceStateChange,
)


def server(send, recv):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("", 58008))
        s.listen(1)
        print("Waiting for connection...")
        with advertise():
            conn, addr = s.accept()
        print(addr, "connected")
        while True:
            msg = conn.recv(8192)
            if not msg:
                recv.put(["disconnected"])
                return
            recv.put(json.loads(msg))  # TODO: make resilient
            while True:
                response = send.get()  # blocking, wait for game to respond
                if not response and send.qsize():
                    continue  # not guaranteed to work
                break
            print("Actually sending...")
            conn.sendall(json.dumps(response, separators=",:").encode())
    finally:
        s.close()


def client(send, recv):
    conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    print("Connecting...")
    conn.connect(find_server())
    print("Connected!")
    while True:
        try:
            msg = send.get(block=False, timeout=0)
        except queue.Empty:
            sleep(0.5)
            continue
            # msg = {"T": "status"}
        conn.sendall(json.dumps(msg, separators=",:").encode())
        data = conn.recv(8192)
        if not data:
            return
        print("Received:", data)
        recv.put(json.loads(data))
        sleep(0.2)


@contextmanager
def advertise():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(0)
        try:
            s.connect(("10.254.254.254", 1))
            IP = s.getsockname()[0]
        except Exception:
            IP = "127.0.0.1"
    info = ServiceInfo(
        "_halali._tcp.local.",
        f"{random.randint(1, 1000)}._halali._tcp.local.",
        addresses=[socket.inet_aton(IP)],
        port=58008,
    )
    zc = Zeroconf(ip_version=IPVersion.All)
    try:
        zc.register_service(info)
        yield
    finally:
        zc.unregister_service(info)
        zc.close()


def find_server():
    zc = Zeroconf(ip_version=IPVersion.All)
    server = None
    def handler(zeroconf, service_type, name, state_change):
        nonlocal server
        if state_change is ServiceStateChange.Added:
            if info := zeroconf.get_service_info(service_type, name):
                server = (
                    socket.inet_ntoa(info.addresses[0]),
                    info.port,
                )
                return

    ServiceBrowser(
        zc,
        ["_halali._tcp.local."],
        handlers=[handler],
    )
    try:
        for _ in range(20):
            if server:
                return server
            sleep(0.2)
    finally:
        zc.close()


