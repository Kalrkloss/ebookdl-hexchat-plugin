# -*- coding: utf-8 -*-
"""Test-Harness für ebookdl.py: Stub-HexChat + Logik-Tests."""
import os
import sys
import shutil
import zipfile
import tarfile
import gzip
import subprocess
import tempfile
import time as realtime

realnow = realtime.time  # echte Zeit (unbeeinflusst vom time-Patch in Abschnitt 5)

BASE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix='ebookdl_test_')
os.makedirs(os.path.join(TMP, 'dcc'), exist_ok=True)
os.makedirs(os.path.join(TMP, 'completed'), exist_ok=True)
os.makedirs(os.path.join(TMP, 'config'), exist_ok=True)


class StubHexchat:
    EAT_NONE = 0

    def __init__(self):
        self.commands = []
        self.prints = []
        self.pluginprefs = {}
        self.prefs = {'dcc_auto_recv': 1,
                      'dcc_dir': os.path.join(TMP, 'dcc'),
                      'dcc_completed_dir': os.path.join(TMP, 'completed')}
        self.info = {'configdir': os.path.join(TMP, 'config'), 'channel': '#bookz'}

    def prnt(self, s):
        self.prints.append(s)

    def command(self, s):
        self.commands.append(s)

    def get_info(self, n):
        return self.info.get(n)

    def get_prefs(self, n):
        return self.prefs.get(n)

    def hook_print(self, *a, **kw):
        return 1

    def hook_command(self, *a, **kw):
        return 1

    def hook_timer(self, *a):
        return 1

    def hook_unload(self, *a):
        return 1

    def get_pluginpref(self, name):
        return self.pluginprefs.get(name)

    def set_pluginpref(self, name, value):
        self.pluginprefs[name] = value
        return True

    def del_pluginpref(self, name):
        return self.pluginprefs.pop(name, None) is not None


stub = StubHexchat()
sys.modules['hexchat'] = stub
sys.path.insert(0, BASE)

# Minimale ListStore-Emulation (Layout wie im Plugin: 0 Check, 1 Datei,
# 2 Typ, 3 Größe, 4 Request, 5 Bot, 6 Status, 7 Bytes, 8 Klein-Name)
class FakeModel(object):
    def __init__(self, rows):
        self.rows = rows
    def clear(self):
        self.rows = []
    def append(self, row):
        self.rows.append(list(row))
    def get_iter_first(self):
        return 0 if self.rows else None
    def iter_next(self, it):
        return it + 1 if it + 1 < len(self.rows) else None
    def get_value(self, it, col):
        return self.rows[it][col]
    def set_value(self, it, col, val):
        self.rows[it][col] = val

import ebookdl
ebookdl.release_single_instance()  # Import-löst main() aus -> Marker zurücksetzen
from ebookdl import (parse_result_line, parse_results_text, parse_results_zip,
                     nick_matches, name_matches, move_to_target, unique_path,
                     format_bytes, parse_size, filetype_of)

passed = 0
failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
        print('PASS  %s' % name)
    else:
        failed += 1
        print('FAIL  %s' % name)


# --- 1. Zeilen-Parsing ------------------------------------------------------
line = '!artemis_serv 16d6770d2ba9 | 27 - The Last Hero - Graphic Novel.pdf ::INFO:: 49.78MB'
item = parse_result_line(line)
check('parse: request', item is not None and item['request'] == line.split('::INFO::')[0].strip())
check('parse: filename', item is not None and item['filename'] == '27 - The Last Hero - Graphic Novel.pdf')
check('parse: size', item is not None and item['size'] == '49.78MB')
check('parse: botnick', item is not None and item['botnick'] == 'artemis_serv')
check('parse: size_bytes', item is not None and abs(item['size_bytes'] - 49.78 * 1024 * 1024) < 1)
check('parse: filetype', item is not None and item['filetype'] == 'PDF')
check('filetype: mehrfach-endung', filetype_of('Buch.Name.Tar.GZ') == 'GZ')
check('filetype: keine endung', filetype_of('ohne_endung') == '-')
check('parse: junk line', parse_result_line('just some text') is None)
check('parse: no INFO', parse_result_line('!foo_serv abc | x.pdf') is None)

