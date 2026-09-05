/* BlindSp0t — interactions : splash d'intro + diaporamas */
(function () {
  // --- Splash d'intro (une fois par session) ---
  var splash = document.getElementById('splash');
  if (splash) {
    var seen = false;
    try { seen = sessionStorage.getItem('bsp0t_splash') === '1'; } catch (e) {}
    if (seen) {
      splash.parentNode && splash.parentNode.removeChild(splash);
    } else {
      var hide = function () {
        splash.classList.add('hide');
        try { sessionStorage.setItem('bsp0t_splash', '1'); } catch (e) {}
        setTimeout(function () { splash.parentNode && splash.parentNode.removeChild(splash); }, 900);
      };
      setTimeout(hide, 1600);
      splash.addEventListener('click', hide);
    }
  }

  // --- Diaporamas ---
  document.querySelectorAll('.gallery[data-slideshow]').forEach(function (g) {
    var slides = Array.prototype.slice.call(g.querySelectorAll('.slide'));
    if (slides.length === 0) return;
    var dots = Array.prototype.slice.call(g.querySelectorAll('.dot'));
    var i = 0, timer = null;
    var speed = parseFloat(g.getAttribute('data-speed')) || 0;
    var autoplay = g.getAttribute('data-autoplay') === '1';

    function show(n) {
      i = (n + slides.length) % slides.length;
      slides.forEach(function (s, k) { s.classList.toggle('active', k === i); });
      dots.forEach(function (d, k) { d.classList.toggle('active', k === i); });
    }
    function next() { show(i + 1); }
    function prev() { show(i - 1); }
    function start() { if (autoplay && speed > 0 && slides.length > 1) { stop(); timer = setInterval(next, speed * 1000); } }
    function stop() { if (timer) { clearInterval(timer); timer = null; } }

    var l = g.querySelector('.arrow.left'), r = g.querySelector('.arrow.right');
    if (l) l.addEventListener('click', function () { prev(); start(); });
    if (r) r.addEventListener('click', function () { next(); start(); });
    dots.forEach(function (d, k) { d.addEventListener('click', function () { show(k); start(); }); });
    g.addEventListener('mouseenter', stop);
    g.addEventListener('mouseleave', start);

    show(0);
    start();
  });
})();
