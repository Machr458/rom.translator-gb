# ROM Translator

## 1. Nainstaluj

Na počítači potřebuješ:

- Python 3.10 nebo novější
- Node.js 20 nebo novější
- Git

Stáhni projekt a otevři jeho složku v terminálu:

```bash
git clone https://github.com/Machr458/rom.translator-gb.git
cd rom.translator-gb
```

## 2. Spusť aplikaci

Na Windows otevři PowerShell ve složce projektu a spusť:

```powershell
powershell -ExecutionPolicy Bypass -File .\run-local.ps1
```

Na Linuxu nebo macOS spusť:

```bash
bash run-local.sh
```

Při prvním spuštění se doinstalují potřebné součásti. Nezavírej terminál, dokud aplikaci používáš.

## 3. Přelož ROM

1. Otevři [http://localhost:3000](http://localhost:3000).
2. Vyber soubor ROM a klikni na **Načíst ROM**.
3. Vyber cílový jazyk.
4. V nastavení AI vyber poskytovatele, vlož svůj API klíč, otestuj ho a ulož. Použití AI může být zpoplatněné.
5. Klikni na **Přeložit ROM**.
6. Po dokončení stáhni přeloženou ROM.

## 4. Vypni aplikaci

V terminálu, ve kterém aplikace běží, stiskni `Ctrl+C`.
