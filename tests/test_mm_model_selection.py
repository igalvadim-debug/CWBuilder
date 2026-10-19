"""Offline regressions for LoRA suggestions and Gradio mode changes."""

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import mm_images as I
import mm_ui as U


def lora_entry(rel):
    """Build a synthetic model registry entry from a relative LoRA path."""
    return {"full": f"/models/{rel}", "rel": rel,
            "family": rel.split("/")[-2], "trigger": ""}


class LoraSelectionTests(unittest.TestCase):
    def test_safetensors_extension_does_not_match_unrelated_loras(self):
        """Exclude unrelated LoRAs even when they share the model file extension."""
        wanted = lora_entry("loras/moss/rapid_moss.safetensors")
        unrelated = lora_entry("loras/styles/portrait_style.safetensors")
        for unet in (None, "moss_image_sft.safetensors", "MOSS_IMAGE_SFT.SAFETENSORS"):
            with self.subTest(unet=unet):
                picks = I.loras_for_mode("moss_t2i", unet, [unrelated, wanted])
                self.assertEqual([path for _, path in picks], [wanted["full"]])

    def test_token_filtering_and_four_token_limit_are_preserved(self):
        """Ignore filler words and short tokens, keeping only four model tokens."""
        tokens = ["alpha", "bravo", "charlie", "delta", "echo", "image", "sft", "lora", "ab"]
        entries = [lora_entry(f"loras/styles/{token}.safetensors") for token in tokens]
        picks = I.loras_for_mode(
            "custom", "alpha_image_sft_lora_ab_bravo_charlie_delta_echo.safetensors", entries)
        self.assertEqual({path for _, path in picks}, {e["full"] for e in entries[:4]})

    def test_foreign_family_directories_are_excluded_before_scoring(self):
        """Reject foreign family folders while allowing matching style filenames."""
        foreign = [lora_entry(f"loras/{family}/LTX2.3_DMD_hybrid_v2.safetensors")
                   for family in ("ltx", "ltx2", "LTX2.3", "wan")]
        wanted = lora_entry("loras/moss/rapid_moss.safetensors")
        generic = lora_entry("loras/styles/pixel_art_style_z_image_turbo_moss.safetensors")
        picks = I.loras_for_mode("moss_t2i", "moss_image_sft.safetensors",
                                 foreign + [wanted, generic])
        self.assertEqual({path for _, path in picks}, {wanted["full"], generic["full"]})


class ModeSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Build an offline UI and capture its mode change callback."""
        with patch.dict(os.environ, {"GRADIO_ANALYTICS_ENABLED": "False"}), \
                patch.object(U, "load_state", return_value=dict(U.DEFAULTS, mode="qwen21")), \
                patch.object(U, "server_status_md", return_value="offline"):
            cls.app = U.build_ui()
        cls.callback = next(fn for fn in cls.app.fns.values() if fn.fn.__name__ == "apply_mode")

    @classmethod
    def tearDownClass(cls):
        """Close the shared Gradio application after the mode selection tests."""
        cls.app.close()

    def setUp(self):
        """Provide model choices and mock catalog access, state writes, and LoRAs."""
        self.names = {
            "unet": ["moss_image_sft_int8_convrot.safetensors"],
            "text_encoders": ["qwen_2.5_vl_7b_fp8_scaled.safetensors",
                              "qwen3.5_9b_int8_convrot.safetensors",
                              "alternate_encoder.safetensors"],
            "vae": ["other_vae.safetensors", "flux2_vae.safetensors", "alternate_vae.safetensors"],
        }
        self.enterContext(patch.object(U, "catalog_for",
                                      return_value=SimpleNamespace(names=self.names.__getitem__)))
        self.enterContext(patch.object(U, "save_state"))
        self.enterContext(patch.object(I, "loras_for_mode", return_value=[]))

    def selections(self, result):
        """Validate callback output count and extract encoder and VAE selections."""
        updates = {component.label: update
                   for component, update in zip(self.callback.outputs, result)
                   if getattr(component, "label", None)}
        self.assertEqual(len(result), len(self.callback.outputs))
        return updates["Text-Encoder"]["value"], updates["VAE"]["value"]

    def test_mode_change_uses_new_defaults_despite_exact_previous_selections(self):
        """Replace the previous mode's encoder and VAE with the new defaults."""
        result = self.callback.fn("moss_t2i", None, self.names["text_encoders"][0],
                                  self.names["vae"][0], "qwen21")
        self.assertEqual(self.selections(result), (I.default_clip_for("moss_t2i"),
                                                   I.default_vae_for("moss_t2i")))
        self.assertEqual(result[-1], "moss_t2i")

    def test_same_mode_preserves_explicit_selections(self):
        """Keep explicit encoder and VAE selections when the mode is unchanged."""
        result = self.callback.fn("moss_t2i", None, "alternate_encoder.safetensors",
                                  "alternate_vae.safetensors", "moss_t2i")
        self.assertEqual(self.selections(result), ("alternate_encoder.safetensors",
                                                   "alternate_vae.safetensors"))

    def test_previous_mode_is_wired_as_session_state(self):
        """Track mode changes per session without overwriting another session's state."""
        state = self.callback.inputs[-1]
        self.assertIsInstance(state, U.gr.State)
        self.assertIs(self.callback.outputs[-1], state)
        self.assertEqual(state.value, "qwen21")
        result = self.callback.fn("moss_t2i", None, None, None, "qwen21")
        # The next callback consumes the state returned by the previous change.
        same_mode = self.callback.fn("moss_t2i", None, "alternate_encoder.safetensors",
                                     "alternate_vae.safetensors", result[-1])
        self.assertEqual(self.selections(same_mode), ("alternate_encoder.safetensors",
                                                      "alternate_vae.safetensors"))
        # Another session still changes from its own initial mode.
        other_session = self.callback.fn("moss_t2i", None, "alternate_encoder.safetensors",
                                         "alternate_vae.safetensors", state.value)
        self.assertEqual(self.selections(other_session), (I.default_clip_for("moss_t2i"),
                                                          I.default_vae_for("moss_t2i")))


if __name__ == "__main__":
    unittest.main()
