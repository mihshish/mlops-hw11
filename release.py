"""Strict metadata contract and atomic, single-writer publication."""
import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def cache_key(data_path: Path, config: dict) -> str:
    return sha(canonical({'data_sha256': file_sha(data_path), 'config': config}))


def validate_manifest(manifest):
    if not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int or manifest['schema_version'] != 1:
        raise ValueError('Invalid manifest schema')
    for key in ('model_id', 'artifact_uri'):
        if not isinstance(manifest.get(key), str) or not manifest[key].strip():
            raise ValueError('Missing ' + key)
    for key in ('model_sha256', 'protocol_sha256', 'golden_sha256', 'runtime_sha256'):
        if not isinstance(manifest.get(key), str) or not re.fullmatch('[0-9a-f]{64}', manifest[key]):
            raise ValueError('Invalid ' + key)
    runtime = manifest.get('runtime')
    if not isinstance(runtime, dict) or not runtime:
        raise ValueError('Missing runtime')
    try:
        actual = sha(canonical(runtime))
    except (TypeError, ValueError) as exc:
        raise ValueError('Invalid runtime') from exc
    if actual != manifest['runtime_sha256']:
        raise ValueError('Stale runtime hash')


def validate_release(manifest: dict, report: dict) -> None:
    validate_manifest(manifest)
    if not isinstance(report, dict) or report.get('status') != 'complete' or report.get('passed') is not True:
        raise ValueError('Incomplete or rejected evaluation')
    if not isinstance(report.get('evaluation_run_id'), str) or not report['evaluation_run_id'].strip():
        raise ValueError('Missing evaluation run ID')
    for key in ('model_id', 'model_sha256', 'protocol_sha256', 'golden_sha256', 'runtime_sha256'):
        if report.get(key) != manifest[key]:
            raise ValueError('Evaluation binding mismatch: ' + key)
    metrics = report.get('metrics')
    if not isinstance(metrics, dict):
        raise ValueError('Missing metrics')
    for key in ('accuracy', 'format_rate'):
        value = metrics.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError('Invalid metric ' + key)


def atomic_bytes(target, payload):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def publish(manifest: dict, report: dict, target: Path) -> None:
    validate_release(manifest, report)
    atomic_bytes(target, canonical(manifest) + b'\n')


def verify_artifact(manifest):
    """Recompute file hashes before publication AND actual backend loading."""
    validate_manifest(manifest)
    artifact = Path(manifest['artifact_uri']).resolve()
    root = artifact if artifact.is_dir() else artifact.parent
    expected = manifest.get('file_hashes')
    if not isinstance(expected, dict) or not expected:
        raise ValueError('Missing artifact file list')
    actual = {}
    for name, digest in expected.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError('Unsafe or missing artifact file: ' + name)
        actual[name] = file_sha(path)
        if actual[name] != digest:
            raise ValueError('Artifact modified: ' + name)
    if sha(canonical(actual)) != manifest['model_sha256']:
        raise ValueError('Artifact aggregate hash mismatch')
    return artifact
