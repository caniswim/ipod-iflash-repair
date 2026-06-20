# Roadmap de melhorias — segurança e robustez

Análise de risco da ferramenta (`ipod_repair.py` + `ipod-watch.py` + sudoers NOPASSWD +
auto git push) e o que precisamos endurecer antes de confiar 100% na automação.

Itens marcados **[ ]** são pendentes; **[x]** já implementados.

---

## 🔴 Crítico

### [ ] 1. Identificação do dispositivo por `05ac:1261`, não por substring "ipod"
**Risco:** `find_ipod_disk()` casa qualquer `/sys/block/sd*` cujo `device/model` contenha
"ipod". O `restore` escreve MBR (4 KB) + região reservada (128 KB) como **root**. Um
enclosure genérico, pendrive ou dispositivo malicioso reportando model "iPod" pode ser
escrito por engano → no pior caso, gravação numa partição de sistema e **perda de dados**.

**Mitigação:**
- Casar por **USB VID:PID `05ac:1261`** (via `udevadm info` / sysfs `idVendor`/`idProduct`),
  não por substring de model.
- **Abortar se houver mais de um disco** casando (ambíguo).
- Confirmar que o device é USB/removível antes de qualquer escrita.

### [ ] 2. `restore` não deve confiar no offset `abs` do `meta.json`
**Risco:** o `restore` lê `abs` (offset absoluto) do `meta.json`, que vive em
`~/ipod-repair` (**gravável pelo usuário**). Com o NOPASSWD, um processo rodando como o
usuário pode forjar `meta.json` + `part*.bin` e obter **escrita root de bytes arbitrários
em offset arbitrário** do disco casado. Hoje confinado ao iPod, mas **combinado com o
risco nº1** (casar disco de sistema) vira escalonamento total.

**Mitigação:**
- Recalcular os offsets a partir da **tabela de partição viva**; só permitir escrita no
  **setor 0** e nos **inícios reais de partição** — nunca num offset arbitrário do JSON.
- Validar `len` (limites) e que `abs` cai dentro dos limites do disco.
- Considerar deixar `meta.json` / backups **root-only**.

---

## 🟠 Alto

### [ ] 3. Preview read-only antes do `fsck -a -w`
**Risco:** em FAT genuinamente danificada (e esse adaptador corrompe na escrita), o
`fsck.fat -a -w` "conserta" de forma destrutiva (trunca, apaga, move p/ `FOUND.000`). Um
"Sim" apressado no popup pode perder arquivos.

**Mitigação:**
- Rodar primeiro `fsck.fat -n` (read-only) e **mostrar no popup o que ele pretende mudar**;
  só então oferecer o `-a -w`.
- Manter o `--default-cancel` e avisar no texto que pode alterar/remover arquivos.

### [ ] 4. Fingerprint do disco no `meta.json`, exigido no auto-restore
**Risco:** o `restore` só escreve regiões **zeradas** (bom guard), mas (a) um backup
defasado pós-reformatação restauraria um MBR antigo com layout errado; (b) um cartão
**apagado de propósito** também tem setor 0 zerado → o daemon auto-restauraria por cima
enquanto o usuário reparticiona.

**Mitigação:**
- Gravar no `meta.json` um **fingerprint do disco** (tamanho total + assinatura).
- Auto-restore só quando: é o iPod (`05ac:1261`) **E** setor 0 zerado **E** fingerprint bate.

---

## 🟡 Médio

### [ ] 5. Corrida umount→fsck (TOCTOU)
O `autofsck` desmonta, checa BUSY, e fsck-a. O udisks pode **remontar** na janela entre o
check e o fsck → fsck num FS montado = corrupção.
**Mitigação:** `udevadm settle` + `sync`, re-checar montagem imediatamente antes de cada
fsck, inibir o automount do udisks durante a operação (ou `flock` no device).

### [ ] 6. Repo público + push automático = permanente e potencialmente vazante
Para este iPod (só FAT) o backup é metadado sem dado pessoal. Mas o caminho de fallback
`raw`/`fat-fallback` captura **64 KiB do início da partição**, que em outros layouts pode
conter **dados de arquivo**. Histórico git é **irreversível**.
**Mitigação:** preferir **repo privado** (clone/restore via gh auth continua funcionando);
ou recusar auto-push de blobs `raw`/`fallback` (só `fat-reserved`). Documentar que o
histórico é permanente.

### [ ] 7. Daemon bloqueia enquanto o popup está aberto
`handle()` roda no loop do `udevadm monitor`; o zenity é síncrono → se o usuário ignora o
popup, o daemon não processa outros eventos.
**Mitigação:** `zenity --timeout=60` e/ou rodar `handle()` numa thread.

---

## 🟢 Baixo

### [ ] 8. Confiança no repo ao "restaurar de qualquer máquina"
Restaurar = `git clone` + `sudo ./ipod_repair.py`. Se a conta/repo for comprometida,
roda-se código alheio como root.
**Mitigação:** clonar via SSH autenticado do próprio repo, revisar antes de rodar como
root, eventualmente assinar commits.

### [ ] 9. Premissa 4Kn fixa (`SS=4096`)
Quebra se o cartão for trocado por 512 B. Baixo impacto (leituras).
**Mitigação:** validar o sector size real do device em vez de assumir.

---

## Salvaguardas já existentes
- `restore` só escreve setores **zerados** (nunca sobrescreve dado não-zero).
- `autofsck` **aborta com BUSY** se não desmontar (proteção contra sync ativa).
- Regra "só `save` se saudável" (fsck confirma antes).
- Popup com **default-cancel**.
- Helper **root-only** em `/usr/local/sbin` (não editável sem senha).
- Git como **histórico de backups** (`git checkout` de um backup anterior se um `save`
  capturar estado ruim).

## Ordem de implementação sugerida
1 → 2 → 4 → 3 → 5 → (6 = tornar o repo privado).
