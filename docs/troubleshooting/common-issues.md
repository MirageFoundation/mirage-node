# Common Issues After Deployment (Public)

This guide covers frequent issues encountered after deploying Mirage. It is safe to share publicly and avoids hard-coded IPs, SSH shortcuts, and server-specific runbooks.

### Variables used below

```bash
CONTAINER="${CONTAINER:-mirage}"
NODE_DOMAIN="<YOUR_NODE_DOMAIN>"
```

### Issue 1: Web interface returns 503

**Symptoms:**

- Browser shows 503
- `curl` to the site returns 503 or times out

**Diagnosis (from your machine):**

```bash
curl -I "https://${NODE_DOMAIN}/"
curl -I "https://${NODE_DOMAIN}/api/get_parameters"
```

**Diagnosis (on the Docker host):**

```bash
docker ps -a
docker logs "${CONTAINER}" --tail 200
docker exec "${CONTAINER}" ps aux | grep -E "caddy|python|miraged"
```

**Common causes:**

- Container is restarting or still starting up
- Web server is not running
- Backend/indexer is down and the web server is proxying to an unhealthy upstream

### Issue 2: HTTPS is not working

**Symptoms:**

- `https://...` fails but `http://...` works
- Browser shows TLS or connection errors

**Diagnosis:**

```bash
curl -I "http://${NODE_DOMAIN}/" || true
curl -I "https://${NODE_DOMAIN}/" || true
```

**Typical fixes:**

- Confirm DNS is pointed to your server and has propagated.
- Confirm ports 80 and 443 are open to the internet.
- Re-run your TLS provisioning workflow. If you are using the Mirage Caddy setup, the helper script is:

```bash
docker exec "${CONTAINER}" python3 /opt/mirage/deploy/setup_letsencrypt.py --domain="${NODE_DOMAIN}"
```

### Issue 3: Wrong machine or wrong container

**Symptoms:**

- You are checking logs, but nothing matches what the website shows
- Commands refer to a different container name

**Prevention:**

- Always confirm which host you are operating on (your standard process).
- Always confirm the container name:

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

### Related documentation

- [Infrastructure Reference](./infrastructure.md)
- [Validator Unjail Failure](./validator-unjail-failure.md)


