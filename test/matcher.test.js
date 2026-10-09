// Unit tests for TPMatch (extracted from teleprompter.html <script id="matcher">)
const fs = require('fs'), path = require('path'), assert = require('assert');
const html = fs.readFileSync(path.join(__dirname, '..', 'teleprompter.html'), 'utf8');
const src = html.match(/<script id="matcher">([\s\S]*?)<\/script>/)[1];
const m = { exports: {} }; new Function('module', src)(m); const T = m.exports;

const SCRIPT = `Hey everyone, welcome back to the channel. Today I want to show you something simple that has made
recording videos a lot easier for me. This is a teleprompter that listens to my voice and scrolls along as I talk.
If I slow down, it waits for me. If I skip a few words, it catches up. You can paste any script, make the text
bigger or smaller, and mirror it for teleprompter glass. That's it for today. Thanks for watching, and I'll see you in the next one.`;
const S = T.tokenize(SCRIPT);
let pass = 0, fail = 0;
function test(name, fn) { try { fn(); pass++; console.log('  ok  ', name); } catch (e) { fail++; console.log('  FAIL', name, '\n       ', e.message); } }
// Simulate a recognizer session: words arrive one at a time (interim growth); return position after each
function speak(text, startPos = -1, opts) {
  const words = T.tokenize(text); let pos = startPos; const trace = [];
  for (let i = 1; i <= words.length; i++) { const r = T.advance(S, words.slice(0, i).slice(-12), pos, opts); pos = r.pos; trace.push(pos); }
  return { pos, trace };
}
const idx = (w, from = 0) => S.indexOf(w, from);

test('tokenize normalizes case/punctuation/numbers/hyphens', () => {
  assert.deepStrictEqual(T.tokenize("That's it -- Five well-known DON'T!"), ['thats', 'it', '5', 'well', 'known', 'dont']);
});
test('perfect reading tracks every word', () => {
  const { pos, trace } = speak('hey everyone welcome back to the channel today I want to show you');
  assert.strictEqual(pos, idx('you'));
  for (let i = 1; i < trace.length; i++) assert.ok(trace[i] >= trace[i - 1], 'never backward');
});
test('full script read lands at the last word', () => {
  assert.strictEqual(speak(SCRIPT).pos, S.length - 1);
});
test('skipped words (speaker drops 3 words) still advances', () => {
  // script: "something simple that has made recording videos" -> skip "that has made"
  const start = idx('show') ; const r = speak('show you something simple recording videos a lot', start);
  assert.strictEqual(r.pos, idx('lot'));
});
test('misheard words (recognizer substitutions) still advances', () => {
  const start = idx('teleprompter') - 1;
  // "teleprompter"->"tele prompter", "listens"->"lessons", "scrolls"->"rolls"
  const r = speak('a tele prompter that lessons to my voice and rolls along as I talk', start);
  assert.strictEqual(r.pos, idx('talk'));
});
test('extra filler words (um, uh, "you know") are tolerated', () => {
  const start = idx('slow') - 3;
  const r = speak('if I um slow down uh it waits for me you know', start);
  assert.ok(r.pos >= idx('me', idx('waits')) , 'pos=' + r.pos + ' (' + S[r.pos] + ')');
});
test('silence / unrelated chatter does not move', () => {
  const start = idx('paste');
  const r = speak('okay hold on let me grab some water real quick', start);
  assert.strictEqual(r.pos, start);
});
test('single stopword does not jump ahead', () => {
  const start = idx('channel');
  const r = T.advance(S, ['the'], start);
  assert.strictEqual(r.pos, start);
});
test('repeated phrase prefers nearest occurrence ("for me")', () => {
  const start = idx('easier'); // first "for me" right after "easier"
  const r = speak('for me', start);
  assert.strictEqual(r.pos, idx('me', start));
});
test('never jumps backward when speaker repeats an earlier sentence', () => {
  const start = idx('glass');
  const r = speak('welcome back to the channel', start);
  assert.strictEqual(r.pos, start);
});
test('re-start after recognizer restart (new session, partial tail) keeps going', () => {
  let pos = speak('hey everyone welcome back to the channel').pos;
  pos = speak('today I want to show you', pos).pos; // new session: spoken buffer reset
  assert.strictEqual(pos, idx('you'));
});
test('skipping a whole sentence (far jump) works with strong evidence', () => {
  const start = idx('talk');
  // skip "If I slow down, it waits for me. If I skip a few words, it catches up."
  const r = speak('you can paste any script make the text', start);
  assert.strictEqual(r.pos, idx('text'));
});
test('number words match digits', () => {
  const S2 = T.tokenize('I have 3 tips for you today');
  assert.strictEqual(T.advance(S2, T.tokenize('i have three tips'), -1).pos, 3);
});
test('fuzzy sim rules', () => {
  assert.strictEqual(T.sim('the', 'tho'), 0);
  assert.ok(T.sim('recording', 'recordings') > 0.7);
  assert.ok(T.sim('teleprompter', 'teleprompters') > 0.7);
  assert.strictEqual(T.sim('glass', 'grass') > 0, true);
});
test('noisy simulation: 15% dropped + 10% misheard words, 5 sessions', () => {
  let seed = 7; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const junk = ['blue', 'cart', 'zebra', 'piano', 'walrus'];
  for (let run = 0; run < 5; run++) {
    const said = []; S.forEach(w => { const r = rnd(); if (r < 0.15) return; said.push(r < 0.25 ? junk[Math.floor(rnd() * 5)] : w); });
    // recognizer restarts every ~15 words (buffer reset)
    let pos = -1, worstLag = 0, k = 0;
    for (let i = 0; i < said.length; i += 15) {
      const chunk = said.slice(i, i + 15);
      for (let j = 1; j <= chunk.length; j++) pos = T.advance(S, chunk.slice(0, j).slice(-12), pos).pos;
    }
    assert.ok(pos >= S.length - 3, `run ${run}: ended at ${pos}/${S.length - 1}`);
  }
});
console.log(`\n${pass} passed, ${fail} failed`); process.exit(fail ? 1 : 0);
