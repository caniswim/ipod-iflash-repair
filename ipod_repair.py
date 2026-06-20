#!/usr/bin/env python3
"""Repara a corrupcao de "first sector" do iPod iFlash clone (FC1307A).

O bug zera o setor 0 (MBR) e/ou o primeiro setor de partições no cold boot.
O MBR guarda a tabela de TODAS as partições; restaurá-lo traz todas de volta.
Este script faz backup do MBR + a regiao inicial de CADA particao e restaura
apenas o que estiver zerado -> nunca toca na FAT/dados. Seguro e idempotente.

  sudo ipod_repair.py save      # rodar com o iPod saudavel (e apos cada reformat)
  sudo ipod_repair.py restore   # rodar quando o iPod nao funcionar (padrao)
  sudo ipod_repair.py check     # read-only: imprime OK | CORRUPT | NOTFOUND
  sudo ipod_repair.py autofsck  # desmonta -> fsck.fat -a -w -> save (so se saudavel)
"""
import os, sys, re, glob, json, subprocess, time


def backup_dir():
    """Onde ficam mbr.bin/part*.bin/meta.json.

    Ordem: $IPOD_BK -> pasta do proprio script se ela tiver o backup (checkout) ->
    ~SUDO_USER/ipod-repair (caso instalado em /usr/local/sbin e rodado via sudo) ->
    pasta do script. Mantem o repo publicado portatil e o helper root-only funcional.
    """
    env = os.environ.get("IPOD_BK")
    if env:
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    if os.path.exists(os.path.join(here, "meta.json")):
        return here
    su = os.environ.get("SUDO_USER")
    if su:
        import pwd
        try:
            return os.path.join(pwd.getpwnam(su).pw_dir, "ipod-repair")
        except KeyError:
            pass
    return here


BK = backup_dir()
SS = 4096                  # setor logico (4Kn)
RAW_LEAD = 16 * SS         # 64 KiB de cabecalho p/ particoes nao-FAT (ex: firmware)


def find_ipod_disk():
    for d in glob.glob("/sys/block/sd*"):
        try:
            model = open(os.path.join(d, "device/model")).read().strip().lower()
        except OSError:
            continue
        if "ipod" in model:
            return "/dev/" + os.path.basename(d)
    return None


def list_partitions(disk):
    """[(indice, devpath, parttype_lower), ...]"""
    out = subprocess.run(["lsblk", "-rno", "NAME,TYPE,PARTTYPE", disk],
                         capture_output=True, text=True).stdout
    parts = []
    for line in out.splitlines():
        f = line.split()
        if len(f) >= 2 and f[1] == "part":
            ptype = f[2].lower() if len(f) >= 3 else ""
            m = re.search(r"(\d+)$", f[0])
            parts.append((int(m.group(1)) if m else 0, "/dev/" + f[0], ptype))
    return parts


def sysfs_start_bytes(part_name):
    """Offset absoluto da particao no disco (sysfs 'start' e sempre em setores de 512)."""
    return int(open(f"/sys/class/block/{part_name}/start").read().strip()) * 512


def read_at(path, off, n):
    with open(path, "rb") as f:
        f.seek(off)
        return f.read(n)


def is_zero(path, off=0, length=512):
    return read_at(path, off, length) == b"\x00" * length


def find_fs_vbr(part):
    """Offset do boot sector FAT32 + tamanho da regiao reservada (estatica)."""
    data = read_at(part, 0, 4 << 20)
    for m in re.finditer(rb"FAT32   ", data):
        v = m.start() - 82
        if v < 0 or data[v + 510:v + 512] != b"\x55\xaa":
            continue
        bps = int.from_bytes(data[v + 11:v + 13], "little") or SS
        reserved = int.from_bytes(data[v + 14:v + 16], "little")
        fat_off = v + reserved * bps
        if fat_off + 4 <= len(data) and data[fat_off:fat_off + 4] == b"\xf8\xff\xff\x0f":
            return v, bps, reserved
    return None


