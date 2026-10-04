import { useEffect, useRef, useState } from 'react';
import ColorBends from './ColorBends.jsx';
import { CONFIG } from './config.js';
import { initAnalytics, track } from './analytics.js';
import { NAV, STATS, SERVICES, WHY, STEPS, CASES, REVIEWS, PLANS, FAQ } from './data.js';

/* Плавное появление при прокрутке; без IntersectionObserver блок сразу виден */
function Reveal({ as: Tag = 'div', className = '', children, ...rest }) {
  const ref = useRef(null);
  const [seen, setSeen] = useState(typeof IntersectionObserver === 'undefined');
  useEffect(() => {
    if (seen) return;
    const io = new IntersectionObserver(([e]) => {
      if (e.isIntersecting) { setSeen(true); io.disconnect(); }
    }, { threshold: 0.12 });
    io.observe(ref.current);
    return () => io.disconnect();
  }, [seen]);
  return <Tag ref={ref} className={`reveal ${seen ? 'in' : ''} ${className}`} {...rest}>{children}</Tag>;
}

const Ico = () => <span className="ico" aria-hidden="true" />;

function Header() {
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 10);
    window.addEventListener('scroll', on, { passive: true });
    return () => window.removeEventListener('scroll', on);
  }, []);
  return (
    <header className={'nav' + (scrolled ? ' scrolled' : '')}>
      <div className="wrap nav__in">
        <a href="#top" className="logo" aria-label="На главную"><span className="logo__dot" />AI·Бизнес</a>
        <nav className={'menu' + (open ? ' open' : '')} aria-label="Основное меню" onClick={(e) => e.target.tagName === 'A' && setOpen(false)}>
          {NAV.map(([h, t]) => <a key={h} href={h}>{t}</a>)}
        </nav>
        <a href="#contact" className="btn btn--sm nav__cta">Обсудить проект</a>
        <button className="burger" aria-label="Открыть меню" aria-expanded={open} onClick={() => setOpen(!open)}><span /><span /></button>
      </div>
    </header>
  );
}

function Hero() {
  return (
    <section className="hero">
      <ColorBends className="hero__bg" />
      <div className="wrap hero__in">
        <p className="eyebrow reveal in">Внедрение ИИ под ключ</p>
        <h1 className="reveal in">Освободим до 30 часов в неделю: внедрим ИИ в ваш бизнес за 14 дней</h1>
        <p className="lead reveal in">Автоматизируем рутину на Wildberries, Ozon и других площадках, в продажах, поддержке и контенте — так, чтобы команда занималась ростом, а не копированием между вкладками.</p>
        <div className="hero__cta reveal in">
          <a href="#contact" className="btn">Получить бесплатный аудит</a>
          <a href="#services" className="btn btn--ghost">Что можем автоматизировать</a>
        </div>
        <ul className="stats reveal in">
          {STATS.map(([b, s]) => <li key={b}><b>{b}</b><span>{s}</span></li>)}
        </ul>
      </div>
    </section>
  );
}

