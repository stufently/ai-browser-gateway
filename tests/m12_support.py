"""Shared filesystem and CLI assertions for M12 author tests."""
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import importlib.machinery
import importlib.util
import io
from pathlib import Path
import stat
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ERROR = '{"error":"invalid_configuration"}\n'


def script(name):
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / 'scripts' / name))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@contextmanager
def captured():
    output, error = io.StringIO(), io.StringIO()
    with redirect_stdout(output), redirect_stderr(error):
        yield output, error


def mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def identity(path):
    info = path.stat()
    return info.st_ino, info.st_mode, info.st_mtime_ns


class FileCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='m12-contract-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)

    def invoke(self, module, argv, expected=0, success=''):
        with captured() as (output, error):
            result = module.main(argv)
        self.assertEqual((result, output.getvalue(), error.getvalue()),
                         (expected, success if not expected else '', ERROR if expected else ''))
