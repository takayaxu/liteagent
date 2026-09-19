# Deployment status

Verified on 2026-09-19 UTC.

- Shared container: `liteagent-shared-osworld`
- Container state: `running`
- Docker image: `happysixd/osworld-docker:latest`
- Image ID: `sha256:fe8d9a5e5ad6c593d059887ea2c790481b3f32dd42fa961f2441cdbbe2c70cf4`
- Control endpoint: `http://127.0.0.1:5020`
- noVNC endpoint: `http://127.0.0.1:8020`
- Shared qcow2: `/var/lib/liteagent-shared/Ubuntu.qcow2`

The shared qcow2 and the original file have the same filesystem device and
inode, with link count 2. This confirms that the deployment did not allocate a
second 24.46 GB Ubuntu image.

Validation completed:

- 1920x1080 PNG screenshot returned by the control endpoint.
- All ten Adapter deployments returned `status=ok`:
  Calc, Impress, Chrome, GIMP, OS, Writer, VS Code, VLC, Thunderbird and
  Multi-Apps.
- LiteAgent Python source compiled and its runtime, tool catalog and Docker
  provider imported successfully.

Run `./bin/guest-status.sh` for a fresh local check.
