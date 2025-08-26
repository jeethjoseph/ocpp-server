# OCPP 1.6 over GSM (EC200U) to Render via WSS

This guide explains how to connect a charger using a GSM module (Quectel EC200U) to the Render-hosted backend over WSS for OCPP 1.6, and how to resolve common TLS issues (especially ECDSA vs RSA certs).

Applies to backend endpoint: `wss://<your-domain>/ocpp/{charge_point_id}` (FastAPI in `backend/main.py`).

## TL;DR checklist

- Render public services require HTTPS/WSS; plain `ws://` will not work.
- The Render default domain `ocpp-server-uwli.onrender.com` currently negotiates an ECDSA cert.
- Many cellular modules fail with ECDSA server certs. Use RSA instead.
- Easiest path: add a custom domain that negotiates an RSA cert, or front with Cloudflare/Nginx to present RSA.
- EC200U needs correct time, SNI, TLS 1.2, and the issuing CA loaded.
- Keep the connection alive over GSM with heartbeats/pings (~60s).

## 1) Render and WebSockets

- Render terminates TLS at the edge. Public HTTP (80) redirects to HTTPS (443).
- WebSocket redirects (ws->wss) won’t work; device must connect using `wss://`.
- The FastAPI app is scheme-agnostic; TLS is handled by the edge/proxy.

## 2) Your current TLS handshake (Render default domain)

Observed on 2025‑08‑26 for `ocpp-server-uwli.onrender.com`:

- Cipher: `ECDHE-ECDSA-AES128-GCM-SHA256`
- Issuer: Google Trust Services (WE1 → GTS Root R4)
- Conclusion: ECDSA P‑256 leaf certificate (algorithm many GSM modules don’t support).

Verification command (don’t include https:// in -servername):

```zsh
openssl s_client -connect ocpp-server-uwli.onrender.com:443 \
  -servername ocpp-server-uwli.onrender.com -tls1_2 </dev/null | sed -n '1,120p'
# Look for: "Cipher is ECDHE-ECDSA-..." (problem for some GSM modules)
```

## 3) Move to RSA for GSM compatibility

Option A — Custom domain directly on Render (preferred first step):
- Add a custom domain to your Render service and enable Managed TLS.
- After issuance, verify the handshake again:

```zsh
openssl s_client -connect your.domain:443 -servername your.domain -tls1_2 </dev/null | sed -n '1,120p'
# You want to see: "Cipher is ECDHE-RSA-..."
```

If it’s RSA now, proceed to EC200U provisioning (section 4).

Option B — Cloudflare proxy in front of Render:
- Point your custom domain to Cloudflare, enable the orange-cloud proxy.
- SSL mode: "Full (strict)". WebSockets are supported by default.
- Cloudflare presents RSA or ECDSA depending on client; GSM modules will typically get RSA.

Option C — Your own RSA-terminating Nginx/Caddy proxy:
- Obtain an RSA cert (e.g., Let’s Encrypt RSA). Terminate at your VM and proxy to Render.
- Minimal Nginx example:

```nginx
server {
    listen 443 ssl http2;
    server_name your.domain;

    ssl_certificate     /etc/ssl/your-domain.fullchain.pem;  # RSA chain
    ssl_certificate_key /etc/ssl/your-domain.key;            # RSA key
    ssl_protocols TLSv1.2;  # many modules need TLS 1.2
    ssl_ciphers ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384:
                AES128-GCM-SHA256:AES256-GCM-SHA384;  # RSA-friendly
    ssl_prefer_server_ciphers on;

    location /ocpp/ {
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_pass https://ocpp-server-uwli.onrender.com;
    }
}
```

## 4) EC200U TLS provisioning (server-auth, OCPP Security Profile 2)

Prereqs:
- Use your final domain (with RSA cert) in the charger config. Do not use IPs (SNI required).
- Ensure outbound 443 is allowed by the APN and no TLS interception is present.

Steps (commands may vary slightly by firmware — consult EC200U AT manual):

1) Ensure date/time is correct (cert validation is time-bound)

```text
AT+QLTS?                       # Check local time
AT+QNTP=1,"pool.ntp.org"       # Sync via NTP
AT+QLTS?                       # Re-check
```