text = '\n'.join([
    'Search results for: artemis',
    line,
    '!other_serv deadbeef | Another Book.epub ::INFO:: 1.20MB',
    '!artemis_serv 16d6770d2ba9 | 27 - The Last Hero - Graphic Novel.pdf ::INFO:: 49.78MB',  # dup
    '-- end of results --',
])
res = parse_results_text(text)
check('parse_text: 2 unique', len(res) == 2)
check('parse_text: order', res[0]['filename'].startswith('27 - The Last Hero'))

# --- 2. ZIP-Parsing ---------------------------------------------------------
zip_path = os.path.join(TMP, 'results.zip')
with zipfile.ZipFile(zip_path, 'w') as zf:
    zf.writestr('search_results.txt', text)
    zf.writestr('readme.nfo', 'irrelevant')
results, hint = parse_results_zip(zip_path)
check('zip: 2 results', len(results) == 2)
check('zip: hint', hint is not None and ('Textdatei' in hint or 'text file' in hint))

txt_path = os.path.join(TMP, 'direct.txt')
with open(txt_path, 'w', encoding='utf-8') as fh:
    fh.write(text)
results2, hint2 = parse_results_zip(txt_path)
check('txt: 2 results', len(results2) == 2)

empty_zip = os.path.join(TMP, 'empty.zip')
with zipfile.ZipFile(empty_zip, 'w') as zf:
    zf.writestr('nothing.bin', b'\x00\x01')
r3, h3 = parse_results_zip(empty_zip)
check('zip: empty -> 0', r3 == [] and h3 is not None)

# --- 3. Matching ------------------------------------------------------------
check('nick exact', nick_matches('artemis_serv', 'artemis_serv'))
check('nick sub', nick_matches('artemis_serv', 'Artemis_Serv2'))
check('nick no', not nick_matches('artemis_serv', 'foo_bar'))
check('name sub', name_matches('27 - The Last Hero - Graphic Novel.pdf',
                               '27 The Last Hero Graphic Novel.pdf.zip'))
check('name exact', name_matches('book.epub', 'Book.EPUB'))
check('name no', not name_matches('artemis novel', 'something else entirely'))

# --- 4. move_to_target ------------------------------------------------------
target = os.path.join(TMP, 'target')
os.makedirs(target, exist_ok=True)

# ZIP entpacken
dl_zip = os.path.join(TMP, 'book.zip')
with zipfile.ZipFile(dl_zip, 'w') as zf:
    zf.writestr('book.epub', b'fake epub content')
final, hint3 = move_to_target(dl_zip, target, True)
check('move: zip entfernt', not os.path.exists(dl_zip))
check('move: entpackt', os.path.exists(os.path.join(final, 'book.epub')))
check('move: hint', 'entpackt' in hint3 or 'unzipped' in hint3)

# EPUB ist ein ZIP-Container, darf aber NICHT entpackt werden
epub_file = os.path.join(TMP, 'completed', 'Buch.epub')
with zipfile.ZipFile(epub_file, 'w') as zf:
    zf.writestr('mimetype', 'application/epub+zip')
    zf.writestr('OEBPS/content.opf', '<package/>')
final_epub, _ = move_to_target(epub_file, target, True)
check('move: epub bleibt datei', final_epub.endswith('.epub') and os.path.isfile(final_epub))
check('move: epub nicht entpackt', not os.path.isdir(os.path.join(target, 'Buch')))

# TAR entpacken (nativ via tarfile)
tar_file = os.path.join(TMP, 'completed', 'TarBuch.tar')
inner = os.path.join(TMP, 'completed', 'inner.txt')
with open(inner, 'w', encoding='utf-8') as fh:
    fh.write('inhalt')
with tarfile.open(tar_file, 'w') as tf:
    tf.add(inner, arcname='inner.txt')
final_tar, _ = move_to_target(tar_file, target, True)
check('move: tar entpackt', os.path.exists(os.path.join(target, 'TarBuch', 'inner.txt')))
check('move: tar.ordner', final_tar == os.path.join(target, 'TarBuch'))

# GZ-Einzeldatei -> dekomprimiert zu Datei (kein Unterordner)
gz_file = os.path.join(TMP, 'completed', 'Daten.txt.gz')
with gzip.open(gz_file, 'wb') as fh:
    fh.write(b'gzip inhalt')
