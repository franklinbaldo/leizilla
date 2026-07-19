import subprocess
import os

env = os.environ.copy()
env["IA_ACCESS_KEY"] = "fake_access"
env["IA_SECRET_KEY"] = "fake_secret"
env["IA_ACCESS"] = "fake_access"
env["IA_SECRET"] = "fake_secret"

try:
    res = subprocess.run(
        ["ia", "upload", "test_fake_item", "test_ia.py"],
        env=env,
        capture_output=True,
        text=True,
    )
    print("STDOUT:", res.stdout)
    print("STDERR:", res.stderr)
except Exception as e:
    print("ERROR:", e)
