"""Real HTTP demonstration in three subprocesses; never touches existing runtime data."""

import argparse
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path

import httpx

from building_federation.provision import NODES, provision
from building_federation.service import Node


def run_demo(base_port: int) -> None:
    processes: dict[str, subprocess.Popen] = {}
    with tempfile.TemporaryDirectory(prefix="building-federation-demo-") as temporary:
        root = Path(temporary) / "federation"
        provision(root, base_port)
        # Refuse busy ports before making any requests to an unrelated service.
        with ExitStack() as stack:
            for port in range(base_port, base_port + 3):
                listener = stack.enter_context(socket.socket())
                listener.bind(("127.0.0.1", port))
        with httpx.Client(timeout=10, trust_env=False) as client:
            urls = {node: f"http://127.0.0.1:{base_port + i}" for i, node in enumerate(NODES)}

            def start(node: str) -> None:
                log_path = Path(temporary) / f"{node}.log"
                with log_path.open("ab") as log:
                    process = subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "building_federation",
                            "serve",
                            "--root",
                            str(root),
                            "--node",
                            node,
                        ],
                        stdout=log,
                        stderr=log,
                    )
                processes[node] = process
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError(f"{node} failed to start: {log_path.read_text()}")
                    try:
                        response = client.get(f"{urls[node]}/health", timeout=0.3)
                        if (
                            response.status_code == 200
                            and response.json().get("node_id") == node
                            and process.poll() is None
                        ):
                            return
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                raise RuntimeError(f"{node} startup timed out")

            def stop(node: str) -> None:
                process = processes[node]
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)

            def check(response: httpx.Response, status: int, code: str | None = None) -> None:
                if response.status_code != status:
                    raise AssertionError(f"Expected HTTP {status}, got {response.status_code}")
                if code is not None and response.json().get("detail") != code:
                    raise AssertionError(f"Expected error {code}")

            def unlock() -> httpx.Response:
                return client.post(f"{urls['hvac']}/v1/unlock", json={})

            try:
                for node in NODES:
                    start(node)
                for node in NODES:
                    response = client.post(f"{urls[node]}/v1/unlock", json={})
                    check(response, 200)
                    if response.json()["data"]["controller"] != node:
                        raise AssertionError("Unexpected decrypted owner")
                print("PASS 01: all three controllers unlock with both peers", flush=True)

                # Trusted demo driver reads HVAC identity to create explicit attack fixtures.
                driver = Node(root / "hvac", client)
                request = driver.make_request().model_dump()
                check(client.post(f"{urls['lighting']}/v1/share", json=request), 200)
                check(
                    client.post(f"{urls['lighting']}/v1/share", json=request),
                    409,
                    "replay_detected",
                )
                print("PASS 02: repeated signed request is rejected", flush=True)

                stop("lighting")
                start("lighting")
                check(
                    client.post(f"{urls['lighting']}/v1/share", json=request),
                    409,
                    "replay_detected",
                )
                print("PASS 03: replay protection survives a peer process restart", flush=True)

                forged = driver.make_request().model_dump()
                forged["signature"] = "A" * 88
                check(
                    client.post(f"{urls['lighting']}/v1/share", json=forged),
                    403,
                    "invalid_request_signature",
                )
                print("PASS 04: invalid device signature is rejected", flush=True)

                manifest = root / "hvac" / "manifest.txt"
                original = manifest.read_bytes()
                try:
                    manifest.write_bytes(original + b"unauthorized-update\n")
                    check(unlock(), 503, "quorum_unavailable")
                finally:
                    manifest.write_bytes(original)
                print("PASS 05: changed boot manifest prevents unlock", flush=True)

                storage = root / "hvac" / "storage.enc"
                original = storage.read_bytes()
                try:
                    storage.write_bytes(original + b"tampered")
                    check(unlock(), 503, "quorum_unavailable")
                finally:
                    storage.write_bytes(original)
                print("PASS 06: modified ciphertext prevents unlock", flush=True)

                stop("access")
                check(unlock(), 503, "quorum_unavailable")
                print("PASS 07: one unavailable holder prevents unlock", flush=True)
                start("access")
                check(unlock(), 200)
                print(
                    "PASS 08: unlock recovers with a fresh request after peer recovery", flush=True
                )
            finally:
                for node in list(processes):
                    stop(node)
    print("Demo complete: processes stopped and temporary keys removed.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-port", type=int, default=18101)
    run_demo(parser.parse_args().base_port)


if __name__ == "__main__":
    main()
