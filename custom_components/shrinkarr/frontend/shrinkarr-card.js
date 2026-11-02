// Shrinkarr card for Home Assistant. Served by the Shrinkarr integration (custom_components/shrinkarr); no build step.
// type: custom:shrinkarr-card, variant: full | compact | kept | gpu, optional url (link target), language (nl | en) and entry_id.
const VERSION = new URL(import.meta.url).searchParams.get('v') || '';  // the integration's version, from the script URL
const VARIANTS = ['full', 'compact', 'kept', 'gpu'];

const STR = {
  en: {
    'v.full': 'Overview', 'v.compact': 'Compact', 'v.kept': 'Kept originals', 'v.gpu': 'Graphics card',
    'f.variant': 'Card', 'f.language': 'Language', 'l.auto': 'Like Home Assistant', 'f.url': 'Link to Shrinkarr (optional)', 'f.urlHelp': 'Opened when you tap the title. Empty = the address of the integration.',
    'st.running': 'Converting', 'st.pausing': 'Pausing after this conversion', 'st.paused': 'Paused',
    'st.waiting': 'Waiting for the time window', 'st.waiting_auto': 'Waiting for the automatic window', 'st.idle': 'All done',
    'st.idleQueue': 'Idle', 'st.setup': 'Not set up yet',
    'chip.active': 'active', 'chip.paused': 'paused', 'chip.busy': 'busy',
    queued: '{n} in the queue', queueEmpty: 'The queue is empty', together: 'total ~{t}', left: '{t} left', thenPause: 'then pause',
    toGain: 'to gain', toSave: 'To save', saved: 'Saved', remains: 'Remains', toSaveShort: 'to save', savedShort: 'saved',
    library: 'Library', encTime: 'Encode time', todo: 'To do', titles: '{n} titles', done: 'Done', files: '{n} files',
    quality: 'Quality: {q}', 'p.high': 'High quality', 'p.balanced': 'Balanced', 'p.max': 'Maximum savings',
    pause: 'Pause', resume: 'Resume', startNow: 'Start now', nothing: 'Nothing to convert', pausedLine: 'Paused',
    keptTitle: '{n} originals kept', keptTitle1: '1 original kept', keptSub: '{size} · kept {d} days', keptNone: 'No kept originals',
    keptOff: 'Keeping originals is off (Shrinkarr → Settings → Encoding)', firstGone: 'First one deleted', freed: 'Freed',
    keptFoot: 'Until then a conversion can be undone', purgeAll: 'Delete now', purgeShort: 'Now', purgeAsk: 'Delete {size} now?',
    yes: 'Yes', no: 'No', keptLine: '{n} originals · {size}', goneFrom: 'gone from {d}', today: 'now',
    gpuEncoding: 'converting now', gpuIdle: 'idle', busy: 'busy', temp: 'Temperature', clock: 'Clock speed', cpu: 'Processor',
    throttled: 'Limited', no_: 'no', power: 'Power limit ({r})', hot: 'Too hot',
    'e.render': 'Render', 'e.video': 'Video', 'e.video-enhance': 'Enhance', 'e.copy': 'Copy', 'e.encoder': 'Encoder', 'e.decoder': 'Decoder',
    'enc.qsv': 'Intel Quick Sync', 'enc.vaapi': 'VA-API', 'enc.nvenc': 'NVIDIA NVENC', 'enc.cpu': 'Processor (software)',
    'stage.analyze': 'Analysing', 'stage.cc': 'Extracting captions', 'stage.verify': 'Verifying', 'stage.wait_plex': 'Waiting: being watched in Plex',
    'stage.replace': 'Replacing', 'stage.update': 'Updating the library',
    offline: 'Shrinkarr can’t be reached; these are the last known numbers.', notSetUp: 'Set up the Shrinkarr integration first.',
    h: 'h', d: 'd',
  },
  nl: {
    'v.full': 'Overzicht', 'v.compact': 'Compact', 'v.kept': 'Bewaarde originelen', 'v.gpu': 'Videokaart',
    'f.variant': 'Kaart', 'f.language': 'Taal', 'l.auto': 'Zoals Home Assistant', 'f.url': 'Link naar Shrinkarr (optioneel)', 'f.urlHelp': 'Opent als je op de titel tikt. Leeg = het adres van de integratie.',
    'st.running': 'Bezig met omzetten', 'st.pausing': 'Pauzeert na deze omzetting', 'st.paused': 'Gepauzeerd',
    'st.waiting': 'Wacht op het tijdvenster', 'st.waiting_auto': 'Wacht op het venster voor automatisch', 'st.idle': 'Alles is klaar',
    'st.idleQueue': 'Niets bezig', 'st.setup': 'Nog niet ingesteld',
    'chip.active': 'actief', 'chip.paused': 'pauze', 'chip.busy': 'bezig',
    queued: '{n} in de wachtrij', queueEmpty: 'De wachtrij is leeg', together: 'samen ~{t}', left: 'nog {t}', thenPause: 'daarna pauze',
    toGain: 'te winnen', toSave: 'Te besparen', saved: 'Bespaard', remains: 'Resterend', toSaveShort: 'te besparen', savedShort: 'bespaard',
    library: 'Bibliotheek', encTime: 'Omzettijd', todo: 'Te doen', titles: '{n} titels', done: 'Klaar', files: '{n} bestanden',
    quality: 'Kwaliteit: {q}', 'p.high': 'Hoge kwaliteit', 'p.balanced': 'Gebalanceerd', 'p.max': 'Maximale besparing',
    pause: 'Pauzeren', resume: 'Hervatten', startNow: 'Nu starten', nothing: 'Niets aan het omzetten', pausedLine: 'Gepauzeerd',
    keptTitle: '{n} originelen bewaard', keptTitle1: '1 origineel bewaard', keptSub: '{size} · {d} dagen bewaren', keptNone: 'Geen bewaarde originelen',
    keptOff: 'Originelen bewaren staat uit (Shrinkarr → Instellingen → Omzetten)', firstGone: 'Eerste gaat weg', freed: 'Komt vrij',
    keptFoot: 'Tot dan kun je een omzetting terugdraaien', purgeAll: 'Nu leegmaken', purgeShort: 'Nu', purgeAsk: '{size} nu verwijderen?',
    yes: 'Ja', no: 'Nee', keptLine: '{n} originelen · {size}', goneFrom: 'weg vanaf {d}', today: 'nu',
    gpuEncoding: 'zet nu om', gpuIdle: 'rust', busy: 'bezet', temp: 'Temperatuur', clock: 'Kloksnelheid', cpu: 'Processor',
    throttled: 'Begrensd', no_: 'nee', power: 'Vermogenslimiet ({r})', hot: 'Te warm',
    'e.render': 'Render', 'e.video': 'Video', 'e.video-enhance': 'Enhance', 'e.copy': 'Kopiëren', 'e.encoder': 'Encoder', 'e.decoder': 'Decoder',
    'enc.qsv': 'Intel Quick Sync', 'enc.vaapi': 'VA-API', 'enc.nvenc': 'NVIDIA NVENC', 'enc.cpu': 'Processor (software)',
    'stage.analyze': 'Analyseren', 'stage.cc': 'Ondertitels uitlezen', 'stage.verify': 'Controleren', 'stage.wait_plex': 'Wacht: wordt bekeken in Plex',
    'stage.replace': 'Vervangen', 'stage.update': 'Bibliotheek bijwerken',
    offline: 'Shrinkarr is niet bereikbaar; dit zijn de laatst bekende cijfers.', notSetUp: 'Stel eerst de Shrinkarr-integratie in.',
    h: 'u', d: 'd',
  },
};

