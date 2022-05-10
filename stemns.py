#!/usr/bin/env python3

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
# python3 stemns.py
#
# ...and then visit any .onion address, and it'll get re-directed to
# txtorcon documentation.

import os
import warnings
import importlib.util
from functools import reduce
from pathlib import Path
import secrets
import subprocess
import sys
import time
import itertools
from copy import deepcopy

from threading import Thread

import stem
from stem.control import EventType, Controller
from stem.response import ControlLine
from stem.version import Version

tor_control_port = None
service_to_command = None
bootstrap_callback = None
exit_callback = None


def load_config_from_dir(searchdir, attrs):
    root = Path(__file__).parent / searchdir
    filenames = sorted(os.listdir(root))
    modules = [import_without_bind(root / fn) for fn in filenames]
    config = {}
    for attr, mt in attrs.items():
        # Special logic to merge config files together
        possible = [m.get(attr) for m in modules]
        stack = [c for c in possible if c is not None]
        if (mt == 'shadow'):
            if len(stack) == 0:
                raise ValueError(f"config option {attr} in {root} is not set")
            config[attr] = stack[-1]
            if len(stack) > 1:
                offending = {k: v for k, v in zip(filenames, possible)
                             if v is not None}.keys()
                warnings.warn(f"config option {attr} set multiple times "
                              f"({', '.join(offending)}), the last file in "
                              f"the list will be used")
        elif (mt == 'call'):
            config[attr] = lambda cbs=stack: [f() for f in cbs]
            # Call all callbacks sequentially
        elif (mt == 'merge'):
            overlaps = reduce(lambda a, b:
                              [a[0] | set(b.keys()),
                               (a[0] & set(b.keys())) | a[1]],
                              stack, [set(), set()])[1]
            offending = {k: v for k, v in zip(filenames, possible)
                         if (v is not None and set(v.keys()) & overlaps)
                         }.keys()
            # Get all options that would shadow one another
            n = len(overlaps)
            if n > 0:
                warnings.warn(f"following item{'' if n==1 else 's'} of {attr} "
                              f"set multiple times: {', '.join(overlaps)} "
                              f"(in {', '.join(offending)})")

            config[attr] = reduce(lambda a, b: {**a, **b}, stack, {})
    return config


def import_without_bind(filename):
    # Import a module, get a dict
    spec = importlib.util.spec_from_file_location('config', filename)
    if spec is None:
        return {}  # Not a module
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.__dict__


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


class NoService(Exception):
    pass


class _TorNameServiceProtocol(object):
    delimiter = '\n'

    def __init__(self, tor, process):
        self._queries = dict()
        self._names = dict()
        self._stream_isolation_ids = dict()
        self._timeout = dict()
        self._id_gen = itertools.count(1)
        self._tor = tor
        self._process = process

    def watch_stdout(self):
        for line in self._process.stdout:
            self.lineReceived(line)

    def watch_stderr(self):
        for line in self._process.stderr:
            print(line, file=sys.stderr)

    def lineReceived(self, line):
        args = line.split()
        if args[0] == 'RESOLVED':
            # Answer might contain whitespace if it's an error message; if so,
            # len(answer) will be greater than 1.
            query_id, status, answer = args[1], args[2], args[3:]
            query_id = int(query_id)
            status = int(status)

            # GenericFail, Timeout
            if status in [1, 4] and self._timeout[query_id] > time.time():
                # Wait 1 second and retry
                time.sleep(1.0)
                self._process.stdin.write('RESOLVE {} {} {}\n'.format(
                    query_id,
                    self._names[query_id],
                    self._stream_isolation_ids[query_id]))
                return

            try:
                stream_id = self._queries[query_id]
                del self._queries[query_id]
                del self._names[query_id]
                del self._stream_isolation_ids[query_id]
                del self._timeout[query_id]
            except KeyError:
                print("No query {}: {}".format(query_id, self._queries.keys()),
                      file=sys.stderr)

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
                self._tor.close_stream(stream_id,
                                       stem.RelayEndReason.RESOLVEFAILED)

    def request_lookup(self, stream_id, name, stream_isolation_id):
        query_id = next(self._id_gen)
        self._queries[query_id] = stream_id
        self._names[query_id] = name
        self._stream_isolation_ids[query_id] = stream_isolation_id
        self._timeout[query_id] = time.time() + 60
        self._process.stdin.write('RESOLVE {} {} {}\n'.format(
            query_id,
            name,
            stream_isolation_id))


