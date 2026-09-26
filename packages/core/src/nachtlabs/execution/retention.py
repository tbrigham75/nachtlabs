"""Remove only aged, unreferenced candidate snapshots while broker owns its host lock."""

import re
import shutil
import time

from sqlalchemy import select

from nachtlabs.database import session
from nachtlabs.execution.stages import STORE
from nachtlabs.factory_models import Evidence, RetentionPolicy, Run


def retention_tick() -> None:
    if not STORE.exists():
        return
    with session() as db:
        protected = {str(v) for v in db.scalars(select(Evidence.candidate))}
        for run in db.scalars(select(Run)):
            if run.candidate is not None:
                protected.add(run.candidate)
            base = run.snapshot.get("discovery", {}).get("base_candidate")
            if isinstance(base, str):
                protected.add(base)
        days = max(list(db.scalars(select(RetentionPolicy.artifact_days))) or [90])
    cutoff = time.time() - days * 86400
    for path in STORE.iterdir():
        if not re.fullmatch("[a-f0-9]{64}", path.name) or path.name in protected:
            continue
        if path.is_symlink() or path.resolve().parent != STORE.resolve() or not path.is_dir():
            continue
        if path.stat().st_mtime < cutoff:
            shutil.rmtree(path)