const uiLang = (hass, config) => {
  if (config?.language === 'nl' || config?.language === 'en') return config.language;
  const l = hass?.locale?.language || hass?.language || document.querySelector('home-assistant')?.hass?.locale?.language || 'en';
  return l.startsWith('nl') ? 'nl' : 'en';
};
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const PURPLE = '149, 117, 248', GREEN = '102, 187, 106', ORANGE = '255, 167, 38', BLUE = '66, 165, 245', GREY = '158, 158, 158';

const STYLE = `
  :host { --fill: rgba(var(--rgb-primary-text-color, 225, 225, 225), .05); --fill-border: rgba(var(--rgb-primary-text-color, 225, 225, 225), .08);
    --track: rgba(var(--rgb-primary-text-color, 225, 225, 225), .12); --t2: var(--secondary-text-color); }
  ha-card { padding: 16px; color: var(--primary-text-color); }
  ha-icon { --ha-icon-display: block; display: block; line-height: 0; }
  button { font: inherit; }
  .hd { display: flex; align-items: center; gap: 14px; }
  .hd.link { cursor: pointer; }
  .ic { width: 48px; height: 48px; border-radius: 50%; display: grid; place-items: center; flex: none; background: rgba(var(--k), .18); color: rgb(var(--k)); }
  .ic ha-icon { --mdc-icon-size: 26px; }
  .tx { flex: 1; min-width: 0; } .t { font-size: 17px; font-weight: 600; } .s { font-size: 12px; color: var(--t2); margin-top: 2px; }
  .chip { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 999px;
    background: rgba(var(--k), .16); color: rgb(var(--k)); border: 1px solid rgba(var(--k), .4); white-space: nowrap; }
  .chip i { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
  .chip.live i { animation: pulse 1.6s ease-in-out infinite; }
  @keyframes pulse { 50% { opacity: .25; } }
  .warnline { margin-top: 12px; padding: 7px 10px; border-radius: 10px; font-size: 12px; background: rgba(${ORANGE}, .12); border: 1px solid rgba(${ORANGE}, .45); }
  .mid { display: grid; grid-template-columns: auto 1fr; gap: 16px; align-items: center; margin-top: 14px; }
  .ringbox { position: relative; width: 96px; height: 96px; }
  .ring { width: 100%; height: 100%; display: block; transform: rotate(-90deg); }
  .ring circle { fill: none; stroke-width: 8; }
  .rin { position: absolute; inset: 0; display: grid; place-content: center; text-align: center; }
  .rp { font-size: 24px; font-weight: 500; line-height: 1; font-variant-numeric: tabular-nums; } .rp small { font-size: 13px; color: var(--t2); }
  .rl { font-size: 10.5px; color: var(--t2); margin-top: 2px; }
  .nums { display: grid; gap: 8px; min-width: 0; }
  .lg { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--t2); }
  .lg i { width: 7px; height: 7px; border-radius: 50%; flex: none; }
  .big { font-size: 22px; font-weight: 600; font-variant-numeric: tabular-nums; line-height: 1.15; }
  .pair { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .val { font-size: 14px; font-weight: 600; font-variant-numeric: tabular-nums; }
  .panel { margin-top: 12px; padding: 10px 12px; border-radius: 12px; background: var(--fill); border: 1px solid var(--fill-border); min-width: 0; }
  .pt { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
  .pt b { font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
  .pt span { font-size: 12px; color: rgb(var(--k)); font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .ps { font-size: 11.5px; color: var(--t2); margin-top: 1px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .lb { position: relative; height: 7px; border-radius: 4px; margin-top: 8px; background: var(--track); overflow: hidden; }
  .lb > div { height: 100%; border-radius: 4px; background: rgb(var(--k)); transition: width .6s; }
  .pm { display: flex; justify-content: space-between; gap: 8px; margin-top: 6px; font-size: 11px; color: var(--t2); font-variant-numeric: tabular-nums; }
  .feiten { display: grid; grid-template-columns: repeat(auto-fill, minmax(124px, 1fr)); gap: 6px; margin-top: 12px; }
  .ft { display: grid; grid-template-columns: 16px 1fr; column-gap: 7px; align-items: center; padding: 7px 9px; border-radius: 10px;
    background: var(--fill); border: 1px solid var(--fill-border); min-width: 0; }
  .ft ha-icon { --mdc-icon-size: 16px; color: var(--t2); }
  .ft.let { background: rgba(${ORANGE}, .12); border-color: rgba(${ORANGE}, .45); } .ft.let ha-icon { color: rgb(${ORANGE}); }
  .fl { font-size: 10px; color: var(--t2); } .fw { font-size: 12px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-variant-numeric: tabular-nums; }
  .btn { cursor: pointer; display: inline-flex; align-items: center; gap: 6px; padding: 6px 11px; border-radius: 10px; font-size: 12.5px; font-weight: 600;
    background: var(--fill); border: 1px solid var(--divider-color, var(--fill-border)); color: var(--primary-text-color); }
  .btn ha-icon { --mdc-icon-size: 16px; }
  .btn:hover { background: var(--track); }
  .btn:disabled { opacity: .5; cursor: default; }
  .btn.warn { color: rgb(239, 83, 80); border-color: rgba(239, 83, 80, .45); background: rgba(239, 83, 80, .1); }
  .btn.xs { padding: 4px 9px; font-size: 11.5px; border-radius: 8px; } .btn.xs ha-icon { --mdc-icon-size: 14px; }
  .foot { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 12px; font-size: 11.5px; color: var(--t2); flex-wrap: wrap; }
  .acts { display: inline-flex; gap: 6px; align-items: center; }
  .empty { margin-top: 14px; font-size: 12.5px; color: var(--t2); }
  .days { display: grid; grid-template-columns: repeat(var(--n), 1fr); gap: 6px; height: 92px; margin-top: 14px; }
  .day { display: grid; grid-template-rows: auto 1fr auto; height: 100%; text-align: center; min-width: 0; }
  .day .v { font-size: 10px; color: var(--t2); font-variant-numeric: tabular-nums; white-space: nowrap; min-height: 13px; }
  .day .col { display: flex; align-items: flex-end; justify-content: center; }
  .day .col div { width: 100%; max-width: 26px; border-radius: 5px 5px 2px 2px; background: rgba(var(--k), .85); }
  .day .col div.zero { background: var(--track); }
  .day .d { font-size: 10.5px; color: var(--t2); margin-top: 4px; }
  .day.today .d { color: var(--primary-text-color); font-weight: 600; }
  .eng { display: grid; gap: 7px; min-width: 0; }
  .er { display: grid; grid-template-columns: 70px 1fr 38px; gap: 8px; align-items: center; font-size: 11.5px; }
  .er span { color: var(--t2); } .er .lb { margin-top: 0; height: 6px; } .er b { text-align: right; font-weight: 600; font-variant-numeric: tabular-nums; }
  /* compact */
  .cmp { display: grid; grid-template-columns: 44px 1fr auto; gap: 12px; align-items: center; padding: 12px 14px; }
  .cmp .ringbox { width: 44px; height: 44px; } .cmp .ring circle { stroke-width: 10; }
  .cmp .rp { font-size: 12px; font-weight: 600; } .cmp .rp small { font-size: 9px; }
  .cmp .t { font-size: 14px; font-weight: 500; } .cmp .s { margin-top: 1px; font-variant-numeric: tabular-nums; }
  .cmp .s b { color: var(--primary-text-color); font-weight: 600; }
  .cmp .link { cursor: pointer; min-width: 0; }
  .ib { cursor: pointer; width: 34px; height: 34px; border-radius: 50%; display: grid; place-items: center; padding: 0;
    background: var(--fill); border: 1px solid var(--divider-color, var(--fill-border)); color: var(--primary-text-color); }
  .ib ha-icon { --mdc-icon-size: 18px; } .ib:hover { background: var(--track); } .ib:disabled { opacity: .5; }
  .ib.on { color: rgb(${ORANGE}); border-color: rgba(${ORANGE}, .45); background: rgba(${ORANGE}, .12); }
  .rows { grid-column: 1 / -1; border-radius: 10px; background: var(--fill); border: 1px solid var(--fill-border); min-width: 0; }
  .row { display: grid; grid-template-columns: 16px 1fr auto; gap: 8px; align-items: center; min-height: 34px; padding: 0 10px; font-size: 12px; min-width: 0; }
  .row + .row { border-top: 1px solid var(--fill-border); }
  .row > ha-icon { --mdc-icon-size: 16px; color: var(--t2); }
  .row.k > ha-icon { color: rgb(var(--k)); } .row.o > ha-icon { color: rgb(${ORANGE}); }
  .row b { font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
  .row b span { color: var(--t2); font-weight: 400; }
  .row em { font-style: normal; color: var(--t2); font-variant-numeric: tabular-nums; white-space: nowrap; }
  .row em strong { color: rgb(var(--k)); font-weight: 600; }
  @media (prefers-reduced-motion: reduce) { .chip.live i { animation: none; } .lb > div { transition: none; } }
`;

