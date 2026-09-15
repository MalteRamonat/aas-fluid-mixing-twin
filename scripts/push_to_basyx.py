#!/usr/bin/env python
"""Push the built environment into a running BaSyx AAS environment and verify it.

The compose stack preloads ``out/modva.aasx`` on start, so for a fresh stack this script is a
verification tool. It is the update path when the environment is rebuilt while the stack is
running, and its ``--verify`` pass is the definitive check that the Java server accepted the
metamodel-3.1 serialisation the Python SDK produces.

Usage::

    python scripts/push_to_basyx.py                 # push everything, then verify
    python scripts/push_to_basyx.py --verify        # only read back and compare
    python scripts/push_to_basyx.py --aasx          # upload out/modva.aasx via POST /upload
    python scripts/push_to_basyx.py --url http://host:8081

Exit status is non-zero when the server's copy differs from the local build.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from basyx.aas import model

from aas_fluid_twin import config
from aas_fluid_twin.aas import Endpoints, build_environment, load_context
from aas_fluid_twin.aas.environment import BuiltEnvironment
from aas_fluid_twin.aas.traverse import fingerprint, id_short_paths
from aas_fluid_twin.client import BasyxClient, BasyxError

DEFAULT_URL = os.environ.get("AAS_BASYX_URL", "http://localhost:8081")


def wait_until_up(client: BasyxClient, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if client.is_up():
            return
        time.sleep(2.0)
    raise SystemExit(f"BaSyx at {client.base_url} did not become healthy within {seconds:.0f} s")


def push(client: BasyxClient, env: BuiltEnvironment) -> None:
    concepts = list(env.concept_descriptions())
    print(f"pushing {len(concepts)} concept descriptions …", end=" ", flush=True)
    for concept in concepts:
        client.put_concept_description(concept)
    print("ok")

    print(f"pushing {len(env.submodels)} submodels …", end=" ", flush=True)
    for submodel in env.submodels.values():
        client.put_submodel(submodel)
    print("ok")

    print(f"pushing {len(env.shells)} shells …", end=" ", flush=True)
    for shell in env.shells.values():
        client.put_shell(shell)
    print("ok")


def push_attachments(client: BasyxClient, env: BuiltEnvironment) -> int:
    """Upload every File element's bytes. Returns the number uploaded."""
    by_part = {a.package_path: a for a in env.attachments}
    count = 0
    for submodel in env.submodels.values():
        for path, element in id_short_paths(submodel):
            if not isinstance(element, model.File) or not element.value:
                continue
            attachment = by_part.get(element.value)
            if attachment is None or not attachment.exists:
                continue
            client.upload_attachment(
                submodel.id,
                path,
                attachment.source.name,
                attachment.source.read_bytes(),
                attachment.content_type,
            )
            count += 1
    return count


def verify(client: BasyxClient, env: BuiltEnvironment, *, check_attachments: bool) -> bool:
    """Read everything back and compare against the local build. True when identical."""
    remote = model.DictIdentifiableStore[model.Identifiable]()
    problems: list[str] = []

    for aas_id in env.shells:
        try:
            remote.add(client.get_shell(aas_id))
        except BasyxError as error:
            problems.append(str(error))
    for submodel_id in env.submodels:
        try:
            remote.add(client.get_submodel(submodel_id))
        except BasyxError as error:
            problems.append(str(error))

    local = fingerprint(env.store, ignore_file_values=True)
    served = fingerprint(remote, ignore_file_values=True)
    for identifier, expected in local.items():
        if identifier not in served:
            if identifier in env.shells or identifier in env.submodels:
                problems.append(f"missing on server: {identifier}")
            continue
        if served[identifier] != expected:
            diff = sorted(set(expected) ^ set(served[identifier]))
            problems.append(f"differs: {identifier} ({len(diff)} lines), e.g. {diff[:3]}")

    remote_cds = set(client.list_concept_description_ids())
    missing_cds = {cd.id for cd in env.concept_descriptions()} - remote_cds
    if missing_cds:
        problems.append(f"{len(missing_cds)} concept descriptions missing on server")

    if check_attachments:
        checked = 0
        by_part = {a.package_path: a for a in env.attachments}
        for submodel in env.submodels.values():
            for path, element in id_short_paths(submodel):
                if not isinstance(element, model.File) or not element.value:
                    continue
                attachment = by_part.get(element.value)
                if attachment is None or not attachment.exists:
                    continue
                try:
                    served_bytes = client.download_attachment(submodel.id, path)
                except BasyxError as error:
                    problems.append(str(error))
                    continue
                if (
                    hashlib.sha256(served_bytes).digest()
                    != hashlib.sha256(attachment.source.read_bytes()).digest()
                ):
                    problems.append(f"attachment differs: {submodel.id_short}/{path}")
                checked += 1
        print(f"attachments checked: {checked}")

    for problem in problems[:20]:
        print(f"  ✗ {problem}")
    if len(problems) > 20:
        print(f"  … and {len(problems) - 20} more")
    return not problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url", default=DEFAULT_URL, help=f"AAS environment URL (default {DEFAULT_URL})"
    )
    parser.add_argument("--verify", action="store_true", help="only read back and compare")
    parser.add_argument(
        "--aasx", action="store_true", help="upload out/modva.aasx instead of pushing objects"
    )
    parser.add_argument("--no-attachments", action="store_true", help="skip file uploads / checks")
    parser.add_argument("--wait", type=float, default=120.0, help="seconds to wait for the server")
    args = parser.parse_args()

    timeseries_api = os.environ.get("AAS_TIMESERIES_ENDPOINT", Endpoints().timeseries_api)
    sim_runner = os.environ.get("AAS_SIM_RUNNER_ENDPOINT", Endpoints().sim_runner)
    env = build_environment(
        load_context(endpoints=Endpoints(timeseries_api=timeseries_api, sim_runner=sim_runner))
    )

    with BasyxClient(args.url) as client:
        wait_until_up(client, args.wait)
        print(f"BaSyx at {args.url} is up")

        if args.aasx and not args.verify:
            package = config.OUT_DIR / "modva.aasx"
            if not package.is_file():
                raise SystemExit(f"{package} not found — run scripts/build_aas.py first")
            print(
                f"uploading {package.name} ({package.stat().st_size / 1e6:.1f} MB) …",
                end=" ",
                flush=True,
            )
            client.upload_aasx(package)
            print("ok")
        elif not args.verify:
            push(client, env)
            if not args.no_attachments:
                uploaded = push_attachments(client, env)
                print(f"uploaded {uploaded} attachments")

        print("verifying …")
        ok = verify(client, env, check_attachments=not args.no_attachments)
        print("server copy matches the local build" if ok else "MISMATCH — see above")
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
