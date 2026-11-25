"""Headless test: after Reset, voice-follow must keep tracking from the top.

Installs a mock SpeechRecognition before the page script runs, feeds transcripts
before and after Reset, and checks that the script position and scroll follow
the new take. Also checks that leftover results from the previous take do not
jump the cursor, and that Reset does not abort the recognizer.
"""
import json, subprocess, time, sys, os
from playwright.sync_api import sync_playwright

os.chdir(os.path.dirname(os.path.abspath(__file__)) + '/..')
SHOT = '/workspace/teleprompter-reset'
os.makedirs(SHOT, exist_ok=True)

MOCK = r"""
window.__mockSRInstances = [];
window.SpeechRecognition = window.webkitSpeechRecognition = function MockSR() {
  this.continuous = false;
  this.interimResults = false;
  this.lang = '';
  this.maxAlternatives = 1;
  this.onstart = this.onresult = this.onerror = this.onend = null;
  this._started = false;
  this._aborted = false;
  this._results = [];
  var self = this;
  this.start = function () {
    if (self._started) { var e = new Error('already started'); e.name = 'InvalidStateError'; throw e; }
    self._started = true;
    self._aborted = false;
    setTimeout(function () { if (self.onstart) self.onstart(); }, 0);
  };
  this.abort = function () {
    self._started = false;
    self._aborted = true;
    if (self.onerror) self.onerror({ error: 'aborted' });
    if (self.onend) self.onend();
  };
  this.stop = function () { this.abort(); };
  this._feed = function (text, replaceLast) {
    if (replaceLast && self._results.length) self._results.pop();
    self._results.push({ isFinal: true, '0': { transcript: text }, length: 1 });
    if (self.onresult) self.onresult({ results: self._results, resultIndex: self._results.length - 1 });
  };
  window.__mockSRInstances.push(this);
  window.__latestMockSR = this;
};
"""

srv = subprocess.Popen([sys.executable, '-m', 'http.server', '8766'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1)
errors, failed = [], []

def feed(pg, text, replace_last=False):
  pg.evaluate(
    """(args) => { if (!window.__latestMockSR) throw new Error('no mock SR'); window.__latestMockSR._feed(args[0], args[1]); }""",
    [text, replace_last],
  )

def wait_pos_at_least(pg, n, timeout=2500):
  pg.wait_for_function(f"() => window.__tp && window.__tp.state.pos >= {n}", timeout=timeout)
  return pg.evaluate("() => ({ pos: __tp.state.pos, offset: __tp.state.offset, target: __tp.state.target, running: __tp.state.running, listening: __tp._wantListening(), aborted: !!(window.__latestMockSR && window.__latestMockSR._aborted), started: !!(window.__latestMockSR && window.__latestMockSR._started), instances: (window.__mockSRInstances||[]).length })")

def wait_reset_landed(pg, timeout=2500):
  pg.wait_for_function(
    """() => { const s = window.__tp.state; return s.pos === -1 && Math.abs(s.offset) < 0.05 && Math.abs(s.target) < 0.05; }""",
    timeout=timeout,
  )
  return pg.evaluate("() => ({ pos: __tp.state.pos, offset: __tp.state.offset, target: __tp.state.target, cur: document.querySelectorAll('.w.cur').length, past: document.querySelectorAll('.w.past').length, listening: __tp._wantListening(), aborted: !!(window.__latestMockSR && window.__latestMockSR._aborted), started: !!(window.__latestMockSR && window.__latestMockSR._started), instances: (window.__mockSRInstances||[]).length, resultOffset: __tp._resultOffset() })")

try:
  with sync_playwright() as p:
    b = p.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--use-fake-ui-for-media-stream'])
    results = {}
    for label, how in [
      ('click-reset', 'click'),
      ('home-key', 'Home'),  # Bluetooth remotes often send Home; not a mic user-gesture
    ]:
      ctx = b.new_context(viewport={'width': 390, 'height': 844})
      pg = ctx.new_page()
      pg.add_init_script(MOCK)
      pg.on('console', lambda m: m.type == 'error' and errors.append(f'{label}: {m.text}'))
      pg.on('pageerror', lambda e: errors.append(f'{label} pageerror: {e}'))
      pg.goto('http://localhost:8766/teleprompter.html')
      pg.wait_for_timeout(300)
      pg.click('#sampleBtn')
      pg.click('#toPrompt')
      pg.wait_for_timeout(300)
      # Voice mode + Start (creates the mock recognizer)
      if not pg.evaluate("document.getElementById('modeVoice').classList.contains('on')"):
        pg.click('#modeVoice')
      pg.click('#play')
      pg.wait_for_timeout(200)
      r = {}
      r['listening_after_start'] = pg.evaluate("() => __tp._wantListening() && window.__latestMockSR && window.__latestMockSR._started")
      # First take: speak the opening lines
      feed(pg, 'Hey everyone welcome back to the channel today I want to show you')
      r['after_first_take'] = wait_pos_at_least(pg, 8)
      r['scrolled_on_first_take'] = r['after_first_take']['offset'] > 10 or r['after_first_take']['target'] > 10
      pg.screenshot(path=os.path.join(SHOT, f'voice-{label}-before-reset.png'))
      # Reset via button or Home (no new user-gesture for the mic)
      if how == 'click':
        pg.click('#resetBtn')
      else:
        pg.keyboard.press(how)
      r['after_reset'] = wait_reset_landed(pg)
      r['mic_still_running'] = r['after_reset']['listening'] and r['after_reset']['started'] and not r['after_reset']['aborted']
      r['same_session'] = r['after_reset']['instances'] == 1
      # Leftover: the mock still has the old results. Re-firing an update of the
      # last result (same length) must not jump the cursor.
      feed(pg, 'Hey everyone welcome back to the channel today I want to show you', True)
      pg.wait_for_timeout(300)
      r['pos_after_stale_result'] = pg.evaluate("__tp.state.pos")
      r['stale_does_not_jump'] = r['pos_after_stale_result'] == -1
      # Second take: speak from the top again
      feed(pg, 'Hey everyone welcome back to the channel')
      r['after_second_take'] = wait_pos_at_least(pg, 4)
      r['tracks_after_reset'] = r['after_second_take']['pos'] >= 4
      r['scrolls_after_reset'] = r['after_second_take']['target'] > 0 or r['after_second_take']['offset'] > 0
      pg.screenshot(path=os.path.join(SHOT, f'voice-{label}-after-second-take.png'))
      results[label] = r
      ctx.close()
    b.close()
finally:
  srv.terminate()

print(json.dumps(results, indent=1))
print('CONSOLE ERRORS:', errors or 'none')

for label, r in results.items():
  if not r.get('listening_after_start'):
    failed.append(f'{label}: mic did not start')
  if not r.get('scrolled_on_first_take'):
    failed.append(f'{label}: first take did not advance ({r.get("after_first_take")})')
  if not r.get('mic_still_running'):
    failed.append(f'{label}: mic died after reset ({r.get("after_reset")})')
  if not r.get('same_session'):
    failed.append(f'{label}: recognizer was recreated after reset')
  if not r.get('stale_does_not_jump'):
    failed.append(f'{label}: leftover transcript jumped pos to {r.get("pos_after_stale_result")}')
  if not r.get('tracks_after_reset'):
    failed.append(f'{label}: did not follow speech after reset ({r.get("after_second_take")})')
  if not r.get('scrolls_after_reset'):
    failed.append(f'{label}: did not scroll after reset ({r.get("after_second_take")})')
if failed:
  print('FAILED:', failed)
  sys.exit(1)
print('VOICE RESET CHECKS: all passed')
