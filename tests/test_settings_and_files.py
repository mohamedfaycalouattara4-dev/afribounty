import unittest
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from config.settings.base import database_from_url
from config.settings.validators import validate_production_values
from tools.verify_zip08 import REQUIRED_FILES, validate

ROOT = Path(__file__).resolve().parents[1]


class SettingsContractTests(SimpleTestCase):
    VALID_FERNET_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="

    def test_postgresql_url_builds_expected_database_contract(self):
        result = database_from_url("postgresql://service:password@db.private:5433/afribounty")
        self.assertEqual(result["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(result["NAME"], "afribounty")
        self.assertEqual(result["HOST"], "db.private")
        self.assertEqual(result["PORT"], "5433")

    def test_production_rejects_default_secret(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_production_values(
                debug=False,
                secret_key="development-only-not-for-production",
                allowed_hosts=["app.test"],
                database_engine="django.db.backends.postgresql",
                redis_url="redis://redis.test:6379/0",
            )

    def test_production_rejects_non_postgresql_and_non_redis(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_production_values(
                debug=False,
                secret_key="x" * 60,
                allowed_hosts=["app.test"],
                database_engine="django.db.backends.sqlite3",
                redis_url="redis://redis.test:6379/0",
            )
        with self.assertRaises(ImproperlyConfigured):
            validate_production_values(
                debug=False,
                secret_key="x" * 60,
                allowed_hosts=["app.test"],
                database_engine="django.db.backends.postgresql",
                redis_url="amqp://broker.test",
            )

    def test_production_rejects_unsafe_hosts_origins_and_local_evidence_storage(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_production_values(
                debug=False,
                secret_key="x" * 60,
                allowed_hosts=["*"],
                database_engine="django.db.backends.postgresql",
                redis_url="rediss://redis.private:6380/0",
                csrf_trusted_origins=["https://app.example.bf"],
            )
        with self.assertRaises(ImproperlyConfigured):
            validate_production_values(
                debug=False,
                secret_key="x" * 60,
                allowed_hosts=["app.example.bf"],
                database_engine="django.db.backends.postgresql",
                redis_url="rediss://redis.private:6380/0",
                csrf_trusted_origins=["http://app.example.bf"],
                evidence_storage_backend="local-private",
            )

    def test_production_rejects_invalid_evidence_encryption_key(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_production_values(
                debug=False,
                secret_key="x" * 60,
                allowed_hosts=["app.example.bf"],
                database_engine="django.db.backends.postgresql",
                redis_url="rediss://redis.private:6380/0",
                csrf_trusted_origins=["https://app.example.bf"],
                evidence_encryption_key="not-a-fernet-key",
            )

    def test_production_rejects_missing_or_weak_audit_integrity_key(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_production_values(
                debug=False,
                secret_key="x" * 60,
                allowed_hosts=["app.example.bf"],
                database_engine="django.db.backends.postgresql",
                redis_url="rediss://redis.private:6380/0",
                csrf_trusted_origins=["https://app.example.bf"],
                audit_integrity_key="short",
            )


class FileControlTests(unittest.TestCase):
    def test_required_files_exist(self):
        self.assertEqual([item for item in REQUIRED_FILES if not (ROOT / item).is_file()], [])

    def test_static_control_finds_no_issue(self):
        self.assertEqual(validate(ROOT), [])
