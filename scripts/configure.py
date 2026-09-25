"""Operator-run Linux credential bootstrap. Refuses to overwrite an existing configuration."""
import argparse
import base64
import getpass
import grp
import os
from pathlib import Path
import secrets
import shlex
from urllib.parse import quote, urlparse


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--origin', required=True)
    parser.add_argument('--development', action='store_true')
    parser.add_argument('--smtp-host', default='')
    parser.add_argument('--smtp-port', type=int, default=587)
    parser.add_argument('--smtp-tls', choices=['starttls', 'tls', 'plain'], default='starttls')
    parser.add_argument('--smtp-from', default='nachtlabs@example.invalid')
    parser.add_argument('--smtp-username', default='')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('Run as a Linux administrator after install-systemd.sh')
    origin = urlparse(args.origin)
    if not origin.hostname or origin.path not in ('', '/') or origin.query or origin.fragment or origin.username:
        raise SystemExit('Provide an origin with no path, query, or credentials')
    if not args.development and origin.hostname and origin.hostname.endswith('.invalid'):
        raise SystemExit('Replace the placeholder hostname with the actual deployment hostname')
    if origin.scheme != 'https' and not (args.development and origin.scheme == 'http' and origin.hostname in ('localhost', '127.0.0.1')):
        raise SystemExit('Use HTTPS, or explicit loopback-only HTTP development')
    if args.smtp_tls == 'plain' and not args.development:
        raise SystemExit('Plain SMTP is limited to development')
    root = Path('/etc/nachtlabs')
    if any((root / name).exists() for name in ('api.env', 'worker.env', 'web.env', 'migration.env')):
        raise SystemExit('Existing configuration found. Refusing to replace credentials or keys.')
    def save(path: Path, value: str, group: str | None = None) -> None:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640 if group else 0o600)
        os.fchmod(fd, 0o640 if group else 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(value + '\n')
        if group:
            os.chown(path, 0, grp.getgrnam(group).gr_gid)
    for name, role, group in [('api-db', 'nachtlabs_api', 'nachtlabs-api'), ('worker-db', 'nachtlabs_worker', 'nachtlabs-worker'), ('migration-db', 'nachtlabs_migrator', None), ('executor-db', 'nachtlabs_executor', None)]:
        password = getpass.getpass(f'PostgreSQL password already assigned to {role}: ')
        if not password:
            raise SystemExit('Empty database passwords are not accepted')
        save(root / 'credentials' / name, f'postgresql+psycopg://{role}:{quote(password, safe="")}@127.0.0.1:5432/nachtlabs', group)
    save(root / 'credentials/master-key', base64.b64encode(secrets.token_bytes(32)).decode(), 'nachtlabs-secrets')
    save(root / 'credentials/bootstrap-token', secrets.token_urlsafe(32), 'nachtlabs-api')
    if args.smtp_username:
        save(root / 'credentials/smtp-password', getpass.getpass('SMTP password: '), 'nachtlabs-secrets')
    common = {
        'NACHTLABS_ENV': 'development' if args.development else 'production',
        'NACHTLABS_PUBLIC_URL': args.origin.rstrip('/'),
        'NACHTLABS_ALLOWED_HOSTS': f'{origin.hostname},localhost,127.0.0.1',
        'NACHTLABS_MASTER_KEY_FILE': str(root / 'credentials/master-key'),
        'NACHTLABS_MASTER_KEY_ID': 'v1',
        'NACHTLABS_INTEGRATION_NETWORK_ENABLED': 'false',
        'NACHTLABS_GIT_PROVIDER_NETWORK_ENABLED': 'false',
        'NACHTLABS_SMTP_HOST': args.smtp_host,
        'NACHTLABS_SMTP_PORT': str(args.smtp_port),
        'NACHTLABS_SMTP_TLS_MODE': args.smtp_tls,
        'NACHTLABS_SMTP_FROM': args.smtp_from,
        'NACHTLABS_SMTP_USERNAME': args.smtp_username,
        'NACHTLABS_SMTP_PASSWORD_FILE': str(root / 'credentials/smtp-password'),
    }
    def env(values: dict[str, str]) -> str:
        if any('\n' in v or '\r' in v for v in values.values()):
            raise SystemExit('Configuration values must not contain newlines')
        return '\n'.join(f'{key}={shlex.quote(value)}' for key, value in values.items())
    save(root / 'api.env', env({**common, 'NACHTLABS_DATABASE_URL_FILE': str(root / 'credentials/api-db'), 'NACHTLABS_BOOTSTRAP_TOKEN_FILE': str(root / 'credentials/bootstrap-token')}))
    save(root / 'worker.env', env({**common, 'NACHTLABS_DATABASE_URL_FILE': str(root / 'credentials/worker-db')}))
    save(root / 'executor.env', env({**common, 'NACHTLABS_DATABASE_URL_FILE': str(root / 'credentials/executor-db')}))
    save(root / 'migration.env', env({**common, 'NACHTLABS_DATABASE_URL_FILE': str(root / 'credentials/migration-db'), 'NACHTLABS_MIGRATION_DATABASE_URL_FILE': str(root / 'credentials/migration-db')}))
    save(root / 'web.env', env({'NODE_ENV': 'production', 'HOSTNAME': '127.0.0.1', 'PORT': '3000', 'NACHTLABS_INTERNAL_API_URL': 'http://127.0.0.1:8000'}))
    print('Configuration created. Credentials were not printed. Review permissions, apply migrations and grants, then start services.')


if __name__ == '__main__':
    main()