def chown_bk():
    """Garante que os backups pertencam ao dono do diretorio (e nao a root via pkexec/sudo)."""
    try:
        st = os.stat(BK)
    except OSError:
        return
    for fn in os.listdir(BK):
        if fn.endswith((".bin", ".json")):
            try:
                os.chown(os.path.join(BK, fn), st.st_uid, st.st_gid)
            except OSError:
                pass


def do_save():
    disk = find_ipod_disk()
    if not disk:
        sys.exit("iPod nao encontrado.")
    os.makedirs(BK, exist_ok=True)

    with open(f"{BK}/mbr.bin", "wb") as f:
        f.write(read_at(disk, 0, SS))
    print(f"MBR salvo de {disk}")

    regions = []
    for idx, dev, ptype in list_partitions(disk):
        pstart = sysfs_start_bytes(os.path.basename(dev))
        if ptype in ("0xb", "0xc"):                  # FAT32: salva a regiao reservada
            vbr = find_fs_vbr(dev)
            if vbr:
                off, bps, reserved = vbr
                length, kind = reserved * bps, "fat-reserved"
            else:
                off, length, kind = 0, RAW_LEAD, "fat-fallback"
        else:                                        # firmware/outras: 64 KiB iniciais
            off, length, kind = 0, RAW_LEAD, "raw"
        abs_off = pstart + off                        # offset absoluto no disco
        fn = f"part{idx}.bin"
        with open(f"{BK}/{fn}", "wb") as f:
            f.write(read_at(disk, abs_off, length))
        regions.append({"part": idx, "abs": abs_off, "len": length, "file": fn,
                        "kind": kind, "type": ptype})
        print(f"  part {idx} ({dev}, {ptype or 'sem tipo'}) -> {fn}: {length} bytes @ disco:{abs_off} [{kind}]")

    with open(f"{BK}/meta.json", "w") as f:
        json.dump({"disk_model_match": "ipod", "regions": regions}, f, indent=2)

    for old in ("databoot.bin", "vbr.bin"):          # remove backups do formato antigo
        try:
            os.remove(f"{BK}/{old}")
        except OSError:
            pass
    chown_bk()
    print("Backup atualizado em", BK)
    git_sync()


def git_sync():
    """Best-effort: commita e da push do backup p/ o remoto, para restaurar de
    qualquer maquina. Roda o git como o DONO do BK (usa as credenciais dele, nao
    do root) e nunca derruba o save se falhar. Desligar com IPOD_GIT_PUSH=0."""
    if os.environ.get("IPOD_GIT_PUSH", "1") == "0":
        return
    if not os.path.isdir(f"{BK}/.git"):
        return
    import pwd, datetime
    try:
        st = os.stat(BK)
        owner = pwd.getpwuid(st.st_uid).pw_name
    except (OSError, KeyError):
        return
    files = [f for f in ("mbr.bin", "meta.json") if os.path.exists(f"{BK}/{f}")]
    files += [os.path.basename(p) for p in glob.glob(f"{BK}/part*.bin")]
    if not files:
        return

    def g(*a):                                       # git como o dono, se estamos root
        pre = ["sudo", "-u", owner, "-H"] if (os.geteuid() == 0 and st.st_uid != 0) else []
        return subprocess.run(pre + ["git", *a], cwd=BK, capture_output=True, text=True)

    msg = "backup: auto-save " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c = g("commit", "-m", msg, "--", *files)         # commita so os arquivos de backup
    if c.returncode != 0:
        if "nothing to commit" in (c.stdout + c.stderr):
            print("GIT: backup ja commitado, nada a enviar")
        else:
            print("GIT: commit falhou:", (c.stderr or c.stdout).strip()[:200])
        return
    p = g("push")
    print("GIT: backup commitado e enviado ao remoto" if p.returncode == 0
          else "GIT: commitado local, push falhou (offline?): "
               + (p.stderr or p.stdout).strip()[:200])


