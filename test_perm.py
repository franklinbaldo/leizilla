import tempfile
import os

with tempfile.NamedTemporaryFile() as f:
    st = os.stat(f.name)
    print(oct(st.st_mode))
