#!/usr/bin/env bash
set -euo pipefail

CREDENTIALS_FILE="${1:?Usage: setup.sh <path-to-credentials-file>}"
INSTALL_DIR="/opt/email-reader"
VENV="$INSTALL_DIR/venv"
SYSTEMD_DIR="/etc/systemd/system"
CONF_DIR="/etc/email-reader"
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Reading poll interval from database..."
POLL_INTERVAL=$(python3 - "$CREDENTIALS_FILE" <<'PYEOF'
import sys
import psycopg2
lines = open(sys.argv[1]).read().strip().splitlines()
host, port, user, password = [l.strip() for l in lines]
conn = psycopg2.connect(host=host, port=int(port), user=user,
                        password=password, dbname="mailpoller")
cur = conn.cursor()
cur.execute("SELECT value FROM parameters WHERE key = 'poll_interval_minutes'")
row = cur.fetchone()
print(row[0] if row else "30")
conn.close()
PYEOF
)

echo "Poll interval: ${POLL_INTERVAL} minutes"

# Create system user if it does not exist
id -u email-reader &>/dev/null || \
    useradd --system --no-create-home --shell /bin/false email-reader

# Create directories
mkdir -p "$INSTALL_DIR" "$CONF_DIR"

# Create venv and install package
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip --quiet
"$VENV/bin/pip" install -e "$REPO_DIR" --quiet
"$VENV/bin/playwright" install chromium

# Install credentials file (owner email-reader, mode 0600)
install -o email-reader -g email-reader -m 0600 \
    "$CREDENTIALS_FILE" "$CONF_DIR/credentials.txt"

# Install systemd units (substituting poll interval into timer)
sed "s/__POLL_INTERVAL__/${POLL_INTERVAL}/" \
    "$REPO_DIR/systemd/email-reader.timer" > "$SYSTEMD_DIR/email-reader.timer"
cp "$REPO_DIR/systemd/email-reader.service" "$SYSTEMD_DIR/email-reader.service"

# Enable and start
systemctl daemon-reload
systemctl enable email-reader.timer
systemctl start email-reader.timer

echo ""
echo "Installation complete."
systemctl status email-reader.timer --no-pager
