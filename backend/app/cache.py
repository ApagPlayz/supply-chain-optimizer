"""
Cache management for scenario results.
- Stores results in ScenarioCache table
- TTL: 1 hour (3600 seconds)
- Supports get (hit/miss), set (store with expiry), expire (cleanup)
"""
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import json
import hashlib
from sqlalchemy.orm import Session
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
            Hex-encoded SHA256 hash (64 chars)
        """
        # Sort params by key for deterministic hashing
        sorted_params = json.dumps(params, sort_keys=True, default=str)
        combined = f"{scenario_type}:{sorted_params}"
        return hashlib.sha256(combined.encode()).hexdigest()

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
