"""Regression tests for native dependency resolution and package verification."""

import importlib.util
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SOURCE = Path(os.environ.get("SLICER_MACOS_PACKAGING_SOURCE_DIR", Path(__file__).resolve().parents[2]))


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, SOURCE / "Utilities/Scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


close = load_script("SlicerBundleCloseDeps")
signer = load_script("SlicerSignBundleMacOS")


class PackageFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.app = self.root / "Example.app"
        self.contents = self.app / "Contents"
        self.entry = self.contents / "MacOS/Example"
        self.entry.parent.mkdir(parents=True)
        (self.contents / "Info.plist").write_bytes(plistlib.dumps({
            "CFBundleExecutable": "Example",
            "CFBundleIdentifier": "org.slicer.packagingtest",
            "CFBundlePackageType": "APPL",
            "CFBundleVersion": "1",
        }))

    @staticmethod
    def binary(path, loads=(), rpaths=(), identity=None):
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"loads": list(loads), "rpaths": list(rpaths), "identity": identity}
        path.write_bytes(b"\xcf\xfa\xed\xfe" + json.dumps(data).encode())
        return str(path)


class DependencyResolutionTest(PackageFixture):
    def test_bare_internal_reference_is_relocated(self):
        library = self.contents / "lib/Slicer-5.13/libDependency.dylib"
        identity = "@rpath/lib/Slicer-5.13/libDependency.dylib"
        consumer = self.binary(self.entry, loads=["libDependency.dylib"])
        target = self.binary(library, identity=identity)
        metadata = {consumer: (["libDependency.dylib"], [], None), target: ([], [], identity)}
        with mock.patch.object(close, "scan", side_effect=metadata.__getitem__), mock.patch.object(close.subprocess, "run") as tool:
            close.close_deps(str(self.app), [str(library.parent)], "lib/Slicer-5.13")
        changes = [call.args[0] for call in tool.call_args_list]
        self.assertIn(["install_name_tool", "-change", "libDependency.dylib", identity, consumer], changes)

    def test_external_search_directory_reuses_bundled_library(self):
        library = self.contents / "lib/Python/site-packages/torch/lib/libtorch_cpu.dylib"
        source = self.root / "build/torch/lib/libtorch_cpu.dylib"
        consumer = self.contents / "lib/Python/site-packages/torchvision/_C.so"
        identity = "@rpath/" + library.relative_to(self.contents).as_posix()
        self.binary(source)
        target = self.binary(library, identity=identity)
        caller = self.binary(consumer, loads=["@rpath/libtorch_cpu.dylib"])
        metadata = {target: ([], [], identity), caller: (["@rpath/libtorch_cpu.dylib"], [], None)}
        with mock.patch.object(close, "scan", side_effect=metadata.__getitem__), mock.patch.object(close.subprocess, "run") as tool:
            close.close_deps(str(self.app), [str(source.parent)], "lib/Slicer-5.13")
        self.assertIn(["install_name_tool", "-change", "@rpath/libtorch_cpu.dylib", identity, caller],
                      [call.args[0] for call in tool.call_args_list])
        self.assertFalse((self.contents / "lib/Slicer-5.13/libtorch_cpu.dylib").exists())


@unittest.skipUnless(shutil.which("cmake"), "CMake is required")
class BundleVerificationTest(PackageFixture):
    def setUp(self):
        super().setUp()
        self.otool = self.root / "otool"
        self.otool.write_text(
            f"#!{sys.executable}\n"
            "import json, pathlib, sys\n"
            "data = json.loads(pathlib.Path(sys.argv[-1]).read_bytes()[4:])\n"
            "for path in data['rpaths']:\n"
            " print('cmd LC_RPATH\\npath ' + path + ' (offset 12)')\n"
            "for path in data['loads']:\n"
            " print('cmd LC_LOAD_DYLIB\\nname ' + path + ' (offset 24)')\n",
        )
        self.otool.chmod(0o755)
        self.binary(self.entry, rpaths=["@loader_path/.."])

    def verify(self):
        return subprocess.run([
            "cmake", "-DSlicer_INSTALL_DIR=" + str(self.root),
            "-DOTOOL_EXECUTABLE=" + str(self.otool),
            "-P", str(SOURCE / "CMake/SlicerCPackBundleVerify.cmake"),
        ], capture_output=True, text=True, check=False)

    def framework(self, name, loads=()):
        framework = self.contents / "Frameworks" / (name + ".framework")
        binary = framework / "Versions/A" / name
        self.binary(binary, loads=loads, rpaths=["@loader_path/../../../"])
        (framework / "Versions/Current").symlink_to("A")
        (framework / name).symlink_to("Versions/Current/" + name)
        return binary

    def test_framework_alias_uses_real_binary_directory(self):
        self.framework("QtDependency")
        self.framework("QtConsumer", ["@rpath/QtDependency.framework/Versions/A/QtDependency"])
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_missing_framework_dependency_fails(self):
        self.framework("QtConsumer", ["@rpath/QtMissing.framework/Versions/A/QtMissing"])
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("QtMissing", result.stdout + result.stderr)

    def test_native_symlink_outside_bundle_fails(self):
        external = self.root / "external.dylib"
        self.binary(external)
        (self.contents / "lib").mkdir()
        (self.contents / "lib/external.dylib").symlink_to(external)
        result = self.verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("outside the bundle", result.stdout + result.stderr)


