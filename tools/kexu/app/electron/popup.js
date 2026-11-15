let remaining = 12000, started = Date.now(), timer, hovered = false;
const card = document.querySelector('article');
const dismiss = () => window.reminderPopup.action('dismiss');
function resume() { started = Date.now(); timer = setTimeout(dismiss, remaining); }
card.addEventListener('mouseenter', () => { hovered = true; clearTimeout(timer); remaining = Math.max(0, remaining - (Date.now() - started)); });
card.addEventListener('mouseleave', () => { if (hovered) { hovered = false; resume(); } });
document.querySelectorAll('[data-action]').forEach(button => button.addEventListener('click', async () => {
  button.disabled = true;
  try { await window.reminderPopup.action(button.dataset.action); } catch { button.disabled = false; }
}));
window.reminderPopup.content().then(reminder => {
  if (!reminder) return dismiss();
  document.getElementById('title').textContent = reminder.title;
  document.getElementById('body').textContent = reminder.body;
  document.querySelector('.content').title = reminder.title + '\n' + reminder.body;
  try { if (reminder.sound) {
    const audio = new AudioContext();
    [660, 880].forEach((frequency, i) => {
      const tone = audio.createOscillator(), volume = audio.createGain(), at = audio.currentTime + i * .16;
      tone.frequency.value = frequency; volume.gain.setValueAtTime(0, at); volume.gain.linearRampToValueAtTime(.08, at + .02); volume.gain.exponentialRampToValueAtTime(.001, at + .24);
      tone.connect(volume); volume.connect(audio.destination); tone.start(at); tone.stop(at + .25);
    });
    setTimeout(() => audio.close(), 1000);
  } } catch (error) { console.error('Reminder sound unavailable', error); }
  resume();
});
