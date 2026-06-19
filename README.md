# ipod-iflash-repair

Conserto rápido da corrupção de **"first sector"** que afeta iPods modados com
adaptadores **iFlash clone (controlador FC1307A)**: a cada cold boot o adaptador
às vezes **zera o setor 0** (MBR e/ou o boot sector da partição), e o iPod deixa
de ser reconhecido / a partição não monta mais.

Este projeto faz **backup dos setores estáticos** (MBR + início de cada partição)
e **restaura só o que estiver zerado**, com um comando. Ele **nunca toca na FAT
nem nos seus dados** — é seguro e idempotente.

> ⚠️ É um **paliativo**. A cura definitiva é regravar o firmware do adaptador para
> uma versão sem o bug (iFlash **v85 / LBA48**). Enquanto isso, este script deixa
> o iPod utilizável.

---

## O problema (por que isso acontece)

iPods Classic com adaptador iFlash clone usam o controlador **FC1307A**. As
revisões de firmware **1.2–1.4** têm uma falha conhecida: **no cold boot
(energia totalmente cortada e religada) o setor 0 do disco é escrito com zeros**.

Sintomas típicos:

- O iPod não reconhece o disco / não boota.
- No PC: `mount` falha com *"wrong fs type, bad superblock"*.
- `fsck.fat` reclama: ***"Logical sector size is zero"*** (lê o campo de
  bytes-por-setor zerado).

### Detalhe: por que o setor é de 4096 bytes (4Kn)

O firmware antigo só fala **LBA28**, que endereça no máximo 268.435.456 setores:

| Tamanho do setor | Capacidade máxima (LBA28) |
| ---------------- | ------------------------- |
| 512 B            | ~128 GB                   |
| **4096 B**       | **~1 TB**                 |

Usar setores de 4096 B é o truque que permite alcançar cartões grandes (200 GB+)
dentro do limite do LBA28. Por isso esses cartões aparecem como **4Kn**.

O bug é a **nível do adaptador**: acontece independente do filesystem (FAT/HFS) e
da firmware do iPod (stock da Apple ou Rockbox).

---

## Como funciona

O MBR e os boot sectors **não mudam** quando você adiciona/remove música — só a
tabela FAT e os diretórios mudam. Então dá pra guardar uma cópia desses setores e
restaurá-los quantas vezes for preciso.

- **`save`** — com o iPod saudável, guarda:
  - `mbr.bin` → setor 0 do disco (tabela de **todas** as partições);
  - `part<N>.bin` → início de **cada** partição (FAT: região reservada; firmware/outras: 64 KiB);
  - `meta.json` → as regiões, com **offset absoluto no disco**.
- **`restore`** — verifica e, **só se estiver zerado**, restaura o MBR e o início
  de cada partição (tudo por offset absoluto, sem depender do nó da partição
  reaparecer). No fim, re-lê a tabela de partições.

Propriedades de segurança:

1. **Só restaura setor zerado** — não mexe em nada íntegro.
2. **Nunca toca na FAT/dados** — só os setores estáticos.
3. **Idempotente** — pode rodar à vontade; adicionar música depois continua valendo.
4. **Detecção automática** do iPod pelo modelo `"iPod"` no sysfs (imune a `sdX` mudar).
5. **Cobre qualquer layout** — partição única ou multi-partição (firmware + dados).

---

## Requisitos

- Linux, **Python 3**, e **root** (lê/escreve o block device cru).
- `dosfstools` opcional (útil pra recuperação alternativa via backup boot sector).

## Instalação

```bash
git clone https://github.com/caniswim/ipod-iflash-repair.git
cd ipod-iflash-repair
chmod +x ipod_repair.py
```

Atalho opcional (`ipod` no shell):

```bash
# bash (~/.bashrc):
alias ipod='sudo /caminho/para/ipod-iflash-repair/ipod_repair.py restore'
# fish (~/.config/fish/functions/ipod.fish):
function ipod; sudo /caminho/para/ipod-iflash-repair/ipod_repair.py restore $argv; end
```

## Uso

```bash
# 1) UMA vez, com o iPod conectado e funcionando:
sudo ./ipod_repair.py save

# 2) Quando o iPod corromper (não monta / não boota):
sudo ./ipod_repair.py restore      # ou só:  ipod
```

> 🔁 **Re-rode `save`** sempre que **reformatar** ou **restaurar pelo iTunes**
> (o layout/offsets mudam, e o iTunes também troca o serial do iPod).

---

## ⚠️ Sobre os arquivos de backup neste repositório

Os arquivos `mbr.bin`, `part1.bin` e `meta.json` aqui são **específicos do meu
cartão e da minha formatação** (offsets, volume ID, tabela de partição). Eles
servem de **exemplo** e como meu backup pessoal.

**NÃO restaure os meus backups no seu iPod** — gere os seus com `sudo ./ipod_repair.py save`.

## Recuperação de emergência (se o backup faltar)

Se o boot sector da partição FAT for zerado e você não tiver o `part<N>.bin`, dá
pra recuperar do **backup boot sector do próprio FAT32** (que fica no setor 6):
copie o offset `partição+24576` para `partição+0`.

---

## Escopo e limitações

- Conserta **exatamente** o bug documentado: setor 0 zerado (MBR e/ou boot sector).
- **Não** recupera outros danos (FAT corrompida, dados sobrescritos) — por desenho,
  ele nunca toca na FAT/dados.
- **Nota sobre Rockbox:** o driver FAT do Rockbox tende a **corromper a escrita**
  em cartões 4Kn (panics tipo *"Dir entry not free"*, travas no coverflow/database).
  A firmware **stock da Apple não tem** esse problema. Se for usar Rockbox no 4Kn,
  considere o firmware v85/LBA48 + formato de 512 B.

## Aviso

Esta ferramenta **escreve diretamente no block device**. Use por sua conta e risco,
sempre com o device certo e o iPod desmontado. Sem garantias.

## Licença

[MIT](LICENSE)
