# Instalace na Raspberry Pi

Navod je pro Raspberry Pi 3B s 64bitovym Debianem 12. Aplikace bezi na portu `8081`, Mainsail zustava beze zmeny. SQLite databaze a ROM jsou v `/var/lib/rom-translator`.

## Prvni instalace

V terminalu projektu vytvor archiv. Skript sestavi frontend se stejnou verzi jako archiv:

```bash
bash deploy/raspberry-pi/package.sh install
```

Skript vypise cestu k souboru `deploy/raspberry-pi/rom-translator-install-v1.2.tar.gz`. Verze je ulozena v `deploy/raspberry-pi/VERSION`.

Stahni vytvoreny archiv do pocitace. Pokud je v koreni disku C, posli ho na Pi z PowerShellu. Pouzij presne jmeno, ktere vypsal skript:

```powershell
scp C:\rom-translator-install-v1.2.tar.gz pi@192.168.0.120:/tmp/
```

Pripoj se k Pi a rozbal archiv. Ve vsech prikazech nahrad ukazkove jmeno skutecnym jmenem souboru:

```powershell
ssh pi@192.168.0.120
```

Pak v SSH terminalu na Pi:

```bash
tar -xzf /tmp/rom-translator-install-v1.2.tar.gz -C /home/pi
cd /home/pi/rom-translator
sudo bash deploy/raspberry-pi/install.sh
```

Po instalaci otevri `http://192.168.0.120:8081/`. Aplikace nema vlastni prihlasovani; port `8081` nepresmerovavej z internetu.

Pokud je ngrok nainstalovany a prihlaseny pod uzivatelem `pi`, instalator vytvori sluzbu `rom-translator-ngrok` a povoli jeji spusteni po restartu. Sluzba pouzije vychozi ngrok endpoint tohoto uctu a presmeri ho na port `8081`. Pokud uz ngrok bezi rucne, sluzba se zapne az po dalsim restartu, aby se nespustily dva tunely najednou.

Aplikace nema vlastni prihlasovani. Verejny ngrok odkaz proto muze pouzit kdokoli, kdo ho zna; nevystavuj ho trvale bez dalsi ochrany pristupu.

## Aktualizace

Po zmene aplikace vytvor update z terminalu projektu. Kazdy update automaticky zvysi minor verzi, napr. `1.2` na `1.3`, a stejnou verzi zobrazi v patičce aplikace:

```bash
bash deploy/raspberry-pi/package.sh update
```

Skript vypise napr. `deploy/raspberry-pi/rom-translator-update-v1.3.tar.gz`. Prenes tento soubor stejne jako vyse:

```powershell
scp C:\rom-translator-update-v1.3.tar.gz pi@192.168.0.120:/tmp/
```

V SSH terminalu na Pi rozbal novy archiv a spust instalator:

```bash
tar -xzf /tmp/rom-translator-update-v1.3.tar.gz -C /home/pi
cd /home/pi/rom-translator
sudo bash deploy/raspberry-pi/install.sh
```

Instalator aplikaci restartuje. Databaze, prekladova cache a ROM zustavaji zachovane v `/var/lib/rom-translator`.

Po aktualizaci muzes rucni tunel ukoncit pomoci `Ctrl+C` a spustit spravovanou sluzbu:

```bash
sudo systemctl start rom-translator-ngrok
sudo systemctl status rom-translator-ngrok
```

Stav tunelu po restartu Pi zkontroluj stejne. Logy jsou dostupne prikazem `sudo journalctl -u rom-translator-ngrok -n 50 --no-pager`.

## Kontrola sluzby

```bash
sudo systemctl status rom-translator
sudo journalctl -u rom-translator -n 50 --no-pager
```
