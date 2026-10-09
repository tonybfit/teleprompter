import json, subprocess, time, sys, os
from playwright.sync_api import sync_playwright
os.chdir(os.path.dirname(os.path.abspath(__file__)) + '/..')
srv = subprocess.Popen([sys.executable, '-m', 'http.server', '8765'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1)
errors, results = [], {}
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
      pg.keyboard.press('r'); r['reset_offset'] = pg.evaluate("__tp.state.offset")
      # voice-mode position highlight + smooth scroll (simulate matcher result)
      pg.click('#modeVoice')
      pg.evaluate("__tp.setPos(60,false)"); pg.wait_for_timeout(1500)
      r['voice_cur_word'] = pg.evaluate("document.querySelector('.w.cur').textContent")
      r['voice_cur_y_frac'] = pg.evaluate("(()=>{const e=document.querySelector('.w.cur').getBoundingClientRect();return +((e.top+e.height/2)/document.getElementById('stage').clientHeight).toFixed(3)})()")
      r['past_words_dimmed'] = pg.evaluate("document.querySelectorAll('.w.past').length")
      r['persist_after_reload'] = None
      pg.screenshot(path=f'screenshot{"" if label=="desktop" else "-iphone"}.png')
      pg.reload(); pg.wait_for_timeout(300)
      r['persist_after_reload'] = pg.evaluate("[localStorage.getItem('tp.fs'), document.getElementById('script').value.slice(0,20)]")
      results[label] = r; ctx.close()
    # file:// check: message for insecure context? (file is secure-ish in chrome) just record
    b.close()
finally:
  srv.terminate()
print(json.dumps(results, indent=1)); print('CONSOLE ERRORS:', errors or 'none')