def spawn_name_service(tor, name):
    try:
        args = service_to_command[name]
    except KeyError:
        raise NoService(
            "No such service '{}'".format(name)
        )
    spawn_env = deepcopy(os.environ)
    spawn_env.update({
        'TOR_NS_STATE_LOCATION': '/var/lib/tor/ns_state',
        'TOR_NS_PROTO_VERSION': '1',
        'TOR_NS_PLUGIN_OPTIONS': '',
    })
    process = subprocess.Popen(args, bufsize=1, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               universal_newlines=True, env=spawn_env)

    proto = _TorNameServiceProtocol(tor, process)

    tout = Thread(target=proto.watch_stdout)
    tout.start()

    terr = Thread(target=proto.watch_stderr)
    terr.start()

    return proto


class _Attacher(object):
    def __init__(self, tor):
        self._tor = tor
        self._services = {}
        self._circuits = []
        self._current_nym_epoch = None
        self._stream_isolation_count = 0
        self._stream_isolation_prefix = secrets.token_hex()
        self._tor_version = self._tor.get_version()
        self._tor_supports_controller_wait = (self._tor_version
                                              >= Version("0.4.5.1"))

    def maybe_launch_service(self, name):
        suffix = None
        srv = None

        for candidate_suffix in service_to_command:
            if name.endswith("." + candidate_suffix):
                suffix = candidate_suffix
                srv = self._services.get(suffix, None)
                break

        if srv is None:
            srv = spawn_name_service(self._tor, suffix)
            self._services[suffix] = srv
        return srv

    def stream_compatible(self, circuit_stream, new_stream):
        iso_fields_missing_message = "WARNING: Isolation fields are missing; \
stream isolation won't work properly.  Maybe you have an outdated Tor daemon?"

        # Extract list of isolated fields
        try:
            circuit_iso_fields = circuit_stream["ISO_FIELDS"]
        except KeyError:
            print(iso_fields_missing_message, file=sys.stderr)
            circuit_iso_fields = ""
        try:
            new_iso_fields = new_stream["ISO_FIELDS"]
        except KeyError:
            print(iso_fields_missing_message, file=sys.stderr)
            new_iso_fields = ""

        circuit_iso_fields = circuit_iso_fields.split(",")
        new_iso_fields = new_iso_fields.split(",")

        iso_fields = set(circuit_iso_fields)
        iso_fields.update(set(new_iso_fields))

        # If all of the isolated fields are equal, then the streams are
        # compatible.
        for field in iso_fields:
            try:
                circuit_field = circuit_stream[field]
            except KeyError:
                circuit_field = None
            try:
                new_field = new_stream[field]
            except KeyError:
                new_field = None

            if new_field != circuit_field:
                return False

        return True

    def circuit_compatible(self, circuit_streams, new_stream):
        # A circuit is compatible with a new stream if all of its existing
        # streams are compatible with the new stream.
        for circuit_stream in circuit_streams:
            if not self.stream_compatible(circuit_stream, new_stream):
                return False
        return True

    def get_stream_isolation_id(self, keyword_args):
        # Extract the nym epoch
        try:
            nym_epoch = keyword_args["NYM_EPOCH"]
        except KeyError:
            print("WARNING: Nym epoch is missing; stream isolation won't be \
cleared.  Maybe you have an outdated Tor daemon?", file=sys.stderr)
            nym_epoch = 1

        # If the nym epoch has changed, then we can clear the history
        if nym_epoch != self._current_nym_epoch:
            self._current_nym_epoch = nym_epoch
            self._circuits = []
            print("New nym epoch; cleared history.")

        # Look for compatible existing circuits
        for circuit in self._circuits:
            if self.circuit_compatible(circuit["streams"], keyword_args):
                return circuit["id"]

        # No compatible existing circuit exists; create a new one
        self._stream_isolation_count += 1
        circuit = {
            "id": self._stream_isolation_count,
            "streams": [keyword_args],
        }
        self._circuits.append(circuit)

        # Uncomment for verbose logging of stream isolation
        # print("Assigning clean circuit.")
        return circuit["id"]

    def attach_stream(self, stream):
        # Uncomment for verbose logging of STREAM events
        # print("attach_stream {}".format(stream))

        # Only attach streams that are waiting for us to attach them.
        if self._tor_supports_controller_wait:
            # Tor is recent enough to do this the right way.

            try:
                # Stem 1.9.0 and higher
                if stream.status != stem.StreamStatus.CONTROLLER_WAIT:
                    return
            except AttributeError:
                # Stem 1.8.0 and earlier
                if stream.status != "CONTROLLER_WAIT":
                    return
        else:
            # Tor is too old to do this the right way; we'll work around it by
            # rolling our own simulation of __LeaveStreamsUnattached.  This may
            # have bugs but it usually works.

            # Don't attach streams if their status indicates that they were
            # already attached.
            if stream.status not in [stem.StreamStatus.NEW,
                                     stem.StreamStatus.NEWRESOLVE]:
                return

            # Don't attach streams if their purpose indicates that they will be
            # automatically attached.
            if stream.purpose not in [stem.StreamPurpose.DNS_REQUEST,
                                      stem.StreamPurpose.USER]:
                return

        try:
            srv = self.maybe_launch_service(stream.target_address)
        except NoService:
            # No service is configured for this address; just pass it through
            # to Tor unaltered.
            try:
                self._tor.attach_stream(stream.id, 0)
            except stem.UnsatisfiableRequest:
                pass
            return
        except Exception as e:
            print("Unable to launch service: {}".format(
                str(e)), file=sys.stderr)
            # A service is configured for this address, but we failed to launch
            # it.  Do not try to attach the stream, since we can't do so
            # safely.  Instead just tell Tor that the resolution failed.
            self._tor.close_stream(stream.id,
                                   stem.RelayEndReason.RESOLVEFAILED)
            return

        # Apply the special-case grandfathered stream-isolation args
        keyword_args = stream.keyword_args
        keyword_args["CLIENTADDR"] = stream.source_address
        keyword_args["CLIENTPORT"] = stream.source_port
        keyword_args["DESTADDR"] = stream.target_address
        keyword_args["DESTPORT"] = stream.target_port

        # Figure out which stream isolation ID to pass to the naming plugin
        stream_isolation_id = self.get_stream_isolation_id(keyword_args)

        srv.request_lookup(stream.id,
                           stream.target_address,
                           self._stream_isolation_prefix + "-" +
                           str(stream_isolation_id))


