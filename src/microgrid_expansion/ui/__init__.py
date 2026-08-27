"""The graphical interface: a local server and the window that shows it.

The engine is a library and stays one. Everything here talks to it through the same public
entry points a script would use, so the interface can be replaced without touching the
model, and the model can be driven without the interface.
"""
from .server import create_app

__all__ = ["create_app"]
