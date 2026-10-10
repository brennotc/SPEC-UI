() => {
  // Instantâneo do DOM e do CSS para as métricas de qualidade de código (Figma2Code).
  const root = document.querySelector('app-root');
  const elements = [];
  if (root) {
    for (const el of [root, ...root.querySelectorAll('*')]) {
      const cs = getComputedStyle(el);
      elements.push({
        tag: el.tagName.toLowerCase(),
        classes: Array.from(el.classList),
        inline_style: el.hasAttribute('style') && el.getAttribute('style').trim() !== '',
        position: cs.position,
        display: cs.display,
        child_count: el.childElementCount,
        in_svg: !!el.closest('svg') && el.tagName.toLowerCase() !== 'svg',
      });
    }
  }

  const rules = [];
  const sheets = [];
  const walk = (list, ctx) => {
    for (const rule of Array.from(list)) {
      if (rule.type === CSSRule.STYLE_RULE) {
        // cssText preserva os atalhos (padding: calc(var(--spacing) * 4)); iterar rule.style
        // expandiria em propriedades individuais e perderia o valor quando há var().
        rules.push({ selector: rule.selectorText, media: ctx.media, layer: ctx.layer, origin: ctx.origin,
                     nested: ctx.nested, css_text: rule.style.cssText });
        if (rule.cssRules && rule.cssRules.length) walk(rule.cssRules, { ...ctx, nested: true });
      } else if (rule.cssRules) {  // @media, @supports, @layer { }, @container
        const next = { ...ctx };
        if (rule.constructor.name === 'CSSMediaRule') {
          next.media = ctx.media ? ctx.media + ' and ' + rule.conditionText : rule.conditionText;
        } else if (rule.constructor.name === 'CSSLayerBlockRule') {
          next.layer = ctx.layer ? ctx.layer + '.' + rule.name : rule.name;
        }
        walk(rule.cssRules, next);
      }
    }
  };
  for (const sheet of Array.from(document.styleSheets)) {
    const owner = sheet.ownerNode;
    const href = sheet.href || null;
    const origin = owner && owner.tagName === 'STYLE' ? 'component' : 'global';
    try {
      const list = sheet.cssRules;
      sheets.push({ href, origin, n_rules: list.length });
      walk(list, { media: null, layer: null, origin, nested: false });
    } catch (e) {
      sheets.push({ href, origin, n_rules: 0, error: String(e) });
    }
  }
  return { viewport: { w: window.innerWidth, h: window.innerHeight }, elements, rules, sheets };
}