def do_restore():
    disk = find_ipod_disk()
    if not disk:
        sys.exit("iPod nao encontrado.")
    if not os.path.exists(f"{BK}/mbr.bin") or not os.path.exists(f"{BK}/meta.json"):
        sys.exit(f"Sem backup em {BK}. Rode: sudo {sys.argv[0]} save")
    meta = json.load(open(f"{BK}/meta.json"))
    changed = False

    # Tudo via offset absoluto no DISCO -> nao depende do no da particao reaparecer.
    if is_zero(disk, 0, 512):
        print("[!] MBR zerado -> restaurando (traz TODAS as particoes de volta)")
        with open(f"{BK}/mbr.bin", "rb") as s, open(disk, "r+b") as d:
            d.write(s.read()); d.flush(); os.fsync(d.fileno())
        changed = True

    for r in meta.get("regions", []):
        abs_off = r.get("abs")
        if abs_off is None:
            print(f"  part {r['part']}: backup antigo sem offset absoluto, pulando (rode 'save')")
            continue
        if is_zero(disk, abs_off, 512):
            print(f"[!] inicio da part {r['part']} zerado -> restaurando (disco @ {abs_off}, {r['kind']})")
            with open(f"{BK}/{r['file']}", "rb") as s, open(disk, "r+b") as d:
                d.seek(abs_off); d.write(s.read()); d.flush(); os.fsync(d.fileno())
            changed = True

    if changed:                                  # releitura so no fim, p/ o SO ver tudo restaurado
        subprocess.run(["blockdev", "--rereadpt", disk], check=False)
        subprocess.run(["partprobe", disk], check=False)
        time.sleep(1)
    print("Reparo concluido." if changed else "Setores OK, nada a reparar.")


def do_check():
    """Read-only. Imprime OK | CORRUPT | NOTFOUND. Nao escreve NADA no disco."""
    disk = find_ipod_disk()
    if not disk:
        print("NOTFOUND")
        sys.exit(3)
    corrupt = is_zero(disk, 0, 512)                 # MBR zerado = bug do cold-boot
    meta_path = f"{BK}/meta.json"
    if os.path.exists(meta_path):
        for r in json.load(open(meta_path)).get("regions", []):
            ab = r.get("abs")
            if ab is not None and is_zero(disk, ab, 512):
                corrupt = True
    print("CORRUPT" if corrupt else "OK")
    sys.exit(1 if corrupt else 0)


def do_autofsck():
    """Desmonta as particoes FAT -> fsck.fat -a -w -> save (so se fsck < 4).

    Aborta sem mexer em nada se a particao nao desmontar (provavel sincronizacao
    em andamento). Nunca roda fsck num filesystem montado. Output parseavel.
    """
    disk = find_ipod_disk()
    if not disk:
        print("NOTFOUND")
        sys.exit(3)
    fats = [(i, dev) for i, dev, pt in list_partitions(disk) if pt in ("0xb", "0xc")]
    if not fats:
        print("NOFAT")
        sys.exit(4)

    for _, dev in fats:                              # desmonta o que estiver montado
        if dev in open("/proc/mounts").read():
            subprocess.run(["umount", dev], check=False)
    busy = [dev for _, dev in fats if dev in open("/proc/mounts").read()]
    if busy:                                         # nao desmontou -> NAO fscka (seguranca)
        print("BUSY", " ".join(busy))
        sys.exit(6)

    worst = 0
    for _, dev in fats:
        rc = subprocess.run(["fsck.fat", "-a", "-w", dev]).returncode
        print(f"FSCK {dev} rc={rc}")
        worst = max(worst, rc)

    if worst < 4:                                    # 0/1/2 = ok ou corrigido
        do_save()
        print("SAVED=1")
        sys.exit(0)
    print(f"SAVED=0 fsck_rc={worst} (erros nao corrigidos, backup NAO atualizado)")
    sys.exit(5)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "restore"
    if cmd == "save":
        do_save()
    elif cmd == "restore":
        do_restore()
    elif cmd == "check":
        do_check()
    elif cmd == "autofsck":
        do_autofsck()
    else:
        sys.exit(f"uso: {sys.argv[0]} [save|restore|check|autofsck]")
