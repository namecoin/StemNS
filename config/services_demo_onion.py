from os.path import join, split
import sys

service_to_command = {
    "demo.onion": [
        sys.executable,
        join(split(__file__)[0], 'ns_always_txtorcon.py'),
    ],
}
