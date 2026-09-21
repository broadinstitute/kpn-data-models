'use strict';
document.documentElement.classList.add('js-ready');
const ontology = document.querySelector('#ontology');
const rows = [...document.querySelectorAll('tr[data-ontology]')];
ontology.addEventListener('change', () => {
  let count = 0;
  rows.forEach(row => {
    row.hidden = Boolean(ontology.value && row.dataset.ontology !== ontology.value);
    if (!row.hidden) count++;
  });
  document.querySelector('#mapping-status').textContent = `${count} of ${rows.length} mappings`;
});
