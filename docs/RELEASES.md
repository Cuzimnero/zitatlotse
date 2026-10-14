# Release downloads

[Project page](../README.md)

The repository and the first experimental release are **public**. No GitHub account is required to view the source or download the release assets. Version 0.27.1 remains an experimental prerelease; publication does not change its testing status or known limitations.

## Release files

| File | Contents |
| --- | --- |
| `Zitatlotse-0.27.1.xpi` | Installable Zotero add-on with the Windows x64 Python runtime, CPU libraries and backend. |
| `Zitatlotse-0.27.1-source.zip` | Cleaned project source, tests and documentation. |
| `third-party-sources.zip` | Corresponding unmodified source for the bundled AGPL PDF library. |
| `SHA256SUMS.txt` | SHA-256 checksums for the downloads. |

For normal use, you only need the **XPI**. Source archives are provided for development, review and license compliance.

Download [`Zitatlotse-0.27.1.xpi`](https://github.com/Cuzimnero/zitatlotse/releases/download/v0.27.1/Zitatlotse-0.27.1.xpi) or open the [public experimental release](https://github.com/Cuzimnero/zitatlotse/releases/tag/v0.27.1) for the source archives and checksums. Version 0.27.1 fixes the installation failure in 0.27.0. Install the corrected XPI; older snapshots remain in the Git history.

## Publishing

The manually triggered **Build a draft release** workflow builds and tests the complete package. It creates an unpublished release draft only. The files are attached as assets; the XPI can be downloaded directly after the release is published. A regular push does not publish a release.

The requested tag must match `plugin/manifest.json`. An existing release is not overwritten. See the [release notes for 0.27.1](releases/v0.27.1.md).
