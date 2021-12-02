import os
from os.path import join, split
import sys

_service_to_command = {
    "pet.onion": [
        sys.executable,
        join(split(__file__)[0], 'ns_petname.py'),
    ],
    "demo.onion": [
        sys.executable,
        join(split(__file__)[0], 'ns_always_txtorcon.py'),
    ],
}


def _bootstrap_callback():
    pass


def _exit_callback():
    # Can't use sys.exit() here because it's called from a child thread.
    os._exit(0)