final_gz, _ = move_to_target(gz_file, target, True)
check('move: gz dekomprimiert', os.path.exists(os.path.join(target, 'Daten.txt'))
      and open(os.path.join(target, 'Daten.txt'), 'rb').read() == b'gzip inhalt')
check('move: gz quelle weg', not os.path.exists(gz_file))

# 7z entpacken (extern via p7zip, nur wenn installiert)
if shutil.which('7z') and subprocess.call(['7z', 'i'], stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL) == 0:
    z7 = os.path.join(TMP, 'completed', 'SevenBuch.7z')
    inner7 = os.path.join(TMP, 'completed', 'inner7.txt')
    with open(inner7, 'w', encoding='utf-8') as fh:
        fh.write('7z inhalt')
    if subprocess.call(['7z', 'a', '-y', z7, 'inner7.txt'], cwd=os.path.dirname(z7),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
        final_7z, _ = move_to_target(z7, target, True)
        check('move: 7z entpackt', os.path.exists(os.path.join(target, 'SevenBuch', 'inner7.txt')))

# Quelle liegt bereits im Zielordner (DCC-Ordner == Zielordner):
# darf NICHT zu "Name (1)" umbenannt werden
own = os.path.join(target, 'EigenesBuch.epub')
with open(own, 'wb') as fh:
    fh.write(b'epub')
final_own, _ = move_to_target(own, target, True)
check('move: im Ziel -> gleicher Name', os.path.basename(final_own) == 'EigenesBuch.epub')
check('move: im Ziel -> kein (1)', not os.path.exists(os.path.join(target, 'EigenesBuch (1).epub')))

# Archiv, das bereits im Zielordner liegt, wird trotzdem entpackt
ownzip = os.path.join(target, 'EigenesArchiv.zip')
with zipfile.ZipFile(ownzip, 'w') as zf:
    zf.writestr('buch.txt', 'inhalt')
final_ownzip, _ = move_to_target(ownzip, target, True)
check('move: archiv im Ziel -> entpackt',
      os.path.exists(os.path.join(target, 'EigenesArchiv', 'buch.txt')))

# Datei verschieben + Kollision
f1 = os.path.join(TMP, 'plain.pdf')
with open(f1, 'wb') as fh:
    fh.write(b'pdf')
d1, _ = move_to_target(f1, target, False)
check('move: plain', os.path.basename(d1) == 'plain.pdf')
f2 = os.path.join(TMP, 'plain.pdf')  # gleicher Dateiname -> Kollision im Ziel
with open(f2, 'wb') as fh:
    fh.write(b'pdf')
d2, _ = move_to_target(f2, target, False)
check('move: collision', os.path.basename(d2) == 'plain (1).pdf')
check('unique_path', unique_path(target, 'plain.pdf') != os.path.join(target, 'plain.pdf'))

# --- 5. Queue-Scheduling (simulierte Zeit) ----------------------------------
# Netiquette: eine Anfrage pro 'delay'-Intervall, max. 'max_concurrent' aktiv.
import ebookdl as edl
fake_time = [1000.0]
edl.time.time = lambda: fake_time[0]

p = edl.EbookDLPlugin()
p.config.data['target_dir'] = target  # Test-Zielordner, nicht ~/Downloads/ebooks
stub.commands.clear()
p.config.data['delay'] = 10.0
p.config.data['max_concurrent'] = 2

rows = [
    {'request': '!artemis_serv aa11 | Book One.pdf ::INFO:: 1MB',
     'filename': 'Book One.pdf', 'size': '1MB', 'botnick': 'artemis_serv',
     'size_bytes': parse_size('1MB')},
    {'request': '!artemis_serv bb22 | Book Two.epub ::INFO:: 2MB',
     'filename': 'Book Two.epub', 'size': '2MB', 'botnick': 'artemis_serv',
     'size_bytes': parse_size('2MB')},
    {'request': '!other_serv cc33 | Book Three.mobi ::INFO:: 3MB',
     'filename': 'Book Three.mobi', 'size': '3MB', 'botnick': 'other_serv',
     'size_bytes': parse_size('3MB')},
]
for r in rows:
    p.downloads[r['request']] = dict(r, state='wartet', sent_ts=0.0, offer_ts=0.0,
                                     dcc_name=None, path=None, error=None, progress=0.0)
    p.queue.append(r['request'])

p.next_send_ts = 0.0
p.on_timer(None)  # t=1000 -> 1 senden (eine pro Takt)
msgs = [c for c in stub.commands if c.startswith('MSG ')]
check('sched: 1 gesendet', len(msgs) == 1 and 'Book One.pdf' in msgs[0])
check('sched: next_send_ts', abs(p.next_send_ts - 1010.0) < 0.01)
check('sched: zustand SENT', p.downloads[rows[0]['request']]['state'] == 'angefragt')
check('sched: zwei+ drei warten', p.downloads[rows[1]['request']]['state'] == 'wartet'
      and p.downloads[rows[2]['request']]['state'] == 'wartet')

stub.commands.clear()
fake_time[0] = 1005.0
p.on_timer(None)  # Pause nicht vorbei -> nichts
check('sched: pause respektiert', not [c for c in stub.commands if c.startswith('MSG ')])

fake_time[0] = 1010.0
p.on_timer(None)  # Pause vorbei -> zweite
msgs = [c for c in stub.commands if c.startswith('MSG ')]
check('sched: zweite gesendet', len(msgs) == 1 and 'Book Two.epub' in msgs[0])

# max_concurrent: beide noch aktiv (SENT) -> dritte wird blockiert
stub.commands.clear()
fake_time[0] = 1020.0
p.on_timer(None)
check('sched: limit blockiert', not [c for c in stub.commands if c.startswith('MSG ')])

# erste Übertragung abschließen -> Slot frei
p.downloads[rows[0]['request']]['state'] = 'fertig'
fake_time[0] = 1030.0
p.on_timer(None)
msgs = [c for c in stub.commands if c.startswith('MSG ')]
check('sched: dritte nach Slot-Freigabe', len(msgs) == 1 and 'Book Three.mobi' in msgs[0])

# Abbruch: wartende Einträge werden übersprungen
p.queue.append('!x_serv dead | Never.pdf ::INFO:: 1MB')
p.downloads['!x_serv dead | Never.pdf ::INFO:: 1MB'] = dict(
    request='!x_serv dead | Never.pdf ::INFO:: 1MB', filename='Never.pdf', size='1MB',
    botnick='x_serv', size_bytes=1024 ** 2, state='wartet', sent_ts=0.0, offer_ts=0.0,
    dcc_name=None, path=None, error=None, progress=0.0)
p.downloads['!x_serv dead | Never.pdf ::INFO:: 1MB']['state'] = 'abgebrochen'
stub.commands.clear()
fake_time[0] = 1040.0
p.on_timer(None)
check('sched: abgebrochen übersprungen', not [c for c in stub.commands if c.startswith('MSG ')])

# --- 6. DCC-Zuordnung --------------------------------------------------------
# Alle Downloads auf 'fertig' setzen, damit nichts mehr aktiv matcht
for r in rows:
    p.downloads[r['request']]['state'] = 'fertig'

# Ergebnis-Suche: RECV Connect während searching
# WICHTIG: word[] beginnt mit dem ERSTEN Argument (kein Event-Name!)
# 'DCC RECV Connect' -> word = [nick, host, dateiname]
p.state = 'searching'
p.pending_result = None
p.on_dcc_connect(['artemis_serv', '1.2.3.4:1234', 'search_results.txt.zip'], None, None)
check('connect: pending_result gesetzt', p.pending_result is not None
      and p.pending_result['filename'] == 'search_results.txt.zip')

# Complete: Ergebnisdatei -> Parsing-Job
res_file = os.path.join(TMP, 'completed', 'search_results.txt.zip')
shutil.copy(zip_path, res_file)
p.on_dcc_complete(['search_results.txt.zip', res_file, 'artemis_serv', '12345'], None, None)
check('complete: state idle', p.state == 'idle')
# Parsing läuft im Thread -> pollen bis die Ergebnisse da sind
deadline = realnow() + 5
while realnow() < deadline and len(p.results) != 2:
    while not p.ui_queue.empty():
        p.handle_ui_msg(p.ui_queue.get())
    realtime.sleep(0.05)
check('complete: parse job queued', len(p.results) == 2)
check('complete: results korrekt', p.results[0]['filename'] == '27 - The Last Hero - Graphic Novel.pdf')
# Ergebnis-ZIP wurde nach dem Parsen gelöscht
deadline = realnow() + 5
while realnow() < deadline and os.path.exists(res_file):
    realtime.sleep(0.05)
check('ergebnis-zip geloescht', not os.path.exists(res_file))

# Neue Spalten im Model: Typ (2), Bytes (7), Klein-Name (8)
fm2 = FakeModel([])
p.model = fm2
p.handle_ui_msg(('results', p.results, '1 Datei', 'x'))
check('results: spalte typ', len(fm2.rows) == 2 and fm2.rows[0][2] == 'PDF')
check('results: spalte groesse', len(fm2.rows) == 2 and fm2.rows[0][3] == '49.78MB')
check('results: spalte bytes', len(fm2.rows) == 2 and abs(fm2.rows[0][7] - 49.78 * 1024 * 1024) < 1)
check('results: spalte kleinname', len(fm2.rows) == 2
      and fm2.rows[0][8] == '27 - the last hero - graphic novel.pdf')

# Complete: Download-Datei -> moved
dl_item = p.downloads[rows[1]['request']]
dl_item['state'] = 'angefragt'
dl_item['sent_ts'] = 1000.0
dl_file = os.path.join(TMP, 'completed', 'Book One.pdf')
with open(dl_file, 'wb') as fh:
    fh.write(b'fake pdf')

# Checkbox-Abwahl nach Download prüfen (FakeModel oben definiert)
fm = FakeModel([[True, 'Book One.pdf', 'PDF', '1.0MB', rows[1]['request'], 'artemis_serv', '']])
p.model = fm
p.on_dcc_complete(['Book One.pdf', dl_file, 'artemis_serv', '99999'], None, None)
# Verschieben läuft im Thread -> pollen bis Datei im Ziel liegt
deadline = realnow() + 5
while realnow() < deadline:
    while not p.ui_queue.empty():
        p.handle_ui_msg(p.ui_queue.get())
    if os.path.exists(os.path.join(target, 'Book One.pdf')):
        break
    realtime.sleep(0.05)
check('moved: datei im ziel', os.path.exists(os.path.join(target, 'Book One.pdf')))
check('moved: status fertig', dl_item['state'] == 'fertig')
check('moved: zuordnung richtig', dl_item['request'] == rows[1]['request'])
check('moved: checkbox abgewaehlt', fm.rows[0][0] is False)

# --- 7. Fehlerfall -----------------------------------------------------------
bad = rows[1]['request']
p.downloads[bad]['state'] = 'angefragt'
p._make_failed_handler('DCC RECV Failed')(['Book Two.epub', os.path.join(TMP, 'x'), 'artemis_serv', 'connection reset'], None, None)
check('failed: status', p.downloads[bad]['state'] == 'Fehler')
check('failed: reason', p.downloads[bad]['error'] == 'connection reset')

# Timeout
fake_time[0] = 2000.0
p.downloads[bad]['state'] = 'angefragt'
p.downloads[bad]['sent_ts'] = 1000.0
p.on_timer(None)
check('timeout: status', p.downloads[bad]['state'] == 'Timeout')

# --- 8. Helper ---------------------------------------------------------------
check('fmt: bytes', format_bytes(1048576) == '1.00 MB')
check('parse_size: MB', abs(parse_size('49.78MB') - 49.78 * 1024 * 1024) < 1)
check('parse_size: GB', abs(parse_size('1.5 GB') - 1.5 * 1024 ** 3) < 1)
check('parse_size: nix', parse_size('abc') == 0.0)

# --- 9. Einzelinstanz-Schutz --------------------------------------------------
check('single: marker anfangs frei',
      ebookdl.acquire_single_instance() is True and stub.pluginprefs.get('ebookdl_running') == os.getpid())
check('single: zweite Instanz blockiert',
      ebookdl.acquire_single_instance() is False)
# Verwaister Marker (tote PID) -> wird übernommen
stub.pluginprefs['ebookdl_running'] = 999999999
check('single: verwaister Marker uebernommen',
      ebookdl.acquire_single_instance() is True and stub.pluginprefs.get('ebookdl_running') == os.getpid())
# Marker einer ANDEREN (lebenden) PID -> blockiert
stub.pluginprefs['ebookdl_running'] = 1  # PID 1 (init) lebt praktisch immer
check('single: fremder Marker blockiert', ebookdl.acquire_single_instance() is False)
ebookdl.release_single_instance()
check('single: release loescht nur eigenen Marker',
      stub.pluginprefs.get('ebookdl_running') == 1)
stub.pluginprefs['ebookdl_running'] = os.getpid()
ebookdl.release_single_instance()
check('single: release loescht eigenen Marker',
      'ebookdl_running' not in stub.pluginprefs)
# main(): bei lebendem Fremd-Marker blockiert es und meldet sich
stub.pluginprefs['ebookdl_running'] = os.getpid()
check('single: main blockiert zweite Instanz',
      ebookdl.main() is None and stub.prints and 'EbookDL' in stub.prints[-1])
ebookdl.release_single_instance()

# --- 10. Spracherkennung -----------------------------------------------------
_orig_lang = {k: os.environ.get(k) for k in ('LANGUAGE', 'LC_ALL', 'LC_MESSAGES', 'LANG')}
def _setenv(**kw):
    for k in ('LANGUAGE', 'LC_ALL', 'LC_MESSAGES', 'LANG'):
        os.environ.pop(k, None)
    os.environ.update({k: v for k, v in kw.items() if v is not None})

_setenv(LANG='de_DE.UTF-8')
check('lang: de aus LANG', ebookdl.detect_lang() == 'de')
_setenv(LANGUAGE='en_US', LANG='de_DE.UTF-8')
check('lang: LANGUAGE hat Vorrang', ebookdl.detect_lang() == 'en')
_setenv(LANGUAGE='de:en', LANG='en_US.UTF-8')
check('lang: Prioritätsliste de:en', ebookdl.detect_lang() == 'de')
_setenv(LANG='en_US.UTF-8')
check('lang: en default', ebookdl.detect_lang() == 'en')
_setenv()
check('lang: leer -> en', ebookdl.detect_lang() == 'en')
for k, v in _orig_lang.items():
    if v is None:
        os.environ.pop(k, None)
    else:
        os.environ[k] = v

# --- 11. Konvertierung (Calibre) ---------------------------------------------
check('convert: default aus', ebookdl.DEFAULT_CONFIG['convert_format'] == '')
check('convert: formate', ebookdl.CONVERT_FORMATS == ['', 'epub', 'mobi', 'pdf'])
check('convert: is_ebook ja', ebookdl.is_ebook_file('Buch.lit')
      and ebookdl.is_ebook_file('b.epub') and ebookdl.is_ebook_file('C.PDF'))
check('convert: is_ebook nein', not ebookdl.is_ebook_file('archiv.zip')
      and not ebookdl.is_ebook_file('Buch.epub.gz') and not ebookdl.is_ebook_file('x.7z'))

# Fake-ebook-convert: kopiert die Datei in das Zielformat (rc=0)
fake_exe = os.path.join(TMP, 'ebook-convert')
with open(fake_exe, 'w') as fh:
    fh.write('#!/bin/sh\ncp "$1" "$2"\n')
os.chmod(fake_exe, 0o755)
lit_file = os.path.join(TMP, 'completed', 'Buch.lit')
with open(lit_file, 'wb') as fh:
    fh.write(b'lit content')
conv_dst = ebookdl.convert_ebook(lit_file, 'epub', ebook_convert=fake_exe)
check('convert: zielpfad', conv_dst.endswith('.epub') and conv_dst != lit_file)
check('convert: datei da', os.path.exists(conv_dst))

# Fehlschlag (rc!=0)
fail_exe = os.path.join(TMP, 'ebook-convert-fail')
with open(fail_exe, 'w') as fh:
    fh.write('#!/bin/sh\nexit 3\n')
os.chmod(fail_exe, 0o755)
try:
    ebookdl.convert_ebook(lit_file, 'mobi', ebook_convert=fail_exe)
    check('convert: fehlerfall', False)
except RuntimeError:
    check('convert: fehlerfall', True)

# Calibre fehlt komplett (which findet nichts -> RuntimeError)
_orig_which = shutil.which
shutil.which = lambda name: None
try:
    ebookdl.convert_ebook(lit_file, 'epub')
    check('convert: calibre fehlt', False)
except RuntimeError:
    check('convert: calibre fehlt', True)
finally:
    shutil.which = _orig_which
check('convert: calibre_available nein',
      ebookdl.calibre_available() is (shutil.which('ebook-convert') is not None))

# Zielformat == Quellformat -> kein Aufruf noetig
same = ebookdl.convert_ebook(lit_file, 'lit', ebook_convert='/nonexistent/ebook-convert')
check('convert: gleiches format', same == lit_file)

# --- 12. Filter: Nicht-E-Book-Dateien ausblenden ------------------------------
check('filter: default an', ebookdl.DEFAULT_CONFIG['filter_non_ebooks'] is True)
check('filter: is_book ebook', ebookdl.is_book_file('Buch.epub')
      and ebookdl.is_book_file('B.lit') and ebookdl.is_book_file('C.PDF'))
check('filter: is_book archiv', ebookdl.is_book_file('D.rar')
      and ebookdl.is_book_file('E.zip') and ebookdl.is_book_file('F.7z')
      and ebookdl.is_book_file('G.tar.gz'))
check('filter: is_book nein', not ebookdl.is_book_file('H.opf')
      and not ebookdl.is_book_file('I.jpg') and not ebookdl.is_book_file('J.png')
      and not ebookdl.is_book_file('K.nfo') and not ebookdl.is_book_file('L.jpeg')
      and not ebookdl.is_book_file('M.gif') and not ebookdl.is_book_file('N.sfv'))

mix = [
    {'filename': 'Buch 1.epub', 'request': '!a 1'},
    {'filename': 'Cover.jpg', 'request': '!a 2'},
    {'filename': 'Buch 2.rar', 'request': '!a 3'},
    {'filename': 'Meta.opf', 'request': '!a 4'},
    {'filename': 'Buch 3.lit', 'request': '!a 5'},
]
flt = ebookdl.filter_results(mix, True)
check('filter: nur ebooks+archive', [r['filename'] for r in flt]
      == ['Buch 1.epub', 'Buch 2.rar', 'Buch 3.lit'])
flt_off = ebookdl.filter_results(mix, False)
check('filter: aus = alle', len(flt_off) == 5)
check('filter: original unveraendert', len(mix) == 5)

# --- 13. Kopieren aus der Ergebnisliste --------------------------------------
class CopyModel(object):
    def __init__(self, rows):
        self.rows = rows
    def get_iter(self, path):
        try:
            idx = int(path)
            return idx if 0 <= idx < len(self.rows) else None
        except (TypeError, ValueError):
            return None
    def get_value(self, it, col):
        return self.rows[it][col]

cm = CopyModel([
    ['False', 'Buch 1.epub', 'EPUB'],
    ['False', 'Buch 2.lit', 'LIT'],
    ['False', 'Buch 3.pdf', 'PDF'],
])
check('copy: eine zeile',
      ebookdl.copy_text_from_model(cm, ['0']) == 'Buch 1.epub')
check('copy: mehrere zeilen',
      ebookdl.copy_text_from_model(cm, ['0', '2']) == 'Buch 1.epub\nBuch 3.pdf')
check('copy: leere auswahl', ebookdl.copy_text_from_model(cm, []) == '')
check('copy: ungueltiger pfad', ebookdl.copy_text_from_model(cm, ['99']) == '')

# --- 14. Status-Uebersetzung vollstaendig ------------------------------------
# Jede ST_-Konstante muss in der Anzeige-Tabelle stecken (sonst bleibt der
# deutsche Wert stehen, z. B. 'wartet' statt 'waiting' in englischer UI)
check('state: alle konstanten uebersetzt',
      all(ebookdl.t_state(v) != v for v in (ebookdl.ST_WAIT, ebookdl.ST_SENT,
                                            ebookdl.ST_RECV, ebookdl.ST_DONE,
                                            ebookdl.ST_ERR, ebookdl.ST_TOUT,
                                            ebookdl.ST_CANCEL)))

# --- 15. Cancel + erneuter Start + Suche (User-Sequenz) ----------------------
class SeqModel(object):
    def __init__(self, rows):
        self.rows = rows
    def get_iter_first(self):
        return 0 if self.rows else None
    def iter_next(self, it):
        nxt = it + 1
        return nxt if nxt < len(self.rows) else None
    def get_value(self, it, col):
        return self.rows[it][col]
    def get_iter(self, path):
        try:
            idx = int(path)
            return idx if 0 <= idx < len(self.rows) else None
        except (TypeError, ValueError):
            return None
    def set_value(self, it, col, val):
        self.rows[it][col] = val
    def clear(self):
        self.rows = []
    def append(self, row):
        self.rows.append(row)

def make_seq_plugin():
    p = ebookdl.EbookDLPlugin()
    p.model = SeqModel([
        ['True', 'Buch 1.epub', 'EPUB', '1MB', '!a 111', 'artemis_serv', '',
         1048576.0, 'buch 1.epub'],
        ['True', 'Buch 2.lit', 'LIT', '2MB', '!b 222', 'bookz_serv', '',
         2097152.0, 'buch 2.lit'],
    ])
    p.tree = None
    return p

# 1) Markierte Dateien einreihen -> cancel -> erneut starten: ALLE werden
#    wieder eingereiht (cancelled ist nur ein Hinweis)
p = make_seq_plugin()
p.start_downloads()
check('seq: 2 eingereiht', len(p.queue) == 2)
p.cancel_queue()
check('seq: cancelled', all(p.downloads[r]['state'] == ebookdl.ST_CANCEL
                            for r in p.downloads))
check('seq: queue leer', p.queue == [])
p.start_downloads()   # erneuter Start mit weiterhin markierten Zeilen
check('seq: erneut 2 eingereiht', len(p.queue) == 2)
check('seq: status zurueck auf waiting',
      all(p.downloads[r]['state'] == ebookdl.ST_WAIT for r in p.downloads))
check('seq: statuszelle waiting',
      all(p.model.rows[i][6] == 'waiting' for i in range(2)))
# Markierung entfernen + erneut markieren (on_toggle): Status bleibt
# 'cancelled' als Hinweis stehen, bis der naechste Start ihn ueberschreibt
p.cancel_queue()
p.on_toggle(None, '0')
p.on_toggle(None, '0')
check('seq: cancelled bleibt hinweis', p.model.rows[0][6] == 'cancelled'
      and p.downloads['!a 111']['state'] == ebookdl.ST_CANCEL)
p.start_downloads()
check('seq: re-toggle + start -> wieder drin', len(p.queue) == 2)
check('seq: status wieder waiting', p.model.rows[0][6] == 'waiting')

# 2) Nach cancel + NEUER Suche: Ergebnis-Datei muss eingelesen werden
p = make_seq_plugin()
p.start_downloads()
p.cancel_queue()
p.start_search('asimov')
check('seq: suche laeuft', p.state == ebookdl.STATE_SEARCHING)
# Ergebnis-ZIP anlegen (wie vom Bot); fester Timestamp, weil Abschnitt 5
# time.time gefaked hat (ZIP braucht Zeit >= 1980)
res_zip = os.path.join(TMP, 'seq', 'SearchBot_results_for_asimov.txt.zip')
os.makedirs(os.path.dirname(res_zip), exist_ok=True)
_zipinfo = zipfile.ZipInfo('results.txt', (2024, 1, 1, 12, 0, 0))
with zipfile.ZipFile(res_zip, 'w') as zf:
    zf.writestr(_zipinfo, '!artemis 1 | Asimov, Isaac - Foundation.epub ::INFO:: 1MB\n'
                          '!bookz 2 | Asimov, Isaac - Robot.epub ::INFO:: 2MB\n')
# DCC-Events simulieren (word[] = erstes Argument zuerst, Python-Bridge)
p.on_dcc_connect(['Search', 'host:1234', 'SearchBot_results_for_asimov.txt.zip'],
                 None, None)
check('seq: pending_result gesetzt', p.pending_result is not None)
p.on_dcc_complete(['SearchBot_results_for_asimov.txt.zip', res_zip, 'Search'],
                  None, None)
realtime.sleep(1.0)  # Parser-Thread
msgs = []
while True:
    try:
        msgs.append(p.ui_queue.get_nowait())
    except Exception:
        break
results_msg = [m for m in msgs if m[0] == 'results']
check('seq: ergebnis eingelesen', len(results_msg) == 1
      and len(results_msg[0][1]) == 2)
for m in msgs:
    p.handle_ui_msg(m)   # wie der 1s-Timer in HexChat
check('seq: liste gefuellt', len(p.results) == 2)
check('seq: model befuellt', len(p.model.rows) == 2)

# --- Ende --------------------------------------------------------------------
shutil.rmtree(TMP, ignore_errors=True)
print('\n%d passed, %d failed' % (passed, failed))
sys.exit(0 if failed == 0 else 1)
