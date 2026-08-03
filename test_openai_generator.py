import asyncio
import base64
import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.services.openai_generator import OpenAIImageGenerator, PNG_HEADER


class OpenAIGeneratorTest(unittest.TestCase):
    def test_fake_png_and_parameters(self):
        calls = {}

        class FakeImages:
            def generate(self, **kwargs):
                calls.update(kwargs)
                encoded = base64.b64encode(PNG_HEADER + b"fake-png").decode("ascii")
                return SimpleNamespace(data=[SimpleNamespace(b64_json=encoded)])

        class FakeOpenAI:
            def __init__(self, **kwargs):
                calls["client"] = kwargs
                self.images = FakeImages()

        original_cwd = os.getcwd()
        test_root = tempfile.mkdtemp(dir=original_cwd)
        try:
            os.chdir(test_root)
            with patch("backend.services.openai_generator.OpenAI", FakeOpenAI), \
                 patch("backend.services.openai_generator.settings.OPENAI_IMAGE_MODEL", "gpt-image-2"), \
                 patch("backend.services.openai_generator.settings.OPENAI_IMAGE_QUALITY", "low"), \
                 patch("backend.services.openai_generator.settings.OPENAI_IMAGE_SIZE", "1024x1024"):
                filename, _, error = asyncio.run(
                    OpenAIImageGenerator().generate_image("A teacher", None)
                )
            self.assertIsNone(error)
            self.assertEqual(calls["model"], "gpt-image-2")
            self.assertEqual(calls["quality"], "low")
            self.assertEqual(calls["size"], "1024x1024")
            self.assertTrue(filename.startswith("openai_") and filename.endswith(".png"))
            path = os.path.join("frontend", "assets", "generations", filename)
            self.assertTrue(os.path.isfile(path))
            with open(path, "rb") as image_file:
                self.assertTrue(image_file.read().startswith(PNG_HEADER))
        finally:
            os.chdir(original_cwd)
            shutil.rmtree(test_root)


if __name__ == "__main__":
    unittest.main()
