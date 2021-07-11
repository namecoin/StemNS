
# Proposal 279

This is an implementation of the "Tor side" of Proposal 279 ("naming
layer api") so that actual naming plugins can be tested/prototyped
"now" without changing Tor.

StemNS is a fork of the original [TorNS](https://github.com/meejah/TorNS) by meejah, which is modified to use Stem instead of txtorcon.

# Configuration and usage

Currently only tag `v0.1.1` of StemNS works correctly. This is because of `stem v1.8.0` is not compatible with the current master branch.

It will currently connect to a system Tor daemon on `localhost:9051` or you can
change the port to `9151` in `settings_port.py` to react a Tor Browser Bundle
instance.

Tor must be configured with the following option before launching StemNS:

```
__LeaveStreamsUnattached 1
```

In a typical Tor Browser installation, `torrc-defaults` is the correct place to
add this option.  For Tor daemon installed in the system, the option can be added
to `/etc/tor/torrc`.

If the flag is not enabled, StemNS will exit with an error.

Once the flag is enabled, the ***StemNS daemon must be running for Tor to
work***.  The reason is that by default, with the flag disabled, Tor
automatically attaches streams to circuits, but with the flag enabled, Tor
instead waits for the controller (StemNS in this case) to attach them. StemNS
does a REDIRECTSTREAM command on each .bit stream prior to attaching it to a
circuit; this command is how it redirects .bit to .onion.

The choice to not make StemNS configure this option itself is deliberate;
making StemNS configure the option itself would leave a short window during
initial connect where name resolution is incorrectly forwarded to the exit
relay, which would be a security issue.

# Name resolution services

By default StemNS daemon is configured with two example name resolution
services, invoked for resolving `<something>.<service>.onion`:
* `.pet.onion` implemented in `ns_petname.py` resolves a predefined set
of names (try, e.g., "http://txtorcon.pet.onion" in TBB).
* `.demo.onion` always remap to txtorcon's documentation hidden-service. So
  `<anything>.demo.onion` will redirect you to txtorcon's documentation.

You can implement custom services and add them to the map in
`settings_services.py`.

# Naming Implementations

 - "banana" does naming based on /etc/hosts: https://github.com/pickfire/banana
 - "dns-prop279" does naming based on DNS `TXT` records: https://github.com/namecoin/dns-prop279

# License

Code specific to StemNS, and the code StemNS inherits from TorNS, is licensed under the Unlicense (see `LICENSE`).  StemNS inherits some code from [OnioNS-client](https://github.com/Jesse-V/OnioNS-client), which is licensed under the Modified/New BSD License (see `LICENSE.OnioNS`).

This product is produced independently from the Tor® anonymity software and carries no guarantee from The Tor Project about quality, suitability or anything else.
