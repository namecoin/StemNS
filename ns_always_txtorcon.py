# this is a Tor Proposition 279-compliant name resolution provider
# that sends any .onion request to txtorcon's documentation site.

import sys


print('INIT 1 0')
while True:
    line = sys.stdin.readline()
    args = line.split()
    if args[0] == 'RESOLVE':
        query_id, nm = args[1:]
        print('RESOLVED {} 0 timaq4ygg2iegci7.onion'.format(query_id))
    elif args[0] == 'CANCEL':
        query_id = args[1]
        print('CANCELED {}'.format(query_id))
    sys.stdout.flush()
