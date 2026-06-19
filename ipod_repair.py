#!/usr/bin/env python3
"""Repara a corrupcao de "first sector" do iPod iFlash clone (FC1307A).

O bug zera o setor 0 (MBR) e/ou o primeiro setor de partições no cold boot.
O MBR guarda a tabela de TODAS as partições; restaurá-lo traz todas de volta.
Este script faz backup do MBR + a regiao inicial de CADA particao e restaura
apenas o que estiver zerado -> nunca toca na FAT/dados. Seguro e idempotente.

  sudo ipod_repair.py save      # rodar com o iPod saudavel (e apos cada reformat)
  sudo ipod_repair.py restore   # rodar quando o iPod nao funcionar (padrao)
"""
import os, sys, re, glob, json, subprocess, time

BK = os.path.dirname(os.path.abspath(__file__))   # backups ficam junto do script
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


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "restore"
    if cmd == "save":
        do_save()
    elif cmd == "restore":
        do_restore()
    else:
        sys.exit(f"uso: {sys.argv[0]} [save|restore]")
