# Instalace na Raspberry Pi

Navod je pro Raspberry Pi 3B s 64bitovym Debianem 12. Aplikace bezi na portu `8081`, Mainsail zustava beze zmeny. SQLite databaze a ROM jsou v `/var/lib/rom-translator`.

## Prvni instalace

V terminalu projektu sestav frontend a vytvor verzovany archiv:

```bash
REACT_APP_BACKEND_URL= yarn --cwd frontend build
bash deploy/raspberry-pi/package.sh install
```

Skript vypise cestu k novemu souboru, napr. `deploy/raspberry-pi/rom-translator-install-v1.0-20261020-161500-1234.tar.gz`. Dodatkovy identifikator brani prepsani starsiho archivu.

Stahni vytvoreny archiv do pocitace. Pokud je v koreni disku C, posli ho na Pi z PowerShellu. Pouzij presne jmeno, ktere vypsal skript:

```powershell
scp C:\rom-translator-install-v1.0-20261020-161500-1234.tar.gz pi@192.168.0.120:/tmp/
```

Pripoj se k Pi a rozbal archiv. Ve vsech prikazech nahrad ukazkove jmeno skutecnym jmenem souboru:

```powershell
ssh pi@192.168.0.120
```

Pak v SSH terminalu na Pi:

```bash
tar -xzf /tmp/rom-translator-install-v1.0-20261020-161500-1234.tar.gz -C /home/pi
cd /home/pi/rom-translator
sudo bash deploy/raspberry-pi/install.sh
```

Po instalaci otevri `http://192.168.0.120:8081/`. Aplikace nema vlastni prihlasovani; port `8081` nepresmerovavej z internetu.

## Aktualizace

Po zmene aplikace vytvor novy archiv z terminalu projektu:

```bash
bash deploy/raspberry-pi/package.sh update
```

Skript vypise nove jedinecne jmeno, napr. `rom-translator-update-v1.0-20261020-161500-1234.tar.gz`. Prenes tento konkretni soubor stejne jako vyse:

```powershell
scp C:\rom-translator-update-v1.0-20261020-161500-1234.tar.gz pi@192.168.0.120:/tmp/
```

V SSH terminalu na Pi rozbal novy archiv a spust instalator:

```bash
tar -xzf /tmp/rom-translator-update-v1.0-20261020-161500-1234.tar.gz -C /home/pi
cd /home/pi/rom-translator
sudo bash deploy/raspberry-pi/install.sh
```

Instalator aplikaci restartuje. Databaze, prekladova cache a ROM zustavaji zachovane v `/var/lib/rom-translator`.

## Kontrola sluzby

```bash
sudo systemctl status rom-translator
sudo journalctl -u rom-translator -n 50 --no-pager
```
