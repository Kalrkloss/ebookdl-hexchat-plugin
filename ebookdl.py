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
import threading
import queue

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
            return [], 'Keine Textdatei im ZIP gefunden: %s' % os.path.basename(path)
        hinweis = '%d Textdatei(en) im ZIP' % len(texts)
        results = []
        for t in texts:
            results.extend(parse_results_text(t))
        return results, hinweis
    try:
        with open(path, 'rb') as fh:
            return parse_results_text(decode_text(fh.read())), 'Direkte Textdatei'
    except OSError as exc:
        return [], 'Datei konnte nicht gelesen werden: %s' % exc


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
    Gibt (finaler_pfad, hinweis) oder wirft OSError.
    """
    os.makedirs(target_dir, exist_ok=True)
    name = os.path.basename(src)
    if unzip and zipfile.is_zipfile(src):
        base = os.path.splitext(name)[0]
        subdir = None
        for i in range(1, 10000):
            cand = os.path.join(target_dir, base if i == 1 else '%s (%d)' % (base, i))
            if not os.path.exists(cand):
                subdir = cand
                break
        os.makedirs(subdir, exist_ok=True)
        with zipfile.ZipFile(src) as zf:
            zf.extractall(subdir)
        os.remove(src)
        return subdir, 'entpackt nach %s' % subdir
    dst = unique_path(target_dir, name)
    shutil.move(src, dst)
    return dst, 'gespeichert als %s' % dst


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
            hexchat.prnt('EbookDL: Konfiguration konnte nicht gespeichert werden: %s' % exc)

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
        self.model = None
        self.entry_search = None
        self.entry_channel = None
        self.log_buffer = None
        self.progress = None
        self.label_status = None

        self.timer = hexchat.hook_timer(1000, self.on_timer)
        hexchat.hook_print('DCC RECV Connect', self.on_dcc_connect)
        hexchat.hook_print('DCC RECV Complete', self.on_dcc_complete)
        for ev in ('DCC RECV Failed', 'DCC RECV File Open Error',
                   'DCC Stall', 'DCC Timeout'):
            hexchat.hook_print(ev, self._make_failed_handler(ev))
        hexchat.hook_print('DCC RECV Abort', self.on_dcc_abort)
        hexchat.hook_command('ebookdl', self.on_cmd, help='/ebookdl - Ebook-Suche & Download-Fenster öffnen')
        hexchat.hook_unload(self.on_unload)
        self.log('EbookDL geladen. Fenster mit /ebookdl öffnen.')

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
            self.log('FEHLER: Kein Kanal gesetzt (Einstellungen oder aktueller Kanal).')
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
            self.log('Bitte Suchbegriff eingeben.')
            return
        if self.state == STATE_SEARCHING:
            self.log('Suche läuft bereits - bitte warten.')
            return
        channel = self.get_channel()
        if not channel:
            self.log('FEHLER: Kein Kanal. Bitte in einen Channel wechseln oder Kanal in den Einstellungen setzen.')
            return
        cmd = self.config.get('search_cmd').format(query=query)
        self.state = STATE_SEARCHING
        self.search_started = time.time()
        self.pending_result = None
        self.ensure_auto_accept(True)
        self.clear_results()
        self.send_msg(channel, cmd)
        self.log('Suche gesendet an %s: %s' % (channel, cmd))
        self.set_status('Suche läuft ...')

    def on_search_result_file(self, path):
        """Ergebnisdatei empfangen -> im Thread parsen."""
        def work():
            try:
                results, hinweis = parse_results_zip(path)
                self.ui_queue.put(('results', results, hinweis, path))
            except Exception as exc:
                self.ui_queue.put(('results', [], 'Fehler beim Parsen: %s' % exc, path))
            finally:
                self._cleanup_result_file(path)
        threading.Thread(target=work, daemon=True).start()

    def _cleanup_result_file(self, path):
        """Ergebnis-ZIP nach dem Parsen löschen (best effort)."""
        try:
            if path and os.path.exists(path):
                os.remove(path)
                self.log('Ergebnis-ZIP gelöscht: %s' % os.path.basename(path))
        except Exception as exc:
            self.log('Warnung: Ergebnis-ZIP konnte nicht gelöscht werden: %s (%s)'
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
            self.log('Keine Bücher markiert.')
            return
        channel = self.get_channel()
        if not channel:
            self.log('FEHLER: Kein Kanal gesetzt.')
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
        self.set_status('%d Download(s) in Warteschlange' % added)
        self.log('%d Download(s) eingereiht (Kanal %s, max. %d parallel, %ds Pause).'
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
        self.log('%d wartende Download(s) abgebrochen.' % cancelled)
        if cancelled:
            self.set_status('%d abgebrochen' % cancelled)

    def set_row_status(self, request, status):
        if self.model is None:
            return
        it = self.model.get_iter_first()
        while it is not None:
            if self.model.get_value(it, 4) == request:
                self.model.set_value(it, 6, status)
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
                self.log('Empfang gestartet: %s (von %s)' % (item['filename'], nick))
                self.set_row_status(req, ST_RECV)
            return hexchat.EAT_NONE
        # 2) Sonst: erwartete Ergebnisdatei der Suche?
        if self.state == STATE_SEARCHING and self.pending_result is None:
            low = fname.lower()
            if low.endswith(('.zip', '.txt', '.log')):
                self.pending_result = {'filename': fname, 'nick': nick,
                                       'ts': time.time()}
                self.log('Ergebnis-Datei wird empfangen: %s (von %s)' % (fname, nick))
                self.set_status('Ergebnis-Datei wird empfangen ...')
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
                self.log('Ergebnis-Datei komplett: %s' % (dest or fname))
                self.set_status('Ergebnis wird ausgewertet ...')
                if dest and os.path.exists(dest):
                    self.on_search_result_file(dest)
                else:
                    self.log('FEHLER: Empfangene Datei nicht gefunden: %s' % (dest or fname))
                    self.set_status('Fehler bei Ergebnis-Datei')
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
                reason = word[1] if len(word) > 1 else 'Datei konnte nicht geöffnet werden'
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
                self.log('Download fehlgeschlagen: %s (%s)' % (item['filename'], reason))
                self.set_status('Download fehlgeschlagen')
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
            self.log('Download abgebrochen: %s' % item['filename'])
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
            item['error'] = 'Datei nicht gefunden: %s' % (src or '?')
            self.set_row_status(req, ST_ERR)
            self.log('FEHLER: %s' % item['error'])
            return
        item['state'] = ST_DONE
        self.set_row_status(req, ST_DONE)
        self.log('Download komplett: %s' % item['filename'])

        def work():
            try:
                final, hinweis = move_to_target(src, self.config.get('target_dir'),
                                                self.config.get('unzip'))
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
            self.log('Timeout: Keine Ergebnis-Datei empfangen.')
            self.state = STATE_IDLE
            self.pending_result = None
            self.ensure_auto_accept(False)
            self.set_status('Suche abgelaufen (Timeout)')

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
                self.log('FEHLER: Kein Kanal für "%s"' % item['filename'])
            else:
                channel = self.get_channel()
                hexchat.command('MSG %s %s' % (channel, item['request']))
                item['state'] = ST_SENT
                item['sent_ts'] = now
                self.set_row_status(req, ST_SENT)
                self.log('Angefragt (%s): %s' % (channel, item['filename']))
                self.next_send_ts = now + float(self.config.get('delay'))

        # Timeouts pro Download
        for req, item in self.downloads.items():
            if item['state'] == ST_SENT and now - item['sent_ts'] > self.config.get('timeout'):
                item['state'] = ST_TOUT
                self.set_row_status(req, ST_TOUT)
                self.log('Timeout: Keine Antwort für "%s"' % item['filename'])
            elif item['state'] == ST_RECV and item.get('offer_ts') and \
                    now - item['offer_ts'] > self.config.get('timeout'):
                item['state'] = ST_TOUT
                self.set_row_status(req, ST_TOUT)
                self.log('Timeout: Übertragung von "%s" hängt' % item['filename'])

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
            self.log('Ergebnis ausgewertet (%s): %d Treffer' % (hinweis, len(results)))
            self.results = list(results)
            if self.model is not None:
                self.model.clear()
                for r in results:
                    self.model.append([False, r['filename'],
                                       r.get('filetype', filetype_of(r['filename'])),
                                       r['size'], r['request'], r['botnick'], '',
                                       float(r.get('size_bytes') or 0.0),
                                       r['filename'].lower()])
            self.set_status('%d Treffer - Bücher markieren und Download starten' % len(results))
        elif kind == 'moved':
            _, req, final, hinweis, error = msg
            item = self.downloads.get(req)
            if error:
                item['state'] = ST_ERR
                self.set_row_status(req, '%s: %s' % (ST_ERR, error))
                self.log('FEHLER bei %s: %s' % (item['filename'], error))
                self.set_status('Fehler beim Verschieben')
            else:
                item['path'] = final
                self.set_row_status(req, '%s: %s' % (ST_DONE, final))
                self.set_row_checked(req, False)
                self.log('Fertig: %s (%s)' % (item['filename'], hinweis))
                self.set_status('Fertig: %s' % os.path.basename(final))

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
            hexchat.prnt('EbookDL: GUI-Bindings fehlen (%s). Bitte python3-gi und gir1.2-gtk-2.0 installieren.' % exc)
            return
        self.Gtk = Gtk

        win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        win.set_title('EbookDL - IRC Ebook Suche')
        win.set_default_size(940, 660)
        win.set_border_width(6)
        win.connect('delete-event', self.on_close)

        vbox = Gtk.VBox(homogeneous=False, spacing=4)

        # -- Kopfzeile: Kanal + Suche
        head = Gtk.HBox(homogeneous=False, spacing=4)
        lbl_ch = Gtk.Label()
        lbl_ch.set_text('Kanal:')
        self.entry_channel = Gtk.Entry()
        self.entry_channel.set_width_chars(14)
        self.entry_channel.set_text(self.config.get('channel'))
        lbl_q = Gtk.Label()
        lbl_q.set_text('Suche:')
        self.entry_search = Gtk.Entry()
        self.entry_search.set_width_chars(40)
        self.entry_search.connect('activate', lambda *a: self.start_search(self.entry_search.get_text()))
        btn_search = Gtk.Button()
        btn_search.set_label('Suche starten')
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
        for r in self.results:
            self.model.append([False, r['filename'],
                               r.get('filetype', filetype_of(r['filename'])),
                               r['size'], r['request'], r['botnick'], '',
                               float(r.get('size_bytes') or 0.0),
                               r['filename'].lower()])
        tree = Gtk.TreeView()
        tree.set_model(self.model)
        tree.set_rules_hint(True)
        tree.set_headers_visible(True)
        rend_toggle = Gtk.CellRendererToggle()
        rend_toggle.set_property('activatable', True)
        rend_toggle.connect('toggled', self.on_toggle)
        col_toggle = Gtk.TreeViewColumn('Download', rend_toggle, active=0)
        col_toggle.set_fixed_width(70)
        tree.append_column(col_toggle)
        col_name = Gtk.TreeViewColumn('Datei', Gtk.CellRendererText(), text=1)
        col_name.set_sort_column_id(8)  # case-insensitive über Klein-Name
        tree.append_column(col_name)
        col_type = Gtk.TreeViewColumn('Typ', Gtk.CellRendererText(), text=2)
        col_type.set_sort_column_id(2)
        col_type.set_fixed_width(70)
        tree.append_column(col_type)
        col_size = Gtk.TreeViewColumn('Größe', Gtk.CellRendererText(), text=3)
        col_size.set_sort_column_id(7)  # numerisch nach Bytes
        col_size.set_fixed_width(90)
        tree.append_column(col_size)
        col_status = Gtk.TreeViewColumn('Status', Gtk.CellRendererText(), text=6)
        col_status.set_fixed_width(240)
        tree.append_column(col_status)
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.add(tree)
        vbox.pack_start(sw, True, True, 0)

        # -- Aktionsleiste
        bar = Gtk.HBox(homogeneous=False, spacing=4)
        btn_all = Gtk.Button()
        btn_all.set_label('Alle markieren')
        btn_all.connect('clicked', lambda *a: self.set_all_checked(True))
        btn_none = Gtk.Button()
        btn_none.set_label('Keine markieren')
        btn_none.connect('clicked', lambda *a: self.set_all_checked(False))
        btn_dl = Gtk.Button()
        btn_dl.set_label('Download starten')
        btn_dl.connect('clicked', lambda *a: self.start_downloads())
        btn_cancel = Gtk.Button()
        btn_cancel.set_label('Wartende abbrechen')
        btn_cancel.connect('clicked', lambda *a: self.cancel_queue())
        btn_cfg = Gtk.Button()
        btn_cfg.set_label('Einstellungen')
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
        self.label_status.set_text('Bereit.')
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
        self.window.hide()
        return True  # Fenster nur verstecken, Plugin läuft weiter

    def on_toggle(self, renderer, path):
        if self.model is None:
            return
        it = self.model.get_iter(path)
        if it is not None:
            cur = self.model.get_value(it, 0)
            self.model.set_value(it, 0, not cur)

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
        Gtk = self.Gtk
        win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        win.set_title('EbookDL - Einstellungen')
        win.set_default_size(520, -1)
        win.set_border_width(8)
        win.connect('delete-event', self.on_settings_close)

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
        row('Kanal (leer = aktueller):', e_channel)

        e_search = Gtk.Entry()
        e_search.set_text(self.config.get('search_cmd'))
        row('Suchbefehl ({query}):', e_search)

        e_target = Gtk.Entry()
        e_target.set_text(self.config.get('target_dir'))
        row('Zielordner (Pfad eintragen):', e_target)

        e_delay = Gtk.Entry()
        e_delay.set_text(str(int(self.config.get('delay'))))
        row('Pause zwischen Anfragen (s):', e_delay)

        e_max = Gtk.Entry()
        e_max.set_text(str(int(self.config.get('max_concurrent'))))
        row('Max. parallele Downloads:', e_max)

        e_to = Gtk.Entry()
        e_to.set_text(str(int(self.config.get('timeout'))))
        row('Timeout pro Download (s):', e_to)

        e_so = Gtk.Entry()
        e_so.set_text(str(int(self.config.get('search_timeout'))))
        row('Timeout Suche (s):', e_so)

        c_unzip = Gtk.CheckButton()
        c_unzip.set_label('ZIP-Dateien nach dem Download entpacken')
        c_unzip.set_active(bool(self.config.get('unzip')))
        box.pack_start(c_unzip, False, False, 2)

        c_auto = Gtk.CheckButton()
        c_auto.set_label('DCC-Dateien während Suche/Download automatisch annehmen')
        c_auto.set_active(bool(self.config.get('auto_accept')))
        box.pack_start(c_auto, False, False, 2)

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
                self.config.save()
                if self.entry_channel is not None:
                    self.entry_channel.set_text(self.config.get('channel'))
                self.log('Einstellungen gespeichert: Zielordner %s, %ds Pause, max. %d parallel'
                         % (self.config.get('target_dir'), int(self.config.get('delay')),
                            self.config.get('max_concurrent')))
            except ValueError:
                self.log('FEHLER: Ungültige Zahl in den Einstellungen - nicht gespeichert.')
            win.destroy()

        def on_cancel(*a):
            win.destroy()

        btn_ok = Gtk.Button()
        btn_ok.set_label('OK')
        btn_ok.connect('clicked', on_ok)
        btn_cancel = Gtk.Button()
        btn_cancel.set_label('Abbrechen')
        btn_cancel.connect('clicked', on_cancel)
        btnrow.pack_start(btn_ok, True, True, 0)
        btnrow.pack_start(btn_cancel, True, True, 0)
        box.pack_start(btnrow, False, False, 4)

        win.add(box)
        win.show_all()

    def on_settings_close(self, widget, event):
        widget.destroy()
        return True

    # -- Kommandos ------------------------------------------------------------

    def on_cmd(self, word, word_eol, userdata):
        self.open_window()
        return hexchat.EAT_ALL

    def on_unload(self, userdata):
        self.ensure_auto_accept(False)
        release_single_instance()
        hexchat.prnt('EbookDL entladen.')


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
        hexchat.prnt('EbookDL: Läuft bereits (PID %s) - zweite Instanz wird ignoriert. '
                     'Zum Neuladen: /ebookdl-Fenster schließen, dann /py unload EbookDL '
                     'und erneut laden.' % pid)
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
