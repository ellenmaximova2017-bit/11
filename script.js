(function () {
  'use strict';

  // ===== Настройки (заполните своими значениями) =====
  var CONFIG = {
    YANDEX_METRIKA_ID: '',   // например 12345678
    GOOGLE_ANALYTICS_ID: '', // например G-XXXXXXXXXX
    FORM_ENDPOINT: ''        // URL приёма заявок (Formspree, свой бэкенд, Google Apps Script и т.п.)
  };

  // ===== Аналитика =====
  if (CONFIG.YANDEX_METRIKA_ID) {
    (function (m, e, t, r, i, k, a) {
      m[i] = m[i] || function () { (m[i].a = m[i].a || []).push(arguments); };
      m[i].l = 1 * new Date();
      k = e.createElement(t); a = e.getElementsByTagName(t)[0]; k.async = 1; k.src = r; a.parentNode.insertBefore(k, a);
    })(window, document, 'script', 'https://mc.yandex.ru/metrika/tag.js', 'ym');
    window.ym(CONFIG.YANDEX_METRIKA_ID, 'init', { clickmap: true, trackLinks: true, accurateTrackBounce: true, webvisor: true });
  }
  if (CONFIG.GOOGLE_ANALYTICS_ID) {
    var gs = document.createElement('script');
    gs.async = true;
    gs.src = 'https://www.googletagmanager.com/gtag/js?id=' + CONFIG.GOOGLE_ANALYTICS_ID;
    document.head.appendChild(gs);
    window.dataLayer = window.dataLayer || [];
    window.gtag = function () { window.dataLayer.push(arguments); };
    window.gtag('js', new Date());
    window.gtag('config', CONFIG.GOOGLE_ANALYTICS_ID);
  }
  function track(goal) {
    if (window.ym && CONFIG.YANDEX_METRIKA_ID) window.ym(CONFIG.YANDEX_METRIKA_ID, 'reachGoal', goal);
    if (window.gtag && CONFIG.GOOGLE_ANALYTICS_ID) window.gtag('event', goal);
  }

  // ===== Меню =====
  var nav = document.getElementById('nav');
  var burger = document.getElementById('burger');
  var menu = document.getElementById('menu');
  function closeMenu() { menu.classList.remove('open'); burger.setAttribute('aria-expanded', 'false'); }
  burger.addEventListener('click', function () {
    var open = menu.classList.toggle('open');
    burger.setAttribute('aria-expanded', String(open));
  });
  menu.addEventListener('click', function (e) { if (e.target.tagName === 'A') closeMenu(); });
  window.addEventListener('scroll', function () { nav.classList.toggle('scrolled', window.scrollY > 10); }, { passive: true });

  // ===== Плавное появление секций =====
  var items = document.querySelectorAll('.reveal');
  if ('IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { en.target.classList.add('in'); io.unobserve(en.target); }
      });
    }, { threshold: 0.12 });
    items.forEach(function (el, i) { el.style.transitionDelay = (i % 3) * 80 + 'ms'; io.observe(el); });
  } else {
    items.forEach(function (el) { el.classList.add('in'); });
  }

  // ===== Выбор тарифа =====
  var form = document.getElementById('lead-form');
  document.querySelectorAll('[data-plan]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      form.elements.plan.value = btn.getAttribute('data-plan');
      track('select_plan');
    });
  });

  // ===== Форма =====
  var msg = document.getElementById('form-msg');
  function setMsg(text, cls) { msg.textContent = text; msg.className = 'form__msg ' + (cls || ''); }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    if (form.elements.website.value) return; // honeypot

    var bad = false;
    ['name', 'contact'].forEach(function (n) {
      var f = form.elements[n];
      var ok = f.value.trim().length >= 2;
      f.classList.toggle('invalid', !ok);
      if (!ok) bad = true;
    });
    if (!form.elements.agree.checked) bad = true;
    if (bad) { setMsg('Заполните имя, контакт и подтвердите согласие.', 'err'); return; }

    var data = {
      name: form.elements.name.value.trim(),
      contact: form.elements.contact.value.trim(),
      plan: form.elements.plan.value,
      comment: form.elements.comment.value.trim(),
      page: location.href
    };
    var btn = form.querySelector('button[type=submit]');
    btn.disabled = true; setMsg('Отправляем…');

    function done() {
      track('lead_submit');
      form.reset();
      setMsg('Спасибо! Заявка отправлена — свяжемся в течение рабочего дня.', 'ok');
      btn.disabled = false;
    }
    function fail() {
      setMsg('Не удалось отправить. Попробуйте ещё раз или напишите нам напрямую.', 'err');
      btn.disabled = false;
    }

    if (!CONFIG.FORM_ENDPOINT) { // демо-режим, пока не подключён приём заявок
      console.info('Заявка (демо-режим, FORM_ENDPOINT не задан):', data);
      setTimeout(done, 400);
      return;
    }
    fetch(CONFIG.FORM_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify(data)
    }).then(function (r) { r.ok ? done() : fail(); }).catch(fail);
  });

  document.getElementById('year').textContent = new Date().getFullYear();
})();
