# note: this needs the 'master' version of txtorcon to run. you can
# install it in a fresh virtualenv on Debian (after "apt-get install
# python-virtualenv") like so:
#
# virtualenv venv
# source venv/bin/activate
# pip install --upgrade pip
# pip install https://github.com/meejah/txtorcon/archive/master.zip
#
# Then you can run this:
# python poc.py
#
# ...and then visit any .onion address, and it'll get re-directed to
# txtorcon documentation.

import re
import sys
import itertools
from os.path import join, split

import txtorcon
from twisted.internet import defer, task, endpoints
from twisted.internet.protocol import ProcessProtocol
from twisted.protocols.basic import LineReceiver
from zope.interface import implementer

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


class _TorNameServiceProtocol(ProcessProtocol, object):
    delimiter = '\n'

    def __init__(self):
        super(_TorNameServiceProtocol, self).__init__()
        self._queries = dict()
        self._id_gen = itertools.count(1)

    def childDataReceived(self, fd, data):
        if fd == 1:
            # XXX just presuming we get these as "lines" -- actually,
            # want to buffer e.g. with LineReceiver
            self.lineReceived(data)
        else:
            print("Ignoring write to fd {}: {}".format(fd, repr(data)))

    def lineReceived(self, line):
        args = line.split()
        if args[0] == 'RESOLVED':
            query_id, status, answer = args[1:]
            query_id = int(query_id)
            status = int(status)

            try:
                d = self._queries[query_id]
                del self._queries[query_id]
            except KeyError:
                print("No query {}: {}".format(query_id, self._queries.keys()))

            if status == 0:
                d.callback(answer)
            else:
                err = NameLookupError(status)
                d.errback(err)

    def request_lookup(self, name):
        query_id = next(self._id_gen)
        d = defer.Deferred()
        self._queries[query_id] = d
        self.transport.write('RESOLVE {} {}\n'.format(query_id, name))
        return d


@defer.inlineCallbacks
def spawn_name_service(reactor, name):
    proto = _TorNameServiceProtocol()
    try:
        args = _service_to_command[name]
    except KeyError:
        raise Exception(
            "No such service '{}'".format(name)
        )
    process = yield reactor.spawnProcess(
        proto,
        args[0],
        args,
        env={
            'TOR_NS_STATE_LOCATION': '/var/lib/tor/ns_state',
            'TOR_NS_PROTO_VERSION': '1',
            'TOR_NS_PLUGIN_OPTIONS': '',
        },
#        path='/tmp',
    )
    defer.returnValue(proto)


@implementer(txtorcon.interface.IStreamAttacher)
class _Attacher(object):
    def __init__(self, reactor, tor):
        self._reactor = reactor
        self._tor = tor
        self._services = {}

    @defer.inlineCallbacks
    def maybe_launch_service(self, name):
        suffix = None
        srv = None

        for candidate_suffix in _service_to_command:
            if name.endswith("." + candidate_suffix):
                suffix = candidate_suffix
                srv = self._services.get(suffix, None)
                break

        if srv is None:
            srv = yield spawn_name_service(self._reactor, suffix)
            self._services[suffix] = srv
        defer.returnValue(srv)

    @defer.inlineCallbacks
    def attach_stream(self, stream, circuits):
        print("attach_stream {}".format(stream))

        try:
            srv = yield self.maybe_launch_service(stream.target_host)
        except Exception:
            print("Unable to launch service for '{}'".format(stream.target_host))
            return

        try:
            remap = yield srv.request_lookup(stream.target_host)
            print("{} becomes {}".format(stream.target_host, remap))
        except NameLookupError as e:
            print("lookup failed: {}".format(e))
            remap = None
            stream.close()

        if remap is not None and remap != stream.target_host:
            cmd = 'REDIRECTSTREAM {} {}'.format(stream.id, remap)
            yield self._tor.protocol.queue_command(cmd)
        defer.returnValue(None)  # ask Tor to attach the stream, always


@task.react
@defer.inlineCallbacks
def main(reactor):
    # this will connect to TBB
    control_ep = endpoints.TCP4ClientEndpoint(reactor, 'localhost', 9051)
    tor = yield txtorcon.connect(reactor, control_ep)
    print("tor {}".format(tor))

    state = yield tor.create_state()
    print("state {}".format(state))

    # run all stream-attachments through our thing
    ns_service = _Attacher(reactor, tor)
    yield state.set_attacher(ns_service, reactor)

    # wait forever
    yield defer.Deferred()
