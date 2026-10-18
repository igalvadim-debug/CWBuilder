"""Offline documentation contracts for the README and MOSS workflow notes.

PR #15 changes documentation only. These artifact tests read the shipped files
without requiring ComfyUI, model weights, network access, or a Windows host.
"""

import json
import re
import unittest
from pathlib import Path, PureWindowsPath


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "output" / "simpleWorkflowForMOSS_t2iBBOX (1).json"
# The model guidance and plain text-to-image guidance edited in PR #15.
NOTE_IDS = (60, 65)


class ReadmeOfflineDocsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        cls.local_notice = "\n".join(
            line for line in readme.splitlines() if line.startswith(">")
        )

    def test_local_notice_explains_offline_use_without_account_or_credits(self):
        self.assertIn("аккаунт и кредиты не нужны", self.local_notice)
        self.assertIn("без интернета", self.local_notice)
        self.assertIn("ComfyUI", self.local_notice)
        self.assertIn("safetensors", self.local_notice)

    def test_local_notice_identifies_the_unrelated_cloud_login_error(self):
        for label in ("OpenCreator-Konto", "Anmeldedienst ist nicht verfügbar", "Credits"):
            with self.subTest(label=label):
                self.assertIn(label, self.local_notice)
        self.assertIn("сторонний облачный сервис", self.local_notice)
        self.assertIn("НЕ относится к этому проекту", self.local_notice)


class MossWorkflowOfflineDocsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = json.loads(WORKFLOW.read_text(encoding="utf-8"))
        cls.nodes = {node["id"]: node for node in cls.workflow["nodes"]}

    def note_texts(self):
        """Check both ComfyUI widget serialization formats independently."""
        for node_id in NOTE_IDS:
            node = self.nodes[node_id]
            yield node_id, "positional", node["widgets_values"][0]
            yield node_id, "named", node["widgets_values_named"]["text"]

    def test_both_notes_keep_positional_and_named_text_in_sync(self):
        # A stale named value can restore the old note on workflow import.
        for node_id in NOTE_IDS:
            with self.subTest(node_id=node_id):
                node = self.nodes[node_id]
                self.assertEqual(len(node["widgets_values"]), 1)
                self.assertIsInstance(node["widgets_values"][0], str)
                self.assertEqual(
                    node["widgets_values"][0], node["widgets_values_named"]["text"]
                )

    def test_each_note_explains_offline_use_without_account_or_credits(self):
        for node_id, representation, text in self.note_texts():
            with self.subTest(node_id=node_id, representation=representation):
                for claim in ("local", "offline", "no account", "no credits"):
                    self.assertIn(claim, text.casefold())

    def test_each_note_identifies_the_unrelated_cloud_service(self):
        for node_id, representation, text in self.note_texts():
            with self.subTest(node_id=node_id, representation=representation):
                for label in ("OpenCreator-Konto", "Credits", "third-party cloud service"):
                    self.assertIn(label, text)
                self.assertRegex(
                    text.casefold(), r"nothing to do with this workflow|unrelated to this workflow"
                )

    def test_model_paths_survive_json_escaping_as_windows_paths(self):
        expected_root = PureWindowsPath(r"D:\ComfyUiCuda\models")
        expected_lora = PureWindowsPath(r"MOSS\MOSS-Image-SFT-8-steps-dmd.safetensors")
        for node_id, representation, text in self.note_texts():
            with self.subTest(node_id=node_id, representation=representation):
                # Interpret inline paths semantically, allowing Markdown to use
                # either single or doubled backslashes, including at the end.
                paths = [PureWindowsPath(value) for value in re.findall(
                    r"(?<!`)`([^`]+)`(?!`)", text
                )]
                self.assertIn(expected_root, paths)
                self.assertIn(expected_lora, paths)

    def test_offline_guidance_stays_in_disconnected_documentation_nodes(self):
        for node_id in NOTE_IDS:
            with self.subTest(node_id=node_id):
                node = self.nodes[node_id]
                self.assertEqual(node["type"], "MarkdownNote")
                self.assertEqual(node["inputs"], [])
                self.assertEqual(node["outputs"], [])
                for link in self.workflow["links"]:
                    self.assertNotIn(node_id, (link[1], link[3]))


if __name__ == "__main__":
    unittest.main()
