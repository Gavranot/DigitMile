# SSL Certificate Setup Guide

## Option 1: Self-Signed Certificate (Localhost/Testing)

Use this when you **don't have a domain** and want to test HTTPS locally.

### Pros
- Works immediately without domain
- Free
- Good for local development

### Cons
- Browser warnings ("Not Secure")
- Not trusted by browsers
- Only for testing, NOT for production

### Setup

1. **Generate self-signed certificate:**
   ```bash
   cd nginx-proxy
   bash generate-self-signed-cert.sh
   ```

2. **Start with localhost configuration:**
   ```bash
   docker-compose -f docker-compose.yml -f docker-compose.localhost.yml up -d
   ```

3. **Access your site:**
   - HTTP: http://localhost
   - HTTPS: https://localhost (you'll see a browser warning - click "Advanced" → "Proceed anyway")

4. **Update Unity game URL:**
   ```csharp
   // In your Unity C# scripts
   string backendUrl = "https://localhost/panel/";
   // OR for HTTP only
   string backendUrl = "http://localhost/panel/";
   ```

---

## Option 2: Let's Encrypt (Production with Domain)

Use this when you **have a domain** pointing to your server.

### Pros
- Free, automated, and trusted by all browsers
- Auto-renewal every 90 days
- Production-ready

### Cons
- Requires a domain name
- Requires port 80/443 accessible from internet
- Rate limits (5 certs per domain per week)

### Prerequisites

1. **Own a domain** (e.g., from Namecheap, GoDaddy, Cloudflare)
2. **DNS A record** pointing to your server's public IP
   ```
   digitmile.com      A    123.45.67.89
   www.digitmile.com  A    123.45.67.89
   ```
3. **Ports 80 and 443** open on your firewall

### Setup

1. **Initialize Let's Encrypt certificates:**
   ```bash
   chmod +x scripts/init-letsencrypt.sh
   ./scripts/init-letsencrypt.sh your-domain.com your-email@example.com
   ```

2. **Start with production configuration:**
   ```bash
   docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
   ```

3. **Certificates auto-renew** every 12 hours (if within 30 days of expiry)

4. **Update Unity game URL:**
   ```csharp
   // In your Unity C# scripts
   string backendUrl = "https://your-domain.com/panel/";
   ```

### Manual Certificate Renewal

If needed, renew manually:
```bash
docker-compose run --rm certbot renew
docker-compose restart nginx-proxy
```

---

## Option 3: Cloudflare SSL (Production Alternative)

Use this if you use Cloudflare for DNS and want easier SSL management.

### Pros
- Free SSL/TLS
- DDoS protection
- CDN included
- Easier than Let's Encrypt

### Cons
- Requires using Cloudflare nameservers
- SSL between Cloudflare and your server can be "Flexible" (insecure) or "Full"

### Setup

1. **Add domain to Cloudflare**
2. **Set SSL mode to "Full (strict)"** in Cloudflare dashboard
3. **Generate Origin Certificate** in Cloudflare:
   - SSL/TLS → Origin Server → Create Certificate
   - Download `.pem` and `.key` files

4. **Add certificates to your server:**
   ```bash
   mkdir -p certbot/conf/live/your-domain.com
   # Copy your certificates:
   cp cloudflare-cert.pem certbot/conf/live/your-domain.com/fullchain.pem
   cp cloudflare-key.pem certbot/conf/live/your-domain.com/privkey.pem
   ```

5. **Update nginx configuration** to use these certificates
6. **Enable Cloudflare proxy** (orange cloud) in DNS settings

---

## Comparison Table

| Feature | Self-Signed | Let's Encrypt | Cloudflare |
|---------|-------------|---------------|------------|
| **Cost** | Free | Free | Free |
| **Domain Required** | No | Yes | Yes |
| **Browser Trust** | ❌ No | ✅ Yes | ✅ Yes |
| **Setup Difficulty** | Easy | Medium | Easy |
| **Auto-Renewal** | N/A | ✅ Yes | ✅ Yes |
| **Production Ready** | ❌ No | ✅ Yes | ✅ Yes |
| **Best For** | Local dev | Self-hosted | Cloudflare users |

---

## Recommended Path

### For Development/Testing (No Domain)
1. Use **self-signed certificates**
2. Accept browser warnings
3. Test your HTTPS setup

### For Production (With Domain)
1. If using Cloudflare DNS → Use **Cloudflare SSL**
2. If self-hosting → Use **Let's Encrypt**

---

## Troubleshooting

### Let's Encrypt fails with "unauthorized"
- Check DNS points to your server: `nslookup your-domain.com`
- Ensure ports 80/443 are open
- Check nginx is running: `docker-compose ps`

### Browser shows "Not Secure" (Self-Signed)
- This is expected for self-signed certificates
- Click "Advanced" → "Proceed to site"
- For production, use Let's Encrypt or Cloudflare

### Certificate expired
- Let's Encrypt certs last 90 days
- Auto-renewal runs every 12 hours
- Manual renewal: `docker-compose run --rm certbot renew`

### Unity game can't connect to HTTPS backend
- Check URL uses `https://` not `http://`
- For self-signed, you may need to accept the certificate in a browser first
- Check CORS is enabled in Django settings (already configured)
