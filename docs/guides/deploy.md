# Deploying a Mirage Node

Run your own Mirage validator node in minutes.

## Requirements

- A Linux server (Ubuntu 22.04+ recommended)
- Docker installed on the server
- A domain name pointing to your server (for HTTPS)
- A funded wallet with at least **15 MIRAGE** (25 recommended)

### Server specs

Minimum recommended:

- 2 vCPUs
- 4 GB RAM
- 25 GB disk

A DigitalOcean droplet at ~$24/month works great.

## Step 1: Get a funded mnemonic

You need a wallet with MIRAGE tokens to run a validator node.

**How to get funded:**

1. Visit [mirage.talk](https://mirage.talk)
2. Create a free account
3. Post in the **#mirage** topic asking for validator funding
4. We'll send you MIRAGE tokens and help you get set up

You'll receive a 12-word mnemonic phrase. Keep it safe — this is your validator identity.

## Step 2: Clone the repository

On your **local machine** (not the server):

```bash
git clone https://github.com/MirageFoundation/mirage-node.git
cd mirage-node
```

## Step 3: Deploy

Run the deploy script:

```bash
deploy/deploy.sh root@your-server --init --moniker your-node-name
```

Replace:
- `your-server` with your server's IP or domain
- `your-node-name` with whatever you want to call your node

You'll be prompted for your funded mnemonic. Paste the 12 words when asked.

That's it! The script builds the Docker image, uploads it to your server, and starts everything.

## Step 4: Enable HTTPS (optional)

If you have a domain pointing to your server, enable TLS:

```bash
ssh root@your-server
docker exec mirage bash /opt/mirage/deploy/letsencrypt_register.sh --domain your-domain.com
```

If you're just using an IP address, skip this step — your node will be accessible at `http://your-server-ip` directly.

## Updating your node

To update to the latest version:

```bash
deploy/deploy.sh root@your-server --update
```

This rebuilds the image and restarts the container while preserving all your data and keys.

## What the deploy script does

The script handles everything automatically:

1. **Installs Docker** on the server if it's not already installed
2. **Builds the Docker image** on your local machine
3. **Uploads the image** to your server
4. **Prompts for your mnemonic** and securely imports your validator keys
5. **Sets up PostgreSQL** inside the container (no manual database config needed)
6. **Starts all services** (blockchain node, indexer, web backend, frontend)
7. **Creates your validator** on-chain

All data is persisted in `~/.mirage` on the server, so updates preserve your keys and state.

## Monitoring

```bash
# View logs
ssh root@your-server 'docker logs mirage'

# Attach to tmux session
ssh -t root@your-server 'docker exec -it mirage tmux attach -t mirage'
```

## Need help?

Join the conversation on [mirage.talk/r/mirage](https://mirage.talk/t/mirage). We're happy to help you get your node running!
