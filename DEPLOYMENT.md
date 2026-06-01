# SI Assistant — AWS Deployment Guide

Written for a DevOps engineer deploying SI Assistant on AWS for the first time.

**Recommended stack:** EC2 (t3.medium) + EBS + Nginx + Let's Encrypt
**Estimated setup time:** 2-3 hours
**Monthly cost estimate:** ~USD $35-60 (EC2 t3.medium + EBS + data transfer)

---

## Prerequisites

- AWS account with permissions to create EC2, Security Groups, and Elastic IP
- A domain name (e.g. `siagent.yourorg.org`) with DNS you control
- Anthropic API key (or use Bedrock with IAM role — see Optional section below)
- SSH keypair already created in your target AWS region

---

## Architecture overview

```
Internet
   |
   | HTTPS (443)
   v
Nginx (reverse proxy + SSL termination via Let's Encrypt)
   |
   | HTTP (127.0.0.1:8501)
   v
Streamlit app (app.py)
   |
   |-- data/chroma_db/     (EBS volume -- persistent vector database)
   |-- data/raw/           (EBS volume -- source documents)
   |-- data/users.json     (EBS volume -- user accounts)
   |-- Anthropic API       (outbound HTTPS to api.anthropic.com)
```

---

## Step 1 — Launch EC2 instance

1. Go to EC2 > Launch Instance in the AWS Console.

2. Choose:
   - AMI: Ubuntu Server 22.04 LTS (64-bit x86)
   - Instance type: t3.medium (2 vCPU, 4 GB RAM minimum). Use t3.large (8 GB) if you have more than 10,000 documents.
   - Key pair: select your existing keypair (or create one and download the .pem file)

3. Network settings — create a new security group with these inbound rules:

   | Type  | Protocol | Port | Source       | Purpose              |
   |-------|----------|------|--------------|----------------------|
   | SSH   | TCP      | 22   | Your IP only | Admin access         |
   | HTTP  | TCP      | 80   | 0.0.0.0/0    | Let's Encrypt verify |
   | HTTPS | TCP      | 443  | 0.0.0.0/0    | User access          |

   Do NOT open port 8501 to the internet — Nginx proxies it internally.

4. Storage:
   - Root volume: 20 GB gp3 (OS and app code)
   - Add a second EBS volume: 30 GB gp3 for persistent data (documents, vector DB, user accounts). Increase to 100 GB if you have many large PDFs.

5. Click Launch Instance.

6. Attach an Elastic IP so the IP does not change on reboot:
   EC2 > Elastic IPs > Allocate > Associate with your instance.

7. Point your domain A record at the Elastic IP. Wait for DNS propagation (5 min for Route 53, up to 24h elsewhere).

---

## Step 2 — Connect and provision the server

```bash
ssh -i your-keypair.pem ubuntu@YOUR_ELASTIC_IP
```

### 2a. Mount the data EBS volume

```bash
# Find the device name of the second volume (usually /dev/xvdb or /dev/nvme1n1)
lsblk

# Format it -- run ONLY on first deployment, NOT when redeploying
sudo mkfs -t ext4 /dev/xvdb    # replace xvdb with your actual device name

# Create mount point and mount
sudo mkdir -p /data
sudo mount /dev/xvdb /data

# Auto-mount on reboot
echo '/dev/xvdb /data ext4 defaults,nofail 0 2' | sudo tee -a /etc/fstab
```

### 2b. Install system packages

```bash
sudo apt-get update && sudo apt-get upgrade -y

# Python 3.11 (required -- app has known warnings on 3.14)
sudo apt-get install -y python3.11 python3.11-venv python3.11-dev python3-pip

# Nginx and Certbot for SSL
sudo apt-get install -y nginx certbot python3-certbot-nginx

# Git and utilities
sudo apt-get install -y git htop curl wget
```

---

## Step 3 — Deploy the application

### 3a. Clone the repository

```bash
cd /opt
sudo git clone https://github.com/YOUR-ORG/siagent.git siagent
sudo chown -R ubuntu:ubuntu /opt/siagent
cd /opt/siagent
```

### 3b. Create Python virtual environment

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3c. Set up persistent data directories

```bash
sudo mkdir -p /data/chroma_db /data/raw /data/raw/sscp /data/reports
sudo chown -R ubuntu:ubuntu /data

# Symlink so the app finds data in its expected relative paths
ln -s /data/chroma_db /opt/siagent/data/chroma_db
ln -s /data/raw       /opt/siagent/data/raw
ln -s /data/reports   /opt/siagent/reports
```

### 3d. Create the .env configuration file

```bash
cp /opt/siagent/.env.example /opt/siagent/.env
nano /opt/siagent/.env
```

Set these values:

```
LLM_MODEL=anthropic/claude-sonnet-4-6
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
EMBEDDING_MODEL=all-MiniLM-L6-v2
CHROMA_DB_PATH=/data/chroma_db
CHROMA_COLLECTION=siagent

# S3 document storage
STORAGE_BACKEND=s3
AWS_BUCKET_NAME=siagent-documents-yourorg
AWS_PREFIX=documents/
AWS_REGION=ap-southeast-2
```

