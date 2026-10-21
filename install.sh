#!/bin/bash
# Run on the Pi from inside the kidsbank folder:  bash install.sh
set -e
APP_DIR=/opt/kidsbank
USER_NAME=$(whoami)

sudo apt-get update
sudo apt-get install -y python3-pil fonts-dejavu-core

sudo mkdir -p "$APP_DIR"
sudo cp app.py "$APP_DIR/"
# let this user write to the USB printer without sudo
sudo usermod -aG lp "$USER_NAME"

sudo tee /etc/systemd/system/kidsbank.service >/dev/null <<EOF
[Unit]
Description=Kids Play Bank
After=network-online.target

[Service]
User=$USER_NAME
SupplementaryGroups=lp
Environment=PRINTER=tcp://192.168.1.123:9100
Environment=PAPER_DOTS=576
Environment="BANK_NAME=BANK OF FUN"
Environment=PORT=8080
ExecStart=/usr/bin/python3 $APP_DIR/app.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now kidsbank
echo
echo "Done! Open http://$(hostname).local:8080 on a phone or tablet."
