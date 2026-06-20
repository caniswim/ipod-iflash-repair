#!/usr/bin/env bash
# Instala a automacao de deteccao do iPod. Rode com sudo, fora de sincronizacao:
#   sudo ~/ipod-repair/install-watch.sh
# Parte privilegiada apenas. O servico de USUARIO e habilitado no fim (sem sudo).
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="${SUDO_USER:-$USER}"
USER_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"

if [[ $EUID -ne 0 ]]; then
  echo "Rode com sudo: sudo $0" >&2; exit 1
fi

# 1) Helper root-only (NOPASSWD so e seguro num arquivo que o usuario nao edita).
install -o root -g root -m 0755 "$SRC/ipod_repair.py" /usr/local/sbin/ipod_repair.py
echo "[ok] helper -> /usr/local/sbin/ipod_repair.py (root:root 0755)"

# 2) sudoers NOPASSWD, escopo restrito aos subcomandos do helper.
cat > /etc/sudoers.d/ipod <<EOF
$USER_NAME ALL=(root) NOPASSWD: /usr/local/sbin/ipod_repair.py check, /usr/local/sbin/ipod_repair.py restore, /usr/local/sbin/ipod_repair.py autofsck
EOF
chmod 0440 /etc/sudoers.d/ipod
visudo -cf /etc/sudoers.d/ipod >/dev/null && echo "[ok] sudoers /etc/sudoers.d/ipod valido"

# 3) Unit de usuario.
install -o "$USER_NAME" -g "$USER_NAME" -d "$USER_HOME/.config/systemd/user"
install -o "$USER_NAME" -g "$USER_NAME" -m 0644 \
  "$SRC/ipod-watch.service" "$USER_HOME/.config/systemd/user/ipod-watch.service"
echo "[ok] unit -> ~/.config/systemd/user/ipod-watch.service"

cat <<EOF

Instalacao privilegiada concluida. Agora, como SEU usuario (sem sudo):

  systemctl --user daemon-reload
  systemctl --user enable --now ipod-watch.service
  systemctl --user status ipod-watch.service   # deve ficar 'active (running)'

Se voce editar o ipod_repair.py no repo depois, rode este install de novo
para sincronizar a copia root-only em /usr/local/sbin.
EOF