Note: AWS credentials are not needed in .env when the EC2 instance has an IAM role attached (Step 3f). The SDK picks up the role automatically.

Save and exit (Ctrl+O, Enter, Ctrl+X), then lock down the file:

```bash
chmod 600 /opt/siagent/.env
```

### 3e. Create the S3 document bucket

This is where all source documents live. The app downloads from S3 at ingestion time.

```bash
# Create the bucket (run from your local machine or AWS CloudShell)
aws s3 mb s3://siagent-documents-yourorg --region ap-southeast-2
```

Upload your documents from your local machine:

```bash
# General knowledge base documents
aws s3 sync C:\path\to\your\documents\ s3://siagent-documents-yourorg/documents/ \
    --exclude "*" --include "*.pdf" --include "*.docx" --include "*.txt" --include "*.md"

# SSCP priority documents (go in the sscp/ subfolder -- tagged for priority retrieval)
aws s3 sync C:\path\to\sscp\documents\ s3://siagent-documents-yourorg/documents/sscp/ \
    --exclude "*" --include "*.pdf" --include "*.docx"
```

The bucket structure must look like this:

```
siagent-documents-yourorg/
    documents/                  <- general KB documents
        WHO-Digital-Health.pdf
        FHIR-R4-spec.pdf
        OpenHIE-architecture.pdf
        ...
    documents/sscp/             <- SSCP priority documents
        field-learning-pacific.pdf
        country-assessment.pdf
        ...
```

### 3f. Attach IAM role to EC2 for S3 access

The EC2 instance needs permission to read from the document bucket.

1. Go to IAM > Roles > Create Role > AWS Service > EC2.
2. Create a new inline policy with this JSON (replace the bucket name):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:CopyObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::siagent-documents-yourorg",
        "arn:aws:s3:::siagent-documents-yourorg/*"
      ]
    }
  ]
}
```

3. Name the role `siagent-ec2-role` and attach it to your EC2 instance:
   EC2 > Instances > select instance > Actions > Security > Modify IAM role.

### 3g. Run the ingestion pipeline

```bash
cd /opt/siagent
source .venv/bin/activate
python -X utf8 scripts/run_ingestion.py
```

The script downloads all documents from S3, indexes them into ChromaDB, then discards the downloaded copies. The first run also downloads the embedding model (~90 MB). Expected output:

```
Storage backend: S3
Downloading documents from s3://siagent-documents-yourorg/documents/ ...
  Downloading: WHO-Digital-Health.pdf
  Downloading: sscp/field-learning-pacific.pdf
  ...
Downloaded 45 documents from S3

Ingested N new chunks from X files.
Vector store now has TOTAL total chunks.
```

### 3h. Create the initial admin user

```bash
python -c "
from src.auth import add_user
add_user('admin', 'YourStrongPassword123!', role='admin')
print('Admin user created.')
"
```

---

## Step 4 — Create a systemd service

This keeps the app running and restarts it automatically on failure or reboot.

```bash
sudo nano /etc/systemd/system/siagent.service
```

Paste this content exactly:

```ini
[Unit]
Description=SI Assistant - Standards and Interoperability RAG Chatbot
After=network.target
Wants=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/siagent
Environment=PYTHONIOENCODING=utf-8
ExecStart=/opt/siagent/.venv/bin/streamlit run app.py \
    --server.port=8501 \
    --server.address=127.0.0.1 \
    --server.headless=true \
    --server.enableCORS=false \
    --server.enableXsrfProtection=true
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=siagent

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable siagent
sudo systemctl start siagent

# Verify it started cleanly (look for "Active: active (running)")
sudo systemctl status siagent

