"""Export measured metadata only; archives never contain weights or runtime caches."""
import hashlib
import shutil
import subprocess
from pathlib import Path
import release
from process_core import write


def main():
    destination=Path('evidence/release'); destination.mkdir(parents=True,exist_ok=True)
    for name in ('accepted.json','manifest-baseline.json','manifest-candidate.json',
                 'report-baseline.json','report-candidate.json',
                 'release-report-baseline.json','release-report-candidate.json'):
        shutil.copy2(Path('.runtime/real')/name,destination/name)
    files={p.as_posix():release.file_sha(p) for folder in ('evidence','upstream')
           for p in sorted(Path(folder).rglob('*')) if p.is_file() and p!=Path('evidence/manifest.json')}
    tracked=subprocess.check_output(['git','ls-files','-z']).decode('utf-8').split('\0')
    source={name:release.file_sha(name) for name in sorted(tracked) if name.endswith('.py')}
    head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    write('evidence/manifest.json',dict(source_commit=head,
          original_commit='59c11d4c9c510780b85a5a72c0170f83724f1278',files_sha256=files,
          python_sources_sha256=source,measured_model_training=False))
    print('Exported release manifests, actual decisions, hashes and immutable evidence; no weights')


if __name__=='__main__': main()
