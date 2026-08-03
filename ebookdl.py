# -*- coding: utf-8 -*-
"""
EbookDL - HexChat-Plugin: IRC-Ebook-Suche & Download-Automation
================================================================

Automatisiert den typischen "bookz"-Ablauf (z. B. irc.irchighway.net):

  1. "@search <begriff>" in den Channel senden
  2. Ergebnis-ZIP per DCC empfangen, entpacken, Trefferliste parsen
  3. Treffer in einer scrollbaren Liste mit Checkboxen anzeigen
  4. Markierte Bücher nacheinander anfordern (mit Pause & Limit,
     entsprechend der Netiquette) und per DCC empfangen
  5. Fertige Dateien in den konfigurierten Zielordner verschieben
     (ZIPs werden optional entpackt)
  6. Fortschritt von Anfragen und Downloads im Plugin-Fenster anzeigen

Abhängigkeiten:  hexchat (mit Python-Plugin), python3-gi, gir1.2-gtk-2.0
Plattform:       überall, wo HexChat mit Python-Plugin läuft (Linux bevorzugt)

Installation:  Datei nach ~/.config/hexchat/plugins/ebookdl.py kopieren
               (oder Symlink), HexChat neu starten, Fenster mit /ebookdl öffnen.
"""

__module_name__ = "EbookDL"
__module_version__ = "0.1.0"
__module_description__ = "IRC ebook search & download automation"

import hexchat
import os
import re
import sys
import json
import time
import shutil
import zipfile
import tarfile
import gzip
import bz2
import lzma
import subprocess
import threading
import queue

# -- Sprachunterstützung ------------------------------------------------------
# Die Sprache wird aus derselben Umgebung gelesen, die HexChat/gettext
# verwendet (LANGUAGE/LC_ALL/LC_MESSAGES/LANG) - das Plugin folgt damit
# automatisch der Sprache von HexChat. Unterstützt Deutsch und Englisch.

def detect_lang():
    for var in ('LANGUAGE', 'LC_ALL', 'LC_MESSAGES', 'LANG'):
        v = (os.environ.get(var) or '').lower()
        for part in v.split(':'):
            part = part.split('.')[0].split('_')[0]
            if part in ('de', 'deu', 'german'):
                return 'de'
            if part in ('en', 'eng'):
                return 'en'
    return 'en'


LANG = detect_lang()

_TR = {
    # Fenster, Labels, Buttons
    'win_title': ('EbookDL - IRC Ebook Suche', 'EbookDL - IRC Ebook Search'),
    'win_title_settings': ('EbookDL - Einstellungen', 'EbookDL - Settings'),
    'lbl_channel': ('Kanal:', 'Channel:'),
    'lbl_search': ('Suche:', 'Search:'),
    'btn_search': ('Suche starten', 'Start search'),
    'col_download': ('Download', 'Download'),
    'col_file': ('Datei', 'File'),
    'col_type': ('Typ', 'Type'),
    'col_size': ('Größe', 'Size'),
    'col_status': ('Status', 'Status'),
    'btn_all': ('Alle markieren', 'Select all'),
    'btn_none': ('Keine markieren', 'Select none'),
    'btn_dl': ('Download starten', 'Start download'),
    'btn_cancel': ('Wartende abbrechen', 'Cancel waiting'),
    'btn_settings': ('Einstellungen', 'Settings'),
    'status_ready': ('Bereit.', 'Ready.'),
    # Einstellungen
    'set_channel': ('Kanal (leer = aktueller):', 'Channel (empty = current):'),
    'set_search_cmd': ('Suchbefehl ({query}):', 'Search command ({query}):'),
    'set_target': ('Zielordner (Pfad eintragen):', 'Target folder (enter path):'),
    'set_delay': ('Pause zwischen Anfragen (s):', 'Delay between requests (s):'),
    'set_max': ('Max. parallele Downloads:', 'Max. parallel downloads:'),
    'set_timeout': ('Timeout pro Download (s):', 'Download timeout (s):'),
    'set_search_timeout': ('Timeout Suche (s):', 'Search timeout (s):'),
    'set_unzip': ('ZIP-Dateien nach dem Download entpacken',
                  'Unzip files after download'),
    'set_auto': ('DCC-Dateien während Suche/Download automatisch annehmen',
                 'Auto-accept DCC files during search/download'),
    'set_convert': ('Nach dem Download konvertieren (Calibre):',
                    'Convert after download (Calibre):'),
    'conv_off': ('Keine Konvertierung', 'No conversion'),
    'conv_epub': ('EPUB', 'EPUB'),
    'conv_mobi': ('MOBI', 'MOBI'),
    'conv_pdf': ('PDF', 'PDF'),
    'conv_missing': ('Calibre nicht gefunden - Konvertierung deaktiviert. '
                     'Installation: sudo apt install calibre',
                     'Calibre not found - conversion disabled. '
                     'Install with: sudo apt install calibre'),
    'log_convert_ok': ('Konvertiert nach %s (Calibre)',
                       'Converted to %s (Calibre)'),
    'log_convert_fail': ('Konvertierung fehlgeschlagen: %s',
                         'Conversion failed: %s'),
    'set_filter': ('Nur E-Books und Archive anzeigen (Bilder, OPF, NFO usw. ausblenden)',
                   'Show only ebooks and archives (hide images, OPF, NFO, etc.)'),
    'log_filtered': ('%d Nicht-E-Book-Datei(en) ausgeblendet',
                     '%d non-ebook file(s) hidden'),
    'log_copied': ('%d Zeile(n) kopiert', '%d row(s) copied'),
    'btn_ok': ('OK', 'OK'),
    'btn_cancel_short': ('Abbrechen', 'Cancel'),
    # Log-/Status-Meldungen
    'log_loaded': ('EbookDL geladen. Fenster mit /ebookdl öffnen.',
                   'EbookDL loaded. Open the window with /ebookdl.'),
    'log_unloaded': ('EbookDL entladen.', 'EbookDL unloaded.'),
    'log_config_error': ('EbookDL: Konfiguration konnte nicht gespeichert werden: %s',
                         'EbookDL: Could not save configuration: %s'),
    'log_no_channel': ('FEHLER: Kein Kanal. Bitte in einen Channel wechseln oder Kanal in den Einstellungen setzen.',
                       'ERROR: No channel. Join a channel or set one in the settings.'),
    'log_no_channel2': ('FEHLER: Kein Kanal gesetzt (Einstellungen oder aktueller Kanal).',
                        'ERROR: No channel set (settings or current channel).'),
    'log_no_channel_dl': ('FEHLER: Kein Kanal gesetzt.', 'ERROR: No channel set.'),
    'log_no_channel_for': ('FEHLER: Kein Kanal für "%s"', 'ERROR: No channel for "%s"'),
    'log_enter_query': ('Bitte Suchbegriff eingeben.', 'Please enter a search term.'),
    'log_search_running': ('Suche läuft bereits - bitte warten.',
                           'Search already running - please wait.'),
    'log_search_sent': ('Suche gesendet an %s: %s', 'Search sent to %s: %s'),
    'status_search_running': ('Suche läuft ...', 'Searching ...'),
    'log_result_received': ('Ergebnis-Datei wird empfangen: %s (von %s)',
                            'Result file being received: %s (from %s)'),
    'status_result_received': ('Ergebnis-Datei wird empfangen ...',
                               'Receiving result file ...'),
    'log_result_complete': ('Ergebnis-Datei komplett: %s', 'Result file complete: %s'),
    'status_parsing': ('Ergebnis wird ausgewertet ...', 'Parsing results ...'),
    'log_result_not_found': ('FEHLER: Empfangene Datei nicht gefunden: %s',
                             'ERROR: Received file not found: %s'),
    'status_result_error': ('Fehler bei Ergebnis-Datei', 'Error with result file'),
    'log_no_books': ('Keine Bücher markiert.', 'No books selected.'),
    'log_recv_started': ('Empfang gestartet: %s (von %s)', 'Receiving: %s (from %s)'),
    'log_zip_deleted': ('Ergebnis-ZIP gelöscht: %s', 'Result ZIP deleted: %s'),
    'log_zip_delete_warn': ('Warnung: Ergebnis-ZIP konnte nicht gelöscht werden: %s (%s)',
                            'Warning: could not delete result ZIP: %s (%s)'),
    'status_queued': ('%d Download(s) in Warteschlange', '%d download(s) queued'),
    'log_queued': ('%d Download(s) eingereiht (Kanal %s, max. %d parallel, %ds Pause).',
                   '%d download(s) queued (channel %s, max %d parallel, %ds delay).'),
    'log_cancelled': ('%d wartende Download(s) abgebrochen.',
                      '%d waiting download(s) cancelled.'),
    'status_cancelled': ('%d abgebrochen', '%d cancelled'),
    'log_dl_failed': ('Download fehlgeschlagen: %s (%s)', 'Download failed: %s (%s)'),
    'status_dl_failed': ('Download fehlgeschlagen', 'Download failed'),
    'log_dl_aborted': ('Download abgebrochen: %s', 'Download aborted: %s'),
    'log_dl_complete': ('Download komplett: %s', 'Download complete: %s'),
    'log_timeout_search': ('Timeout: Keine Ergebnis-Datei empfangen.',
                           'Timeout: No result file received.'),
    'status_search_timeout': ('Suche abgelaufen (Timeout)', 'Search timed out'),
    'log_sent': ('Angefragt (%s): %s', 'Requested (%s): %s'),
    'log_timeout_no_answer': ('Timeout: Keine Antwort für "%s"',
                              'Timeout: No answer for "%s"'),
    'log_timeout_stall': ('Timeout: Übertragung von "%s" hängt',
                          'Timeout: Transfer of "%s" stalled'),
    'log_results_parsed': ('Ergebnis ausgewertet (%s): %d Treffer',
                           'Results parsed (%s): %d hits'),
    'status_hits': ('%d Treffer - Bücher markieren und Download starten',
                    '%d hits - select books and start download'),
    'log_move_error': ('FEHLER bei %s: %s', 'ERROR with %s: %s'),
    'status_move_error': ('Fehler beim Verschieben', 'Error moving file'),
    'log_done': ('Fertig: %s (%s)', 'Done: %s (%s)'),
    'status_done': ('Fertig: %s', 'Done: %s'),
    'log_gui_missing': ('EbookDL: GUI-Bindings fehlen (%s). Bitte python3-gi und gir1.2-gtk-2.0 installieren.',
                        'EbookDL: GUI bindings missing (%s). Please install python3-gi and gir1.2-gtk-2.0.'),
    'log_settings_saved': ('Einstellungen gespeichert: Zielordner %s, %ds Pause, max. %d parallel',
                           'Settings saved: target folder %s, %ds delay, max %d parallel'),
    'log_settings_invalid': ('FEHLER: Ungültige Zahl in den Einstellungen - nicht gespeichert.',
                             'ERROR: Invalid number in settings - not saved.'),
    'guard_already': ('EbookDL: Läuft bereits (PID %s) - zweite Instanz wird ignoriert. '
                      'Zum Neuladen: /ebookdl-Fenster schließen, dann /py unload EbookDL '
                      'und erneut laden.',
                      'EbookDL: Already running (PID %s) - second instance ignored. '
                      'To reload: close the /ebookdl window, then /py unload EbookDL '
                      'and load again.'),
    # Parser/Worker-Hinweise
    'hinweis_no_txt': ('Keine Textdatei im ZIP gefunden: %s',
                       'No text file found in ZIP: %s'),
    'hinweis_n_txt': ('%d Textdatei(en) im ZIP', '%d text file(s) in ZIP'),
    'hinweis_direct': ('Direkte Textdatei', 'Direct text file'),
    'hinweis_saved': ('gespeichert als %s', 'saved as %s'),
    'hinweis_read': ('Datei konnte nicht gelesen werden: %s',
                     'Could not read file: %s'),
    'hinweis_extracted': ('entpackt nach %s', 'unzipped to %s'),
    'parse_error': ('Fehler beim Parsen: %s', 'Parse error: %s'),
    'reason_open': ('Datei konnte nicht geöffnet werden', 'Could not open file'),
    'err_not_found': ('Datei nicht gefunden: %s', 'File not found: %s'),
}

