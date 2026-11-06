import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import apply_db_updates
import post_sync_sql
import preprocess_sql


class ScriptNumberingTests(unittest.TestCase):
    def test_next_sequence_across_digit_boundaries(self):
        for module in (preprocess_sql, post_sync_sql):
            for letter in ("G", "S"):
                for latest in (9998, 9999, 10003, 99999, 100000):
                    with self.subTest(module=module.__name__, letter=letter, latest=latest):
                        with tempfile.TemporaryDirectory() as tmp:
                            folder = Path(tmp)
                            for seq in (9998, latest):
                                (folder / f"{seq}.0.{letter}GU.sql").touch()
                            # Outra família e arquivos fora do padrão não afetam a sequência.
                            other = "S" if letter == "G" else "G"
                            (folder / f"999999.0.{other}JO.sql").touch()
                            (folder / f"999999.0.{letter}JO.sql.bak").touch()
                            self.assertEqual(module.next_seq_for(folder, letter), latest + 1)

    def test_database_version_keeps_all_digits(self):
        for seq in (9999, 10000, 10003, 10004, 100000):
            for letter in ("G", "S"):
                for suffix in ("", ".sql"):
                    name = f"{seq}.0.{letter}JO{suffix}"
                    with self.subTest(name=name):
                        self.assertEqual(apply_db_updates.parse_seq_from_name(name), seq)

    def test_pending_scripts_are_sorted_numerically(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for seq in (10003, 9999, 10000, 9998):
                (folder / f"{seq}.0.GGU.sql").touch()
            (folder / "10004.0.GJO.sql.bak").touch()
            scripts = apply_db_updates.list_repo_scripts_for_dir(folder)
            self.assertEqual([item[0] for item in scripts], [9998, 9999, 10000, 10003])
            with patch.object(apply_db_updates, "get_last_applied_seq", return_value=(9999, "9999.0.GGU")):
                with patch.object(apply_db_updates, "apply_full_script_file") as apply:
                    apply_db_updates.apply_pending_repo_scripts(None, folder, "GESTOR/TEST")
            self.assertEqual(
                [call.args[1].name for call in apply.call_args_list],
                ["10000.0.GGU.sql", "10003.0.GGU.sql"],
            )

    def test_preprocessing_and_output_use_same_next_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "Gestor"
            folder.mkdir()
            for seq in (9999, 10000, 10001, 10002, 10003):
                (folder / f"{seq}.0.GGU.sql").touch()
            src = root / "gestor.sql"
            sql = "create function exemplo() returns text\nlanguage sql\nas $$ select 'ação'; $$;\n"
            src.write_text(sql.replace("language sql\n", "language sql\n    PARALLEL UNSAFE\n"),
                           encoding="utf-8")
            backup = root / "backup"
            with patch.multiple(preprocess_sql, THIS_DIR=root, GESTOR_DIR=folder,
                                BACKUP_DIR=backup, PENDING_FILE=backup / "pending.txt"):
                with patch.object(preprocess_sql, "get_local_ip", return_value="127.0.0.1"):
                    name = preprocess_sql.process_one(src, "Autor", "JO")
            with patch.object(post_sync_sql, "CREATED_FILES", []):
                output = post_sync_sql.write_file_bytes(
                    folder, "G", "JO", post_sync_sql._clean_cstyle_header_markers(src.read_bytes())
                )
            self.assertEqual(name, "10004.0.GJO.sql")
            self.assertEqual(output.name, name)
            content = output.read_text(encoding="cp1252")
            self.assertIn(sql.strip(), content)
            self.assertNotIn("PARALLEL UNSAFE", content)
            self.assertIn("fn_verifica_script('10004.0.GJO')", content)
            self.assertIn("fn_atualiza_script('10004.0.GJO')", content)
            self.assertEqual(apply_db_updates.extract_script_id_from_text(content), "10004.0.GJO")
            self.assertEqual((root / ".target_gestor.txt").read_text(), "10004.0.GJO")


if __name__ == "__main__":
    unittest.main()
