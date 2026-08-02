# EbookDL - HexChat-Plugin für IRC-Ebook-Suche & Download

Automatisiert den Ablauf mit den "bookz"-Bots (z. B. `#bookz` auf
`irc.irchighway.net`):

1. `@search <begriff>` in den Channel senden
2. Ergebnis-ZIP per DCC empfangen, entpacken, Trefferliste parsen
3. Treffer in einer scrollbaren Liste mit Checkboxen anzeigen
4. Markierte Bücher nacheinander anfordern und per DCC empfangen
5. Fertige Dateien in den Zielordner verschieben (ZIPs optional entpacken)
6. Fortschritt von Anfragen und Downloads im Plugin-Fenster anzeigen

Lizenz: MIT (siehe LICENSE). Haftung: Bitte die Regeln des jeweiligen
IRC-Netzwerks und Channels respektieren (Netiquette-Vorgaben sind im
Plugin standardmäßig eingestellt und änderbar).

## Installation

Voraussetzungen (Linux):

    sudo apt-get install python3-gi gir1.2-gtk-2.0

Plugin installieren (Python-Skripte laden aus `addons/`, nicht `plugins/`):

    mkdir -p ~/.config/hexchat/addons
    cp ebookdl.py ~/.config/hexchat/addons/
    # oder als Symlink, wenn du im Repo weiterentwickeln willst:
    ln -s "$PWD/ebookdl.py" ~/.config/hexchat/addons/ebookdl.py

HexChat neu starten (oder `/py load /pfad/zu/ebookdl.py` im laufenden HexChat).
Fenster mit `/ebookdl` öffnen.

Windows:

- HexChat installieren (hexchat.github.io / GitHub Releases)
- `ebookdl.py` nach `%APPDATA%\HexChat\addons\` kopieren
- Die GUI (Fenster, Liste) benötigt PyGObject (`gi`) mit Gtk-2.0-Typelibs —
  unter Windows im HexChat-Installer in der Regel nicht enthalten. Ohne
  diese meldet das Plugin einen Hinweis; die Such-/Download-Logik
  (Hook-basiert) läuft trotzdem.
- HexChat neu starten, `/ebookdl` tippen

Hinweis: Der Zielordner (Standard `~/Downloads/ebooks` bzw.
`%USERPROFILE%\Downloads\ebooks`) ist in den Einstellungen änderbar.

## Bedienung

- **Kanal**: Feld oben im Fenster; leer = aktueller Kanal. Oder in den
  Einstellungen fest hinterlegen.
- **Suche**: Suchbegriff eingeben, Enter oder "Suche starten".
  Das Plugin sendet `@search <begriff>` in den Channel.
- **Treffer**: Die Liste zeigt Dateiname und Größe; Häkchen setzen,
  "Download starten" klicken.
- **Fortschritt**: Unterer Bereich zeigt Statuszeile, Fortschrittsbalken
  und ein Log mit Zeitstempel.

## Netiquette / Regeln (standardmäßig eingestellt)

- Pause zwischen zwei Anfragen: **10 s** (strikt eingehalten)
- Max. gleichzeitige Übertragungen: **2**
- Timeout pro Download: **300 s**
- Timeout für die Ergebnis-Datei: **180 s**
- DCC-Dateien werden während Suche/Download automatisch angenommen
  (`dcc_auto_recv` wird temporär auf 2 gesetzt und danach wieder
  zurückgesetzt). Alternativ in HexChat fest einstellen:
  Einstellungen → DCC → "Dateiübertragungen automatisch annehmen".

Alle Werte sind in den Einstellungen des Plugins änderbar
(Schaltfläche "Einstellungen").

## Konfiguration

Wird als `ebookdl.json` im HexChat-Konfigurationsordner gespeichert
(~/.config/hexchat/ebookdl.json):

| Schlüssel         | Bedeutung                                  | Standard                  |
|-------------------|--------------------------------------------|---------------------------|
| channel           | Ziel-Channel (leer = aktueller)            | ""                        |
| search_cmd        | Suchbefehl, `{query}` wird ersetzt         | "@search {query}"         |
| target_dir        | Zielordner für Downloads                   | ~/Downloads/ebooks        |
| delay             | Pause zwischen Anfragen (Sekunden)         | 10                        |
| max_concurrent    | max. parallele Übertragungen               | 2                         |
| timeout           | Timeout pro Download (Sekunden)            | 300                       |
| search_timeout    | Timeout bis zur Ergebnis-Datei (Sekunden)  | 180                       |
| unzip             | ZIPs nach dem Download entpacken           | true                      |
| auto_accept       | DCC automatisch annehmen während Betrieb   | true                      |

## Ablauf im Detail

**Suche**: `@search <begriff>` → der Bot schickt per DCC eine ZIP mit einer
Textdatei. Zeilen im Format:

    !artemis_serv 16d6770d2ba9 | 27 - The Last Hero - Graphic Novel.pdf ::INFO:: 49.78MB

**Download**: Für jedes markierte Buch wird der Teil vor `::INFO::` gesendet:

    !artemis_serv 16d6770d2ba9 | 27 - The Last Hero - Graphic Novel.pdf

Der Bot antwortet per DCC mit der Datei (meist ZIP, wird entpackt).

**Zuordnung**: Eingehende DCC-Dateien werden dem passenden Download
zugeordnet (Bot-Nickname aus der Anfrage, dann Dateinamen-Vergleich,
dann FIFO). Empfangene Dateien landen in `target_dir`.

## Tests

    python3 test_ebookdl.py

Testet Parsing, ZIP-Auswertung, Datei-Matching, Queue-Scheduling
(Pause/Limit) und den kompletten DCC-Datenfluss mit einem HexChat-Stub.

## Bekannte Grenzen

- Ergebnis-ZIPs werden nach dem Parsen automatisch gelöscht (der
  Such-Ergebnis-Puffer bleibt sauber).
- Falls der Bot die Datei unter stark abweichendem Namen sendet, greift
  die FIFO-Zuordnung (älteste offene Anfrage).
- GTK2-GUI: läuft in-process im GTK2 von HexChat. Auf Systemen ohne
  python3-gi/gir1.2-gtk-2.0 meldet das Plugin beim Öffnen des Fensters
  einen Hinweis.
- Das Gtk-2.0-Typelib von Ubuntu ist unvollständig: Einige Konstruktoren
  (Gtk.TreeView(model), Gtk.Dialog, Gtk.SpinButton, Gtk.FileChooserButton,
  Gtk.Table) nehmen keine Argumente oder sind kaputt. Das Plugin verwendet
  deshalb nur die funktionierenden Muster; die Einstellungen sind bewusst
  als einfache Eingabefelder gebaut (kein Gtk.Dialog, kein Datei-Browser,
  kein SpinButton). Der Zielordner-Pfad wird direkt eingetragen.
- Der Einstellungs-Dialog ist ein eigenes Fenster (kein modaler Dialog);
  "OK" speichert, "Abbrechen" oder Fenster schließen verwirft.

## Wichtige API-Erkenntnisse (HexChat-Python-Plugin)

- In Print-Hook-Callbacks beginnt das `word[]`-Array mit dem ERSTEN
  Argument des Events (`word[0]` = $1) - der Event-Name steht NICHT im
  Array. Beispiel 'DCC RECV Connect': `word = [nick, host, dateiname]`.
  (Im C-Plugin-API ist es anders; die Python-Bridge verschiebt.)
- Bei EMPFANGENEN Dateien feuert KEIN 'DCC Offer'-Event (das ist das
  Event für ausgehende Angebote). Eingehende Transfers melden 'DCC RECV
  Connect' (Transfer beginnt) und 'DCC RECV Complete' (fertig; word =
  [dateiname, zielpfad, nick, cps]).
- Autoload-Skripte (addons/) und per '/py load' geladene Skripte
  registrieren Hooks identisch; nach einem '/py reload' bleiben alte
  Fenster-Instanzen als "Zombies" mit weiterhin registrierten Hooks
  bestehen (GTK-Fenster halten die Plugin-Objekte am Leben). Sauberer
  Neustart oder unload+load vermeidet Verwirrung beim Testen.
