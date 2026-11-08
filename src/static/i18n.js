/* The interface's language (plan 038): English, or Arabic right to left.

   Chosen per person, in Preferences and with the switch this script puts in
   every page's top bar, and kept on the server with the person. The device
   keeps a copy, so a page is drawn in it from the first paint, before the
   session is read; a page whose copy differs takes the person's
   (`I18n.follow(session)`). Loaded first, in the <head>, before anything draws.

   The pages are written in English, and English is the key. Every Arabic
   word is in the catalogs in `static/i18n/`, translated with the glossary's
   terms (docs/design/arabic-glossary.md). A string with no Arabic shows its
   English, and the catalog test fails (tests/test_i18n_catalogs.py).

     I18n.lang                  "en" or "ar"
     I18n.rtl                   true in Arabic
     I18n.locale                for toLocale*(): the browser's own in English, as before;
                                Arabic, Gregorian, with Western digits, in Arabic
     I18n.t(english, params)    the text in the interface's language. `{name}` is filled
                                from `params`. A catalog entry may be plural forms
                                ({ zero, one, two, few, many, other }), chosen by `params.n`.
                                Where one English needs two Arabic, the key says which
                                it means before a bar: "action|Set aside" is the button,
                                "Set aside" the state. English never shows the bar.
     I18n.translate(root)       the text and the title, placeholder, aria-label and alt
                                attributes under `root`, where the catalog has the whole
                                text; `data-i18n-html="English key"` puts the catalog's
                                markup in an element whose sentence has elements inside.
                                The page's own markup is translated once it has loaded.
     I18n.date(value, options)  toLocaleDateString in I18n.locale
     I18n.time(value, options)  toLocaleTimeString in I18n.locale
     I18n.dateTime(value, options)  toLocaleString in I18n.locale
     I18n.number(n)             toLocaleString in I18n.locale
     I18n.server(text)          a sentence the server wrote (a review reason, why an
                                answer is held back): the catalog's, by the whole sentence
                                or a pattern, or the English
     I18n.error(error)          an API error's message: its own Arabic (whole sentence or
                                pattern), else its code's ("error.<code>"), else the English
     I18n.add(entries)          for a catalog: English -> Arabic, or plural forms
     I18n.addPatterns(list)     for a catalog: [RegExp, Arabic with $1 ...] pairs
     I18n.follow(session)       take the person's choice from the session the page read
     I18n.setLanguage(lang)     keep it for the person and this device, and draw the page
                                again in it
     I18n.beforeSwitch          a page with unsaved typing sets it to a function returning
                                the question to ask before the page is drawn again

   Text inside `data-no-translate`, <script>, <style>, <textarea>, <code>,
   <pre> and <kbd> is never translated: names, files and keys stay as they are.
*/

