# TB2.1 Residual images

All 31 Residual images are public in [lijinze956/swe-residual-tb21](https://hub.docker.com/r/lijinze956/swe-residual-tb21). Each `linux/amd64` image
has a state tag, such as `fs31-r002-v1`, and a fixed registry digest recorded in
`assets/tb21/dockerhub-images.json`.

## Download

From the repository root, prepare all 31 images with:

```bash
python scripts/prepare.py --benchmark tb21 --condition residual
```

The script pulls each image by registry digest, verifies its recorded identity,
and assigns the local tag expected by the Residual catalog. Classic Docker stores
are checked against the source config digest. Docker's containerd stores are
checked against the independently verified manifest digest. Public pulls do not
require login and remain subject to Docker Hub's download limits.

Clean tasks use their 20 pinned official images. DeepSWE uses its official base
images and the exact patches in this repository. See [DATASET.md](DATASET.md).

## Maintainer: review an upload plan

The source image names, config digests, and verified manifest digests are recorded
in `assets/tb21/image-manifest.json`. The optional offline export is excluded from
Git; `assets/tb21/image-archive.json` records its hash and size.

For a separate mirror, replace `YOUR_ACCOUNT` with the destination Docker Hub
account. Create a repository there and authenticate with `docker login`.

```bash
python scripts/publish_docker.py --repository YOUR_ACCOUNT/swe-residual-tb21
```

This prints the 31 source images, destination tags, and expected identities.
It does not run Docker commands or upload anything.

## Maintainer: upload

If the source images are already loaded in the Docker daemon:

```bash
python scripts/publish_docker.py \
  --repository YOUR_ACCOUNT/swe-residual-tb21 --push
```

To load the existing export first:

```bash
python scripts/publish_docker.py \
  --repository YOUR_ACCOUNT/swe-residual-tb21 \
  --archive /path/to/images.tar.gz --push
```

The script verifies the archive checksum when supplied and checks all 31 source
image identities before the first upload. It tags and pushes the prepared images
without rebuilding them. After each push, it saves the returned registry digest
in `assets/tb21/dockerhub-images.json` and updates `SHA256SUMS.json`.

A failed or interrupted upload leaves a partial manifest. `publication_status`
becomes `complete` only after all 31 images return registry digests. Rerunning the
upload reuses uploaded Docker layers. Audit the remote config digests against
the source records before committing updated download references.

```bash
git add assets/tb21/dockerhub-images.json SHA256SUMS.json
git commit -m "Record published TB2.1 Residual image digests"
git push
```

Keep the original archive as an offline backup. Readers can obtain the images
directly from Docker Hub.