# Statusanzeige der Tabellenzeilen (interne Werte bleiben unverändert)
_STATE_DISPLAY = {
    'wartend': ('wartend', 'waiting'),
    'angefragt': ('angefragt', 'requested'),
    'empfange': ('empfange', 'receiving'),
    'fertig': ('fertig', 'done'),
    'Fehler': ('Fehler', 'error'),
    'Timeout': ('Timeout', 'timeout'),
    'abgebrochen': ('abgebrochen', 'cancelled'),
}


def t(key):
    """Übersetzte Zeichenkette für die aktive Sprache."""
    de, en = _TR[key]
    return de if LANG == 'de' else en


def t_state(status):
    """Statuswert für die Anzeige übersetzen (interne Werte unangetastet)."""
    if isinstance(status, str):
        for key, (de, en) in _STATE_DISPLAY.items():
            if status == key:
                return de if LANG == 'de' else en
            if status.startswith(key + ':'):
                return (de if LANG == 'de' else en) + status[len(key):]
    return status

# ---------------------------------------------------------------------------
# Pure Logik (ohne hexchat/GUI, damit testbar)
# ---------------------------------------------------------------------------

RE_INFO = re.compile(r'\s*::INFO::\s*(.*?)\s*$')


def parse_size(text):
    """'49.78MB' / '1.2GB' / '500KB' / '1234' -> Bytes (float)."""
    if not text:
        return 0.0
    m = re.match(r'^([\d.,]+)\s*([KMG]?B?)$', text.strip().upper())
    if not m:
        return 0.0
    try:
        value = float(m.group(1).replace(',', '.'))
    except ValueError:
        return 0.0
    unit = m.group(2)
    mult = {'': 1.0, 'B': 1.0, 'KB': 1024.0, 'MB': 1024.0 ** 2,
            'GB': 1024.0 ** 3, 'K': 1024.0, 'M': 1024.0 ** 2, 'G': 1024.0 ** 3}
    return value * mult.get(unit, 1.0)


def format_bytes(num):
    try:
        num = float(num)
    except (TypeError, ValueError):
        return '?'
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if num < 1024.0 or unit == 'TB':
            if unit == 'B':
                return '%d %s' % (num, unit)
            return '%.2f %s' % (num, unit)
        num /= 1024.0
    return '?'


def filetype_of(filename):
    """Dateityp (Endung) aus dem Dateinamen, z. B. 'PDF', 'EPUB', '-'."""
    ext = os.path.splitext(filename or '')[1].lstrip('.').lower()
    return ext.upper() if ext else '-'


def parse_result_line(line):
    """
    Eine Zeile aus der Ergebnisdatei parsen, z. B.:

      !artemis_serv 16d6770d2ba9 | 27 - The Last Hero - Graphic Novel.pdf ::INFO:: 49.78MB

    -> dict(request, filename, size, botnick, filetype) oder None.
    """
    line = line.strip()
    if not line.startswith('!'):
        return None
    if '::INFO::' not in line:
        return None
    left, _, right = line.partition('::INFO::')
    request = left.strip()
    size = right.strip()
    if not request:
        return None
    parts = request.split()
    if len(parts) < 2:
        return None
    botnick = parts[0][1:] if parts[0].startswith('!') else parts[0]
    filename = request.split('|', 1)[1].strip() if '|' in request else request
    return {
        'request': request,
        'filename': filename,
        'filetype': filetype_of(filename),
        'size': size,
        'botnick': botnick,
        'size_bytes': parse_size(size),
    }


def parse_results_text(text):
    """Alle gültigen Treffer-Zeilen aus einem Text extrahieren."""
    results = []
    seen = set()
    for line in text.splitlines():
        item = parse_result_line(line)
        if item and item['request'] not in seen:
            seen.add(item['request'])
            results.append(item)
    return results


def decode_text(data):
    for enc in ('utf-8', 'latin-1', 'cp1252'):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, ValueError):
            continue
    return data.decode('utf-8', errors='replace')


def parse_results_zip(path):
    """
    ZIP (oder TXT) mit den Suchergebnissen öffnen und alle Treffer parsen.
    Gibt (results, hinweis) zurück.
    """
    hinweis = None
    if zipfile.is_zipfile(path):
        texts = []
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            for name in names:
                low = name.lower()
                if low.endswith(('.txt', '.log', '.lst', '.out', '.dat')) \
                        and not low.endswith(('.nfo.txt',)):
                    try:
                        texts.append(decode_text(zf.read(name)))
                    except Exception:
                        continue
        if not texts:
            return [], t('hinweis_no_txt') % os.path.basename(path)
        hinweis = t('hinweis_n_txt') % len(texts)
        results = []
        for txt in texts:
            results.extend(parse_results_text(txt))
        return results, hinweis
    try:
        with open(path, 'rb') as fh:
            return parse_results_text(decode_text(fh.read())), t('hinweis_direct')
    except OSError as exc:
        return [], t('hinweis_read') % exc


