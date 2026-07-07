# Deploying blogger-backend to EC2

`.github/workflows/deploy.yml` SSHes into the EC2 instance on every push to
`main`, pulls the latest code, runs `uv sync` + pending DB migrations, and
restarts the systemd service. No AWS API calls, no AWS credentials in
GitHub — just an SSH key.

## One-time server setup

1. Clone the repo and create `.env` (see `.env.example`) at
   `/home/ubuntu/blogger-backend` — this file is gitignored, so deploys
   (`git reset --hard`) never touch it.
2. Install [`uv`](https://docs.astral.sh/uv/) for the `ubuntu` user
   (`curl -LsSf https://astral.sh/uv/install.sh | sh`), then `uv sync` once
   by hand to confirm the venv builds.
3. Install the service unit and enable it:

   ```bash
   sudo cp deploy/blogger-backend.service /etc/systemd/system/blogger-backend.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now blogger-backend
   ```

4. Let the `ubuntu` user restart *only* this service without a password
   (the deploy workflow runs `sudo systemctl restart blogger-backend`
   non-interactively):

   ```bash
   echo 'ubuntu ALL=(root) NOPASSWD: /bin/systemctl restart blogger-backend, /bin/systemctl status blogger-backend' \
     | sudo tee /etc/sudoers.d/blogger-backend-deploy
   sudo chmod 0440 /etc/sudoers.d/blogger-backend-deploy
   ```

5. Generate a dedicated deploy key pair (don't reuse your personal key) and
   add the **public** half to the server's `~/.ssh/authorized_keys` for the
   `ubuntu` user:

   ```bash
   ssh-keygen -t ed25519 -f deploy_key -N "" -C "github-actions-blogger-backend"
   ```

## GitHub repo configuration

Set these once under **Settings → Secrets and variables → Actions**:

| Type     | Name                     | Value                                                        |
| -------- | ------------------------ | ------------------------------------------------------------- |
| Secret   | `EC2_HOST`               | Instance public IP or DNS name                                 |
| Secret   | `EC2_SSH_PRIVATE_KEY`    | Contents of `deploy_key` (the private half) generated above    |
| Variable | `EC2_USER`               | `ubuntu` (this is already the default if unset)                 |
| Variable | `BACKEND_DEPLOY_PATH`    | Only needed if not `/home/ubuntu/blogger-backend`               |
| Variable | `BACKEND_SERVICE_NAME`   | Only needed if not `blogger-backend`                             |

Via the `gh` CLI instead of the UI:

```bash
gh secret set EC2_HOST --body "<instance-ip-or-dns>"
gh secret set EC2_SSH_PRIVATE_KEY < deploy_key
```

Once both are set, push to `main` (or run the workflow manually via
**Actions → Deploy to EC2 → Run workflow**) to deploy.
