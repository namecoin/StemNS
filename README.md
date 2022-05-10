
# Proposal 279

StemNS is an implementation of the "Tor side" of Proposal 279 ("naming
layer API") so that actual naming plugins can be tested/prototyped
"now" without changing Tor.

StemNS is a fork of the original [TorNS](https://github.com/meejah/TorNS) by meejah, which is modified to use Stem instead of txtorcon, with some additional security features added.

# Dependencies

* Tor v0.4.5.1 Alpha or higher is preferred; older versions should still work.
* Stem v1.9.0 or higher is preferred; older versions should still work.

# Configuration and usage

StemNS loads configuration from the `config` directory.  Example configurations are included; you can use them verbatim by renaming their extension from `.py.example` to `.py`.  You can also use them as a guide to make your own configurations.  You should include:

* Any number of `bootstrap` configs.
    * These are callbacks that run when Tor finishes bootstrap.
* Any number of `exit` configs.
    * These are callbacks that run when Tor disconnects its control port.
* Exactly one `port` config.
    * This is the Tor control port on `localhost` where StemNS connects to.
    * Example configs are provided for system-wide Tor, Tor Browser, and `ControlPort auto`.
* Any number of `service` configs.
    * These are mappings between eTLD's and Prop279 providers.
    * See "Name Resolution Services" below.

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

StemNS comes with two example name resolution
services, invoked for resolving `<something>.<service>.onion`:
* `.pet.onion` implemented in `ns_petname.py` resolves a predefined set
of names (try, e.g., "http://txtorcon.pet.onion" in Tor Browser).
* `.demo.onion` always remap to txtorcon's documentation hidden-service. So
  `<anything>.demo.onion` will redirect you to txtorcon's documentation.

You can implement custom services and add them via your own config files.

# Naming Implementations

 - "banana" does naming based on /etc/hosts: https://github.com/pickfire/banana
 - "dns-prop279" does naming based on DNS `TXT` records: https://github.com/namecoin/dns-prop279
 - "ncprop279" does naming based on Namecoin: https://github.com/namecoin/ncprop279

# License

Code specific to StemNS, and the code StemNS inherits from TorNS, is licensed under the Unlicense (see `LICENSE`).  StemNS inherits some code from [OnioNS-client](https://github.com/Jesse-V/OnioNS-client), which is licensed under the Modified/New BSD License (see `LICENSE.OnioNS`).

StemNS is produced independently from the Tor® anonymity software and carries no guarantee from The Tor Project about quality, suitability or anything else.