def normalize_name(name):
    """Für Dateinamen-Vergleich: lowercase, nur alnum."""
    return re.sub(r'[^a-z0-9]', '', name.lower())


def nick_matches(a, b):
    """Vergleicht zwei Nicknamen (case-insensitiv, substring)."""
    a = a.lower().strip()
    b = b.lower().strip()
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) >= 4 and len(b) >= 4 and (a in b or b in a):
        return True
    return False


def name_matches(expected, actual):
    """Dateinamen-Vergleich: enthält einer den anderen (normalisiert)?"""
    e = normalize_name(expected)
    a = normalize_name(actual)
    if not e or not a:
        return False
    if len(e) < 8 or len(a) < 8:
        return e == a
    return e in a or a in e


def unique_path(directory, filename):
    """Kollisionsfreien Zielpfad bauen: name.txt, name (1).txt, ..."""
    base, ext = os.path.splitext(filename)
    candidate = os.path.join(directory, filename)
    n = 1
    while os.path.exists(candidate):
        candidate = os.path.join(directory, '%s (%d)%s' % (base, n, ext))
        n += 1
    return candidate


def move_to_target(src, target_dir, unzip):
    """
    Fertige DCC-Datei in den Zielordner verschieben (optional entpacken).

    Es werden NUR echte Archive entpackt (Erkennung über die Dateiendung):
    zip, 7z, rar, tar/tar.gz/tar.bz2/tar.xz/tgz, cab, iso, arj, lzh sowie
    einzeln komprimierte Dateien (gz, bz2, xz). E-Book-Formate wie EPUB
    (technisch eine ZIP-Datei) bleiben unangetastet.
    Gibt (finaler_pfad, hinweis) oder wirft OSError.
    """
    os.makedirs(target_dir, exist_ok=True)
    name = os.path.basename(src)
    low = name.lower()
    # Quelle liegt bereits im Zielordner (z. B. DCC-Ordner == Zielordner)?
    # Dann kollidiert die Datei nur mit sich selbst -> nicht umbenennen.
    same_dir = os.path.normcase(os.path.abspath(os.path.dirname(src))) == \
               os.path.normcase(os.path.abspath(target_dir))
    if unzip and _is_archive(name):
        if low.endswith(_SINGLE_COMPRESS_EXTS):
            try:
                dst = _decompress_single(src, target_dir)
                return dst, t('hinweis_saved') % dst
            except Exception:
                pass  # -> unten einfach verschieben
        else:
            base = _strip_archive_ext(name)
            subdir = None
            for i in range(1, 10000):
                cand = os.path.join(target_dir, base if i == 1 else '%s (%d)' % (base, i))
                if not os.path.exists(cand):
                    subdir = cand
                    break
            try:
                os.makedirs(subdir, exist_ok=True)
                if _extract_archive(src, subdir):
                    os.remove(src)
                    return subdir, t('hinweis_extracted') % subdir
            except Exception:
                pass  # Extraktion fehlgeschlagen -> Datei verschieben
    if same_dir:
        # Datei ist schon am richtigen Platz - keine Kollision mit sich selbst
        return src, t('hinweis_saved') % src
    dst = unique_path(target_dir, name)
    shutil.move(src, dst)
    return dst, t('hinweis_saved') % dst


# Nur diese Endungen gelten als "echte Archive" (EPUB/MOBI/AZW3 usw. NICHT)
ARCHIVE_EXTS = ('.zip', '.7z', '.rar', '.tar', '.tgz', '.txz', '.tbz2',
                '.tar.gz', '.tar.bz2', '.tar.xz', '.gz', '.bz2', '.xz', '.z',
                '.cab', '.iso', '.arj', '.lzh')

# Einzeln komprimierte Dateien (werden zu einer Datei dekomprimiert)
_SINGLE_COMPRESS_EXTS = ('.gz', '.bz2', '.xz', '.z')


def _is_archive(name):
    low = (name or '').lower()
    return low.endswith(ARCHIVE_EXTS)


def _strip_archive_ext(name):
    """Alle bekannten Archiv-Endungen abstreifen: 'Buch.tar.gz' -> 'Buch'."""
    low = name.lower()
    for ext in sorted(ARCHIVE_EXTS, key=len, reverse=True):
        if low.endswith(ext):
            return name[:-len(ext)]
    return os.path.splitext(name)[0]


