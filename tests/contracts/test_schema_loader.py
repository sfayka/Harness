from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules.contracts.schema_loader import load_task_envelope_schema, resolve_contract_resource


class ContractSchemaLoaderTests(unittest.TestCase):
    def tearDown(self) -> None:
        load_task_envelope_schema.cache_clear()

    def test_resolve_contract_resource_prefers_bundled_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundled_root = Path(temp_dir)
            bundled_schema = bundled_root / "schemas" / "task_envelope.schema.json"
            bundled_schema.parent.mkdir(parents=True, exist_ok=True)
            bundled_schema.write_text('{"$schema":"bundle","$defs":{}}', encoding="utf-8")

            with patch("modules.contracts.schema_loader.sys._MEIPASS", str(bundled_root), create=True):
                resolved = resolve_contract_resource("schemas/task_envelope.schema.json")

        self.assertEqual(resolved, bundled_schema)

    def test_load_task_envelope_schema_reads_from_bundled_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundled_root = Path(temp_dir)
            bundled_schema = bundled_root / "schemas" / "task_envelope.schema.json"
            bundled_schema.parent.mkdir(parents=True, exist_ok=True)
            bundled_schema.write_text(
                '{"$schema":"https://example.invalid/schema","$defs":{"artifactRecord":{"type":"object"}}}',
                encoding="utf-8",
            )

            load_task_envelope_schema.cache_clear()
            with patch("modules.contracts.schema_loader.sys._MEIPASS", str(bundled_root), create=True):
                payload = load_task_envelope_schema()

        self.assertEqual(payload["$schema"], "https://example.invalid/schema")
        self.assertIn("artifactRecord", payload["$defs"])
