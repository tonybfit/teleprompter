import json, subprocess, time, sys, os
from playwright.sync_api import sync_playwright

os.chdir(os.path.dirname(os.path.abspath(__file__)) + '/..')
SHOT_DIR = '/workspace/teleprompter-reset'
os.makedirs(SHOT_DIR, exist_ok=True)

srv = subprocess.Popen([sys.executable, '-m', 'http.server', '8765'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1)
errors, results = [], {}

def wait_reset(pg, timeout_ms=2500):
  """Wait until smooth reset has landed at the top with voice position cleared."""
  pg.wait_for_function(
    """() => {
      const s = window.__tp.state;
      const t = document.getElementById('content').style.transform || '';
      const atTop = Math.abs(s.offset) < 0.05 && Math.abs(s.target) < 0.05 && s.pos === -1;
      const tx = t.includes('0px') || t.includes('0.0px') || Math.abs(s.offset) < 0.5;
      return atTop && tx;
    }""",
    timeout=timeout_ms,
  )
  return pg.evaluate("""() => {
    const s = window.__tp.state;
    const el = document.getElementById('content');
    const st = document.getElementById('stage');
    return {
      offset: s.offset,
      target: s.target,
      pos: s.pos,
      scrollTop: el.scrollTop,
      stageScrollTop: st.scrollTop,
      transform: el.style.transform,
      cur: document.querySelectorAll('.w.cur').length,
      past: document.querySelectorAll('.w.past').length,
      resetLabel: document.getElementById('resetBtn').textContent.trim(),
      resetVisible: (() => {
        const b = document.getElementById('resetBtn');
        const r = b.getBoundingClientRect();
        const cs = getComputedStyle(b);
        return r.width > 80 && r.height >= 44 && cs.visibility !== 'hidden' && cs.display !== 'none';
      })(),
      resetInFlip: !!document.getElementById('flip').contains(document.getElementById('resetBtn')),
    };
  }""")

try:
  with sync_playwright() as p:
    b = p.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--use-fake-ui-for-media-stream'])
    for label, ctxargs in [('desktop', dict(viewport={'width':1280,'height':800})),
                           ('iphone', dict(**p.devices['iPhone 13']))]:
      ctxargs = {k:v for k,v in ctxargs.items() if k != 'default_browser_type'}
      ctx = b.new_context(**ctxargs); pg = ctx.new_page()
      pg.on('console', lambda m: m.type == 'error' and errors.append(f'{label}: {m.text}'))
      pg.on('pageerror', lambda e: errors.append(f'{label} pageerror: {e}'))
      pg.goto('http://localhost:8765/teleprompter.html'); pg.wait_for_timeout(300)
      r = {}
      r['help_visible_first_run'] = pg.is_visible('#help')
      pg.click('#sampleBtn'); pg.click('#toPrompt'); pg.wait_for_timeout(300)
      r['prompt_visible'] = pg.is_visible('#prompt') and not pg.is_visible('#edit')
      r['words'] = pg.evaluate("document.querySelectorAll('#content .w').length")
      r['speech_api'] = pg.evaluate("!!(window.SpeechRecognition||window.webkitSpeechRecognition)")
      r['reset_btn_visible_on_prompt'] = pg.is_visible('#resetBtn')
      r['reset_btn_label'] = pg.evaluate("document.getElementById('resetBtn').textContent.trim()")
      # mirror
      pg.keyboard.press('m'); r['mirror_transform'] = pg.evaluate("getComputedStyle(document.getElementById('flip')).transform")
      pg.keyboard.press('m')
      pg.click('#mirrorY'); r['flipY_transform'] = pg.evaluate("getComputedStyle(document.getElementById('flip')).transform"); pg.click('#mirrorY')
      # size
      fs0 = pg.evaluate("__tp.state.fs"); pg.keyboard.press('+'); pg.click('#aPlus'); fs1 = pg.evaluate("__tp.state.fs")
      pg.keyboard.press('-'); fs2 = pg.evaluate("__tp.state.fs")
      r['size'] = [fs0, fs1, fs2]; r['size_persisted'] = pg.evaluate("localStorage.getItem('tp.fs')")
      r['css_fs'] = pg.evaluate("getComputedStyle(document.getElementById('content')).fontSize")
      # manual scroll
      pg.click('#modeAuto'); pg.evaluate("__tp.state.speed=200")
      o0 = pg.evaluate("__tp.state.offset"); pg.keyboard.press(' '); pg.wait_for_timeout(1500)
      o1 = pg.evaluate("__tp.state.offset"); r['running_after_space'] = pg.evaluate("__tp.state.running")
      r['bar_autohid'] = None
      pg.keyboard.press(' '); o2 = pg.evaluate("__tp.state.offset"); pg.wait_for_timeout(500); o3 = pg.evaluate("__tp.state.offset")
      r['auto_scroll'] = dict(start=o0, after1500ms=round(o1), paused_holds=abs(o3-o2) < 1)
      pg.keyboard.press('ArrowDown'); r['nudge_down_delta'] = round(pg.evaluate("__tp.state.offset") - o3)
      # R key still resets (now smooth)
      pg.keyboard.press('r')
      r['reset_via_r'] = wait_reset(pg)
      # voice-mode position highlight + smooth scroll (simulate matcher result)
      pg.click('#modeVoice')
      pg.evaluate("__tp.setPos(60,false)"); pg.wait_for_timeout(1500)
      r['voice_cur_word'] = pg.evaluate("document.querySelector('.w.cur').textContent")
      r['voice_cur_y_frac'] = pg.evaluate("(()=>{const e=document.querySelector('.w.cur').getBoundingClientRect();return +((e.top+e.height/2)/document.getElementById('stage').clientHeight).toFixed(3)})()")
      r['past_words_dimmed'] = pg.evaluate("document.querySelectorAll('.w.past').length")
      mid_offset = pg.evaluate("__tp.state.offset")
      r['scrolled_down_before_reset'] = mid_offset > 50
      # screenshot mid-script, then click Reset
      pg.screenshot(path=os.path.join(SHOT_DIR, f'{label}-before-reset.png'))
      pg.click('#resetBtn')
      r['reset_via_button'] = wait_reset(pg)
      r['reset_moved_from_mid'] = mid_offset > 50 and r['reset_via_button']['offset'] < 0.05
      pg.screenshot(path=os.path.join(SHOT_DIR, f'{label}-after-reset.png'))
      # Home key also resets after scrolling again
      pg.evaluate("__tp.setPos(40,true)"); pg.wait_for_timeout(200)
      r['pos_before_home'] = pg.evaluate("__tp.state.pos")
      pg.keyboard.press('Home')
      r['reset_via_home'] = wait_reset(pg)
      # short ArrowUp still nudges (from a mid position); long-press resets
      pg.evaluate("__tp.setPos(30,true)"); pg.wait_for_timeout(100)
      pos_before_nudge = pg.evaluate("__tp.state.pos")
      pg.keyboard.press('ArrowUp')  # keydown+keyup, hold shorter than 0.8s
      pg.wait_for_timeout(200)
      r['short_up_nudges'] = pg.evaluate("__tp.state.pos") < pos_before_nudge and pg.evaluate("__tp.state.pos") != -1
      pg.evaluate("__tp.setPos(30,true)"); pg.wait_for_timeout(100)
      pg.keyboard.down('ArrowUp'); pg.wait_for_timeout(950); pg.keyboard.up('ArrowUp')
      r['reset_via_hold_up'] = wait_reset(pg)
      # existing feature still works after reset: mirror toggle
      pg.keyboard.press('m')
      r['mirror_still_works_after_reset'] = pg.evaluate("!!__tp.state.mirrorX")
      pg.keyboard.press('m')
      r['persist_after_reload'] = None
      # also keep a repo-root screenshot name for backward compatibility (not committed)
      pg.screenshot(path=f'screenshot{"" if label=="desktop" else "-iphone"}.png')
      pg.reload(); pg.wait_for_timeout(300)
      r['persist_after_reload'] = pg.evaluate("[localStorage.getItem('tp.fs'), document.getElementById('script').value.slice(0,20)]")
      results[label] = r; ctx.close()
    b.close()
finally:
  srv.terminate()
print(json.dumps(results, indent=1)); print('CONSOLE ERRORS:', errors or 'none')

# Fail the script if reset checks didn't land at the top
failed = []
for label, r in results.items():
  for key in ('reset_via_r', 'reset_via_button', 'reset_via_home', 'reset_via_hold_up'):
    got = r.get(key) or {}
    if not (got.get('pos') == -1 and abs(got.get('offset', 99)) < 0.05 and got.get('cur') == 0 and got.get('past') == 0):
      failed.append(f'{label}.{key}={got}')
  if r.get('reset_btn_label') != 'Reset':
    failed.append(f'{label}.label={r.get("reset_btn_label")}')
  if not r.get('reset_btn_visible_on_prompt'):
    failed.append(f'{label}.reset not visible')
  if not r.get('reset_moved_from_mid'):
    failed.append(f'{label}.did not scroll down before reset')
  if not r.get('short_up_nudges'):
    failed.append(f'{label}.short ArrowUp should still nudge')
  if r.get('reset_via_button', {}).get('resetInFlip'):
    failed.append(f'{label}.Reset was inside the mirrored layer')
if failed:
  print('RESET CHECKS FAILED:', failed)
  sys.exit(1)
print('RESET CHECKS: all passed')