class ShrinkarrCard extends HTMLElement {
  static getStubConfig() { return { variant: 'full' }; }

  static getConfigForm() {
    const T = STR[uiLang()];
    return {
      schema: [
        { name: 'variant', required: true, selector: { select: { mode: 'dropdown', options: VARIANTS.map((v) => ({ value: v, label: T['v.' + v] })) } } },
        { name: 'language', selector: { select: { mode: 'dropdown', options: [
          { value: 'auto', label: T['l.auto'] }, { value: 'nl', label: 'Nederlands' }, { value: 'en', label: 'English' }] } } },
        { name: 'url', selector: { text: { type: 'url' } } },
      ],
      computeLabel: (s) => T['f.' + s.name],
      computeHelper: (s) => (s.name === 'url' ? T['f.urlHelp'] : undefined),
    };
  }

  setConfig(config) {
    if (config.variant && !VARIANTS.includes(config.variant)) throw new Error(`variant must be one of: ${VARIANTS.join(', ')}`);
    if (config.language && !['auto', 'nl', 'en'].includes(config.language)) throw new Error('language must be auto, nl or en');
    const resub = this._config && this._config.entry_id !== config.entry_id;
    this._config = { variant: 'full', ...config };
    if (resub) this._unsubscribe();
    this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (!this._sub && this.isConnected && Date.now() > (this._retryAt || 0)) this._subscribe();
    if (first) this._render();
  }

