import os
from os.path import join, split
import sys

service_to_command = {
    "pet.onion": [
        sys.executable,
        join(split(__file__)[0], 'ns_petname.py'),
    ],
    "demo.onion": [
        sys.executable,
        join(split(__file__)[0], 'ns_always_txtorcon.py'),
    ],
}


def bootstrap_callback():
    pass


def exit_callback():
    # Can't use sys.exit() here because it's called from a child thread.
    os._exit(0)
