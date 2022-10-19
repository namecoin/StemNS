# this is a Tor Proposition 279-compliant name resolution provider
# that resolves a predefined set of .pet.onion domains.

import sys

pet_names = {
    'txtorcon.pet.onion': 'timaq4ygg2iegci7.onion',
    'duckduckgo.pet.onion':
        'duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion',
    'torist.pet.onion': 'toristinkirir4xj.onion',
    'scihub.pet.onion': 'scihub22266oqcxt.onion',
}


print('INIT 1 0')
while True:
    line = sys.stdin.readline()
    args = line.split()

    if args[0] == 'RESOLVE':
        query_id, nm, _ = args[1:]
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
