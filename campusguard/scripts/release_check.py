"""Check the source payload for credential/data files before a public upload.
This conservative check is useful, but is not a full history/secret scanner.
"""
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parent.parent


def main():
    result=subprocess.run(['git','ls-files','-z'],cwd=ROOT,check=True,capture_output=True)
    paths=[p for p in result.stdout.decode().split('\0') if p]
    if not paths:
        # Enables checking a freshly extracted archive before git add.
        paths=[str(p.relative_to(ROOT)) for p in ROOT.rglob('*') if p.is_file() and not any(part in {'.git','node_modules','.venv','__pycache__','.pytest_cache'} for part in p.relative_to(ROOT).parts)]
    problems=[]
    private_names={'.env','.env.terminal','metrics_token','id_rsa','id_ed25519'}
    forbidden_suffixes={'.sqlite','.sqlite3','.db','.dump','.enc','.pem','.key','.pyc'}
    for name in paths:
        path=Path(name)
        if path.name in private_names or path.suffix in forbidden_suffixes or any(part in {'backups','data','.deploy'} for part in path.parts):
            problems.append(name+': private/generated file')
            continue
        if path.suffix not in {'.py','.js','.mjs','.md','.html','.yaml','.yml','.txt','.example','.json'}:
            continue
        text=(ROOT/path).read_text(errors='replace')
        if re.search(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',text):
            problems.append(name+': private key')
        if re.search(r'(?:ghp_|github_pat_)[a-zA-Z0-9_]{30,}',text):
            problems.append(name+': possible GitHub credential')
    if problems:
        raise SystemExit('\n'.join(problems))
    print(f'Release payload check passed ({len(paths)} files). Review git history and photos separately before publishing.')


if __name__=='__main__': main()
