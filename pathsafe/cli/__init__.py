"""PathSafe CLI -- entry point and subcommand registration.

Each subcommand lives in its own module within this package.
Run via ``pathsafe <subcommand>`` or ``python -m pathsafe.cli <subcommand>``.
"""

from __future__ import annotations

import click

import pathsafe


@click.group(
    epilog="Note: PathSafe is not a medical device. De-identification should be verified per institutional requirements."
)
@click.version_option(version=pathsafe.__version__, prog_name="pathsafe")
def main() -> None:
    """PathSafe -- WSI de-identifier.

    Detect and remove Protected Health Information (PHI) from
    whole-slide image files (NDPI, SVS, TIFF).
    """
    pass


# Register subcommands. Imports are local so that importing pathsafe.cli
# does not pay the cost of every subcommand's optional dependencies.
from pathsafe.cli._gui_cmd import gui  # noqa: E402
from pathsafe.cli.convert import convert  # noqa: E402
from pathsafe.cli.deidentify import deidentify  # noqa: E402
from pathsafe.cli.info import info  # noqa: E402
from pathsafe.cli.pipeline import (  # noqa: E402
    classify,
    download_models,
    pipeline,
    transfer,
)
from pathsafe.cli.scan import scan  # noqa: E402
from pathsafe.cli.verify import verify  # noqa: E402


for _cmd in (
    scan,
    deidentify,
    verify,
    info,
    convert,
    gui,
    classify,
    transfer,
    pipeline,
    download_models,
):
    main.add_command(_cmd)


if __name__ == "__main__":
    main()
