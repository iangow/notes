(() => {
  'use strict';
  const collection = document.querySelector('#notes-collection');
  if (!collection) return;
  // Quarto adds its own named-column grid to fenced divs containing an aside.
  // This layout owns its two columns instead.
  collection.parentElement.classList.remove('page-columns', 'page-full');
  const normalize = value => value.normalize('NFKC').toLocaleLowerCase();
  const aliases = new Map([['finance', 'Finance'], ['graphics', 'Data visualization'], ['visualization', 'Data visualization'], ['transport', 'Transport'], ['web data', 'Web data']]);
  const counts = new Map();
  const notes = [];
  const groups = [];
  collection.querySelectorAll('section.level2').forEach(section => {
    const table = section.querySelector('table');
    if (!table) return;
    const grid = document.createElement('div');
    grid.className = 'notes-grid';
    const groupNotes = [];
    table.querySelectorAll('tbody tr').forEach(row => {
      const cells = row.querySelectorAll('td');
      const link = cells[0]?.querySelector('a');
      if (!link || !cells[1]) return;
      const topics = [...new Set(cells[1].textContent.split(',').map(t => t.trim()).filter(Boolean).map(t => aliases.get(normalize(t)) || t))];
      const card = document.createElement('article');
      card.className = 'note-card';
      const heading = document.createElement('h3');
      heading.append(link.cloneNode(true));
      const tags = document.createElement('div');
      tags.className = 'note-tags';
      topics.forEach(topic => {
        counts.set(topic, (counts.get(topic) || 0) + 1);
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = topic;
        button.dataset.topic = topic;
        button.setAttribute('aria-label', `Filter by ${topic}`);
        button.setAttribute('aria-pressed', 'false');
        tags.append(button);
      });
      card.append(heading, tags);
      grid.append(card);
      const note = { card, topics, text: normalize(`${link.textContent} ${topics.join(' ')}`) };
      notes.push(note);
      groupNotes.push(note);
    });
    table.replaceWith(grid);
    section.classList.add('notes-group');
    groups.push({ section, notes: groupNotes });
  });
  if (!notes.length) return;

  const search = document.querySelector('#notes-search');
  const keywordList = document.querySelector('#notes-keyword-list');
  const active = document.querySelector('.notes-active');
  const all = document.createElement('button');
  all.type = 'button';
  all.className = 'keyword';
  all.dataset.topic = '';
  all.append('All notes ', Object.assign(document.createElement('span'), {textContent: notes.length}));
  keywordList.append(all);
  [...counts].sort(([a], [b]) => a.localeCompare(b, 'en', {sensitivity: 'base'})).forEach(([topic, count]) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'keyword';
    button.dataset.topic = topic;
    button.append(`${topic} `, Object.assign(document.createElement('span'), {textContent: count}));
    keywordList.append(button);
  });
  let selected = '';
  let timer;
  function readURL() {
    const params = new URLSearchParams(location.search);
    const requested = params.get('topic') || '';
    selected = [...counts.keys()].find(t => normalize(t) === normalize(requested)) || '';
    search.value = params.get('q') || '';
  }
  function update(saveURL = true) {
    const terms = normalize(search.value.trim()).split(/\s+/).filter(Boolean);
    let visible = 0;
    notes.forEach(note => {
      note.card.hidden = !((!selected || note.topics.includes(selected)) && terms.every(term => note.text.includes(term)));
      if (!note.card.hidden) visible++;
    });
    groups.forEach(group => { group.section.hidden = group.notes.every(note => note.card.hidden); });
    document.querySelector('#notes-count').textContent = `${visible} of ${notes.length} notes`;
    document.querySelector('#notes-empty').hidden = visible !== 0;
    active.hidden = !selected && !terms.length;
    document.querySelector('#notes-filter-label').textContent = [selected, search.value.trim() ? `Search: “${search.value.trim()}”` : ''].filter(Boolean).join(' · ');
    document.querySelectorAll('[data-topic]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.topic === selected)));
    if (saveURL) {
      const url = new URL(location.href);
      selected ? url.searchParams.set('topic', selected) : url.searchParams.delete('topic');
      search.value.trim() ? url.searchParams.set('q', search.value.trim()) : url.searchParams.delete('q');
      history.replaceState(null, '', url);
    }
  }
  document.querySelector('.notes-layout').addEventListener('click', event => {
    const button = event.target.closest('button[data-topic]');
    if (!button) return;
    selected = button.dataset.topic;
    update();
  });
  search.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(update, 100); });
  document.querySelector('#notes-reset').addEventListener('click', () => { selected = ''; search.value = ''; update(); search.focus(); });
  window.addEventListener('popstate', () => { readURL(); update(false); });
  if (matchMedia('(max-width: 760px)').matches) document.querySelector('#notes-keywords').open = false;
  document.querySelector('.notes-tools').hidden = false;
  document.querySelector('.notes-filters').hidden = false;
  readURL();
  update(false);
})();
