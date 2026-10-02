"""Operator-run Docker deployment with migration, pre-upgrade backup and health gate.
This script never sends credentials to GitHub and never configures DNS for you.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import subprocess

from cryptography.fernet import Fernet
from dotenv import dotenv_values
import requests
from app.config import Settings
from .backup import capture

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ['docker','compose','-f',str(ROOT/'compose.production.yaml')]


def run(args, env, capture_output=False):
    return subprocess.run(COMPOSE + args, cwd=ROOT, env=env, check=True,
                          capture_output=capture_output, text=capture_output)


def initialize(domain, email):
    if not re.fullmatch(r'[a-zA-Z0-9.-]+', domain) or '.' not in domain or not email or '\n' in email or '\r' in email:
        raise ValueError('Provide a valid DNS domain and ACME contact email')
    owner, runtime = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    values = {
        'PUBLIC_ORIGIN':'https://'+domain, 'ACME_EMAIL':email, 'ENVIRONMENT':'production',
        'POSTGRES_PASSWORD':owner, 'RUNTIME_DB_PASSWORD':runtime,
        'MIGRATION_DATABASE_URL':f'postgresql://campusguard:{owner}@db:5432/campusguard',
        'RUNTIME_DATABASE_URL':f'postgresql://campusguard_api:{runtime}@db:5432/campusguard',
        'DATABASE_URL':f'postgresql://campusguard:{owner}@127.0.0.1:5432/campusguard',
        'BIOMETRIC_ENCRYPTION_KEY':Fernet.generate_key().decode(),
        'BACKUP_ENCRYPTION_KEY':Fernet.generate_key().decode(), 'METRICS_TOKEN':secrets.token_urlsafe(32),
    }
    fd = os.open(ROOT/'.env',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as file:
        for key, value in values.items():
            file.write(f'{key}={value}\n')
    print('Configuration generated. Store a protected copy of the encryption keys before deployment.')


def preflight():
    env = {**os.environ, **{k:v for k,v in dotenv_values(ROOT/'.env').items() if v is not None}}
    Settings(database_url=env['RUNTIME_DATABASE_URL'], encryption_key=env['BIOMETRIC_ENCRYPTION_KEY'],
             public_origin=env['PUBLIC_ORIGIN'], environment=env.get('ENVIRONMENT','production'), metrics_token=env['METRICS_TOKEN'])
    Fernet(env['BACKUP_ENCRYPTION_KEY'].encode())
    directory = ROOT/'.deploy'
    directory.mkdir(mode=0o700, exist_ok=True)
    directory.chmod(0o700)
    # Directory protects this file on the host; read-only bind permits Prometheus's non-root UID.
    token_file = directory/'metrics_token'
    temp = directory/'metrics_token.new'
    temp.write_text(env['METRICS_TOKEN'])
    temp.chmod(0o444)
    temp.replace(token_file)
    run(['config','--quiet'],env)
    return env


def rollout(image=None, build=False, allow_first_deploy=False):
    env = preflight()
    if image:
        if not re.fullmatch(r'ghcr\.io/[a-z0-9_.\-/]+@sha256:[0-9a-f]{64}', image):
            raise ValueError('Deployment image must be an immutable ghcr.io digest reference')
        env['CAMPUSGUARD_IMAGE'] = image
    if build:
        run(['build','app'],env)
    elif image:
        run(['pull','app','migrate'],env)
    run(['up','-d','--wait','db'],env)
    check=run(['exec','-T','db','psql','-U','campusguard','-d','campusguard','-tAc',"SELECT to_regclass('public.schema_version')"],env,True)
    exists=bool(check.stdout.strip())
    if not exists and not allow_first_deploy:
        raise RuntimeError('No schema found. Use --first-deploy only for a new empty database.')
    if exists:
        # Quiesce writes before the upgrade backup and migration.
        run(['stop','app'],env)
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        dump_command=COMPOSE+['exec','-T','db','pg_dump','-U','campusguard','-d','campusguard','--format=custom','--no-owner','--no-acl']
        capture(ROOT/'backups'/f'predeploy-{stamp}.dump.enc',env['BACKUP_ENCRYPTION_KEY'],command=dump_command)
    run(['run','--rm','migrate'],env)
    run(['run','--rm','migrate','python','-m','scripts.provision_runtime'],env)
    try:
        run(['up','-d','--wait','--wait-timeout','180','app','proxy','prometheus'],env)
        response=requests.get(env['PUBLIC_ORIGIN']+'/health/ready',timeout=15,allow_redirects=False)
        response.raise_for_status()
        if response.json().get('status') != 'ready':
            raise RuntimeError('External HTTPS readiness check failed')
    except Exception:
        print('Deployment failed its health gate. Inspect container logs and use the recovery runbook. No automatic schema downgrade was attempted.')
        raise
    release={'image':image or env.get('CAMPUSGUARD_IMAGE','campusguard:local'),
             'verified_at':datetime.now(timezone.utc).isoformat(),'schema_version':3}
    (ROOT/'.deploy'/'release.json').write_text(json.dumps(release,indent=2)+'\n')
    print('Deployment passed internal readiness and external HTTPS checks.')


def main():
    parser=argparse.ArgumentParser()
    commands=parser.add_subparsers(dest='operation',required=True)
    init=commands.add_parser('init');init.add_argument('--domain',required=True);init.add_argument('--email',required=True)
    commands.add_parser('check')
    deploy=commands.add_parser('up');deploy.add_argument('--image');deploy.add_argument('--build',action='store_true');deploy.add_argument('--first-deploy',action='store_true')
    args=parser.parse_args()
    if args.operation=='init': initialize(args.domain,args.email)
    elif args.operation=='check': preflight();print('Deployment configuration passed preflight.')
    else: rollout(args.image,args.build,args.first_deploy)


if __name__=='__main__': main()
