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

import sys
from os.path import join, split

import txtorcon
from twisted.internet import defer, task, endpoints
from twisted.internet.protocol import ProcessProtocol
from twisted.protocols.basic import LineReceiver
from zope.interface import implementer


def _sequential_id():
    rtn = 1
    while True:
        yield rtn
        rtn += 1


class _TorNameServiceProtocol(ProcessProtocol, object):
    delimiter = '\n'

    def __init__(self):
        super(_TorNameServiceProtocol, self).__init__()
        self._queries = dict()
        self._id_gen = _sequential_id()

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
            try:
                self._queries[query_id].callback(answer)
                del self._queries[query_id]
            except KeyError:
                print("No query {}: {}".format(query_id, self._queries.keys()))

    def request_lookup(self, name):
        query_id = next(self._id_gen)
        d = defer.Deferred()
        self._queries[query_id] = d
        self.transport.write('RESOLVE {} {}\n'.format(query_id, name))
        return d


@defer.inlineCallbacks
def spawn_name_service(reactor):
    proto = _TorNameServiceProtocol()
    process = yield reactor.spawnProcess(
        proto,
        sys.executable,
        ['python', join(split(__file__)[0], 'ns_always_txtorcon.py')],
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
        srv = self._services.get(name, None)
        if srv is None:
            srv = yield spawn_name_service(self._reactor)
            self._services[name] = srv
        defer.returnValue(srv)

    @defer.inlineCallbacks
    def attach_stream(self, stream, circuits):
        print("attach_stream {}".format(stream))
        if stream.target_host.endswith('.onion'):

            # placeholder service, obviously we can run any number of
            # these etc
            srv = yield self.maybe_launch_service('foo')
            remap = yield srv.request_lookup(stream.target_host)

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
    yield ns_service.maybe_launch_service('foo')
    yield state.set_attacher(ns_service, reactor)

    # wait forever
    yield defer.Deferred()