const I18n = (window.I18n = (function () {
  "use strict";

  const STORED = "interface-language";
  const LANGUAGES = ["en", "ar"];

  function stored() {
    try {
      const value = localStorage.getItem(STORED);
      return LANGUAGES.includes(value) ? value : "";
    } catch (error) {
      return "";  // storage blocked: English, and the session's choice is followed without a reload
    }
  }
  function keep(lang) {
    try {
      localStorage.setItem(STORED, lang);
      return localStorage.getItem(STORED) === lang;
    } catch (error) {
      return false;
    }
  }

  const lang = stored() || "en";
  const rtl = lang === "ar";
  document.documentElement.lang = lang;
  document.documentElement.dir = rtl ? "rtl" : "ltr";

  const catalog = Object.create(null);
  const patterns = [];
  const plural = new Intl.PluralRules("ar");

  function fill(text, params) {
    if (!params) return text;
    return text.replace(/\{(\w+)\}/g, (whole, name) => (name in params ? String(params[name]) : whole));
  }

  function arabicFor(english, params) {
    let found = catalog[english];
    if (found && typeof found === "object") {
      const n = params && typeof params.n === "number" ? params.n : 0;
      found = found[plural.select(n)] || found.other;
    }
    return typeof found === "string" ? found : null;
  }

  // "action|Set aside": a meaning, then the English shown.
  const MEANING = /^[a-z]+\|(?=\S)/;

  function t(english, params) {
    const text = String(english);
    const shown = text.replace(MEANING, "");
    if (!rtl) return fill(shown, params);
    const found = arabicFor(text, params);
    return fill(found === null ? shown : found, params);
  }

  /* --- the page's markup --------------------------------------------------- */

  const ATTRIBUTES = ["title", "placeholder", "aria-label", "alt"];
  const LEFT_ALONE = "[data-no-translate], script, style, textarea, code, pre, kbd";

  function whole(text) {
    return text.replace(/\s+/g, " ").trim();
  }
  function settled(english) {
    // Only a whole sentence with nothing left to fill: markup has no parameters.
    const found = catalog[english];
    return typeof found === "string" && !/\{\w+\}/.test(english) ? found : null;
  }

  function translate(root) {
    if (!rtl || !root) return root;
    const scope = root.nodeType === Node.DOCUMENT_NODE ? root.documentElement : root;
    if (scope.nodeType !== Node.ELEMENT_NODE) return root;

    const marked = [...scope.querySelectorAll("[data-i18n-html]")];
    if (scope.matches("[data-i18n-html]")) marked.push(scope);
    marked.forEach((element) => {
      const found = settled(element.getAttribute("data-i18n-html"));
      if (found !== null) element.innerHTML = found;  // the catalog's own markup, written by us
    });

    const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
    const texts = [];
    while (walker.nextNode()) texts.push(walker.currentNode);
    texts.forEach((node) => {
      const parent = node.parentElement;
      if (!parent || parent.closest(LEFT_ALONE)) return;
      const english = whole(node.nodeValue);
      if (!english || !/[A-Za-z]/.test(english)) return;
      const found = settled(english);
      if (found === null) return;
      const lead = node.nodeValue.match(/^\s*/)[0];
      const trail = node.nodeValue.match(/\s*$/)[0];
      node.nodeValue = lead + found + trail;
    });

    const named = [...scope.querySelectorAll(ATTRIBUTES.map((name) => "[" + name + "]").join(","))];
    if (ATTRIBUTES.some((name) => scope.hasAttribute(name))) named.push(scope);
    named.forEach((element) => {
      if (element.closest("[data-no-translate]")) return;
      ATTRIBUTES.forEach((name) => {
        const value = element.getAttribute(name);
        if (!value) return;
        const found = settled(whole(value));
        if (found !== null) element.setAttribute(name, found);
      });
    });
    return root;
  }

  /* --- dates and numbers --------------------------------------------------- */

  // English: the browser's own, exactly as the pages formatted before (`[]` or undefined).
  const locale = rtl ? "ar-u-ca-gregory-nu-latn" : undefined;
  const asDate = (value) => (value instanceof Date ? value : new Date(value));

  /* --- the server's sentences ---------------------------------------------- */

  function server(text) {
    if (!rtl || !text) return text;
    const sentence = String(text);
    const found = arabicFor(sentence);
    if (found !== null) return found;
    for (const [pattern, arabic] of patterns) {
      if (pattern.test(sentence)) return sentence.replace(pattern, arabic);
    }
    return sentence;
  }

  /* The message's own Arabic first, which keeps what it says about this case;
     then its code's, which says what kind of problem it is; then the English. */
  function error(problem) {
    const message = problem && problem.message ? String(problem.message) : String(problem || "");
    if (!rtl) return message;
    const own = server(message);
    if (own !== message) return own;
    const byCode = problem && problem.code ? arabicFor("error." + problem.code) : null;
    return byCode !== null ? byCode : message;
  }

  /* --- the choice ----------------------------------------------------------- */

  async function setLanguage(next) {
    if (!LANGUAGES.includes(next) || next === lang) return;
    const question = typeof api.beforeSwitch === "function" ? api.beforeSwitch() : "";
    if (question && !window.confirm(question)) return;
    keep(next);
    try {
      await fetch("/api/preferences/language", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ language: next }),
      });
    } catch (problem) {
      /* Signed out, or the server away: this device keeps it, and the session's
         choice wins again once it is read. */
    }
    window.location.reload();
  }

  /* The person's choice, from the session the page has read. Drawn again in it
     only when this device's copy could be changed to it: with storage blocked,
     reloading would never settle. */
  function follow(session) {
    const wanted = session && session.interface_language;
    if (!LANGUAGES.includes(wanted) || wanted === lang) return;
    if (keep(wanted)) window.location.reload();
  }

  /* The switch, in every top bar beside the theme's. It names the other
     language in that language, as a person who cannot read this one looks for. */
  function drawSwitch() {
    if (document.getElementById("languageToggle")) return;
    const theme = document.getElementById("themeToggle");
    const bar = theme ? theme.parentElement : document.querySelector(".topbar");
    if (!bar) return;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ghost";
    button.id = "languageToggle";
    const other = rtl ? "en" : "ar";
    button.lang = other;
    button.dir = rtl ? "ltr" : "rtl";
    button.setAttribute("data-no-translate", "");
    button.textContent = rtl ? "English" : "العربية";
    button.title = rtl ? "Show the pages in English" : "اعرض الصفحات بالعربية";
    button.onclick = () => setLanguage(other);
    if (theme) theme.before(button);
    else bar.append(button);
  }

  function whenLoaded() {
    drawSwitch();
    translate(document.body);
    if (rtl && document.title) document.title = t(document.title);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", whenLoaded);
  else whenLoaded();

  const api = {
    lang: lang,
    rtl: rtl,
    locale: locale,
    t: t,
    has: (english) => english in catalog,
    translate: translate,
    date: (value, options) => asDate(value).toLocaleDateString(locale, options),
    time: (value, options) => asDate(value).toLocaleTimeString(locale, options),
    dateTime: (value, options) => asDate(value).toLocaleString(locale, options),
    number: (n) => Number(n).toLocaleString(locale),
    server: server,
    error: error,
    add: (entries) => Object.assign(catalog, entries),
    addPatterns: (list) => patterns.push(...list),
    follow: follow,
    setLanguage: setLanguage,
    beforeSwitch: null,
    catalog: catalog,  // read by the tests
  };
  return api;
})());