2) Load CA certificate(s)
- Load the issuing Root (and intermediate, if required) that signed your server RSA cert.
- Example file path: `UFS:ca.pem` (PEM format). Transfer via `AT+QFUPL` or your vendor tool.

```text
AT+QFUPL="UFS:ca.pem",<len>,60   # Then send the PEM bytes
```

3) Configure the SSL profile

```text
AT+QSSLCFG="sslversion",1,4         # TLS1.2
AT+QSSLCFG="seclevel",1,2           # verify server
AT+QSSLCFG="cacert",1,"UFS:ca.pem"  # path to your CA
AT+QSSLCFG="sni",1,1                # enable SNI
AT+QSSLCFG="ignorelocaltime",1,0    # require valid time
# Optional: constrain ciphers if needed
# AT+QSSLCFG="ciphersuite",1,"0X003C,0X009C,0X002F"  
```

4) Open TLS socket and perform WebSocket upgrade
- The MCU/app composes the HTTP/1.1 Upgrade request. Example headers:

```http
GET /ocpp/<charge_point_id> HTTP/1.1
Host: your.domain
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Version: 13
Sec-WebSocket-Key: <base64-16B>
Origin: null
```

Expect `101 Switching Protocols` if successful.

## 5) Keep the connection alive over GSM

- Cellular NATs often idle-timeout in 60–120s. Use one of:
  - Lower OCPP heartbeat interval for GSM devices (e.g., 60s) in `BootNotification` response.
  - Ensure client WebSocket ping/pong at ~30–60s.

Note: In `backend/main.py`, `BootNotification` currently returns interval `300`. You can reduce this later for GSM-only chargers.

## 6) Troubleshooting matrix

- Certificate algorithm
  - Symptom: TLS handshake fails; module logs generic TLS error.
  - Check: `openssl s_client` shows `ECDHE-ECDSA-...` → switch to RSA per section 3.

- Wrong time
  - Symptom: certificate not yet valid/expired errors.
  - Fix: NTP sync (section 4.1).

- Missing CA / chain
  - Symptom: unknown CA or verify failure.
  - Fix: load correct Root/Intermediate CA that issued your server RSA cert.

- SNI disabled
  - Symptom: handshake to CDN returns wrong cert.
  - Fix: `AT+QSSLCFG="sni",1,1` and connect by domain.

- APN proxy/TLS interception
  - Symptom: handshake breaks only on cellular.
  - Fix: use private/transparent APN; disable proxying.

- Connecting by IP
  - Symptom: cert CN mismatch.
  - Fix: always use domain name.

Useful desktop checks:

```zsh
# Show cipher/key type quickly
openssl s_client -connect your.domain:443 -servername your.domain -tls1_2 </dev/null | sed -n '1,120p'

# Inspect leaf certificate details
openssl s_client -connect your.domain:443 -servername your.domain -tls1_2 </dev/null \
| awk '/-----BEGIN CERTIFICATE-----/{p=1}p;/-----END CERTIFICATE-----/{exit}' \
| openssl x509 -noout -text | egrep 'Subject:|Public Key Algorithm|Signature Algorithm'
```

## 7) Optional: Mutual TLS (Security Profile 3)

- If you require client authentication, terminate mTLS at an edge proxy (Nginx/Envoy) and validate client certs (CN/SAN/serial) against charger identities before forwarding to FastAPI. Provision client cert+key on EC200U and configure `AT+QSSLCFG` for client cert usage.

## 8) Security notes

- Prefer RSA 2048 server cert for broad device compatibility.
- Serve the full certificate chain.
- Enforce TLS1.2+.
- For ws:// fallback, only consider on private APN/VPN with strict network ACLs (not recommended on public Internet).

---

Questions to finalize:
- Custom domain you’ll use?
- Will you front with Cloudflare or your own RSA proxy if Render still presents ECDSA?
- Which CA chain (Root/Intermediate) do you want packaged for EC200U provisioning?

Once confirmed, update your charger config to `wss://your.domain/ocpp/{charge_point_id}` and follow section 4.
