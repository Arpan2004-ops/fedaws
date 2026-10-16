"""Run the whole federation as local processes, without Docker.

This is the fastest inner loop while developing: no image builds, and every
process logs to the same terminal. ``docker compose up`` exercises the real
container images and is what the cloud deployment mirrors.

    python scripts/run_local.py --rounds 5
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from typing import List

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOSPITAL_IDS = ["a", "b", "c"]


def base_environment(args: argparse.Namespace) -> dict:
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONPATH": os.pathsep.join(
                [os.path.join(REPO_ROOT, "common"), os.path.join(REPO_ROOT, "fl_server")]
            ),
            "PYTHONUNBUFFERED": "1",
            "STORAGE_BACKEND": "local",
            "LOCAL_ROOT": args.artifacts,
            "NUM_ROUNDS": str(args.rounds),
            "NUM_HOSPITALS": str(len(HOSPITAL_IDS)),
            "LOCAL_EPOCHS": str(args.local_epochs),
            "BATCH_SIZE": str(args.batch_size),
            "LEARNING_RATE": str(args.learning_rate),
            "DP_ENABLED": "true" if args.dp else "false",
            "DP_NOISE_MULTIPLIER": str(args.noise_multiplier),
            "DP_CLIP_NORM": str(args.clip_norm),
            "TLS_ENABLED": "true" if args.tls else "false",
            "TLS_CA_PATH": os.path.join(REPO_ROOT, "certs", "ca.crt"),
            "TLS_CERT_PATH": os.path.join(REPO_ROOT, "certs", "server.crt"),
            "TLS_KEY_PATH": os.path.join(REPO_ROOT, "certs", "server.key"),
            "RUN_ID": args.run_id,
            # With TLS on, the hostname must match a Subject Alternative Name in
            # the aggregator certificate, so dial "localhost" rather than the IP.
            "SERVER_ADDRESS": "localhost:8080" if args.tls else "127.0.0.1:8080",
            "BIND_ADDRESS": "0.0.0.0:8080",
        }
    )
    return environment


def main() -> int:
    parser = argparse.ArgumentParser(description="Run FedMed locally as plain processes")
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--local-epochs", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--dp", action="store_true", help="Enable differential privacy")
    parser.add_argument("--noise-multiplier", type=float, default=0.05)
    parser.add_argument("--clip-norm", type=float, default=1.0)
    parser.add_argument(
        "--tls",
        action="store_true",
        help="Encrypt the gRPC channel using the certificates in ./certs",
    )
    parser.add_argument("--run-id", default="local-run")
    parser.add_argument("--data", default=os.path.join(REPO_ROOT, "data"))
    parser.add_argument(
        "--artifacts",
        default=os.environ.get("LOCAL_ROOT") or os.path.join(REPO_ROOT, "artifacts"),
        help="Where checkpoints and metrics are written. The sweep gives each "
             "configuration its own directory so runs cannot overwrite each other.",
    )
    args = parser.parse_args()

    environment = base_environment(args)
    processes: List[subprocess.Popen] = []

    server_environment = dict(environment)
    server_environment["TEST_SHARD"] = os.path.join(args.data, "server", "test.npz")
    print("starting aggregation server ...")
    server = subprocess.Popen(
        [sys.executable, os.path.join(REPO_ROOT, "fl_server", "server.py")],
        env=server_environment,
        cwd=REPO_ROOT,
    )
    processes.append(server)

    time.sleep(3)  # let the gRPC listener bind before the hospitals dial in

    for hospital_id in HOSPITAL_IDS:
        hospital_environment = dict(environment)
        hospital_environment["HOSPITAL_ID"] = hospital_id
        hospital_environment["SHARD_PATH"] = os.path.join(
            args.data, f"hospital_{hospital_id}", "shard.npz"
        )
        print(f"starting hospital {hospital_id} ...")
        processes.append(
            subprocess.Popen(
                [sys.executable, os.path.join(REPO_ROOT, "hospital_node", "client.py")],
                env=hospital_environment,
                cwd=REPO_ROOT,
            )
        )

    try:
        exit_code = server.wait()
    except KeyboardInterrupt:
        exit_code = 130
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()

    print(f"server exited with code {exit_code}")
    print(f"artifacts in {environment['LOCAL_ROOT']}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