def _extract_archive(src, subdir):
    """Archiv entpacken; True bei Erfolg. zip/tar nativ, Rest über 7z."""
    low = src.lower()
    if low.endswith('.zip'):
        with zipfile.ZipFile(src) as zf:
            zf.extractall(subdir)
        return True
    if low.endswith(('.tar', '.tgz', '.txz', '.tbz2',
                     '.tar.gz', '.tar.bz2', '.tar.xz')):
        with tarfile.open(src) as tf:
            tf.extractall(subdir)
        return True
    # 7z, rar, cab, iso, arj, lzh, ... -> externes p7zip
    sevenz = shutil.which('7z') or shutil.which('7za') or shutil.which('7zr')
    if not sevenz:
        return False
    rc = subprocess.call([sevenz, 'x', '-y', '-o%s' % subdir, src],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return rc == 0


def _decompress_single(src, target_dir):
    """gz/bz2/xz-Einzeldatei dekomprimieren; liefert den Zielpfad."""
    base = os.path.splitext(os.path.basename(src))[0]
    dst = unique_path(target_dir, base)
    low = src.lower()
    if low.endswith('.gz'):
        with gzip.open(src, 'rb') as fin, open(dst, 'wb') as fout:
            shutil.copyfileobj(fin, fout)
    elif low.endswith('.bz2'):
        with bz2.open(src, 'rb') as fin, open(dst, 'wb') as fout:
            shutil.copyfileobj(fin, fout)
    elif low.endswith('.xz'):
        with lzma.open(src, 'rb') as fin, open(dst, 'wb') as fout:
            shutil.copyfileobj(fin, fout)
    elif low.endswith('.z'):
        with lzma.open(src, 'rb') as fin, open(dst, 'wb') as fout:
            shutil.copyfileobj(fin, fout)
    else:
        raise ValueError('Unsupported compression: %s' % src)
    os.remove(src)
    return dst


# -- Konvertierung (Calibre) -------------------------------------------------

# E-Book-Endungen, die an Calibre durchgereicht werden können
EBOOK_EXTS = ('.epub', '.mobi', '.azw', '.azw3', '.lit', '.fb2', '.prc',
              '.pdb', '.pdf', '.djvu', '.txt', '.html', '.htm', '.rtf',
              '.doc', '.docx', '.odt')

# Zielformate der Konvertierungs-Einstellung (Index im ComboBox)
CONVERT_FORMATS = ['', 'epub', 'mobi', 'pdf']


def is_ebook_file(path):
    """Ist die Datei ein konvertierbares E-Book (kein Archiv)?"""
    return (path or '').lower().endswith(EBOOK_EXTS)


def is_book_file(filename):
    """E-Book ODER Archiv? (alles andere gilt als Nicht-E-Book-Datei)"""
    low = (filename or '').lower()
    return low.endswith(EBOOK_EXTS) or low.endswith(ARCHIVE_EXTS)


def filter_results(results, filter_on):
    """Nicht-E-Book-Dateien (Bilder, OPF, NFO usw.) optional ausblenden."""
    if not filter_on:
        return list(results)
    return [r for r in results if is_book_file(r.get('filename', ''))]


def copy_text_from_model(model, paths):
    """Dateinamen der ausgewählten Zeilen (Spalte 1) als Text, eine pro Zeile."""
    lines = []
    for path in paths:
        it = model.get_iter(path)
        if it is not None:
            lines.append(model.get_value(it, 1) or '')
    return '\n'.join(lines)


def calibre_available():
    return shutil.which('ebook-convert') is not None


def convert_ebook(src, target_format, ebook_convert=None):
    """E-Book mit Calibre (ebook-convert) konvertieren.
    Liefert den Zielpfad; wirft RuntimeError, wenn Calibre fehlt oder der
    Aufruf fehlschlägt."""
    exe = ebook_convert or shutil.which('ebook-convert')
    if not exe:
        raise RuntimeError(t('conv_missing'))
    dst = '%s.%s' % (os.path.splitext(src)[0], target_format)
    if os.path.normcase(os.path.abspath(dst)) == os.path.normcase(os.path.abspath(src)):
        return src  # Zielformat == Quellformat
    rc = subprocess.call([exe, src, dst],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if rc != 0:
        raise RuntimeError('ebook-convert rc=%d' % rc)
    return dst


# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    'channel': '',            # leer = aktueller Kanal verwenden
    'search_cmd': '@search {query}',
    'target_dir': os.path.join(os.path.expanduser('~'), 'Downloads', 'ebooks'),
    'delay': 10.0,            # Sekunden zwischen zwei Anfragen (Netiquette)
    'max_concurrent': 2,      # maximale parallel laufende Downloads
    'timeout': 300,           # Timeout pro Download (Sekunden)
    'search_timeout': 180,    # Timeout bis zur Ergebnis-Datei (Sekunden)
    'unzip': True,            # ZIPs nach dem Download entpacken
    'auto_accept': True,      # DCC während Suche/Download automatisch annehmen
    'convert_format': '',     # '' | epub | mobi | pdf (Calibre-Konvertierung)
    'filter_non_ebooks': True,  # Bilder/OPF/NFO usw. in der Trefferliste ausblenden
}

STATE_IDLE = 'idle'
STATE_SEARCHING = 'searching'

ST_WAIT = 'wartet'
ST_SENT = 'angefragt'
ST_RECV = 'empfange'
ST_DONE = 'fertig'
ST_ERR = 'Fehler'
ST_TOUT = 'Timeout'
ST_CANCEL = 'abgebrochen'


class Config(object):
    def __init__(self, configdir):
        self.path = os.path.join(configdir, 'ebookdl.json')
        self.data = dict(DEFAULT_CONFIG)
        self.load()

    def load(self):
        try:
            with open(self.path, 'r', encoding='utf-8') as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                self.data.update(loaded)
        except (OSError, ValueError):
            pass

    def save(self):
        try:
            with open(self.path, 'w', encoding='utf-8') as fh:
                json.dump(self.data, fh, indent=2, ensure_ascii=False)
        except OSError as exc:
            hexchat.prnt(t('log_config_error') % exc)

    def get(self, key):
        return self.data.get(key, DEFAULT_CONFIG[key])


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------

class EbookDLPlugin(object):
    def __init__(self):
        self.configdir = hexchat.get_info('configdir') or os.path.expanduser('~/.config/hexchat')
        self.config = Config(self.configdir)
        self.dcc_dir = hexchat.get_prefs('dcc_dir') or os.path.expanduser('~/Downloads')
        self.dcc_completed = hexchat.get_prefs('dcc_completed_dir') or self.dcc_dir

        self.state = STATE_IDLE
        self.search_started = 0.0
        self.pending_result = None      # erwartete Ergebnis-Datei

        self.downloads = {}             # request -> item
        self.queue = []                 # Requests in Warteschlange (Reihenfolge)
        self.next_send_ts = 0.0
        self.auto_accept_saved = None   # alter Wert von dcc_auto_recv

        self.ui_queue = queue.Queue()   # Worker -> Haupt-Thread
        self.results = []               # geparste Treffer (unabhängig vom Fenster)
        self.window = None
        self.settings_win = None
        self.model = None
        self.entry_search = None
        self.entry_channel = None
        self.log_buffer = None
        self.progress = None
        self.label_status = None
        self.conv_combo = None
        self.conv_hint = None
        self.tree = None
        self._copy_win = None
        self._copy_entry = None

        self.timer = hexchat.hook_timer(1000, self.on_timer)
        hexchat.hook_print('DCC RECV Connect', self.on_dcc_connect)
        hexchat.hook_print('DCC RECV Complete', self.on_dcc_complete)
        for ev in ('DCC RECV Failed', 'DCC RECV File Open Error',
                   'DCC Stall', 'DCC Timeout'):
            hexchat.hook_print(ev, self._make_failed_handler(ev))
        hexchat.hook_print('DCC RECV Abort', self.on_dcc_abort)
        hexchat.hook_command('ebookdl', self.on_cmd, help='/ebookdl - Ebook-Suche & Download-Fenster öffnen')
        hexchat.hook_unload(self.on_unload)
        self.log(t('log_loaded'))

    # -- kleine Helfer ------------------------------------------------------

    def log(self, text):
        hexchat.prnt('EbookDL: %s' % text)
        if self.log_buffer is not None:
            stamp = time.strftime('%H:%M:%S')
            self.log_buffer.insert(self.log_buffer.get_end_iter(),
                                   '[%s] %s\n' % (stamp, text))
            self.log_view.scroll_to_mark(self.log_buffer.get_insert(), 0.0, True, 0.0, 0.0)

    def set_status(self, text):
        if self.label_status is not None:
            self.label_status.set_text(text)

    def get_channel(self):
        ch = (self.config.get('channel') or '').strip()
        if not ch:
            ch = hexchat.get_info('channel') or ''
        return ch

    def send_msg(self, channel, text):
        if not channel:
            self.log(t('log_no_channel2'))
            return False
        hexchat.command('MSG %s %s' % (channel, text))
        return True

    # -- DCC-Auto-Accept -----------------------------------------------------

    def ensure_auto_accept(self, want):
        """dcc_auto_recv während des Betriebs auf 2 setzen (und später zurück)."""
        if not self.config.get('auto_accept'):
            return
        try:
            cur = hexchat.get_prefs('dcc_auto_recv')
        except Exception:
            return
        if want and cur != 2:
            if self.auto_accept_saved is None:
                self.auto_accept_saved = cur
            hexchat.command('/set dcc_auto_recv 2')
        elif not want and self.auto_accept_saved is not None:
            hexchat.command('/set dcc_auto_recv %s' % self.auto_accept_saved)
            self.auto_accept_saved = None

    # -- Suche ---------------------------------------------------------------

    def start_search(self, query):
        query = (query or '').strip()
        if not query:
            self.log(t('log_enter_query'))
            return
        if self.state == STATE_SEARCHING:
            self.log(t('log_search_running'))
            return
        channel = self.get_channel()
        if not channel:
            self.log(t('log_no_channel'))
            return
        cmd = self.config.get('search_cmd').format(query=query)
        self.state = STATE_SEARCHING
        self.search_started = time.time()
        self.pending_result = None
        self.ensure_auto_accept(True)
        self.clear_results()
        self.send_msg(channel, cmd)
        self.log(t('log_search_sent') % (channel, cmd))
        self.set_status(t('status_search_running'))

    def on_search_result_file(self, path):
        """Ergebnisdatei empfangen -> im Thread parsen."""
        def work():
            try:
                results, hinweis = parse_results_zip(path)
                self.ui_queue.put(('results', results, hinweis, path))
            except Exception as exc:
                self.ui_queue.put(('results', [], t('parse_error') % exc, path))
            finally:
                self._cleanup_result_file(path)
        threading.Thread(target=work, daemon=True).start()

    def _cleanup_result_file(self, path):
        """Ergebnis-ZIP nach dem Parsen löschen (best effort)."""
        try:
            if path and os.path.exists(path):
                os.remove(path)
                self.log(t('log_zip_deleted') % os.path.basename(path))
        except Exception as exc:
            self.log(t('log_zip_delete_warn')
                     % (os.path.basename(path) if path else path, exc))

    # -- Downloads -----------------------------------------------------------

    def start_downloads(self):
        rows = []
        if self.model is None:
            return
        it = self.model.get_iter_first()
        while it is not None:
            if self.model.get_value(it, 0):
                rows.append({
                    'request': self.model.get_value(it, 4),
                    'filename': self.model.get_value(it, 1),
                    'size': self.model.get_value(it, 3),
                    'botnick': self.model.get_value(it, 5),
                    'size_bytes': self.model.get_value(it, 7) or 0.0,
                })
            it = self.model.iter_next(it)
        if not rows:
            self.log(t('log_no_books'))
            return
        channel = self.get_channel()
        if not channel:
            self.log(t('log_no_channel_dl'))
            return
        added = 0
        for row in rows:
            req = row['request']
            if req in self.downloads:
                continue
            self.downloads[req] = {
                'request': req,
                'filename': row['filename'],
                'botnick': row['botnick'],
                'size_bytes': row['size_bytes'],
                'state': ST_WAIT,
                'sent_ts': 0.0,
                'offer_ts': 0.0,
                'dcc_name': None,
                'path': None,
                'error': None,
                'progress': 0.0,
            }
            self.queue.append(req)
            added += 1
            self.set_row_status(req, ST_WAIT)
        self.ensure_auto_accept(True)
        self.set_status(t('status_queued') % added)
        self.log(t('log_queued')
                 % (added, channel, self.config.get('max_concurrent'), int(self.config.get('delay'))))

    def cancel_queue(self):
        cancelled = 0
        for req in list(self.queue):
            if req in self.downloads and self.downloads[req]['state'] == ST_WAIT:
                self.downloads[req]['state'] = ST_CANCEL
                self.set_row_status(req, ST_CANCEL)
                cancelled += 1
        self.queue = [r for r in self.queue
                      if r not in self.downloads or self.downloads[r]['state'] != ST_CANCEL]
        self.log(t('log_cancelled') % cancelled)
        if cancelled:
            self.set_status(t('status_cancelled') % cancelled)

    def set_row_status(self, request, status):
        if self.model is None:
            return
        it = self.model.get_iter_first()
        while it is not None:
            if self.model.get_value(it, 4) == request:
                self.model.set_value(it, 6, t_state(status))
                return
            it = self.model.iter_next(it)

    def set_row_checked(self, request, checked):
        """Checkbox einer Zeile setzen (z. B. nach Download abwählen)."""
        if self.model is None:
            return
        it = self.model.get_iter_first()
        while it is not None:
            if self.model.get_value(it, 4) == request:
                self.model.set_value(it, 0, bool(checked))
                return
            it = self.model.iter_next(it)

    # -- DCC-Hooks (Haupt-Thread) --------------------------------------------
    #
    # WICHTIG (word[]-Layout): In der Python-API beginnt das word-Array bei
    # der Python-Bridge mit dem ERSTEN ARGUMENT des Events (word[0] = $1) -
    # der Event-Name steht NICHT in word[]. Verifiziert per Probe:
    #   'DCC RECV Connect'  -> word = [nick, host, dateiname]
    #   'DCC RECV Complete' -> word = [dateiname, zielpfad, nick, cps]
    # Außerdem: Bei EMPFANGENEN Dateien feuert KEIN "DCC Offer"-Event (das
    # ist das Event für ausgehende Angebote). Eingehende Transfers meldet
    # HexChat über "DCC RECV Connect" (Transfer beginnt) und
    # "DCC RECV Complete" (fertig).

    def on_dcc_connect(self, word, word_eol, userdata):
        nick = word[0] if len(word) > 0 else ''
        fname = word[2] if len(word) > 2 else ''
        # 1) Gehört der Transfer zu einem laufenden Download?
        req = self.match_download(nick, fname)
        if req:
            item = self.downloads[req]
            item['dcc_name'] = fname
            if item['state'] == ST_SENT:
                item['state'] = ST_RECV
                item['offer_ts'] = time.time()
                self.log(t('log_recv_started') % (item['filename'], nick))
                self.set_row_status(req, ST_RECV)
            return hexchat.EAT_NONE
        # 2) Sonst: erwartete Ergebnisdatei der Suche?
        if self.state == STATE_SEARCHING and self.pending_result is None:
            low = fname.lower()
            if low.endswith(('.zip', '.txt', '.log')):
                self.pending_result = {'filename': fname, 'nick': nick,
                                       'ts': time.time()}
                self.log(t('log_result_received') % (fname, nick))
                self.set_status(t('status_result_received'))
        return hexchat.EAT_NONE

    def on_dcc_complete(self, word, word_eol, userdata):
        fname = word[0] if len(word) > 0 else ''
        dest = word[1] if len(word) > 1 else ''
        nick = word[2] if len(word) > 2 else ''
        # Ergebnisdatei der Suche?
        if self.pending_result is not None:
            pr = self.pending_result
            if name_matches(pr['filename'], fname) or nick_matches(pr.get('nick', ''), nick):
                self.pending_result = None
                self.state = STATE_IDLE
                self.ensure_auto_accept(False)
                self.log(t('log_result_complete') % (dest or fname))
                self.set_status(t('status_parsing'))
                if dest and os.path.exists(dest):
                    self.on_search_result_file(dest)
                else:
                    self.log(t('log_result_not_found') % (dest or fname))
                    self.set_status(t('status_result_error'))
                return hexchat.EAT_NONE
        req = self.match_download(nick, fname)
        if not req:
            # Fallback: älteste noch laufende Anfrage
            req = self.oldest_active()
        if req:
            item = self.downloads[req]
            item['path'] = dest or fname
            self.finish_download(req, dest)
        return hexchat.EAT_NONE

    def _make_failed_handler(self, event_name):
        """Fabrik für die Fehler-Events (jedes hat ein anderes word[]-Layout)."""
        def handler(word, word_eol, userdata):
            nick, fname, reason = '', '', ''
            if event_name == 'DCC RECV Failed':
                # [dateiname, zieldatei, nick, fehler]
                fname = word[0] if len(word) > 0 else ''
                nick = word[2] if len(word) > 2 else ''
                reason = word[3] if len(word) > 3 else 'Übertragung fehlgeschlagen'
            elif event_name == 'DCC RECV File Open Error':
                # [dateiname, fehler]
                fname = word[0] if len(word) > 0 else ''
                reason = word[1] if len(word) > 1 else t('reason_open')
            else:  # DCC Stall / DCC Timeout: [typ, dateiname, nick]
                fname = word[1] if len(word) > 1 else ''
                nick = word[2] if len(word) > 2 else ''
                reason = event_name
            req = self.match_download(nick, fname) or self.oldest_active()
            if req:
                item = self.downloads[req]
                item['state'] = ST_ERR
                item['error'] = reason
                self.set_row_status(req, '%s: %s' % (ST_ERR, reason))
                self.log(t('log_dl_failed') % (item['filename'], reason))
                self.set_status(t('status_dl_failed'))
            return hexchat.EAT_NONE
        return handler

    def on_dcc_abort(self, word, word_eol, userdata):
        # DCC RECV Abort: [nick, dateiname]
        nick = word[0] if len(word) > 0 else ''
        fname = word[1] if len(word) > 1 else ''
        req = self.match_download(nick, fname) or self.oldest_active()
        if req:
            item = self.downloads[req]
            item['state'] = ST_ERR
            item['error'] = 'abgebrochen'
            self.set_row_status(req, ST_ERR)
            self.log(t('log_dl_aborted') % item['filename'])
        return hexchat.EAT_NONE

    # -- Zuordnung DCC -> Download -------------------------------------------

    def match_download(self, nick, fname):
        """Passenden Download finden: Nick, dann Dateiname, dann FIFO."""
        # 1) Nick des Bots
        for req, item in self.downloads.items():
            if item['state'] in (ST_SENT, ST_RECV) and item.get('botnick'):
                if nick_matches(item['botnick'], nick):
                    return req
        # 2) Dateiname
        for req, item in self.downloads.items():
            if item['state'] in (ST_SENT, ST_RECV) and item.get('filename') and fname:
                if name_matches(item['filename'], fname):
                    return req
        # 3) FIFO (älteste aktive Anfrage)
        return self.oldest_active()

    def oldest_active(self):
        best = None
        best_ts = None
        for req, item in self.downloads.items():
            if item['state'] in (ST_SENT, ST_RECV):
                ts = item.get('sent_ts') or 0.0
                if best_ts is None or ts < best_ts:
                    best = req
                    best_ts = ts
        return best

    # -- Abschluss eines Downloads -------------------------------------------

    def finish_download(self, req, src):
        item = self.downloads[req]
        if not src or not os.path.exists(src):
            item['state'] = ST_ERR
            item['error'] = t('err_not_found') % (src or '?')
            self.set_row_status(req, ST_ERR)
            self.log('FEHLER: %s' % item['error'])
            return
        item['state'] = ST_DONE
        self.set_row_status(req, ST_DONE)
        self.log(t('log_dl_complete') % item['filename'])

        def work():
            try:
                final, hinweis = move_to_target(src, self.config.get('target_dir'),
                                                self.config.get('unzip'))
                # Optionale Konvertierung (Calibre) nach dem Verschieben
                fmt = self.config.get('convert_format')
                if fmt and final and os.path.isfile(final) and is_ebook_file(final):
                    try:
                        conv = convert_ebook(final, fmt)
                        if conv != final:
                            final = conv
                            hinweis = '%s | %s' % (hinweis,
                                                   t('log_convert_ok') % fmt.upper())
                    except Exception as exc:
                        hinweis = '%s | %s' % (hinweis, t('log_convert_fail') % exc)
                self.ui_queue.put(('moved', req, final, hinweis, None))
            except Exception as exc:
                self.ui_queue.put(('moved', req, None, None, str(exc)))
        threading.Thread(target=work, daemon=True).start()

    # -- Timer (1 s Takt, Haupt-Thread) ---------------------------------------

    def on_timer(self, userdata):
        # Worker-Ergebnisse übernehmen
        try:
            while True:
                msg = self.ui_queue.get_nowait()
                self.handle_ui_msg(msg)
        except queue.Empty:
            pass

        now = time.time()

        # Such-Timeout
        if self.state == STATE_SEARCHING and \
                now - self.search_started > self.config.get('search_timeout'):
            self.log(t('log_timeout_search'))
            self.state = STATE_IDLE
            self.pending_result = None
            self.ensure_auto_accept(False)
            self.set_status(t('status_search_timeout'))

        # Downloads: neue Anfragen senden (Netiquette: Pause + Limit)
        # Es wird höchstens EINE Anfrage pro Takt gesendet; der Abstand
        # zwischen zwei Anfragen ist durch 'delay' strikt begrenzt, und es
        # dürfen nie mehr als 'max_concurrent' Übertragungen gleichzeitig
        # laufen (angefragt oder empfangen).
        limit = int(self.config.get('max_concurrent'))
        inflight = sum(1 for it in self.downloads.values()
                       if it['state'] in (ST_SENT, ST_RECV))
        if self.queue and inflight < limit and now >= self.next_send_ts:
            req = self.queue.pop(0)
            item = self.downloads.get(req)
            if item is None or item['state'] == ST_CANCEL:
                pass  # übersprungen, wird nicht gesendet
            elif not self.get_channel():
                item['state'] = ST_ERR
                item['error'] = 'kein Kanal'
                self.set_row_status(req, ST_ERR)
                self.log(t('log_no_channel_for') % item['filename'])
            else:
                channel = self.get_channel()
                hexchat.command('MSG %s %s' % (channel, item['request']))
                item['state'] = ST_SENT
                item['sent_ts'] = now
                self.set_row_status(req, ST_SENT)
                self.log(t('log_sent') % (channel, item['filename']))
                self.next_send_ts = now + float(self.config.get('delay'))

        # Timeouts pro Download
        for req, item in self.downloads.items():
            if item['state'] == ST_SENT and now - item['sent_ts'] > self.config.get('timeout'):
                item['state'] = ST_TOUT
                self.set_row_status(req, ST_TOUT)
                self.log(t('log_timeout_no_answer') % item['filename'])
            elif item['state'] == ST_RECV and item.get('offer_ts') and \
                    now - item['offer_ts'] > self.config.get('timeout'):
                item['state'] = ST_TOUT
                self.set_row_status(req, ST_TOUT)
                self.log(t('log_timeout_stall') % item['filename'])

        # Fortschritt der laufenden Übertragungen
        self.update_progress()

        # Auto-Accept wieder abschalten, wenn nichts mehr läuft
        busy = self.state == STATE_SEARCHING or \
            any(d['state'] in (ST_SENT, ST_RECV) for d in self.downloads.values())
        if not busy:
            self.ensure_auto_accept(False)

        return True

    def update_progress(self):
        if self.progress is None:
            return
        total = 0.0
        got = 0.0
        label = ''
        for item in self.downloads.values():
            if item['state'] != ST_RECV:
                continue
            fname = item.get('dcc_name') or item['filename']
            path = os.path.join(self.dcc_dir, fname) if fname else None
            size = 0
            if path and os.path.exists(path):
                try:
                    size = os.path.getsize(path)
                except OSError:
                    size = 0
            exp = item.get('size_bytes') or 0
            total += exp or 1
            got += min(size, exp) if exp else size
            label = '%s - %s von %s' % (item['filename'], format_bytes(size),
                                        format_bytes(exp) if exp else '?')
        if total > 0:
            self.progress.set_fraction(min(1.0, got / total))
        else:
            self.progress.set_fraction(0.0)
        self.progress.set_text(label)
        self.progress.set_visible(bool(label))

    # -- UI-Nachrichten aus Workern -------------------------------------------

    def handle_ui_msg(self, msg):
        kind = msg[0]
        if kind == 'results':
            _, results, hinweis, path = msg
            shown = filter_results(results, self.config.get('filter_non_ebooks'))
            hidden = len(results) - len(shown)
            if hidden > 0:
                self.log('%s | %s' % (t('log_results_parsed') % (hinweis, len(results)),
                                      t('log_filtered') % hidden))
            else:
                self.log(t('log_results_parsed') % (hinweis, len(results)))
            self.results = list(results)
            if self.model is not None:
                self.model.clear()
                for r in shown:
                    self.model.append([False, r['filename'],
                                       r.get('filetype', filetype_of(r['filename'])),
                                       r['size'], r['request'], r['botnick'], '',
                                       float(r.get('size_bytes') or 0.0),
                                       r['filename'].lower()])
            self.set_status(t('status_hits') % len(shown))
        elif kind == 'moved':
            _, req, final, hinweis, error = msg
            item = self.downloads.get(req)
            if error:
                item['state'] = ST_ERR
                self.set_row_status(req, '%s: %s' % (ST_ERR, error))
                self.log(t('log_move_error') % (item['filename'], error))
                self.set_status(t('status_move_error'))
            else:
                item['path'] = final
                self.set_row_status(req, '%s: %s' % (ST_DONE, final))
                self.set_row_checked(req, False)
                self.log(t('log_done') % (item['filename'], hinweis))
                self.set_status(t('status_done') % os.path.basename(final))

    # -- GUI ------------------------------------------------------------------

    def open_window(self):
        if self.window is not None:
            try:
                self.window.present()
            except Exception:
                pass
            return
        try:
            import gi
            gi.require_version('Gtk', '2.0')
            from gi.repository import Gtk, Pango
        except Exception as exc:
            hexchat.prnt(t('log_gui_missing') % exc)
            return
        self.Gtk = Gtk

        win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        win.set_title(t('win_title'))
        win.set_default_size(940, 660)
        win.set_border_width(6)
        win.connect('delete-event', self.on_close)

        vbox = Gtk.VBox(homogeneous=False, spacing=4)

        # -- Kopfzeile: Kanal + Suche
        head = Gtk.HBox(homogeneous=False, spacing=4)
        lbl_ch = Gtk.Label()
        lbl_ch.set_text(t('lbl_channel'))
        self.entry_channel = Gtk.Entry()
        self.entry_channel.set_width_chars(14)
        self.entry_channel.set_text(self.config.get('channel'))
        lbl_q = Gtk.Label()
        lbl_q.set_text(t('lbl_search'))
        self.entry_search = Gtk.Entry()
        self.entry_search.set_width_chars(40)
        self.entry_search.connect('activate', lambda *a: self.start_search(self.entry_search.get_text()))
        btn_search = Gtk.Button()
        btn_search.set_label(t('btn_search'))
        btn_search.connect('clicked', lambda *a: self.start_search(self.entry_search.get_text()))
        head.pack_start(lbl_ch, False, False, 0)
        head.pack_start(self.entry_channel, False, False, 0)
        head.pack_start(lbl_q, False, False, 0)
        head.pack_start(self.entry_search, True, True, 0)
        head.pack_start(btn_search, False, False, 0)
        vbox.pack_start(head, False, False, 0)

        # -- Ergebnisliste
        # Spalten: 0 Check, 1 Datei, 2 Typ, 3 Größe, 4 Request, 5 Bot,
        #          6 Status, 7 Größe-Bytes (Sortierung), 8 Datei-Klein (Sortierung)
        self.model = Gtk.ListStore(bool, str, str, str, str, str, str, float, str)
        for r in filter_results(self.results, self.config.get('filter_non_ebooks')):
            self.model.append([False, r['filename'],
                               r.get('filetype', filetype_of(r['filename'])),
                               r['size'], r['request'], r['botnick'], '',
                               float(r.get('size_bytes') or 0.0),
                               r['filename'].lower()])
        tree = Gtk.TreeView()
        tree.set_model(self.model)
        tree.set_rules_hint(True)
        tree.set_headers_visible(True)
        tree.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)  # Mehrfach-Kopieren
        tree.connect('key-press-event', self.on_tree_keypress)
        tree.connect('button-press-event', self.on_tree_button)
        self.tree = tree
        rend_toggle = Gtk.CellRendererToggle()
        rend_toggle.set_property('activatable', True)
        rend_toggle.connect('toggled', self.on_toggle)
        col_toggle = Gtk.TreeViewColumn(t('col_download'), rend_toggle, active=0)
        col_toggle.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        col_toggle.set_fixed_width(70)
        tree.append_column(col_toggle)
        # FIXED-Sizing: Spalten bleiben im Fenster sichtbar, lange Namen/
        # Pfade werden mit "..." abgeschnitten statt die Spalte aufzuziehen.
        rend_name = Gtk.CellRendererText()
        rend_name.set_property('ellipsize', Pango.EllipsizeMode.END)
        col_name = Gtk.TreeViewColumn(t('col_file'), rend_name, text=1)
        col_name.set_sort_column_id(8)  # case-insensitive über Klein-Name
        col_name.set_resizable(True)    # linken Rand von "Typ" ziehbar -> Datei passt sich an
        col_name.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        col_name.set_fixed_width(380)
        col_name.set_min_width(80)
        tree.append_column(col_name)
        rend_type = Gtk.CellRendererText()
        rend_type.set_property('ellipsize', Pango.EllipsizeMode.END)
        col_type = Gtk.TreeViewColumn(t('col_type'), rend_type, text=2)
        col_type.set_sort_column_id(2)
        col_type.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        col_type.set_fixed_width(70)
        tree.append_column(col_type)
        rend_size = Gtk.CellRendererText()
        rend_size.set_property('ellipsize', Pango.EllipsizeMode.END)
        col_size = Gtk.TreeViewColumn(t('col_size'), rend_size, text=3)
        col_size.set_sort_column_id(7)  # numerisch nach Bytes
        col_size.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        col_size.set_fixed_width(90)
        tree.append_column(col_size)
        rend_status = Gtk.CellRendererText()
        rend_status.set_property('ellipsize', Pango.EllipsizeMode.END)
        col_status = Gtk.TreeViewColumn(t('col_status'), rend_status, text=6)
        col_status.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        col_status.set_fixed_width(230)
        tree.append_column(col_status)
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.add(tree)
        vbox.pack_start(sw, True, True, 0)

        # -- Aktionsleiste
        bar = Gtk.HBox(homogeneous=False, spacing=4)
        btn_all = Gtk.Button()
        btn_all.set_label(t('btn_all'))
        btn_all.connect('clicked', lambda *a: self.set_all_checked(True))
        btn_none = Gtk.Button()
        btn_none.set_label(t('btn_none'))
        btn_none.connect('clicked', lambda *a: self.set_all_checked(False))
        btn_dl = Gtk.Button()
        btn_dl.set_label(t('btn_dl'))
        btn_dl.connect('clicked', lambda *a: self.start_downloads())
        btn_cancel = Gtk.Button()
        btn_cancel.set_label(t('btn_cancel'))
        btn_cancel.connect('clicked', lambda *a: self.cancel_queue())
        btn_cfg = Gtk.Button()
        btn_cfg.set_label(t('btn_settings'))
        btn_cfg.connect('clicked', lambda *a: self.settings_dialog())
        bar.pack_start(btn_all, False, False, 0)
        bar.pack_start(btn_none, False, False, 0)
        bar.pack_start(btn_dl, True, True, 0)
        bar.pack_start(btn_cancel, False, False, 0)
        bar.pack_start(btn_cfg, False, False, 0)
        vbox.pack_start(bar, False, False, 0)

        # -- Fortschritt
        self.progress = Gtk.ProgressBar()
        self.progress.set_visible(False)
        vbox.pack_start(self.progress, False, False, 0)

        self.label_status = Gtk.Label()
        self.label_status.set_text(t('status_ready'))
        self.label_status.set_alignment(0.0, 0.5)
        vbox.pack_start(self.label_status, False, False, 0)

        sw_log = Gtk.ScrolledWindow()
        sw_log.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw_log.set_size_request(-1, 130)
        self.log_view = Gtk.TextView()
        self.log_view.set_editable(False)
        self.log_view.set_cursor_visible(False)
        self.log_view.modify_font(Pango.FontDescription('Monospace 9'))
        self.log_buffer = self.log_view.get_buffer()
        sw_log.add(self.log_view)
        vbox.pack_start(sw_log, False, False, 0)

        win.add(vbox)
        win.show_all()
        self.window = win
        self.log('Fenster geöffnet. Kanal: %s' % (self.get_channel() or '(keiner)'))

    def on_close(self, widget, event):
        # Einstellungen-Fenster (falls offen) mit schließen
        if self.settings_win is not None:
            self.settings_win.destroy()
            self.settings_win = None
        self.window.hide()
        return True  # Fenster nur verstecken, Plugin läuft weiter

    def on_toggle(self, renderer, path):
        if self.model is None:
            return
        it = self.model.get_iter(path)
        if it is not None:
            cur = self.model.get_value(it, 0)
            self.model.set_value(it, 0, not cur)

    # -- Kopieren aus der Ergebnisliste --------------------------------------

    def _ensure_copy_widget(self):
        """Unsichtbares Entry als Clipboard-Besitzer (Gtk2-Typelib: kein
        Gdk.Atom erzeugbar -> copy_clipboard() auf realisiertem Entry)."""
        if self._copy_entry is None:
            self._copy_win = self.Gtk.Window(type=self.Gtk.WindowType.POPUP)
            self._copy_win.set_default_size(1, 1)
            self._copy_entry = self.Gtk.Entry()
            self._copy_win.add(self._copy_entry)
            self._copy_win.realize()

    def copy_selection(self):
        """Ausgewählte Dateinamen (Spalte 1) in die Zwischenablage kopieren."""
        if self.model is None or self.tree is None:
            return
        # Typelib: get_selected_rows() ohne Argument (Model ist OUT-Parameter)
        paths = self.tree.get_selection().get_selected_rows()[1]
        text = copy_text_from_model(self.model, paths)
        if not text:
            return
        self._ensure_copy_widget()
        self._copy_entry.set_text(text)
        self._copy_entry.select_region(0, -1)
        self._copy_entry.copy_clipboard()
        self.log(t('log_copied') % len(text.split('\n')))

    def on_tree_keypress(self, widget, event):
        # Strg+C -> Auswahl kopieren (X11 ControlMask = 4)
        if event.keyval in (99, 67) and event.state & 4:
            self.copy_selection()
            return True
        return False

    def on_tree_button(self, widget, event):
        # Rechtsklick -> Auswahl sofort kopieren (Kontextmenue: popup fehlt
        # im Gtk2-Typelib; get_path_at_pos liefert immer None)
        if event.button == 3:
            self.copy_selection()
            return True
        return False

    def set_all_checked(self, value):
        if self.model is None:
            return
        it = self.model.get_iter_first()
        while it is not None:
            self.model.set_value(it, 0, value)
            it = self.model.iter_next(it)

    def clear_results(self):
        self.results = []
        if self.model is not None:
            self.model.clear()

    # -- Einstellungen --------------------------------------------------------
    #
    # Hinweis: bewusst OHNE Gtk.Dialog / Gtk.FileChooserDialog / SpinButton /
    # Adjustment gebaut. Das Gtk-2.0-Typelib von Ubuntu ist unvollständig
    # (Konstruktoren nehmen teils keine Argumente), und Gtk.Dialog +
    # dlg.run() hat HexChat beim Klick auf "Einstellungen" zum Absturz
    # gebracht (Segfault in der gi-Bridge). Alle hier verwendeten Widgets
    # sind dieselben, die im Hauptfenster nachweislich zur Laufzeit
    # funktionieren. Zahlenfelder sind einfache Entries mit Validierung.

    def settings_dialog(self):
        if self.settings_win is not None:
            self.settings_win.present()
            return
        Gtk = self.Gtk
        win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        win.set_title(t('win_title_settings'))
        win.set_default_size(520, -1)
        win.set_border_width(8)
        win.set_modal(True)  # blockiert das Hauptfenster, solange offen
        if self.window is not None:
            win.set_transient_for(self.window)
        win.connect('delete-event', self.on_settings_close)
        win.connect('destroy', self.on_settings_destroy)
        self.settings_win = win

        box = Gtk.VBox(homogeneous=False, spacing=6)

        def label(text):
            lbl = Gtk.Label()
            lbl.set_text(text)
            lbl.set_alignment(0.0, 0.5)
            return lbl

        def row(text, widget):
            hb = Gtk.HBox(homogeneous=False, spacing=8)
            hb.pack_start(label(text), False, False, 0)
            hb.pack_start(widget, True, True, 0)
            box.pack_start(hb, False, False, 2)

        e_channel = Gtk.Entry()
        e_channel.set_text(self.config.get('channel'))
        row(t('set_channel'), e_channel)

        e_search = Gtk.Entry()
        e_search.set_text(self.config.get('search_cmd'))
        row(t('set_search_cmd'), e_search)

        e_target = Gtk.Entry()
        e_target.set_text(self.config.get('target_dir'))
        row(t('set_target'), e_target)

        e_delay = Gtk.Entry()
        e_delay.set_text(str(int(self.config.get('delay'))))
        row(t('set_delay'), e_delay)

        e_max = Gtk.Entry()
        e_max.set_text(str(int(self.config.get('max_concurrent'))))
        row(t('set_max'), e_max)

        e_to = Gtk.Entry()
        e_to.set_text(str(int(self.config.get('timeout'))))
        row(t('set_timeout'), e_to)

        e_so = Gtk.Entry()
        e_so.set_text(str(int(self.config.get('search_timeout'))))
        row(t('set_search_timeout'), e_so)

        c_unzip = Gtk.CheckButton()
        c_unzip.set_label(t('set_unzip'))
        c_unzip.set_active(bool(self.config.get('unzip')))
        box.pack_start(c_unzip, False, False, 2)

        c_auto = Gtk.CheckButton()
        c_auto.set_label(t('set_auto'))
        c_auto.set_active(bool(self.config.get('auto_accept')))
        box.pack_start(c_auto, False, False, 2)

        c_filter = Gtk.CheckButton()
        c_filter.set_label(t('set_filter'))
        c_filter.set_active(bool(self.config.get('filter_non_ebooks')))
        box.pack_start(c_filter, False, False, 2)

        # Konvertierung (Calibre)
        lbl_conv = Gtk.Label()
        lbl_conv.set_text(t('set_convert'))
        lbl_conv.set_alignment(0.0, 0.5)
        box.pack_start(lbl_conv, False, False, 2)
        self.conv_combo = Gtk.ComboBoxText()
        for fmt in CONVERT_FORMATS:
            self.conv_combo.append_text(t('conv_' + (fmt or 'off')))
        try:
            self.conv_combo.set_active(CONVERT_FORMATS.index(self.config.get('convert_format')))
        except ValueError:
            self.conv_combo.set_active(0)
        box.pack_start(self.conv_combo, False, False, 2)
        self.conv_hint = Gtk.Label()
        self.conv_hint.set_alignment(0.0, 0.5)
        self.conv_hint.set_line_wrap(True)
        if calibre_available():
            self.conv_hint.set_text('')
        else:
            self.conv_hint.set_text(t('conv_missing'))
            self.conv_combo.set_sensitive(False)  # Optionen ausgrauen
        box.pack_start(self.conv_hint, False, False, 2)

        # -- OK / Abbrechen
        btnrow = Gtk.HBox(homogeneous=False, spacing=8)

        def on_ok(*a):
            try:
                self.config.data['channel'] = e_channel.get_text().strip()
                self.config.data['search_cmd'] = \
                    e_search.get_text().strip() or DEFAULT_CONFIG['search_cmd']
                td = e_target.get_text().strip()
                if td:
                    self.config.data['target_dir'] = td
                self.config.data['delay'] = float(e_delay.get_text().strip() or 10)
                self.config.data['max_concurrent'] = max(1, int(e_max.get_text().strip() or 2))
                self.config.data['timeout'] = float(e_to.get_text().strip() or 300)
                self.config.data['search_timeout'] = float(e_so.get_text().strip() or 180)
                self.config.data['unzip'] = c_unzip.get_active()
                self.config.data['auto_accept'] = c_auto.get_active()
                self.config.data['filter_non_ebooks'] = c_filter.get_active()
                if self.conv_combo is not None:
                    self.config.data['convert_format'] = CONVERT_FORMATS[self.conv_combo.get_active()]
                self.config.save()
                if self.entry_channel is not None:
                    self.entry_channel.set_text(self.config.get('channel'))
                self.log(t('log_settings_saved')
                         % (self.config.get('target_dir'), int(self.config.get('delay')),
                            self.config.get('max_concurrent')))
            except ValueError:
                self.log(t('log_settings_invalid'))
            win.destroy()

        def on_cancel(*a):
            win.destroy()

        btn_ok = Gtk.Button()
        btn_ok.set_label(t('btn_ok'))
        btn_ok.connect('clicked', on_ok)
        btn_cancel = Gtk.Button()
        btn_cancel.set_label(t('btn_cancel_short'))
        btn_cancel.connect('clicked', on_cancel)
        btnrow.pack_start(btn_ok, True, True, 0)
        btnrow.pack_start(btn_cancel, True, True, 0)
        box.pack_start(btnrow, False, False, 4)

        win.add(box)
        win.show_all()

    def on_settings_close(self, widget, event):
        widget.destroy()
        return True

    def on_settings_destroy(self, widget):
        if self.settings_win is widget:
            self.settings_win = None

    # -- Kommandos ------------------------------------------------------------

    def on_cmd(self, word, word_eol, userdata):
        self.open_window()
        return hexchat.EAT_ALL

    def on_unload(self, userdata):
        self.ensure_auto_accept(False)
        release_single_instance()
        hexchat.prnt(t('log_unloaded'))


