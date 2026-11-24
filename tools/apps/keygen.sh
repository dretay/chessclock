#!/bin/sh
# Make the Ed25519 key that signs apps, and add its public half to the keys the board trusts.
#   tools/apps/keygen.sh [--no-passphrase] [KEY]      (KEY default: ~/.config/licheepi-nano/module-signing.pem)
#
# The private key stays out of the repository (and is ignored there: *.pem); a passphrase protects it
# (OpenSSL asks for it, and again each time it signs). The public key goes into
# board/licheepi_nano/rootfs-overlay/etc/modules/trusted.keys: the base system, so a board trusts it
# once it's rebuilt and flashed (tools/build/build.sh, tools/board/flash_sd.sh). Keep a copy of the
# private key somewhere safe: apps it signs can only be updated with it, or after a new base system.
set -e
OPENSSL=${OPENSSL:-openssl}
"$OPENSSL" version | grep -q "^OpenSSL [3-9]" || { echo "needs OpenSSL 3.0 or newer (OPENSSL=... picks one); this is: $("$OPENSSL" version)"; exit 1; }
ENC=-aes-256-cbc
[ "$1" = --no-passphrase ] && { ENC=; shift; }
KEY=${1:-$HOME/.config/licheepi-nano/module-signing.pem}
TRUSTED=$(cd "$(dirname "$0")/../.." && pwd)/board/licheepi_nano/rootfs-overlay/etc/modules/trusted.keys
[ -e "$KEY" ] && { echo "$KEY exists already: not replacing it"; exit 1; }

mkdir -p "$(dirname "$KEY")"
(umask 077 && "$OPENSSL" genpkey -algorithm ed25519 $ENC -out "$KEY")
PUB=$("$OPENSSL" pkey -in "$KEY" -pubout -outform DER | tail -c 32 | od -An -v -tx1 | tr -d ' \n')
[ ${#PUB} = 64 ] || { echo "couldn't read the new key's public half"; exit 1; }
echo "$PUB $(whoami)@$(hostname -s) $(date +%Y-%m-%d)" >> "$TRUSTED"
echo "key: $KEY (back it up; never commit it)"
echo "public key ${PUB%"${PUB#????????????????}"}... added to $TRUSTED"
echo "sign with: tools/apps/pack.py NAME --key $KEY"
