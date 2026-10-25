import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


class StartupTests(unittest.TestCase):
    def test_server_from_chinese_path_and_occupied_port(self):
        with tempfile.TemporaryDirectory(prefix='课表 测试 ') as folder:
            target = Path(folder)
            for item in ['server.py', 'period_times.json']:
                shutil.copy2(ROOT / item, target / item)
            shutil.copytree(ROOT / 'app', target / 'app', ignore=shutil.ignore_patterns('__pycache__'))
            shutil.copytree(ROOT / 'static', target / 'static')
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            args = [sys.executable, '-B', str(target / 'server.py'), '--port', str(port)]
            process = subprocess.Popen(args, cwd=folder, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                for attempt in range(50):
                    try:
                        with urlopen(f'http://127.0.0.1:{port}/healthz', timeout=0.2) as response:
                            self.assertEqual(response.status, 200)
                        break
                    except OSError:
                        if process.poll() is not None:
                            self.fail('Server exited before becoming ready')
                        time.sleep(0.1)
                else:
                    self.fail('Server did not become ready')
                with urlopen(f'http://127.0.0.1:{port}/', timeout=2) as response:
                    self.assertIn('课表'.encode(), response.read())
                with socket.socket() as occupied:
                    if os.name == 'nt':
                        occupied.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                    occupied.bind(('127.0.0.1', 0))
                    occupied.listen()
                    duplicate = subprocess.run(args[:-1] + [str(occupied.getsockname()[1])], cwd=folder, capture_output=True, timeout=10)
                    self.assertNotEqual(duplicate.returncode, 0)
            finally:
                process.terminate()
                process.wait(timeout=10)

    @unittest.skipUnless(os.name == 'nt', 'Windows launcher only')
    def test_launcher_missing_python_stops(self):
        with tempfile.TemporaryDirectory(prefix='课表 启动 ') as folder:
            target = Path(folder)
            shutil.copy2(ROOT / '启动课表转换工具.cmd', target / 'launch.cmd')
            # Empty PATH: no package installation or browser launch can occur.
            env = dict(os.environ, PATH=folder)
            result = subprocess.run([os.environ['COMSPEC'], '/d', '/c', 'launch.cmd'], cwd=folder, env=env, input=b'\n', capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