# -- Einzelinstanz-Schutz -----------------------------------------------------
#
# Verhindert, dass das Plugin mehrfach geladen wird (Autoload + /py load +
# /py reload aus verschiedenen Pfaden erzeugen sonst mehrere Instanzen mit
# eigenen Fenstern, Hooks und Timern). Als Marker dienen die HexChat-
# Plugin-Prefs mit der PID des Besitzers; ein verwaister Marker
# (abgestürzte Instanz oder Neustart) wird erkannt und übernommen.
# Hinweis: Alle Python-Skripte teilen die Prefs des python-Plugins
# (addon_python.conf) - deshalb ein eindeutiger Key.

SINGLE_INSTANCE_KEY = 'ebookdl_running'


def acquire_single_instance():
    """True, wenn diese Instanz laufen darf (sonst: Meldung + False)."""
    try:
        pid = hexchat.get_pluginpref(SINGLE_INSTANCE_KEY)
        if pid is None:
            hexchat.set_pluginpref(SINGLE_INSTANCE_KEY, os.getpid())
            return True
        try:
            os.kill(int(pid), 0)  # lebt der Besitzer noch?
        except ProcessLookupError:
            # Marker verwaist (Prozess weg) -> übernehmen
            hexchat.set_pluginpref(SINGLE_INSTANCE_KEY, os.getpid())
            return True
        except (ValueError, TypeError):
            # kaputter Marker -> übernehmen
            hexchat.set_pluginpref(SINGLE_INSTANCE_KEY, os.getpid())
            return True
        except OSError:
            # z. B. EPERM: Prozess existiert, nur keine Rechte -> lebt -> blocken
            pass
        hexchat.prnt(t('guard_already') % pid)
        return False
    except Exception:
        # Ohne Plugin-Prefs (z. B. Test-Harness) kein Schutz, aber kein Bruch
        return True


def release_single_instance():
    """Marker entfernen, wenn er dieser Instanz gehört."""
    try:
        if hexchat.get_pluginpref(SINGLE_INSTANCE_KEY) == os.getpid():
            hexchat.del_pluginpref(SINGLE_INSTANCE_KEY)
    except Exception:
        pass


def main():
    if not acquire_single_instance():
        return
    EbookDLPlugin()


if __name__ == '__main__' or __module_name__:
    main()
