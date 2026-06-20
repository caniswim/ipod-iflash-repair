#!/usr/bin/env python3
"""Vigia o iPod iFlash e reage quando ele e conectado.

Roda como servico de USUARIO (systemctl --user) -> tem acesso a sessao grafica,
entao zenity/notify-send funcionam em Niri, Hyprland e XFCE sem gambiarra.

Fluxo ao detectar o iPod (USB 05ac:1261), com debounce p/ os varios eventos udev:
  - setor 0 corrompido (bug cold-boot) -> restore AUTOMATICO + notificacao
  - saudavel                            -> popup zenity: rodar fsck + backup?

Toda escrita em disco passa pelo helper root-only via 'sudo -n' (NOPASSWD).
O daemon em si NUNCA escreve no iPod.
"""
import os, sys, glob, time, shutil, subprocess

HELPER = "/usr/local/sbin/ipod_repair.py"
MATCH_MODEL_ID = "1261"      # ID_MODEL_ID do iPod (USB)
MATCH_VENDOR_ID = "05ac"     # Apple
DEBOUNCE = 20                # s entre acoes p/ um mesmo plug
SETTLE = 3                   # s p/ as particoes aparecerem apos o 'add' do disco


def env_fix():
    """Garante env minimo p/ zenity/notify-send em sessao Wayland."""
    rd = os.environ.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    os.environ.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={rd}/bus")
    if not os.environ.get("WAYLAND_DISPLAY"):
        socks = [s for s in sorted(glob.glob(os.path.join(rd, "wayland-*")))
                 if not s.endswith(".lock")]
        if socks:
            os.environ["WAYLAND_DISPLAY"] = os.path.basename(socks[0])


def notify(title, body, urgency="normal"):
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "-a", "iPod", "-u", urgency, title, body],
                       check=False)
    print(f"[notify:{urgency}] {title} -- {body}", flush=True)


def ask(title, body):
    """True se o usuario clicar Sim. Sem zenity -> nao age (False)."""
    if not shutil.which("zenity"):
        print("[warn] zenity ausente, pulando prompt", flush=True)
        return False
    r = subprocess.run(["zenity", "--question", "--title", title, "--text", body,
                        "--ok-label=Sim", "--cancel-label=Agora nao",
                        "--default-cancel"])
    return r.returncode == 0


def helper(*args):
    return subprocess.run(["sudo", "-n", HELPER, *args],
                          capture_output=True, text=True)


def ipod_fat_part():
    """/dev da 1a particao do iPod (p/ remontar via udisksctl)."""
    for d in glob.glob("/sys/block/sd*"):
        try:
            if "ipod" not in open(d + "/device/model").read().strip().lower():
                continue
        except OSError:
            continue
        base = os.path.basename(d)
        parts = sorted(glob.glob(f"/sys/block/{base}/{base}*"))
        if parts:
            return "/dev/" + os.path.basename(parts[0])
    return None


def remount():
    part = ipod_fat_part()
    if part and shutil.which("udisksctl"):
        subprocess.run(["udisksctl", "mount", "-b", part], check=False)


def handle():
    time.sleep(SETTLE)
    r = helper("check")
    out = (r.stdout or "").strip()
    if r.returncode == 1 or "CORRUPT" in out:
        notify("iPod: setor 0 corrompido",
               "Bug do cold-boot detectado. Restaurando do backup...", "critical")
        rr = helper("restore")
        tail = (rr.stdout or rr.stderr or "").strip().splitlines()[-1:] or ["restore concluido"]
        notify("iPod reparado", tail[0], "critical")
        return
    if "NOTFOUND" in out:
        return                                       # corrida; iPod ja sumiu
    # saudavel
    if not ask("iPod detectado",
               "Rodar verificacao (fsck) e atualizar o backup?\n\n"
               "O iPod sera desmontado por alguns segundos."):
        return
    notify("iPod", "Verificando (fsck) e salvando backup...")
    rr = helper("autofsck")
    body = (rr.stdout or rr.stderr or "").strip().splitlines()[-1:] or [""]
    if "BUSY" in (rr.stdout or ""):
        notify("iPod ocupado",
               "Nao foi possivel desmontar (sincronizando?). Nada foi alterado.", "critical")
        return
    remount()
    ok = rr.returncode == 0
    notify("iPod " + ("pronto" if ok else "atencao"),
           ("fsck + backup concluidos." if ok else body[0]),
           "normal" if ok else "critical")


def main():
    env_fix()
    mon = subprocess.Popen(
        ["stdbuf", "-oL", "udevadm", "monitor", "--udev",
         "--subsystem-match=block", "--property"],
        stdout=subprocess.PIPE, text=True)
    props, last = {}, 0.0
    for line in mon.stdout:
        line = line.rstrip("\n")
        if line == "":                               # fim de um evento
            if (props.get("ACTION") == "add"
                    and props.get("DEVTYPE") == "disk"
                    and props.get("ID_MODEL_ID") == MATCH_MODEL_ID
                    and props.get("ID_VENDOR_ID") == MATCH_VENDOR_ID):
                now = time.monotonic()
                if now - last > DEBOUNCE:
                    last = now
                    try:
                        handle()
                    except Exception as e:           # nunca derruba o daemon
                        notify("iPod watch: erro", str(e), "critical")
            props = {}
            continue
        if "=" in line and not line[0].isspace():
            k, _, v = line.partition("=")
            props[k] = v


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
