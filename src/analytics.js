import { CONFIG } from './config.js';

export function initAnalytics() {
  if (CONFIG.YANDEX_METRIKA_ID) {
    (function (m, e, t, r, i, k, a) {
      m[i] = m[i] || function () { (m[i].a = m[i].a || []).push(arguments); };
      m[i].l = 1 * new Date();
      k = e.createElement(t); a = e.getElementsByTagName(t)[0]; k.async = 1; k.src = r; a.parentNode.insertBefore(k, a);
    })(window, document, 'script', 'https://mc.yandex.ru/metrika/tag.js', 'ym');
    window.ym(CONFIG.YANDEX_METRIKA_ID, 'init', { clickmap: true, trackLinks: true, accurateTrackBounce: true, webvisor: true });
  }
  if (CONFIG.GOOGLE_ANALYTICS_ID) {
    const s = document.createElement('script');
    s.async = true;
    s.src = 'https://www.googletagmanager.com/gtag/js?id=' + CONFIG.GOOGLE_ANALYTICS_ID;
    document.head.appendChild(s);
    window.dataLayer = window.dataLayer || [];
    window.gtag = function () { window.dataLayer.push(arguments); };
    window.gtag('js', new Date());
    window.gtag('config', CONFIG.GOOGLE_ANALYTICS_ID);
  }
}

export function track(goal) {
  if (window.ym && CONFIG.YANDEX_METRIKA_ID) window.ym(CONFIG.YANDEX_METRIKA_ID, 'reachGoal', goal);
  if (window.gtag && CONFIG.GOOGLE_ANALYTICS_ID) window.gtag('event', goal);
}