function ContactForm({ plan, setPlan }) {
  const [msg, setMsg] = useState({ text: '', cls: '' });
  const [busy, setBusy] = useState(false);
  const [bad, setBad] = useState({});

  async function onSubmit(e) {
    e.preventDefault();
    const f = e.currentTarget;
    const fd = new FormData(f);
    if (fd.get('website')) return; // honeypot
    const name = String(fd.get('name') || '').trim();
    const contact = String(fd.get('contact') || '').trim();
    const nb = { name: name.length < 2, contact: contact.length < 2 };
    setBad(nb);
    if (nb.name || nb.contact || !fd.get('agree')) {
      setMsg({ text: 'Заполните имя, контакт и подтвердите согласие.', cls: 'err' });
      return;
    }
    const data = { name, contact, plan, comment: String(fd.get('comment') || '').trim(), page: location.href };
    setBusy(true); setMsg({ text: 'Отправляем…', cls: '' });
    try {
      if (CONFIG.FORM_ENDPOINT) {
        const r = await fetch(CONFIG.FORM_ENDPOINT, { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' }, body: JSON.stringify(data) });
        if (!r.ok) throw new Error('bad status');
      } else {
        console.info('Заявка (демо-режим, FORM_ENDPOINT не задан):', data);
        await new Promise((r) => setTimeout(r, 400));
      }
      track('lead_submit');
      f.reset(); setPlan('Не определился');
      setMsg({ text: 'Спасибо! Заявка отправлена — свяжемся в течение рабочего дня.', cls: 'ok' });
    } catch {
      setMsg({ text: 'Не удалось отправить. Попробуйте ещё раз или напишите нам напрямую.', cls: 'err' });
    }
    setBusy(false);
  }

  return (
    <form className="form reveal in" onSubmit={onSubmit} noValidate>
      <label>Имя
        <input type="text" name="name" autoComplete="name" placeholder="Как к вам обращаться" className={bad.name ? 'invalid' : ''} />
      </label>
      <label>Телефон или Telegram
        <input type="text" name="contact" autoComplete="tel" placeholder="+7 ... или @username" className={bad.contact ? 'invalid' : ''} />
      </label>
      <label>Тариф
        <select name="plan" value={plan} onChange={(e) => setPlan(e.target.value)}>
          <option value="Не определился">Пока не определился</option>
          {PLANS.map((p) => <option key={p.n}>{p.n}</option>)}
        </select>
      </label>
      <label>Коротко о задаче
        <textarea name="comment" rows="3" placeholder="Например: 300 SKU на WB и Ozon, нужны карточки и ответы на отзывы" />
      </label>
      <label className="check"><input type="checkbox" name="agree" /> Согласен на обработку персональных данных</label>
      <input type="text" name="website" className="hp" tabIndex={-1} autoComplete="off" aria-hidden="true" />
      <button className="btn btn--block" type="submit" disabled={busy}>Отправить заявку</button>
      <p className={'form__msg ' + msg.cls} role="status" aria-live="polite">{msg.text}</p>
    </form>
  );
}

export default function App() {
  const [plan, setPlan] = useState('Не определился');
  useEffect(initAnalytics, []);

  return (
    <>
      <a className="skip" href="#top">К содержимому</a>
      <Header />
      <main id="top">
        <Hero />

        <section className="sec" id="about">
          <div className="wrap grid2">
            <div>
              <Reveal as="p" className="eyebrow">О продукте</Reveal>
              <Reveal as="h2">Не «чат-бот ради галочки», а работающие процессы</Reveal>
            </div>
            <Reveal>
              <p>Мы находим в вашем бизнесе повторяющиеся операции, где ИИ даёт измеримый эффект, и встраиваем его в инструменты, которыми вы уже пользуетесь: личные кабинеты маркетплейсов, CRM, таблицы, мессенджеры.</p>
              <p>Вы получаете настроенные сценарии, инструкции и обучение команды — и понимаете, сколько времени и денег это экономит.</p>
            </Reveal>
          </div>
        </section>

        <section className="sec sec--alt" id="services">
          <div className="wrap">
            <Reveal as="p" className="eyebrow">Услуги</Reveal>
            <Reveal as="h2">Где ИИ уже приносит деньги</Reveal>
            <div className="cards">
              {SERVICES.map((s) => (
                <Reveal as="article" key={s.t} className={'card' + (s.lead ? ' card--lead' : '')}>
                  <Ico /><h3>{s.t}</h3><p>{s.d}</p>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        <section className="sec" id="why">
          <div className="wrap">
            <Reveal as="p" className="eyebrow">Почему выбирают нас</Reveal>
            <Reveal as="h2">Результат для бизнеса, а не набор технологий</Reveal>
            <div className="cards cards--3">
              {WHY.map(([t, d]) => (
                <Reveal as="article" key={t} className="card card--flat"><Ico /><h3>{t}</h3><p>{d}</p></Reveal>
              ))}
            </div>
          </div>
        </section>

        <section className="sec sec--alt" id="process">
          <div className="wrap">
            <Reveal as="p" className="eyebrow">Как работаем</Reveal>
            <Reveal as="h2">Четыре шага от заявки до результата</Reveal>
            <ol className="steps">
              {STEPS.map(([t, d], i) => (
                <Reveal as="li" key={t}><span className="steps__n">0{i + 1}</span><h3>{t}</h3><p>{d}</p></Reveal>
              ))}
            </ol>
          </div>
        </section>

        <section className="sec" id="cases">
          <div className="wrap">
            <Reveal as="p" className="eyebrow">Кейсы</Reveal>
            <Reveal as="h2">Типовые сценарии внедрения</Reveal>
            <Reveal as="p" className="note">Ниже — примеры задач, которые мы решаем. Реальные кейсы с цифрами клиентов добавляются по мере согласования публикации.</Reveal>
            <div className="cards cards--3">
              {CASES.map((c) => (
                <Reveal as="article" key={c.t} className="case">
                  <span className="tag">{c.tag}</span>
                  <h3>{c.t}</h3>
                  <p><b>Задача:</b> {c.task}<br /><b>Решение:</b> {c.sol}</p>
                  <p className="case__res">Результат: {c.res}</p>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        <section className="sec sec--alt" id="reviews">
          <div className="wrap">
            <Reveal as="p" className="eyebrow">Отзывы</Reveal>
            <Reveal as="h2">Что говорят клиенты</Reveal>
            <div className="cards cards--3">
              {REVIEWS.map((r, i) => (
                <Reveal as="figure" key={i} className="review">
                  <div className="review__ph" aria-hidden="true">Фото</div>
                  <blockquote>«{r.q}»</blockquote>
                  <figcaption><b>{r.name}</b><span>{r.co}</span></figcaption>
                  <p className="review__res">Результат: {r.res}</p>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        <section className="sec" id="pricing">
          <div className="wrap">
            <Reveal as="p" className="eyebrow">Тарифы</Reveal>
            <Reveal as="h2">Выберите формат работы</Reveal>
            <Reveal as="p" className="note">Цены ориентировочные — точную стоимость назовём после аудита.</Reveal>
            <div className="plans">
              {PLANS.map((p) => (
                <Reveal as="article" key={p.n} className={'plan' + (p.hot ? ' plan--hot' : '')}>
                  {p.hot && <span className="badge">Популярный</span>}
                  <h3>{p.n}</h3>
                  <p className="plan__for">{p.who}</p>
                  <p className="plan__price">{p.price}</p>
                  <ul>{p.items.map((it) => <li key={it}>{it}</li>)}</ul>
                  <a href="#contact" className={'btn' + (p.hot ? '' : ' btn--ghost')} onClick={() => { setPlan(p.n); track('select_plan'); }}>Выбрать</a>
                </Reveal>
              ))}
            </div>

            <div className="faq" id="faq">
              <Reveal as="h2">Частые вопросы</Reveal>
              {FAQ.map(([q, a]) => (
                <Reveal as="details" key={q}><summary>{q}</summary><p>{a}</p></Reveal>
              ))}
            </div>
          </div>
        </section>

        <section className="sec sec--cta" id="contact">
          <div className="wrap grid2">
            <div>
              <Reveal as="p" className="eyebrow">Следующий шаг</Reveal>
              <Reveal as="h2">Расскажите о задаче — вернёмся с планом внедрения</Reveal>
              <Reveal as="p">Оставьте заявку, и мы свяжемся в течение рабочего дня, чтобы назначить бесплатный созвон.</Reveal>
            </div>
            <ContactForm plan={plan} setPlan={setPlan} />
          </div>
        </section>
      </main>

      <footer className="footer">
        <div className="wrap footer__in">
          <a href="#top" className="logo"><span className="logo__dot" />AI·Бизнес</a>
          <p>© {new Date().getFullYear()} Внедрение ИИ в бизнес. Все права защищены.</p>
          <p><a href="#contact">Связаться с нами</a></p>
        </div>
      </footer>
    </>
  );
}
