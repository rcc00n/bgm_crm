"""Run the real application with new synthetic state and no external providers."""

from __future__ import annotations

import argparse
import atexit
import getpass
import ipaddress
import json
import os
from pathlib import Path
import secrets
import runpy
import shutil
import socket
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PG_REQUIRED = True


def disable_external_connections():
    """Fail closed before importing application modules or provider clients."""
    connect, connect_ex = socket.socket.connect, socket.socket.connect_ex
    getaddrinfo = socket.getaddrinfo

    def allowed(address):
        if not isinstance(address, tuple):  # local Unix socket
            return True
        try:
            return ipaddress.ip_address(address[0]).is_loopback
        except ValueError:
            return address[0] == "localhost"

    def guarded_connect(sock, address):
        if not allowed(address):
            raise OSError("External network disabled for SYNTHETIC DEMO")
        return connect(sock, address)

    def guarded_connect_ex(sock, address):
        if not allowed(address):
            raise OSError("External network disabled for SYNTHETIC DEMO")
        return connect_ex(sock, address)

    def guarded_resolve(host, *args, **kwargs):
        if host is not None and not allowed((host, 0)):
            raise OSError("External DNS disabled for SYNTHETIC DEMO")
        return getaddrinfo(host, *args, **kwargs)

    socket.socket.connect = guarded_connect
    socket.socket.connect_ex = guarded_connect_ex
    socket.getaddrinfo = guarded_resolve


def start_private_postgres(state, configured_bin):
    """Use a new, bounded PostgreSQL cluster; never discover an existing DB."""
    candidates = [Path(configured_bin)] if configured_bin else []
    found = shutil.which("initdb")
    if found:
        candidates.append(Path(found).parent)
    candidates.extend(sorted(Path("/usr/lib/postgresql").glob("*/bin"), reverse=True))
    binary = next(
        (
            p
            for p in candidates
            if (p / "initdb").is_file() and (p / "pg_ctl").is_file()
        ),
        None,
    )
    if binary is None:
        raise RuntimeError(
            "Install PostgreSQL server tools or pass --postgres-bin; no Docker or existing database is used"
        )
    password = state / "postgres-password"
    password.write_text(secrets.token_urlsafe(40) + "\n")
    password.chmod(0o600)
    cluster, unix_socket = state / "postgres", state / "socket"
    unix_socket.mkdir(mode=0o700)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    user = getpass.getuser()
    subprocess.run(
        [
            str(binary / "initdb"),
            "-D",
            str(cluster),
            "--no-locale",
            "--encoding=UTF8",
            "--auth-local=trust",
            "--auth-host=scram-sha-256",
            "--pwfile=" + str(password),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    options = f'-h 127.0.0.1 -p {port} -k "{unix_socket}" -c shared_buffers=16MB -c max_connections=8 -c work_mem=2MB -c maintenance_work_mem=16MB -c max_worker_processes=0'
    subprocess.run(
        [
            str(binary / "pg_ctl"),
            "-D",
            str(cluster),
            "-l",
            str(state / "postgres.log"),
            "-o",
            options,
            "-w",
            "start",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )

    def stop():
        subprocess.run(
            [str(binary / "pg_ctl"), "-D", str(cluster), "-m", "fast", "-w", "stop"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    atexit.register(stop)
    config = {
        "host": "127.0.0.1",
        "port": port,
        "database": "bgm_showcase",
        "user": user,
        "password_file": str(password),
    }
    import psycopg2

    connection = psycopg2.connect(
        dbname="postgres",
        host=config["host"],
        port=port,
        user=user,
        password=password.read_text().strip(),
    )
    try:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute("CREATE DATABASE bgm_showcase")
    finally:
        connection.close()
    (state / "postgres.json").write_text(json.dumps(config) + "\n")
    (state / "postgres.json").chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state-dir",
        type=Path,
        help="New private directory; an existing path is refused",
    )
    parser.add_argument("--port", type=int, default=3387)
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Migrate, seed and verify without starting HTTP",
    )
    parser.add_argument(
        "--postgres-bin", help="PostgreSQL server bin directory (BGM only)"
    )
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Choose an unprivileged loopback port between 1024 and 65535")
    if args.state_dir:
        state = args.state_dir.expanduser().resolve()
        state.mkdir(mode=0o700, parents=True, exist_ok=False)
    else:
        state = Path(tempfile.mkdtemp(prefix="synthetic-showcase-"))
    state.chmod(0o700)
    (state / ".synthetic-showcase").write_text(
        "SYNTHETIC DEMO; never production data\n"
    )
    for name in ("django-secret", "admin-password"):
        target = state / name
        target.write_text(secrets.token_urlsafe(40) + "\n")
        target.chmod(0o600)
    os.environ.update(
        SHOWCASE_STATE_DIR=str(state),
        SHOWCASE_PORT=str(args.port),
        DJANGO_SETTINGS_MODULE="showcase_settings",
        PYTHONDONTWRITEBYTECODE="1",
    )
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    os.chdir(ROOT)
    disable_external_connections()
    print(f"SYNTHETIC DEMO · new private state: {state}", flush=True)
    if PG_REQUIRED:
        start_private_postgres(state, args.postgres_bin)
    import django

    django.setup()
    from django.core.management import call_command

    call_command("migrate", interactive=False, verbosity=0)
    runpy.run_path(str(Path(__file__).with_name("seed_showcase.py")))

    print(
        "Checks passed. Login: synthetic-demo. Password is in the private state admin-password file.",
        flush=True,
    )
    print(
        "Keep all state, sessions, logs and generated passwords outside Git.",
        flush=True,
    )
    if not args.prepare_only:
        call_command(
            "runserver",
            f"127.0.0.1:{args.port}",
            use_reloader=False,
            use_threading=False,
        )


if __name__ == "__main__":
    main()