  connectedCallback() { if (this._hass && !this._sub) this._subscribe(); }
  disconnectedCallback() { this._unsubscribe(); }

  getCardSize() { return { full: 7, compact: 3, kept: 4, gpu: 4 }[this._config?.variant] || 4; }
  getGridOptions() { return { columns: 12, min_columns: 6 }; }

  _subscribe() {
    const msg = { type: 'shrinkarr/subscribe' };
    if (this._config?.entry_id) msg.entry_id = this._config.entry_id;
    this._sub = this._hass.connection.subscribeMessage((m) => { this._p = m; this._err = null; this._render(); }, msg);
    this._sub.catch((e) => {
      this._sub = null; this._retryAt = Date.now() + 30000;
      this._err = e?.code === 'not_found' ? 'notSetUp' : (e?.message || String(e));
      this._render();
    });
  }

  _unsubscribe() {
    if (this._sub) this._sub.then((unsub) => unsub()).catch(() => {});
    this._sub = null;
  }

  // --- formatting ---------------------------------------------------------------
  _t(key, vars = {}) {
    const s = STR[this._lang][key] ?? STR.en[key] ?? key;
    return s.replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? '');
  }
  _nf(v, d = 0) { return Number(v).toLocaleString(this._lang, { minimumFractionDigits: d, maximumFractionDigits: d }); }
  _bytes(b) {
    if (b == null) return '–';
    return b >= 1e12 ? `${this._nf(b / 1e12, 2)} TB` : b >= 1e9 ? `${this._nf(b / 1e9, 1)} GB` : `${this._nf(b / 1e6)} MB`;
  }
  _dur(s) {
    if (s == null) return '–';
    const m = Math.round(Math.max(0, s) / 60);
    if (m < 1) return '<1 min';
    if (m < 60) return `${m} min`;
    const h = Math.floor(m / 60), mm = m % 60, H = this._t('h');
    if (h < 48) return `${h} ${H}` + (mm ? ` ${mm} min` : '');
    return `${Math.floor(h / 24)} ${this._t('d')}` + (h % 24 ? ` ${h % 24} ${H}` : '');
  }
  _ft(icon, label, value, cls = '') {
    return `<div class="ft ${cls}"><ha-icon icon="${icon}"></ha-icon><div style="min-width:0"><div class="fl">${label}</div><div class="fw">${value}</div></div></div>`;
  }
  _ring(parts, center, label) {
    const R = 40, C = 2 * Math.PI * R;
    let off = 0;
    const arcs = parts.map(([frac, rgb]) => {
      const len = Math.max(0, Math.min(1, frac || 0) * C), draw = len > 4 ? len - 2 : len;
      const a = len ? `<circle cx="50" cy="50" r="${R}" style="stroke:rgb(${rgb});stroke-dasharray:${draw.toFixed(1)} ${C.toFixed(1)};stroke-dashoffset:${(-off).toFixed(1)}"/>` : '';
      off += len;
      return a;
    }).join('');
    return `<div class="ringbox"><svg class="ring" viewBox="0 0 100 100" aria-hidden="true"><circle cx="50" cy="50" r="${R}" style="stroke:var(--track)"/>${arcs}</svg>
      <div class="rin"><div class="rp">${center}</div>${label ? `<div class="rl">${label}</div>` : ''}</div></div>`;
  }

  // --- state helpers ------------------------------------------------------------
  _state(Q) {
    if (Q.current && Q.paused) return ['st.pausing', ORANGE, true];
    if (Q.paused) return ['st.paused', ORANGE, false];
    if (Q.state === 'running') return ['st.running', PURPLE, true];
    if (Q.state === 'waiting' || Q.state === 'waiting_auto') return ['st.' + Q.state, BLUE, false];
    if (Q.state === 'setup') return ['st.setup', GREY, false];
    return [Q.queued ? 'st.idleQueue' : 'st.idle', GREEN, false];
  }
  _total(Q) { return (Q.queuedSeconds || 0) + (Q.current?.eta || 0); }
  _curLine(c, Q) {
    const pct = `${Math.round((c.progress || 0) * 100)}%`;
    if (Q.paused) return [pct, this._t('thenPause')];
    if (c.stage !== 'encode' && c.stage !== 'encode_sw') return [pct, this._t('stage.' + c.stage)];
    return [pct, c.eta != null ? this._t('left', { t: this._dur(c.eta) }) : ''];
  }

  // --- variants ---------------------------------------------------------------------
  _full(d) {
    const L = d.library, Q = d.queue, c = Q.current, orig = L.size + L.saved || 1;
    const [title, k, live] = this._state(Q);
    const sub = Q.queued ? `${this._t('queued', { n: Q.queued })} · ${this._t('together', { t: this._dur(this._total(Q)) })}` : this._t('queueEmpty');
    const [pct, rest] = c ? this._curLine(c, Q) : [];
    return `<ha-card style="--k: ${k}">
      <div class="hd link" data-act="open">
        <div class="ic"><ha-icon icon="mdi:movie-open-play-outline"></ha-icon></div>
        <div class="tx"><div class="t">${this._t(title)}</div><div class="s">${sub}</div></div>
        <span class="chip ${live ? 'live' : ''}"><i></i>${this._t(Q.paused ? 'chip.paused' : 'chip.active')}</span>
      </div>
      ${this._offline()}
      <div class="mid">
        ${this._ring([[L.saved / orig, GREEN], [L.toSave / orig, PURPLE]], `${L.pct}<small>%</small>`, this._t('toGain'))}
        <div class="nums">
          <div><div class="lg"><i style="background:rgb(${PURPLE})"></i>${this._t('toSave')}</div><div class="big">${L.toSave ? '~' : ''}${this._bytes(L.toSave)}</div></div>
          <div class="pair">
            <div><div class="lg"><i style="background:rgb(${GREEN})"></i>${this._t('saved')}</div><div class="val">${this._bytes(L.saved)}</div></div>
            <div><div class="lg"><i style="background:var(--track)"></i>${this._t('remains')}</div><div class="val">${L.estSize ? '~' : ''}${this._bytes(L.estSize)}</div></div>
          </div>
        </div>
      </div>
      ${c ? `<div class="panel">
        <div class="pt"><b>${esc(c.title)}</b><span>${pct}</span></div>
        <div class="ps">${esc(c.subtitle)}</div>
        <div class="lb"><div style="width:${(c.progress || 0) * 100}%"></div></div>
        <div class="pm"><span>${[c.fps ? `${this._nf(c.fps)} fps` : '', c.speed ? `${this._nf(c.speed, 1)}×` : '', rest].filter(Boolean).join(' · ')}</span>
          <span>${this._bytes(c.size_before)} → ~${this._bytes(c.est_size)}</span></div>
      </div>` : ''}
      <div class="feiten">
        ${this._ft('mdi:harddisk', this._t('library'), this._bytes(L.size))}
        ${this._ft('mdi:timer-sand-complete', this._t('encTime'), L.encodeSeconds ? `~${this._dur(L.encodeSeconds)}` : '–')}
        ${this._ft('mdi:format-list-checks', this._t('todo'), this._t('titles', { n: L.titlesTodo }))}
        ${this._ft('mdi:check-circle-outline', this._t('done'), this._t('files', { n: Q.done }))}
      </div>
      <div class="foot"><span>${this._t('quality', { q: this._t('p.' + L.preset) })}</span>
        <span class="acts">
          ${Q.state === 'waiting' && !Q.paused ? `<button class="btn" data-act="start"><ha-icon icon="mdi:play-speed"></ha-icon>${this._t('startNow')}</button>` : ''}
          <button class="btn" data-act="${Q.paused ? 'resume' : 'pause'}"><ha-icon icon="mdi:${Q.paused ? 'play' : 'pause'}"></ha-icon>${this._t(Q.paused ? 'resume' : 'pause')}</button>
        </span></div>
    </ha-card>`;
  }

  _compact(d) {
    const L = d.library, Q = d.queue, c = Q.current, K = d.kept, orig = L.size + L.saved || 1;
    const k = this._state(Q)[1];
    let now;
    if (c) {
      const [pct, rest] = this._curLine(c, Q);
      const ep = String(c.subtitle || '').split(' · ')[0];
      now = `<div class="row k" title="${esc(c.title)} · ${esc(c.subtitle)}"><ha-icon icon="mdi:play"></ha-icon><b>${esc(c.title)} <span>${esc(ep)}</span></b>
        <em><strong>${pct}</strong>${rest ? ' · ' + rest : ''}</em></div>`;
    } else {
      const label = Q.paused ? this._t('pausedLine') : Q.state === 'waiting' || Q.state === 'waiting_auto' ? this._t('st.' + Q.state) : this._t('nothing');
      now = `<div class="row"><ha-icon icon="mdi:${Q.paused ? 'pause' : Q.state.startsWith('waiting') ? 'clock-outline' : 'check-circle-outline'}"></ha-icon><b>${label}</b><em></em></div>`;
    }
    const queue = `<div class="row"><ha-icon icon="mdi:tray-full"></ha-icon><b>${this._t('queued', { n: Q.queued })}</b>
      <em>${Q.queued ? this._t('together', { t: this._dur(this._total(Q)) }) : ''}</em></div>`;
    let kept = '';
    if (K.count) {
      const next = new Date(K.nextDelete * 1000).toLocaleDateString(this._lang, { weekday: 'short', day: 'numeric', month: 'short' });
      kept = this._confirm
        ? `<div class="row o"><ha-icon icon="mdi:delete-clock-outline"></ha-icon><b>${this._t('purgeAsk', { size: this._bytes(K.bytes) })}</b>
            <span class="acts"><button class="btn xs warn" data-act="purge-yes">${this._t('yes')}</button><button class="btn xs" data-act="purge-no">${this._t('no')}</button></span></div>`
        : `<div class="row o"><ha-icon icon="mdi:delete-clock-outline"></ha-icon><b>${this._t('keptLine', { n: K.count, size: this._bytes(K.bytes) })} <span>· ${this._t('goneFrom', { d: next })}</span></b>
            <span class="acts"><button class="btn xs warn" data-act="purge" title="${esc(this._t('purgeAll'))}"><ha-icon icon="mdi:delete-sweep-outline"></ha-icon>${this._t('purgeShort')}</button></span></div>`;
    }
    return `<ha-card class="cmp" style="--k: ${k}">
      ${this._ring([[L.saved / orig, GREEN], [L.toSave / orig, PURPLE]], `${L.pct}<small>%</small>`, '')}
      <div class="link" data-act="open"><div class="t">Shrinkarr</div>
        <div class="s"><b>${L.toSave ? '~' : ''}${this._bytes(L.toSave)}</b> ${this._t('toSaveShort')} · ${this._bytes(L.saved)} ${this._t('savedShort')}</div></div>
      <button class="ib ${Q.paused ? 'on' : ''}" data-act="${Q.paused ? 'resume' : 'pause'}" title="${this._t(Q.paused ? 'resume' : 'pause')}"
        aria-label="${this._t(Q.paused ? 'resume' : 'pause')}"><ha-icon icon="mdi:${Q.paused ? 'play' : 'pause'}"></ha-icon></button>
      ${this._p.available ? '' : `<div class="warnline" style="grid-column:1/-1;margin:0">${this._t('offline')}</div>`}
      <div class="rows">${now}${queue}${kept}</div>
    </ha-card>`;
  }

  _kept(d) {
    const K = d.kept;
    const title = K.count === 1 ? this._t('keptTitle1') : K.count ? this._t('keptTitle', { n: K.count }) : this._t('keptNone');
    const head = `<div class="hd link" data-act="open"><div class="ic"><ha-icon icon="mdi:delete-clock-outline"></ha-icon></div>
      <div class="tx"><div class="t">${title}</div><div class="s">${K.days ? this._t('keptSub', { size: this._bytes(K.bytes), d: K.days }) : ''}</div></div></div>`;
    if (!K.count) return `<ha-card style="--k: ${ORANGE}">${head}${this._offline()}<div class="empty">${K.days ? this._t('keptNone') : this._t('keptOff')}</div></ha-card>`;
    // What is freed per day, from today to the last deletion.
    const day0 = new Date(); day0.setHours(0, 0, 0, 0);
    const idx = (t) => Math.max(0, Math.floor((new Date(t * 1000).setHours(0, 0, 0, 0) - day0) / 864e5 + 0.5));
    const items = K.items || [];
    const n = Math.min(14, Math.max(K.days + 1, ...items.map(([t]) => idx(t) + 1)));
    const days = Array.from({ length: n }, () => [0, 0]);
    for (const [t, size] of items) { const i = Math.min(n - 1, idx(t)); days[i][0] += size; days[i][1] += 1; }
    const max = Math.max(...days.map((x) => x[0]), 1);
    const wd = (i) => { const dt = new Date(day0); dt.setDate(dt.getDate() + i); return dt.toLocaleDateString(this._lang, { weekday: 'short' }).replace('.', ''); };
    const next = new Date(K.nextDelete * 1000).toLocaleString(this._lang, { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
    return `<ha-card style="--k: ${ORANGE}">${head}${this._offline()}
      ${items.length ? `<div class="days" style="--n:${n}">${days.map(([b, c], i) => `<div class="day ${i === 0 ? 'today' : ''}" title="${c} × ${this._bytes(b)}">
        <div class="v">${b ? this._nf(b / 1e9) + ' GB' : ''}</div>
        <div class="col"><div class="${b ? '' : 'zero'}" style="height:${b ? Math.max(6, (b / max) * 62) : 3}px"></div></div>
        <div class="d">${i === 0 ? this._t('today') : wd(i)}</div></div>`).join('')}</div>` : ''}
      <div class="feiten">
        ${this._ft('mdi:calendar-clock', this._t('firstGone'), next)}
        ${this._ft('mdi:harddisk', this._t('freed'), this._bytes(K.bytes))}
      </div>
      <div class="foot"><span>${this._t('keptFoot')}</span>
        <span class="acts">${this._confirm
          ? `<span>${this._t('purgeAsk', { size: this._bytes(K.bytes) })}</span><button class="btn warn" data-act="purge-yes">${this._t('yes')}</button><button class="btn" data-act="purge-no">${this._t('no')}</button>`
          : `<button class="btn warn" data-act="purge"><ha-icon icon="mdi:delete-sweep-outline"></ha-icon>${this._t('purgeAll')}</button>`}</span></div>
    </ha-card>`;
  }

  _gpu(d) {
    const G = d.gpu;
    const throttle = (G.throttle || []).filter((r) => r !== 'status');
    const power = throttle.filter((r) => /^pl\d/.test(r)).map((r) => r.toUpperCase());
    const hot = throttle.some((r) => /thermal|prochot/.test(r));
    const limited = hot ? this._t('hot') : power.length ? this._t('power', { r: power.join(', ') }) : throttle.length ? throttle.join(', ').toUpperCase() : '';
    const engines = Object.entries(G.engines || {});
    return `<ha-card style="--k: ${BLUE}">
      <div class="hd link" data-act="open"><div class="ic"><ha-icon icon="mdi:expansion-card-variant"></ha-icon></div>
        <div class="tx"><div class="t">${esc(G.name)}</div><div class="s">${this._t('enc.' + G.encoder)} · ${this._t(G.encoding ? 'gpuEncoding' : 'gpuIdle')}</div></div>
        ${G.encoding ? `<span class="chip live"><i></i>${this._t('chip.busy')}</span>` : ''}</div>
      ${this._offline()}
      <div class="mid" ${engines.length ? '' : 'style="grid-template-columns:auto"'}>
        ${this._ring([[(G.busy ?? 0) / 100, BLUE]], G.busy == null ? '–' : `${this._nf(G.busy)}<small>%</small>`, this._t('busy'))}
        ${engines.length ? `<div class="eng">${engines.map(([n, v]) => `<div class="er"><span>${this._t('e.' + n)}</span>
          <div class="lb"><div style="width:${v ?? 0}%"></div></div><b>${v == null ? '–' : this._nf(v) + '%'}</b></div>`).join('')}</div>` : ''}
      </div>
      <div class="feiten">
        ${G.temp != null ? this._ft('mdi:thermometer', this._t('temp'), `${this._nf(G.temp)} °C`) : ''}
        ${G.freq?.act ? this._ft('mdi:speedometer', this._t('clock'), `${this._nf(G.freq.act)}${G.freq.max ? ' / ' + this._nf(G.freq.max) : ''} MHz`) : ''}
        ${G.cpu != null ? this._ft('mdi:cpu-64-bit', this._t('cpu'), `${this._nf(G.cpu, 1)}%`) : ''}
        ${limited ? this._ft('mdi:flash-alert-outline', this._t('throttled'), limited, 'let') : this._ft('mdi:check-circle-outline', this._t('throttled'), this._t('no_'))}
      </div>
    </ha-card>`;
  }

  _offline() { return this._p?.available === false ? `<div class="warnline">${this._t('offline')}</div>` : ''; }

  // --- render and actions ---------------------------------------------------------------
  _render() {
    if (!this._config) return;
    if (!this.shadowRoot) {
      this.attachShadow({ mode: 'open' });
      this.shadowRoot.addEventListener('click', (e) => this._click(e));
    }
    this._lang = uiLang(this._hass, this._config);
    let body;
    if (this._err) body = `<ha-card><div class="empty" style="margin:0">${this._err === 'notSetUp' ? this._t('notSetUp') : esc(this._err)}</div></ha-card>`;
    else if (!this._p?.data) body = `<ha-card><div class="empty" style="margin:0">…</div></ha-card>`;
    else body = this['_' + this._config.variant](this._p.data);
    this.shadowRoot.innerHTML = `<style>${STYLE}</style>${body}`;
    this.shadowRoot.querySelectorAll('button').forEach((b) => { b.disabled = !!this._busy; });
  }

  async _click(e) {
    const el = e.target.closest('[data-act]');
    if (!el || !this._p) return;
    const act = el.dataset.act, ents = this._p.entities || {};
    if (act === 'open') { window.open(this._config.url || this._p.url, '_blank', 'noopener'); return; }
    if (act === 'purge' || act === 'purge-no') { this._confirm = act === 'purge'; this._render(); return; }
    const call = {
      pause: ['switch', 'turn_off', ents.queue_running], resume: ['switch', 'turn_on', ents.queue_running],
      start: ['button', 'press', ents.start_now], 'purge-yes': ['button', 'press', ents.purge_kept],
    }[act];
    if (!call || !call[2]) return;
    this._busy = true; this._confirm = false; this._render();
    try {
      await this._hass.callService(call[0], call[1], { entity_id: call[2] });
    } catch (err) {
      this.dispatchEvent(new CustomEvent('hass-notification', { detail: { message: `Shrinkarr: ${err.message || err}` }, bubbles: true, composed: true }));
    } finally {
      this._busy = false; this._render();
    }
  }
}

// HA 2026 replaces the custom element registry (scoped registries) after the scripts of integrations
// have run, so a card defined right away is not found. Define it once Home Assistant itself is there.
function register() {
  if (customElements.get('shrinkarr-card')) return;
  customElements.define('shrinkarr-card', ShrinkarrCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: 'shrinkarr-card', name: 'Shrinkarr', preview: true,
    description: 'Savings, queue, kept originals and the graphics card of Shrinkarr.',
    documentationURL: 'https://github.com/rvanderend/shrinkarr#home-assistant',
  });
  console.info(`%c SHRINKARR-CARD %c ${VERSION} `, 'background:#8b5cf6;color:#fff;border-radius:3px 0 0 3px', 'background:#14b8a6;color:#fff;border-radius:0 3px 3px 0');
}
customElements.whenDefined('home-assistant').then(register);