# See the startup logs
sudo journalctl -u siagent -n 50
```

The app is now running on http://127.0.0.1:8501 (internal only — not yet internet-accessible).

---

## Step 5 — Configure Nginx reverse proxy

```bash
sudo nano /etc/nginx/sites-available/siagent
```

Paste this (replace `siagent.yourorg.org` with your actual domain):

```nginx
server {
    listen 80;
    server_name siagent.yourorg.org;

    # Required for Let's Encrypt domain verification
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    # Redirect all HTTP to HTTPS
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    server_name siagent.yourorg.org;

    # SSL certs -- Certbot will fill these in automatically
    ssl_certificate     /etc/letsencrypt/live/siagent.yourorg.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/siagent.yourorg.org/privkey.pem;
    include             /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam         /etc/letsencrypt/ssl-dhparams.pem;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options SAMEORIGIN always;
    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;

    # Proxy to Streamlit (WebSocket support required)
    location / {
        proxy_pass         http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade    $http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host            $host;
        proxy_set_header   X-Real-IP       $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
}
```

Enable and test:

```bash
sudo ln -s /etc/nginx/sites-available/siagent /etc/nginx/sites-enabled/
sudo nginx -t            # must print "syntax is ok"
sudo systemctl reload nginx
```

---

## Step 6 — Issue SSL certificate

```bash
sudo certbot --nginx -d siagent.yourorg.org
```

Follow the prompts. Certbot edits the Nginx config automatically and sets up auto-renewal.

Test renewal works:

```bash
sudo certbot renew --dry-run
```

---

## Step 7 — Verify the deployment

1. Open https://siagent.yourorg.org in a browser. You should see the login page.
2. Log in with the admin credentials from Step 3g.
3. Ask a test question in the chat. You should get an answer with citations.
4. Open the admin panel (top of sidebar). Check that "Indexed chunks" shows a number greater than zero.
5. Check the browser padlock — the SSL certificate should show as valid.

---

## Updating the application after a code change

```bash
cd /opt/siagent
git pull origin main
source .venv/bin/activate
pip install -r requirements.txt   # only needed if requirements.txt changed
sudo systemctl restart siagent
sudo journalctl -u siagent -n 30  # watch for errors
```

---

## Adding new documents to the knowledge base

No SSH needed. Upload to S3 from your local machine or the AWS Console, then re-run ingestion on the server.

```bash
# Step 1 — Upload the new document to S3 (from your local machine)
aws s3 cp new-guide.pdf s3://siagent-documents-yourorg/documents/

# For an SSCP priority document:
aws s3 cp new-sscp-doc.pdf s3://siagent-documents-yourorg/documents/sscp/

# Step 2 — SSH to the server and re-run ingestion
ssh -i keypair.pem ubuntu@YOUR_ELASTIC_IP
cd /opt/siagent && source .venv/bin/activate
python -X utf8 scripts/run_ingestion.py
# Safe to run any time -- skips already-indexed files, only processes new ones

# No app restart needed -- ChromaDB is queried at request time
```

You can also upload files via the AWS S3 Console (drag and drop) if you prefer not to use the CLI.

---

## Running the evaluation benchmark

```bash
cd /opt/siagent
source .venv/bin/activate
python -X utf8 scripts/run_eval.py
# Scored report saved to reports/eval_TIMESTAMP.txt
```

---

## Optional: AWS Bedrock instead of Anthropic API

Bedrock keeps all traffic within AWS and removes the need for an Anthropic API key.

1. Enable Claude in Bedrock (AWS Console > Bedrock > Model access > request Claude 3.5 Sonnet).
2. Create an IAM role with this policy and attach it to your EC2 instance:
   ```json
   {
     "Effect": "Allow",
     "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
     "Resource": "arn:aws:bedrock:YOUR_REGION::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0"
   }
   ```
3. Update .env:
   ```
   LLM_MODEL=bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0
   # ANTHROPIC_API_KEY is not needed -- comment it out
   ```
4. Restart: `sudo systemctl restart siagent`

---

---

## Monitoring and logs

```bash
# Live app logs
sudo journalctl -u siagent -f

# Nginx access log
sudo tail -f /var/log/nginx/access.log

# Failed logins and security events
tail -f /data/security_log.jsonl

# Disk usage check (chroma_db is the main consumer)
df -h /data
du -sh /data/chroma_db
```

---

## Backup recommendations

| What                | Location                  | Frequency   | Method                              |
|---------------------|---------------------------|-------------|-------------------------------------|
| Source documents    | S3 bucket                 | Automatic   | S3 versioning or cross-region replication |
| Vector database     | /data/chroma_db (EBS)     | Weekly      | EBS snapshot -- fast to rebuild from S3  |
| User accounts       | /data/users.json (EBS)    | Daily       | EBS snapshot                        |
| Feedback log        | /data/feedback_log.jsonl  | Continuous  | EBS snapshot                        |
| Security log        | /data/security_log.jsonl  | Continuous  | EBS snapshot                        |

Enable S3 versioning on your document bucket (S3 > bucket > Properties > Versioning) to protect against accidental overwrites or deletions.

Enable automated EBS snapshots via AWS Data Lifecycle Manager (DLM) in the console -- takes 5 minutes to set up.

---

## Troubleshooting

| Symptom                             | Likely cause                    | Fix                                                     |
|-------------------------------------|---------------------------------|---------------------------------------------------------|
| App shows "Loading..." forever      | WebSocket not proxied correctly | Check Nginx Upgrade headers; restart nginx              |
| Every answer says "could not find"  | ChromaDB empty or wrong path    | Check CHROMA_DB_PATH in .env; re-run ingestion          |
| Login page loops or crashes         | users.json missing or corrupt   | Re-run Step 3g to recreate admin user                   |
| 502 Bad Gateway                     | Streamlit not running           | sudo systemctl status siagent; check journal            |
| Slow first response each session    | Embedding model loading         | Expected on t3.medium; use t3.large to reduce this      |
| SSL certificate error               | Cert expired or not issued      | sudo certbot renew && sudo systemctl reload nginx       |
| Disk full                           | Chroma DB or log growth         | df -h /data; extend EBS volume in AWS console           |
| Authentication error in app logs    | ANTHROPIC_API_KEY wrong or empty| Check .env; chmod 600 .env; sudo systemctl restart      |
