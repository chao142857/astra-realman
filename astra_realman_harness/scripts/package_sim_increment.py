#!/usr/bin/env python3
"""Portable local handoff: committed source + frozen assets/raw evidence, no auth."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(root):
    manifest=json.loads((root/'MANIFEST.json').read_text())
    for rel,digest in manifest['files'].items():
        p=root/rel
        if not p.is_file() or p.is_symlink() or sha(p)!=digest:raise ValueError('PACKAGE_HASH:'+rel)
    actual={str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()}
    if actual!=set(manifest['files'])|{'MANIFEST.json'}:raise ValueError('PACKAGE_EXTRA_OR_MISSING_FILES')
    return manifest


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo',type=Path,required=True)
    p.add_argument('--evidence',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    dirty=subprocess.check_output(['git','-C',str(a.repo),'status','--porcelain'],text=True)
    if dirty:raise ValueError('COMMIT_SOURCE_BEFORE_PACKAGING')
    commit=subprocess.check_output(['git','-C',str(a.repo),'rev-parse','HEAD'],text=True).strip()
    data=subprocess.check_output(['git','-C',str(a.repo),'archive','--format=tar','HEAD'])
    code=a.output/'source';code.mkdir()
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for member in archive.getmembers():
            if member.issym() or member.islnk() or member.name.startswith('/') or '..' in Path(member.name).parts:
                raise ValueError('UNSAFE_SOURCE_ARCHIVE_MEMBER')
        archive.extractall(code)
    # Explicit simulation evidence root only. Never traverse home/config/login folders.
    for path in a.evidence.rglob('*'):
        if path.is_symlink():raise ValueError('EVIDENCE_SYMLINK')
        if path.name.endswith('.token') or path.name in ('auth.json','config.toml'):
            raise ValueError('CREDENTIAL_FILE_NOT_ALLOWED')
    shutil.copytree(a.evidence,a.output/'evidence')
    subprocess.run(['git','-C',str(a.repo),'bundle','create',str(a.output/'source.bundle'),'HEAD'],check=True)
    files={str(x.relative_to(a.output)):sha(x) for x in sorted(a.output.rglob('*')) if x.is_file()}
    manifest={'commit':commit,'files':files,'raw_paths':'historical absolute paths are unchanged; resolve under evidence/ after relocation',
              'dependencies':'Existing Python environment excluded; versions/requirements recorded in evidence',
              'scope':'Local engineering handoff; no model/hardware authorization'}
    (a.output/'MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
    verify(a.output)
    archive_path=a.output.with_suffix('.tar.gz')
    if archive_path.exists():raise ValueError('ARCHIVE_ALREADY_EXISTS')
    with tarfile.open(archive_path,'w:gz') as archive:archive.add(a.output,arcname=a.output.name)
    # Verify extraction in a fresh directory, not only the gzip stream.
    restored=a.output.parent/(a.output.name+'-verify');restored.mkdir(exist_ok=False)
    with tarfile.open(archive_path) as archive:archive.extractall(restored)
    verify(restored/a.output.name)
    digest=sha(archive_path)
    archive_path.with_suffix(archive_path.suffix+'.sha256').write_text(digest+'  '+archive_path.name+'\n')
    print(json.dumps({'commit':commit,'archive':str(archive_path),'sha256':digest,
                      'verified_files':len(files),'restored':str(restored/a.output.name)},indent=2))


if __name__=='__main__':main()
