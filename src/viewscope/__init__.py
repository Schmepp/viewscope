import os
import platform

# Required for running headless on Linux
if platform.system() == "Linux":
    os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
