import sys

_service_to_command = {
    "pet.onion": [sys.executable, join(split(__file__)[0], 'ns_petname.py')],
    "demo.onion": [sys.executable, join(split(__file__)[0], 'ns_always_txtorcon.py')],
}
