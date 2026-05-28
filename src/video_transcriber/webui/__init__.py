"""Desktop GUI for video-transcriber, powered by PyWebView.

Public entry point: :func:`launch` (called by ``main.py --gui``).

The GUI runs the same pipeline as the CLI; it just adds a user-friendly
control surface. All settings round-trip through the existing
``config.yaml`` so CLI and GUI stay in sync.
"""

from .app import launch  # noqa: F401
