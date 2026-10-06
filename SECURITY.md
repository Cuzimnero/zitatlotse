# Security policy

This project is an experimental prototype. It has no separate private reporting mailbox and offers no guaranteed security-support period.

For a possible vulnerability, first open an issue with a **general description that contains no secrets, private document text or exploitable details**, and ask for a private reporting channel. Never post API keys, databases or unredacted logs publicly.

The local service is intended for `127.0.0.1`. Its client header is not secret authentication. Do not expose the service through port forwarding, a reverse proxy or a LAN binding.

Custom Hugging Face models must be compatible with the supported local encoder. The project does not enable third-party model code through `trust_remote_code`. See [data and privacy](docs/DATA.md) for document and cloud provider handling.