class BundleSigningTest(PackageFixture):
    def setUp(self):
        super().setUp()
        self.binary(self.entry)
        self.nested = self.contents / "lib/libDependency.dylib"
        self.binary(self.nested)

    def test_entry_is_sealed_with_app_after_nested_code(self):
        calls = []

        def codesign(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, "", "")

        with mock.patch.object(signer.subprocess, "run", side_effect=codesign):
            self.assertTrue(signer.sign_bundle(str(self.app), "-"))
        signed = [call[-1] for call in calls if "--sign" in call]
        self.assertEqual(signed, [str(self.nested), str(self.app)])

    def test_failed_final_verification_fails_signing(self):
        def codesign(command, **kwargs):
            failed = "--verify" in command
            return subprocess.CompletedProcess(command, int(failed), "", "invalid signature" if failed else "")

        with mock.patch.object(signer.subprocess, "run", side_effect=codesign):
            self.assertFalse(signer.sign_bundle(str(self.app), "-"))


@unittest.skipUnless(sys.platform == "darwin", "Native Mach-O tests require macOS")
class NativeBundleTest(PackageFixture):
    def compile(self, path, source, arguments=()):
        path.parent.mkdir(parents=True, exist_ok=True)
        source_file = self.root / (path.name + ".c")
        source_file.write_text(source)
        subprocess.run(["clang", str(source_file), "-Wl,-headerpad_max_install_names",
                        *arguments, "-o", str(path)], check=True, capture_output=True)

    def test_repaired_bare_reference_loads_and_signs(self):
        library = self.contents / "lib/Slicer-5.13/libDependency.dylib"
        self.compile(library, "int dependency(void) { return 0; }",
                     ["-dynamiclib", "-Wl,-install_name,libDependency.dylib"])
        self.compile(self.entry, "int dependency(void); int main(void) { return dependency(); }",
                     [str(library), "-Wl,-rpath,@loader_path/../"])
        self.assertTrue(close.close_deps(str(self.app), [str(library.parent)], "lib/Slicer-5.13"))
        self.assertTrue(signer.sign_bundle(str(self.app), "-"))
        subprocess.run([str(self.entry)], check=True, capture_output=True)

    def test_optional_library_loads_without_preloading(self):
        external = self.root / "build/torch/lib/libtorch_cpu.dylib"
        target = self.contents / "lib/Python/site-packages/torch/lib/libtorch_cpu.dylib"
        consumer = self.contents / "lib/Python/site-packages/torchvision/_C.so"
        self.compile(external, "int dependency(void) { return 42; }",
                     ["-dynamiclib", "-Wl,-install_name,@rpath/libtorch_cpu.dylib"])
        target.parent.mkdir(parents=True)
        shutil.copy2(external, target)
        self.compile(consumer, "int dependency(void); int value(void) { return dependency(); }",
                     ["-dynamiclib", str(external)])
        self.compile(self.entry,
                     '#include <dlfcn.h>\nint main(int argc, char **argv) {\n'
                     '  void *m = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);\n'
                     '  if (!m) return 1;\n'
                     '  int (*value)(void) = (int (*)(void))dlsym(m, "value");\n'
                     '  return !value || value() != 42;\n}\n',
                     ["-Wl,-rpath,@loader_path/../"])
        before = subprocess.run([str(self.entry), str(consumer)], capture_output=True, check=False)
        self.assertNotEqual(before.returncode, 0)
        self.assertTrue(close.close_deps(str(self.app), [str(external.parent)], "lib/Slicer-5.13"))
        self.assertTrue(signer.sign_bundle(str(self.app), "-"))
        subprocess.run([str(self.entry), str(consumer)], check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()
