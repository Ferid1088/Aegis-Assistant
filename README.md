# Capstone RAG Appliance

## Upgrading: migrating Qdrant from embedded to server mode

Existing appliance installs run Qdrant in **embedded mode** (`QdrantClient(path=...)`,
reading/writing `./data/qdrant` directly, in-process, with no separate server).
This version defaults every **new** install to **server mode** instead -- a real
`qdrant` container (`docker-compose.yml`'s `qdrant` service), talked to over HTTP
via `QDRANT_URL` (`install.py` writes `QDRANT_URL=http://localhost:6333` into
`.env` for every fresh install).

Embedded and server mode do **not** share an on-disk format (embedded mode uses a
pure-Python/SQLite reimplementation bundled in `qdrant-client`; the server uses
raft + segment storage) -- pointing a server container at an embedded install's
existing `./data/qdrant` files does not error, it just starts with an empty
collection. They *do* share the same client-facing API, which is what makes a
migration at that level possible.

Before or during upgrading an existing (embedded-mode) install to this version,
an operator must run the migration tool once the new `qdrant` service is up,
and before relying on the appliance for real queries:

```
uv run python migrate_qdrant_to_server.py --server-url http://localhost:6333
```

This scrolls every point out of the embedded collection and re-upserts it into
the running server-mode collection. Skipping this step leaves the server
starting empty -- every previously ingested document becomes unsearchable until
it is re-ingested from scratch.

## Release

Pushing a tag matching `v*` (e.g. `v1`, `v2` -- the numeric suffix becomes the
release's integer `version`, consumed by `build_bundle.py`/`sign_bundle.py`)
triggers `.github/workflows/release.yml`. That workflow builds the app image,
runs the same Trivy CRITICAL-severity gate used in CI, builds an unsigned
update bundle, signs it, and attaches the signed bundle to a GitHub Release.

The release Trivy gate additionally ignores 2 specific CVEs
(`.github/release.trivyignore`, passed via the `trivyignores` input) --
CRITICAL findings in Debian's `perl-base`, transitive from the
`python:3.14-slim` base image, with no fix available from Debian. CI's own
`trivy-scan` job in `ci.yml` does not reference this ignore file and keeps
reporting/failing on them as an intentional, accepted-risk indicator.

Before pushing the first release tag, a repo maintainer must populate the
`RELEASE_SIGNING_PRIVATE_KEY` GitHub Actions secret (Settings -> Secrets and
variables -> Actions) out-of-band -- the workflow only ever *reads* this
secret, it never generates, transmits, or otherwise handles real signing-key
material:

1. Generate the Ed25519 keypair locally: `uv run python
   generate_signing_keypair.py`. This writes `keys/update_signing_privkey.pem`
   and `keys/update_signing_pubkey.pem`.
2. Paste the contents of `keys/update_signing_privkey.pem` into the
   `RELEASE_SIGNING_PRIVATE_KEY` secret, then delete the local file or move it
   to a secrets vault (per that script's own docstring -- it must never be
   committed; `keys/update_signing_privkey.pem` is already gitignored).
3. Commit `keys/update_signing_pubkey.pem` -- it ships in every appliance
   image so `update.py` can verify bundle signatures.

Once the secret is populated, pushing a tag matching `v*` (e.g. `v1`)
triggers the release workflow end-to-end.
