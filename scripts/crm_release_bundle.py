"""Build an explicit CRM-only context from an env-free reviewed snapshot."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile

SOURCE_SHA = '141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2'


def bundle(snapshot: Path, destination: Path):
    snapshot = snapshot.resolve()
    if (snapshot/'.env').exists() or not (snapshot/'snapshot.json').is_file():
        raise RuntimeError('An env-free frozen snapshot is required')
    if destination.exists():
        raise RuntimeError('Refuse to overwrite an existing release')
    frozen = json.loads((snapshot/'snapshot.json').read_text())
    for name, expected in frozen['files'].items():
        path = snapshot/name
        if not path.resolve().is_relative_to(snapshot) or path.is_symlink():
            raise RuntimeError('Invalid frozen path')
        if hashlib.sha256(path.read_bytes().replace(b'\r\n',b'\n')).hexdigest() != expected:
            raise RuntimeError('Frozen overlay changed: '+name)
    explicit = ['requirements.txt','Dockerfile.crm','alembic.ini','release-source.pdf',
                'docs/kb-visa-inbound-v1.1-derived.md','scripts/crm_initialize.py']
    extensions = {'.py','.html','.css','.js','.txt','.json','.yaml','.yml','.md','.csv','.mako'}
    for folder in ('app','alembic','knowledge/kg_entry'):
        for path in sorted((snapshot/folder).rglob('*')):
            if not path.is_file() or '__pycache__' in path.parts:
                continue
            relative = path.relative_to(snapshot)
            if path.is_symlink() or any(part.startswith('.') for part in relative.parts):
                raise RuntimeError('Unexpected hidden/symlink asset')
            if path.suffix not in extensions:
                raise RuntimeError('Unexpected asset type: '+str(relative))
            explicit.append(relative.as_posix())
    if hashlib.sha256((snapshot/'release-source.pdf').read_bytes()).hexdigest() != SOURCE_SHA:
        raise RuntimeError('Source PDF identity mismatch')
    release = destination/'release'
    release.mkdir(parents=True)
    hashes = {}
    for name in sorted(set(explicit)):
        src = snapshot/name
        if src.is_symlink():
            raise RuntimeError('Symlink forbidden')
        target = release/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(src,target)
        hashes['release/'+name] = hashlib.sha256(target.read_bytes()).hexdigest()
    for name in ('compose.crm.yaml','scripts/crm_prepare_environment.py'):
        target=destination/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(snapshot/name,target)
        hashes[name]=hashlib.sha256(target.read_bytes()).hexdigest()
    manifest = {'snapshot':frozen,'files':hashes}
    raw = json.dumps(manifest,sort_keys=True,indent=2).encode()
    identity = hashlib.sha256(raw).hexdigest()
    (destination/'manifest.json').write_bytes(raw)
    archive = destination.with_suffix('.tar.gz')
    if archive.exists():
        raise RuntimeError('Archive already exists')
    with tarfile.open(archive,'w:gz') as tar:
        for path in sorted(destination.rglob('*')):
            if path.is_file():tar.add(path,arcname=path.relative_to(destination),recursive=False)
    print(json.dumps({'release':identity[:20],'manifest_sha256':identity,
                      'files':len(hashes),'archive':str(archive)}))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args()
    bundle(args.snapshot,args.destination)
