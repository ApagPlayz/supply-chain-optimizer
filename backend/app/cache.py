"""
Cache management for scenario results.
- Stores results in ScenarioCache table
- TTL: 1 hour (3600 seconds)
- Supports get (hit/miss), set (store with expiry), expire (cleanup)

Every key carries the running build's ``code_version()`` as its leading
component. The cache lives in the TRACKED ``backend/supply_chain.db``, so
without that component a deploy that changed a served string or a computed
value kept serving the OLD body for up to the full hour — see
``app/core/version.py`` for the incident this fixes.
"""
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import json
import hashlib
from sqlalchemy.orm import Session
from app.core.version import code_version
from app.models.scenario import ScenarioCache


class CacheManager:
    TTL_SECONDS = 3600  # 1 hour

    @staticmethod
    def generate_key(scenario_type: str, params: Dict[str, Any]) -> str:
        """
        Generate collision-resistant cache key from scenario type and params.

        Args:
            scenario_type: e.g., "distributor-failure"
            params: dict of request parameters (will be sorted for determinism)

        Returns:
            ``"<code_version>:<sha256 hex>"`` — 77 chars.

        The ``code_version()`` prefix is what makes a deploy invalidate the
        cache: entries written by an older build hash to a different key and
        can never be read back. It is a *prefix* rather than another hashed
        field so the stale rows stay identifiable, and
        ``purge_foreign_versions`` can delete them with one indexed query.
        """
        # Sort params by key for deterministic hashing
        sorted_params = json.dumps(params, sort_keys=True, default=str)
        combined = f"{scenario_type}:{sorted_params}"
        return f"{code_version()}:{hashlib.sha256(combined.encode()).hexdigest()}"

    @staticmethod
    def get(db: Session, cache_key: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve cached result if it exists and hasn't expired.

        Args:
            db: SQLAlchemy session
            cache_key: cache key from generate_key()

        Returns:
            Parsed result_json if cache hit and not expired, else None
        """
        record = db.query(ScenarioCache).filter(
            ScenarioCache.cache_key == cache_key
        ).first()

        if not record:
            return None  # Cache miss

        if record.expires_at and record.expires_at <= datetime.utcnow():
            # Cache expired — delete it and return None
            db.delete(record)
            db.commit()
            return None

        # Cache hit — update accessed_at and return result
        record.accessed_at = datetime.utcnow()
        db.commit()

        try:
            return json.loads(record.result_json)
        except json.JSONDecodeError:
            # Corrupted cache entry — delete and return None
            db.delete(record)
            db.commit()
            return None

    @staticmethod
    def set(db: Session, cache_key: str, scenario_type: str, result: Dict[str, Any]) -> None:
        """
        Store result in cache with 1-hour expiry.

        Args:
            db: SQLAlchemy session
            cache_key: cache key from generate_key()
            scenario_type: e.g., "distributor-failure"
            result: response dict to cache
        """
        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=CacheManager.TTL_SECONDS)

        # Delete existing record if present (ensure uniqueness constraint)
        db.query(ScenarioCache).filter(
            ScenarioCache.cache_key == cache_key
        ).delete()

        record = ScenarioCache(
            scenario_type=scenario_type,
            cache_key=cache_key,
            result_json=json.dumps(result),
            created_at=now,
            expires_at=expires_at,
            accessed_at=now,
        )
        db.add(record)
        db.commit()

    @staticmethod
    def cleanup_expired(db: Session) -> int:
        """
        Delete all expired cache entries.

        Args:
            db: SQLAlchemy session

        Returns:
            Number of rows deleted
        """
        now = datetime.utcnow()
        deleted = db.query(ScenarioCache).filter(
            ScenarioCache.expires_at <= now
        ).delete()
        db.commit()
        return deleted

    @staticmethod
    def purge_foreign_versions(db: Session) -> int:
        """
        Delete every entry written by a build other than the running one.

        The key change alone is already sufficient for *correctness* — a key
        from another build never matches, so a stale body can never be served.
        This is about the table not growing without bound: those rows are dead
        the moment they are written, and would otherwise sit there until their
        1-hour TTL expired and the cleanup loop happened to run. Since the DB
        is tracked and committed, rows written by a local run that never
        reached the cleanup loop ride into production in the repo — there are
        such rows in the working tree today.

        Called at startup and on every cleanup pass, so the table holds only
        entries the running code can actually hit.

        Returns:
            Number of rows deleted
        """
        prefix = f"{code_version()}:"
        deleted = db.query(ScenarioCache).filter(
            ~ScenarioCache.cache_key.startswith(prefix)
        ).delete(synchronize_session=False)
        db.commit()
        return deleted