def bootstrap_initial(info):
    status = ControlLine(info)
    while not status.is_empty():
        if status.is_next_mapping():
            k, v = status.pop_mapping(quoted=status.is_next_quoted())
            if k == "PROGRESS":
                progress = v
                print(f"[debug] Bootstrap initial progress {progress}%")
                if int(progress) == 100:
                    print("Bootstrap complete, running callback...")
                    bootstrap_callback()
        else:
            status.pop(quoted=status.is_next_quoted())


def bootstrap(status):
    if status.action == "BOOTSTRAP":
        progress = status.arguments["PROGRESS"]
        print(f"[debug] Bootstrap progress {progress}%")

        if int(progress) == 100:
            print("Bootstrap complete, running callback...")
            bootstrap_callback()


def socket_state_initial(alive):
    if not alive:
        print("Tor daemon exited; exiting StemNS...")
        exit_callback()


def socket_state(controller, state, timestamp):
    if state == stem.control.State.CLOSED:
        socket_state_initial(False)


def main():
    config = load_config_from_dir("config", {
        'tor_control_port': 'shadow',
        'service_to_command': 'merge',
        'bootstrap_callback': 'call',
        'exit_callback': 'call'
        })

    global tor_control_port
    global service_to_command
    global bootstrap_callback
    global exit_callback

    tor_control_port = config['tor_control_port']
    service_to_command = config['service_to_command']
    bootstrap_callback = config['bootstrap_callback']
    exit_callback = config['exit_callback']

    while True:
        try:
            # open main controller
            controller = Controller.from_port(port=tor_control_port())
            break
        except stem.SocketError:
            time.sleep(0.005)
        except ValueError:
            # port is None
            time.sleep(0.005)

    controller.authenticate()

    print("[notice] Successfully connected to the Tor control port.")

    if controller.get_conf('__LeaveStreamsUnattached') != '1':
        sys.exit('[err] torrc is unsafe for name lookups.  Try adding the \
line "__LeaveStreamsUnattached 1" to torrc-defaults')

    attacher = _Attacher(controller)

    controller.add_event_listener(attacher.attach_stream, EventType.STREAM)
    print('[debug] Now monitoring stream connections.')

    controller.add_event_listener(bootstrap, EventType.STATUS_CLIENT)
    bootstrap_initial(controller.get_info("status/bootstrap-phase"))
    print('[debug] Now monitoring bootstrap.')

    controller.add_status_listener(socket_state)
    socket_state_initial(controller.is_alive())
    print('[debug] Now monitoring shutdown.')

    try:
        # Sleeping for 365 days, as upstream OnioNS does, appears to be
        # incompatible with Windows.  Therefore, we instead sleep for 1 day
        # inside an infinite loop.
        while True:
            time.sleep(60 * 60 * 24 * 1)  # basically, wait indefinitely
    except KeyboardInterrupt:
        print('')


if __name__ == '__main__':
    main()
