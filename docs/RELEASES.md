# Release downloads

[Project page](../README.md)

The repository and the first experimental release are **private**. Sign in to GitHub with an account that has repository access to view or download the assets. No public release has been made.

## Release files

| File | Contents |
| --- | --- |
| `Zitatlotse-0.27.0.xpi` | Installable Zotero add-on with the Windows x64 Python runtime, CPU libraries and backend. |
| `Zitatlotse-0.27.0-source.zip` | Cleaned project source, tests and documentation. |
| `third-party-sources.zip` | Corresponding unmodified source for the bundled AGPL PDF library. |
| `SHA256SUMS.txt` | SHA-256 checksums for the downloads. |

For normal use, you only need the **XPI**. Source archives are provided for development, review and license compliance.

Download [`Zitatlotse-0.27.0.xpi`](https://github.com/Cuzimnero/zitatlotse/releases/download/v0.27.0/Zitatlotse-0.27.0.xpi) or open the [private test release](https://github.com/Cuzimnero/zitatlotse/releases/tag/v0.27.0) for the source archives and checksums. GitHub authentication is required while the repository is private.

## Publishing

The manually triggered **Build a draft release** workflow builds and tests the complete package. It creates an unpublished release draft only. The files are attached as assets; the XPI can be downloaded directly after the release is published. A regular push does not publish a release.

The requested tag must match `plugin/manifest.json`. An existing release is not overwritten. See the [release notes for 0.27.0](releases/v0.27.0.md).
