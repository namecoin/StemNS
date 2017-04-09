# this is a Tor Proposition 279-compliant name resolution provider
# that sends any .onion request to txtorcon's documentation site.

import sys

pet_names = {
    'txtorcon': 'timaq4ygg2iegci7.onion',
    'duckduckgo': '3g2upl4pq6kufc4m.onion',
    'torist': 'toristinkirir4xj.onion',
    'scihub': 'scihub22266oqcxt.onion',
}


print('INIT 1 0')
while True:
    line = sys.stdin.readline()
    args = line.split()

    if args[0] == 'RESOLVE':
        query_id, nm = args[1:]
        try:
            new_name = pet_names[nm]
            print('RESOLVED {} 0 {}'.format(query_id, new_name))
        except KeyError:
            # spec says "XXX Should <RESULT> be optional in the case
            # of failure?" and I think the answer should be "yes", but
            # I'm echoing the asked-for name back here ...
            print('RESOLVED {} 3 {}'.format(query_id, nm))

    elif args[0] == 'CANCEL':
        query_id = args[1]
        print('CANCELED {}'.format(query_id))

    sys.stdout.flush()
