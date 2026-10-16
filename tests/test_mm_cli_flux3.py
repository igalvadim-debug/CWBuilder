"""Flux 3 parser and command forwarding, with all external work isolated."""

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import mm
import mm_common as C
import mm_images as I


class Flux3CliTests(unittest.TestCase):
    def test_parser_defaults_enable_upsampling_with_512_tokens(self):
        args = mm.build_parser().parse_args(["image", "flux3"])
        self.assertIsNone(args.upsampler)
        self.assertFalse(args.no_upsample)
        self.assertEqual(args.upsample_tokens, 512)
        self.assertIs(args.fn, mm.cmd_image)

    def test_parser_accepts_custom_upsampler_and_token_limit(self):
        args = mm.build_parser().parse_args([
            "image", "flux3", "--upsampler", "custom.gguf",
            "--no-upsample", "--upsample-tokens", "128",
        ])
        self.assertEqual(args.upsampler, "custom.gguf")
        self.assertTrue(args.no_upsample)
        self.assertEqual(args.upsample_tokens, 128)

    def test_parser_rejects_missing_or_noninteger_option_values(self):
        for options in (["--upsampler"], ["--upsample-tokens"],
                        ["--upsample-tokens", "many"], ["--upsample-tokens", "1.5"]):
            with self.subTest(options=options), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    mm.build_parser().parse_args(["image", "flux3"] + options)
                self.assertEqual(caught.exception.code, 2)

    def generate(self, directory, mode, options):
        """Exercise the real parser and Params construction without a server."""
        cfg = copy.deepcopy(C.DEFAULT_CONFIG)
        cfg["output_dir"] = directory
        cat = C.Catalog([], prefer_live=False)
        graph = {"1": {"class_type": "SaveImage", "inputs": {}}}
        with ExitStack() as stack:
            stack.enter_context(patch.object(C, "load_config", return_value=cfg))
            stack.enter_context(patch.object(C, "resolve_prompt", return_value=("a lighthouse", "test")))
            stack.enter_context(patch.object(C, "resolve_negative", return_value=""))
            server = stack.enter_context(patch.object(C, "server_alive", return_value=False))
            stack.enter_context(patch.object(C, "timestamp", return_value="test"))
            stack.enter_context(patch.object(mm, "open_catalog", return_value=cat))
            build = stack.enter_context(patch.object(I, "build", return_value=(graph, {})))
            stack.enter_context(patch.object(I, "report", return_value="test workflow"))
            run = stack.enter_context(patch.object(I, "run_on_server"))
            stack.enter_context(redirect_stdout(io.StringIO()))
            result = mm.main(["image", mode, "--prompt", "a lighthouse"] + options)
        self.assertEqual(result, 0)
        server.assert_called_once()
        run.assert_not_called()
        build.assert_called_once()
        self.assertIs(build.call_args.args[1], cat)
        path = Path(directory) / "mm_flux3_test.api.json"
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), graph)
        return build.call_args.args[0]

    def test_each_flux3_alias_dispatches_to_the_canonical_builder(self):
        for alias in ("flux3", "flux-3", "flux3klein", "flux3-base", "f3", "F3", "FLUX-3"):
            with self.subTest(alias=alias), tempfile.TemporaryDirectory() as directory:
                params = self.generate(directory, alias, [])
                self.assertEqual(params.mode, "flux3")
                self.assertEqual(params.prompt, "a lighthouse")
                self.assertIsNone(params.upsampler)
                self.assertFalse(params.no_upsample)
                self.assertEqual(params.upsample_max_tokens, 512)

    def test_custom_options_reach_params_without_renaming_or_losing_values(self):
        with tempfile.TemporaryDirectory() as directory:
            params = self.generate(directory, "flux3", [
                "--upsampler", "vendor/custom.gguf", "--upsample-tokens", "64",
                "--no-upsample", "--steps", "28", "--cfg", "4.0",
            ])
        self.assertEqual(params.upsampler, "vendor/custom.gguf")
        self.assertTrue(params.no_upsample)
        self.assertEqual(params.upsample_max_tokens, 64)
        self.assertEqual(params.steps, 28)
        self.assertEqual(params.cfg, 4.0)


if __name__ == "__main__":
    unittest.main()
