> 🌐 Language: **English** (this file) · [Português](README.md)

# ipod-iflash-repair

Quick fix for the **"first sector"** corruption that affects iPods modded with
**iFlash clone adapters (FC1307A controller)**: on every cold boot the adapter
sometimes **zeroes sector 0** (the MBR and/or the partition's boot sector), and
the iPod stops being recognized / the partition no longer mounts.

This project **backs up the static sectors** (MBR + the start of each partition)
and **restores only what got zeroed**, with a single command. It **never touches
the FAT or your data** — safe and idempotent.

> ⚠️ This is a **workaround**. The real fix is to reflash the adapter firmware to
> a version without the bug (iFlash **v85 / LBA48**). Until then, this script keeps
> the iPod usable.

---

## The problem (why this happens)

iPod Classics with an iFlash clone adapter use the **FC1307A** controller. Firmware
revisions **1.2–1.4** have a known flaw: **on a cold boot (power fully cut and
restored) sector 0 of the disk is written with zeros.**

Typical symptoms:

- The iPod doesn't recognize the disk / won't boot.
- On a PC: `mount` fails with *"wrong fs type, bad superblock"*.
- `fsck.fat` complains: ***"Logical sector size is zero"*** (it reads the zeroed
  bytes-per-sector field).

### Why the sector size is 4096 bytes (4Kn)

The old firmware only speaks **LBA28**, which addresses at most 268,435,456 sectors:

| Sector size | Max capacity (LBA28) |
| ----------- | -------------------- |
| 512 B       | ~128 GB              |
| **4096 B**  | **~1 TB**            |

Using 4096-byte sectors is the trick that reaches large cards (200 GB+) within the
LBA28 limit. That's why these cards show up as **4Kn**.

The bug is at the **adapter level**: it happens regardless of the filesystem
(FAT/HFS) and of the iPod firmware (Apple stock or Rockbox).

---

## How it works

The MBR and boot sectors **don't change** when you add/remove music — only the FAT
table and directories change. So you can keep a copy of those sectors and restore
them as many times as needed.

- **`save`** — with the iPod healthy, it stores:
  - `mbr.bin` → disk sector 0 (the partition table for **all** partitions);
  - `part<N>.bin` → the start of **each** partition (FAT: reserved region; firmware/other: 64 KiB);
  - `meta.json` → the regions, with their **absolute on-disk offset**.
- **`restore`** — checks and, **only if zeroed**, restores the MBR and the start of
  each partition (all via absolute offsets, without relying on the partition node
  reappearing). Finally, it re-reads the partition table.

Safety properties:

1. **Only restores a zeroed sector** — never touches anything intact.
2. **Never touches the FAT/data** — only the static sectors.
3. **Idempotent** — run it as often as you like; adding music later still works.
4. **Auto-detects** the iPod by the `"iPod"` model in sysfs (immune to `sdX` changing).
5. **Covers any layout** — single partition or multi-partition (firmware + data).

---

## Requirements

- Linux, **Python 3**, and **root** (it reads/writes the raw block device).
- `dosfstools` optional (useful for the alternative backup-boot-sector recovery).

## Installation

```bash
git clone https://github.com/caniswim/ipod-iflash-repair.git
cd ipod-iflash-repair
chmod +x ipod_repair.py
```

Optional shortcut (`ipod` in your shell):

```bash
# bash (~/.bashrc):
alias ipod='sudo /path/to/ipod-iflash-repair/ipod_repair.py restore'
# fish (~/.config/fish/functions/ipod.fish):
function ipod; sudo /path/to/ipod-iflash-repair/ipod_repair.py restore $argv; end
```

## Usage

```bash
# 1) ONCE, with the iPod connected and working:
sudo ./ipod_repair.py save

# 2) When the iPod gets corrupted (won't mount / won't boot):
sudo ./ipod_repair.py restore      # or just:  ipod
```

> 🔁 **Re-run `save`** whenever you **reformat** or **restore via iTunes** (the
> layout/offsets change, and iTunes also changes the iPod's serial).

---

## ⚠️ About the backup files in this repository

The `mbr.bin`, `part1.bin` and `meta.json` files here are **specific to my card and
my formatting** (offsets, volume ID, partition table). They serve as an **example**
and as my personal backup.

**Do NOT restore my backups onto your iPod** — generate your own with
`sudo ./ipod_repair.py save`.

## Emergency recovery (if the backup is missing)

If the FAT partition's boot sector gets zeroed and you don't have `part<N>.bin`, you
can recover it from the **FAT32's own backup boot sector** (which lives at sector 6):
copy offset `partition+24576` to `partition+0`.

---

## Scope and limitations

- Fixes **exactly** the documented bug: zeroed sector 0 (MBR and/or boot sector).
- Does **not** recover other damage (corrupted FAT, overwritten data) — by design it
  never touches the FAT/data.
- **Rockbox note:** Rockbox's FAT driver tends to **corrupt writes** on 4Kn cards
  (panics like *"Dir entry not free"*, hangs in coverflow/database). Apple's **stock
  firmware does not** have this issue. If you want Rockbox on 4Kn, consider the
  v85/LBA48 firmware + a 512 B format.

## Disclaimer

This tool **writes directly to the block device**. Use at your own risk, always with
the correct device and the iPod unmounted. No warranty.

## License

[MIT](LICENSE)
