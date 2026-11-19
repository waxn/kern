# Git over SSH

Kern's git server can also be reached over SSH with public keys. It speaks only `git-upload-pack` and `git-receive-pack`: there is no shell, no password sign-in, no port forwarding and no SFTP/SCP.

## Use it

1. Open **Git** → **Sign-in** → **SSH keys**, paste the contents of your `.pub` file (ed25519, ECDSA, or RSA of 2048 bits or more) and add it. A key can be registered once per server.
2. Clone with the SSH tab of the clone box:

   ```sh
   git clone ssh://git@kern.example.com:2222/my-project.git
   git clone ssh://git@kern.example.com:2222/<your-username>/my-project.git   # same thing
   ```

   Any SSH username works (`git@` by convention). A plain `ssh -p 2222 git@host` answers "Hi <user>! Kern does not provide shell access."

3. **Deploy keys**: a repository's Settings tab can hold keys that reach that one repository only, read-only or with push. Deleting the repository deletes them.

Pushes over SSH go through the same checks and events as HTTP pushes (protected branches, push listeners), with `via="ssh"` and the key's title as pusher.

## The service

`docker-compose.yml` has an `ssh` service (same image and data volume as the backend) listening on port 2222 in the container:

```yaml
ports:
  - "${KERN_BIND:-0.0.0.0}:${KERN_SSH_PORT:-2222}:2222"
```

| Variable | Default | |
| --- | --- | --- |
| `KERN_SSH_PORT` | `2222` | Published port, also shown in clone URLs |
| `KERN_SSH_HOST` | host you browse Kern with | Host shown in clone URLs |
| `KERN_BIND` | `0.0.0.0` | Address to publish on (shared with the web port) |

The ed25519 host key is created on first start in `secrets/ssh_host_ed25519_key` inside the data volume and its fingerprint is printed in `docker compose logs ssh` (and shown under SSH keys). Back it up with the volume so clients do not see a changed host key.

The web app shows the SSH option when the service's heartbeat file (`ssh-server.json` in the data folder, refreshed every 30 seconds) is fresh, so it disappears by itself if the service is stopped. To turn SSH off entirely, remove the `ssh` service. Turning off git hosting in the site settings also refuses SSH sign-ins, as does deactivating the user.

## Reverse proxy and firewall

SSH is not HTTP, so the web proxy in front of Kern cannot carry it. Either:

- publish port 2222 (or any `KERN_SSH_PORT`) directly and open it in your firewall; set `KERN_BIND` to an internal address to keep it off the internet, or
- forward it with a TCP proxy, for example nginx's `stream` module (`listen 22; proxy_pass 127.0.0.1:2222;`) or HAProxy in `mode tcp`.

If the connection reaches Kern through a proxy, failed sign-ins are rate limited per proxy address, not per client. Only expose the port to networks you trust if that matters.
