"""Portable baseline API setup from public pinned HF weights and saved full eval."""
import copy
import shutil
from pathlib import Path
from process_core import read,write
import release


def main():
    from huggingface_hub import snapshot_download
    inventory=read('upstream/inventories.json')['baseline']
    manifest=copy.deepcopy(inventory)
    directory=Path(snapshot_download(manifest['base_model'],revision=manifest['runtime']['base_revision'])).resolve()
    manifest['artifact_uri']=str(directory); manifest['base_artifact_uri']=str(directory)
    release.verify_artifact(manifest)
    root=Path('.runtime/real'); root.mkdir(parents=True,exist_ok=True)
    if (root/'accepted.json').exists(): raise ValueError('Workspace already initialized; do not silently overwrite accepted version')
    from provenance import decision
    report=decision(root,manifest)
    write(root/'manifest-baseline.json',manifest); write(root/'report-baseline.json',report)
    release.publish(manifest,report,root/'accepted.json')
    shutil.copy2('upstream/data/eval/golden.jsonl',root/'input.txt')
    write(root/'config.json',dict(tokenizer_revision=manifest['runtime']['base_revision'],
        template_sha256=manifest['runtime']['template_sha256'],max_length=2048,
        code_revision=release.file_sha('process_core.py'),schema='golden-jsonl'))
    print('Pinned baseline restored; no adapter loading/training/evaluation is claimed')


if __name__=='__main__': main()
