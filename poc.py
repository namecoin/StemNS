# note: this needs stem to run. you can
# install it in a fresh virtualenv on Debian (after "apt-get install
# python-virtualenv") like so:
#
# virtualenv venv
# source venv/bin/activate
# pip install --upgrade pip
# pip install stem
#
# Then you can run this:
# python3 poc.py
#
# ...and then visit any .onion address, and it'll get re-directed to
# txtorcon documentation.

import subprocess
import sys
import time
import itertools
from os.path import join, split

from threading import Thread

import stem
from stem.control import EventType, Controller

_service_to_command = {
    "pet.onion": [sys.executable, join(split(__file__)[0], 'ns_petname.py')],
    "demo.onion": [sys.executable, join(split(__file__)[0], 'ns_always_txtorcon.py')],
}


class NameLookupError(Exception):
    def __init__(self, status):
        self.status = status
        msg = {
            0: 'The name resolution was successful',
            1: 'Name resolution generic failure',
            2: 'Name tld not recognized',
            3: 'Name not registered',
            4: 'Name resolution timeout exceeded',
        }
        super(NameLookupError, self).__init__(msg[status])


class _TorNameServiceProtocol(object):
    delimiter = '\n'

    def __init__(self, tor, process):
        self._queries = dict()
        self._id_gen = itertools.count(1)
        self._tor = tor
        self._process = process

    def watch_stdout(self):
        for line in self._process.stdout:
            self.lineReceived(line)

    def lineReceived(self, line):
        args = line.split()
        if args[0] == 'RESOLVED':
            # Answer might contain whitespace if it's an error message; if so,
            # len(answer) will be greater than 1.
            query_id, status, answer = args[1], args[2], args[3:]
            query_id = int(query_id)
            status = int(status)

            try:
                stream_id = self._queries[query_id]
                del self._queries[query_id]
            except KeyError:
                print("No query {}: {}".format(query_id, self._queries.keys()))

            if status == 0:
                # Answer should be a domain name or IP address, neither of
                # which will contain whitespace, so only take the first
                # whitespace-separated token.
                answer = answer[0]
                self._tor.msg('REDIRECTSTREAM ' + stream_id + ' ' + answer)
                try:
                    self._tor.attach_stream(stream_id, 0)
                except stem.UnsatisfiableRequest:
                    pass
            else:
                self._tor.close_stream(stream_id, stem.RelayEndReason.RESOLVEFAILED)

    def request_lookup(self, stream_id, name):
        query_id = next(self._id_gen)
        self._queries[query_id] = stream_id
        self._process.stdin.write('RESOLVE {} {}\n'.format(query_id, name))


def spawn_name_service(tor, name):
    try:
        args = _service_to_command[name]
    except KeyError:
        raise Exception(
            "No such service '{}'".format(name)
        )
    process = subprocess.Popen(args, bufsize=1, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               universal_newlines=True, env={
            'TOR_NS_STATE_LOCATION': '/var/lib/tor/ns_state',
            'TOR_NS_PROTO_VERSION': '1',
            'TOR_NS_PLUGIN_OPTIONS': '',
        })

    proto = _TorNameServiceProtocol(tor, process)

    t = Thread(target=proto.watch_stdout)
    t.start()

    return proto

class _Attacher(object):
    def __init__(self, tor):
        self._tor = tor
        self._services = {}

    def maybe_launch_service(self, name):
        suffix = None
        srv = None

        for candidate_suffix in _service_to_command:
            if name.endswith("." + candidate_suffix):
                suffix = candidate_suffix
                srv = self._services.get(suffix, None)
                break

        if srv is None:
            srv = spawn_name_service(self._tor, suffix)
            self._services[suffix] = srv
        return srv

    def attach_stream(self, stream):
        print("attach_stream {}".format(stream))

        # Not all stream events need to be attached.
        # TODO: check with Tor Project whether NEW and NEWRESOLVE are the correct list.
        if stream.status not in [stem.StreamStatus.NEW, stem.StreamStatus.NEWRESOLVE]:
            return

        try:
            srv = self.maybe_launch_service(stream.target_address)
        except Exception:
            print("Unable to launch service for '{}'".format(stream.target_address))
            try:
                self._tor.attach_stream(stream.id, 0)
            except stem.UnsatisfiableRequest:
                pass
            return

        srv.request_lookup(stream.id, stream.target_address)


def main():
    while True:
        try:
            # open main controller
            controller = Controller.from_port(port = 9051)
            break
        except stem.SocketError:
            time.sleep(0.005)

    controller.authenticate()

    print("[notice] Successfully connected to the Tor control port.")

    if controller.get_conf('__LeaveStreamsUnattached') != '1':
        sys.exit('[err] torrc is unsafe for name lookups.  Try adding the line "__LeaveStreamsUnattached 1" to torrc-defaults')

    attacher = _Attacher(controller)

    controller.add_event_listener(attacher.attach_stream, EventType.STREAM)

    print('[debug] Now monitoring stream connections.')

    try:
        # Sleeping for 365 days, as upstream OnioNS does, appears to be incompatible with Windows.
        # Therefore, we instead sleep for 1 day inside an infinite loop.
        while True:
            time.sleep(60 * 60 * 24 * 1) #basically, wait indefinitely
    except KeyboardInterrupt:
        print('')

if __name__ == '__main__':
  main()
