"""Operator-run integration fixtures; never target the application database."""
import base64
import os
from pathlib import Path
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from nachtlabs.database import engine, limiter_engine
from nachtlabs.security import new_token
from nachtlabs.settings import get_settings
from nachtlabs_api.main import create_app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    credential = os.environ.get('NACHTLABS_TEST_DATABASE_URL_FILE')
    if not credential:
        pytest.skip('Operator has not configured a dedicated PostgreSQL test database')
    url = Path(credential).read_text().strip()
    database = make_url(url).database or ''
    if not database.endswith('_test'):
        pytest.fail('Destructive fixture isolation requires a database ending _test')
    master = tmp_path / 'master'
    master.write_text(base64.b64encode(os.urandom(32)).decode())
    bootstrap = tmp_path / 'bootstrap'
    bootstrap.write_text(new_token())
    monkeypatch.setenv('NACHTLABS_ENV', 'test')
    monkeypatch.setenv('NACHTLABS_PUBLIC_URL', 'http://testserver')
    monkeypatch.setenv('NACHTLABS_ALLOWED_HOSTS', 'testserver')
    monkeypatch.setenv('NACHTLABS_DATABASE_URL_FILE', credential)
    monkeypatch.setenv('NACHTLABS_MASTER_KEY_FILE', str(master))
    monkeypatch.delenv('NACHTLABS_PREVIOUS_MASTER_KEYS_FILE', raising=False)
    monkeypatch.setenv('NACHTLABS_BOOTSTRAP_TOKEN_FILE', str(bootstrap))
    monkeypatch.setenv('NACHTLABS_SMTP_HOST', 'localhost')
    monkeypatch.setenv('NACHTLABS_INTEGRATION_NETWORK_ENABLED', 'false')
    monkeypatch.setenv('NACHTLABS_GIT_PROVIDER_NETWORK_ENABLED', 'false')
    get_settings.cache_clear()
    engine.cache_clear()
    limiter_engine.cache_clear()
    db_engine = create_engine(url, hide_parameters=True)
    with db_engine.begin() as connection:
        if connection.scalar(text('SELECT version_num FROM alembic_version')) != '0003':
            pytest.fail('Apply the migration to the disposable test database first')
        connection.execute(text('TRUNCATE organizations, worker_heartbeats, rate_buckets, mail_jobs CASCADE'))
    with TestClient(create_app(), headers={'Origin': 'http://testserver'}) as browser:
        yield browser
    engine().dispose()
    limiter_engine().dispose()
    limiter_engine.cache_clear()
    engine.cache_clear()
    get_settings.cache_clear()
    db_engine.dispose()


@pytest.fixture
def owner(client: TestClient) -> TestClient:
    response = client.post('/api/v1/auth/setup', json={
        'bootstrap_token': get_settings().bootstrap_token_file.read_text(),
        'email': 'owner@example.com', 'name': 'Test Owner', 'organization': 'Test Factory',
        'password': new_token(),
    })
    assert response.status_code == 201, response.text
    client.headers['X-CSRF-Token'] = client.cookies['nachtlabs_csrf']
    return client
