import ast
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
import uuid
import zipfile


class ExtensionPackageTests(unittest.TestCase):
    def test_download_package_contains_the_extractor_dependency(self):
        source = ast.parse((Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8"))
        function = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == "build_chrome_extension_zip")
        function.decorator_list = []
        constants = [node for node in source.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id in {"CHROME_EXTENSION_FILES", "CHROME_EXTENSION_RAW_BASE"} for target in node.targets)]
        namespace = {"io": io, "zipfile": zipfile, "uuid": uuid}
        def get(url, **kwargs):
            return SimpleNamespace(content=url.encode("utf-8"), raise_for_status=lambda: None)
        namespace["requests"] = SimpleNamespace(get=get)
        exec(compile(ast.Module(body=constants + [function], type_ignores=[]), "extension_package", "exec"), namespace)
        with zipfile.ZipFile(io.BytesIO(namespace["build_chrome_extension_zip"]())) as archive:
            self.assertIn("bunken-web-importer/extractor.js", archive.namelist())
            self.assertIn("bunken-web-importer/popup.js", archive.namelist())


if __name__ == "__main__":
    unittest.main()
