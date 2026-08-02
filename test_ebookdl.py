# -*- coding: utf-8 -*-
"""Test-Harness für ebookdl.py: Stub-HexChat + Logik-Tests."""
import os
import sys
import shutil
import zipfile
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
check('zip: hint', hint is not None and 'Textdatei' in hint)

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
check('move: hint', 'entpackt' in hint3)

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
      ebookdl.main() is None and stub.prints and 'bereits' in stub.prints[-1])
ebookdl.release_single_instance()

# --- Ende --------------------------------------------------------------------
shutil.rmtree(TMP, ignore_errors=True)
print('\n%d passed, %d failed' % (passed, failed))
sys.exit(0 if failed == 0 else 1)
