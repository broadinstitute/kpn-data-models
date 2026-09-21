'use strict';
const catalog = document.querySelector('#catalog');
const statusText = document.querySelector('#result-status');
const results = document.querySelector('#results');
const search = document.querySelector('#search');
const group = document.querySelector('#group');
const source = document.querySelector('#source');
const previous = document.querySelector('#previous');
const next = document.querySelector('#next');
const pageNumber = document.querySelector('#page-number');
const params = new URLSearchParams(location.search);
search.value = params.get('q') || '';
group.value = params.get('group') || '';
const sourceParam = params.get('source');
source.value = sourceParam === 'portal' ? 'KPN' : sourceParam || '';
let data = [];
let page = 0;
const pageSize = 50;
function render() {
  const terms = search.value.toLocaleLowerCase().trim().split(/\s+/).filter(Boolean);
  const found = data.filter(record => (!group.value || record.group === group.value)
    && (!source.value || record.source === source.value)
    && terms.every(term => record.search.includes(term)));
  const pages = Math.max(1, Math.ceil(found.length / pageSize));
  page = Math.max(0, Math.min(page, pages - 1));
  const fragment = document.createDocumentFragment();
  for (const record of found.slice(page * pageSize, (page + 1) * pageSize)) {
    const row = document.createElement('tr');
    const name = document.createElement('td');
    const link = document.createElement('a');
    link.href = `${catalog.dataset.base}/kpn.trait/${record.id.split(':')[1]}/`;
    link.textContent = record.name;
    const id = document.createElement('div');
    id.className = 'identifier';
    id.textContent = record.id;
    name.append(link, id);
    row.append(name);
    for (const value of [record.group, record.source, record.count]) {
      const cell = document.createElement('td');
      cell.textContent = value;
      row.append(cell);
    }
    fragment.append(row);
  }
  results.replaceChildren(fragment);
  statusText.textContent = found.length
    ? `${found.length.toLocaleString()} ${found.length === 1 ? 'trait' : 'traits'}. Showing ${page * pageSize + 1}–${Math.min((page + 1) * pageSize, found.length)}.`
    : 'No traits match. Try another name, ID, or mapped term, or clear the filters.';
  pageNumber.textContent = `Page ${page + 1} of ${pages}`;
  previous.disabled = page === 0;
  next.disabled = page + 1 >= pages;
  const query = new URLSearchParams();
  if (search.value) query.set('q', search.value);
  if (group.value) query.set('group', group.value);
  if (source.value) query.set('source', source.value);
  history.replaceState(null, '', location.pathname + (query.size ? `?${query}` : ''));
}
async function load() {
  try {
    const response = await fetch(catalog.dataset.index);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    data = await response.json();
    data.forEach(record => { record.search = record.search.toLocaleLowerCase(); });
    document.documentElement.classList.add('js-ready');
    render();
    for (const control of [search, group, source]) {
      control.addEventListener('input', () => { page = 0; render(); });
    }
    previous.addEventListener('click', () => { page--; render(); });
    next.addEventListener('click', () => { page++; render(); });
  } catch (error) {
    statusText.textContent = 'Search could not load. Reload this page to retry, or use the complete release downloads below.';
  }
}
load();
