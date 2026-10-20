# Instalace na Raspberry Pi

Tento navod je pro Raspberry Pi 3B s 64bitovym Debianem 12. Aplikace pobezi na portu `8081`, Mainsail zustane beze zmeny. SQLite databaze a ulozene ROM budou v `/var/lib/rom-translator`.

## Prvni instalace

### 1. Priprav balicek na pocitaci

Stahni soubor `rom-translator-pi.tar.gz` z projektu do pocitace. Pokud ho nemas pripraveny, sestav web v korenove slozce projektu:

```powershell
$env:REACT_APP_BACKEND_URL = ""
yarn --cwd frontend build
```

### 2. Posli soubor na Pi

Otevri PowerShell na pocitaci. Pokud je soubor ve slozce Stazene soubory, spust:

```powershell
scp "$HOME\Downloads\rom-translator-pi.tar.gz" pi@192.168.0.120:/tmp/
```

Pokud jsi ho ulozil primo na disk `C:`, pouzij misto toho:

```powershell
scp C:\rom-translator-pi.tar.gz pi@192.168.0.120:/tmp/
```

Pri vyzve zadej heslo k Pi primo do terminalu. Pri psani se znaky nezobrazuji, to je normalni.

### 3. Nainstaluj aplikaci

Pripoj se k Pi:

```powershell
ssh pi@192.168.0.120
```

Az uvidis radek zacinajici `pi@`, zadej na Pi tyto prikazy:

```bash
tar -xzf /tmp/rom-translator-pi.tar.gz -C /home/pi
cd /home/pi/rom-translator
sudo bash deploy/raspberry-pi/install.sh
```

Instalace muze trvat nekolik minut. Kdyz skonci, otevri na zarizeni ve stejne siti adresu:

```text
http://192.168.0.120:8081/
```

V nastaveni aplikace zadej API klic sveho poskytovatele AI. Aplikace nema vlastni prihlasovani; port `8081` nepresmerovavej z internetu.

## Budouci aktualizace

Pi samo zmeny z GitHubu nestahuje. Po zmene kodu je potreba pripravit novy soubor `rom-translator-pi.tar.gz` a zopakovat prenos a instalaci:

1. Posli novy balicek z pocitace prikazem `scp` uvedenym vyse.
2. Pripoj se pres SSH a spust:

```bash
tar -xzf /tmp/rom-translator-pi.tar.gz -C /home/pi
cd /home/pi/rom-translator
sudo bash deploy/raspberry-pi/install.sh
```

Instalator restartuje aplikaci. Databaze, cache prekladu a ulozene ROM zustanou zachovane v `/var/lib/rom-translator`.

## Kdyz aplikace nebezi

Na Pi zkontroluj stav sluzby:

```bash
sudo systemctl status rom-translator
```

Podrobnejsi chyby zobrazis:

```bash
sudo journalctl -u rom-translator -n 50 --no-pager
```
