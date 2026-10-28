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

## Aktualizace pres GitHub

Novy release se sestavi a publikuje po pushi tagu ve formatu `vMAJOR.MINOR`, napr. `v1.4`. Workflow pouzije tag jako verzi balicku a zobrazenou verzi aplikace. Pred vytvorenim tagu commitni zmeny na GitHub.

```bash
git tag v1.4
git push origin v1.4
```

Na Pi spusti tento jediny prikaz pro stazeni a instalaci posledniho verejneho releasu:

```bash
curl -fsSL https://raw.githubusercontent.com/Machr458/rom.translator-gb/main/deploy/raspberry-pi/update-from-github.sh | sudo bash
```

Updater zachova databazi, prekladovou cache i ROM v `/var/lib/rom-translator` a restartuje ngrok sluzbu, pokud je nastavena. Aktualizaci lze overit pres `sudo systemctl status rom-translator` a log tunelu pres `sudo journalctl -u rom-translator-ngrok -n 50 --no-pager`.

## Kontrola sluzby

```bash
sudo systemctl status rom-translator
sudo journalctl -u rom-translator -n 50 --no-pager
```
