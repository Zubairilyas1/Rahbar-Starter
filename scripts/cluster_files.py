#!/usr/bin/env python3
"""Move files on and off the RAGOps volumes with short-lived Jobs (no kubectl exec/cp).

kubectl exec / kubectl cp are broken on some Docker Desktop Kubernetes versions
("server gave HTTP response to HTTPS client"), and they need a long-running pod
anyway. These commands use only `kubectl apply` and `kubectl logs`:

    python scripts/cluster_files.py export                  # /results -> eval/results/cluster, /traces -> traces/cluster
    python scripts/cluster_files.py sh "ls -R /datalake"    # run a shell command next to the volumes
    python scripts/cluster_files.py put ./unseen-batch /datalake/incoming   # upload a folder (via a ConfigMap)

All three mount rahbar-datalake (/datalake), rahbar-results (/results) and
rahbar-traces (/traces) in a pod (local rahbar-eval image) with the same security context as the
other workloads. No network policy admits it to anything; it only touches the volumes.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import subprocess
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NS = "rahbar"
IMAGE = "rahbar-eval:dev"   # local image (sh, tar, base64): no registry pull needed


def kubectl(*args: str, inp: str | None = None, check: bool = True) -> str:
    r = subprocess.run(["kubectl", *args], input=inp, capture_output=True, text=True, encoding="utf-8")
    if check and r.returncode != 0:
        sys.exit(f"kubectl {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def run_job(name: str, script: str, extra_volumes: list[dict] | None = None,
            extra_mounts: list[dict] | None = None, timeout: int = 300) -> str:
    kubectl("delete", "job", name, "-n", NS, "--ignore-not-found", "--wait=true")
    vols = [{"name": n, "persistentVolumeClaim": {"claimName": c}}
            for n, c in (("datalake", "rahbar-datalake"), ("results", "rahbar-results"), ("traces", "rahbar-traces"))]
    mounts = [{"name": "datalake", "mountPath": "/datalake"}, {"name": "results", "mountPath": "/results"},
              {"name": "traces", "mountPath": "/traces"}]
    job = {
        "apiVersion": "batch/v1", "kind": "Job",
        "metadata": {"name": name, "namespace": NS, "labels": {"app": "ragops-files"}},
        "spec": {"backoffLimit": 0, "ttlSecondsAfterFinished": 600, "template": {
            "metadata": {"labels": {"app": "ragops-files"}},
            "spec": {
                "restartPolicy": "Never", "automountServiceAccountToken": False,
                "securityContext": {"runAsNonRoot": True, "runAsUser": 1000, "runAsGroup": 1000, "fsGroup": 1000},
                "containers": [{
                    "name": "files", "image": IMAGE, "imagePullPolicy": "IfNotPresent",
                    "command": ["sh", "-c", script],
                    "securityContext": {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
                                        "capabilities": {"drop": ["ALL"]}},
                    "resources": {"requests": {"cpu": "10m", "memory": "16Mi"}, "limits": {"cpu": "200m", "memory": "64Mi"}},
                    "volumeMounts": mounts + (extra_mounts or []),
                }],
                "volumes": vols + (extra_volumes or []),
            }}},
    }
    kubectl("apply", "-f", "-", inp=json.dumps(job))
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = json.loads(kubectl("get", "job", name, "-n", NS, "-o", "json"))["status"]
        if st.get("succeeded") or st.get("failed"):
            break
        time.sleep(2)
    logs = kubectl("logs", f"job/{name}", "-n", NS, check=False)
    if not json.loads(kubectl("get", "job", name, "-n", NS, "-o", "json"))["status"].get("succeeded"):
        sys.stderr.write(logs[-2000:])
        sys.exit(f"job {name} did not succeed")
    return logs


def export() -> int:
    logs = run_job("ragops-export", "cd / && tar czf - results traces | base64")
    data = base64.b64decode("".join(logs.split()))
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        members = [m for m in tar.getmembers() if m.isfile()]
        for m in members:
            top, _, rest = m.name.partition("/")
            dest = (ROOT / "eval" / "results" / "cluster" if top == "results" else ROOT / "traces" / "cluster") / rest
            dest.parent.mkdir(parents=True, exist_ok=True)
            f = tar.extractfile(m)
            if f:
                dest.write_bytes(f.read())
    print(f"exported {len(members)} files -> eval/results/cluster/, traces/cluster/")
    return 0


def put(src: str, dest: str) -> int:
    files = [p for p in Path(src).iterdir() if p.is_file()]
    if not files:
        sys.exit(f"no files in {src}")
    kubectl("delete", "configmap", "ragops-upload", "-n", NS, "--ignore-not-found")
    kubectl("create", "configmap", "ragops-upload", "-n", NS, *[f"--from-file={p}" for p in files])
    logs = run_job("ragops-put", f"mkdir -p {dest} && cp /upload/* {dest}/ && ls -la {dest}",
                   extra_volumes=[{"name": "upload", "configMap": {"name": "ragops-upload"}}],
                   extra_mounts=[{"name": "upload", "mountPath": "/upload"}])
    print(logs)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("export")
    s = sub.add_parser("sh")
    s.add_argument("script")
    p = sub.add_parser("put")
    p.add_argument("src")
    p.add_argument("dest")
    a = ap.parse_args()
    if a.cmd == "export":
        return export()
    if a.cmd == "put":
        return put(a.src, a.dest)
    print(run_job("ragops-sh", a.script), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
