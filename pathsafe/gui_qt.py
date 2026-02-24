"""Backward-compatibility shim -- the real code now lives in pathsafe.gui."""

from pathsafe.gui import main  # noqa: F401

if __name__ == '__main__':
    main()
