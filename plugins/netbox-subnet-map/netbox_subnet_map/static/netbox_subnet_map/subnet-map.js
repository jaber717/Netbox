(() => {
  'use strict';
  const root = document.getElementById('subnet-map');
  if (!root || root.dataset.ready) return;
  root.dataset.ready = 'true';
  const data = JSON.parse(document.getElementById('sm-data').textContent);
  const occupancyComplete = data.visibility_complete && !data.occupancy_truncated;
  const records = new Map(data.records.map(record => [record.address_host, record]));
  const cells = Array.from(root.querySelectorAll('.sm-cell'));
  const cellMap = new Map(cells.map(cell => [cell.dataset.host, cell]));
  const allocationTriggers = new Map(Array.from(document.querySelectorAll('[data-allocation-trigger]')).map(
    trigger => [trigger.dataset.allocationTrigger, trigger]
  ));
  const inspector = document.getElementById('sm-inspector-body');
  let selected = null;
  if (cells.length) cells[0].tabIndex = 0;
  const element = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  const block = (title, values, links = []) => {
    const node = element('section', undefined, 'sm-detail-block');
    node.append(element('h5', title));
    const dl = element('dl');
    values.forEach(([label, value]) => {
      dl.append(element('dt', label), element('dd', value === null || value === undefined || value === '' ? '—' : String(value)));
    });
    node.append(dl);
    links.forEach(([label, url]) => {
      // URLs are native server-produced object routes; never accept external schemes.
      if (url && url.startsWith('/') && !url.startsWith('//')) {
        const a = element('a', label); a.href = url; node.append(a, element('br'));
      }
    });
    return node;
  };
  const select = host => {
    const record = records.get(host);
    if (!record) return;
    const start = performance.now();
    if (selected) { selected.setAttribute('aria-pressed', 'false'); selected.tabIndex = -1; }
    selected = cellMap.get(host) || null;
    if (selected) { selected.setAttribute('aria-pressed', 'true'); selected.tabIndex = 0; }
    const content = element('div', undefined, 'sm-inspector-content');
    content.append(element('h4', record.address_host));
    record.derived_states.forEach(state => content.append(element('span', state, 'sm-state')));
    const actions = element('section', undefined, 'sm-contextual-actions');
    actions.setAttribute('aria-label', 'Contextual actions');
    // The assembler decides which actions belong to this address context.
    // Enabled allocation routes are still re-authorized and re-evaluated server-side.
    (record.contextual_actions || []).forEach((descriptor, index) => {
      const child = descriptor.child_prefix_id ? data.children_by_id[descriptor.child_prefix_id] : null;
      const action = child ? {...descriptor, object_address: child.label, url: child.map_url} : descriptor;
      const item = element('div', undefined, 'sm-action-item');
      if (action.object_address) item.append(element('small', action.object_address));
      if (action.enabled && action.url && action.url.startsWith('/') && !action.url.startsWith('//')) {
        if (action.kind === 'allocate') {
          const button = element('button', action.label, 'sm-contextual-action');
          button.type = 'button';
          button.dataset.allocationProxy = record.address_host;
          item.append(button);
        } else {
          const link = element('a', action.label, 'sm-contextual-action');
          link.href = action.url;
          item.append(link);
        }
      } else {
        const button = element('button', action.label, 'sm-contextual-action');
        button.type = 'button';
        button.disabled = true;
        const reason = element('span', action.reason, 'sm-action-reason');
        reason.id = `sm-action-reason-${index}`;
        button.setAttribute('aria-describedby', reason.id);
        item.append(button, reason);
      }
      actions.append(item);
    });
    if (actions.childElementCount) content.append(actions);
    const contextBlock = block('Address context', [
      ['Derived State', record.derived_states.join(', ')], ['Visible IPAddress objects', record.ip_objects.length],
      ['Allocation State', {candidate: 'Candidate', blocked: 'Blocked', unknown: 'Unknown'}[record.allocation_state]],
      ['Allocatable', {candidate: 'Context-dependent', blocked: 'No', unknown: 'Unknown'}[record.allocation_state]],
      ['Allocation details', record.allocation_message],
      ['Prefix', data.prefix.cidr], ['VRF', data.prefix.vrf],
      ['Prefix Tenant', data.prefix.tenant], ['VLAN context', data.prefix.vlan], ['Site / Scope', data.prefix.scope],
    ]);
    record.ip_objects.forEach(ip => {
      const a = ip.assignment;
      content.append(block(`IP object #${ip.id}`, [
        ['IP Address — stored mask', ip.address], ['NetBox Status', ip.status], ['Native IP role', ip.role],
        ['IP Tenant', ip.tenant], ['Function — derived', a.function], ['DNS Name', ip.dns_name], ['Description', ip.description],
        ['Assigned Object Type', a.type], ['Device / VM / FHRPGroup', a.parent], ['Assigned Object', a.label],
        ['Interface', a.interface], ['Primary Interface MAC — from NetBox', a.primary_mac],
        [`Other Interface MACs (+${a.other_macs.length}) — from NetBox`, a.other_macs.join(', ') || 'Not recorded'],
        ['Created', ip.created], ['Last Updated', ip.last_updated],
      ], [['Open assigned object', a.url], ['Open parent object', a.parent_url]]));
    });
    content.append(contextBlock);
    if (!record.ip_objects.length) content.append(block('IPAddress object', [['Object', occupancyComplete ? 'None' : 'No visible object']]));
    record.range_ids.map(id => data.ranges_by_id[id]).forEach(range => content.append(block('IPRange', [
      ['Range', range.label], ['Description', range.description], ['Start', range.start], ['End', range.end],
      ['NetBox Status', range.status], ['Role', range.role], ['Tenant', range.tenant],
      ['mark_populated', range.mark_populated ? 'True — populated range space' : 'False'], ['mark_utilized', range.mark_utilized ? 'True' : 'False'],
    ], [['Open native IPRange', range.url]])));
    record.child_prefix_ids.map(id => data.children_by_id[id]).forEach(child => content.append(block('Child Prefix', [
      ['Prefix', child.label], ['NetBox Status', child.status], ['Tenant', child.tenant], ['VRF', child.vrf],
    ], [['Open child Prefix', child.url], ['Open child Subnet Map', child.map_url]])));
    if (!record.range_ids.length) content.append(block('IPRange', [['Membership', occupancyComplete ? 'None' : 'No visible range']]));
    if (!record.child_prefix_ids.length) content.append(block('Child Prefix', [['Membership', occupancyComplete ? 'None' : 'No visible child prefix']]));
    content.append(element('p', 'Availability is not a promise of write acceptance. Allocate IP rechecks current context, permissions, native validation and local validators.', 'sm-inspector-note'));
    inspector.replaceChildren(content);
    const finished = performance.now();
    performance.measure('subnet-map-inspector', { start, end: finished });
    root.dataset.inspectorUpdateMs = (finished - start).toFixed(2);
    root.dataset.originalGridIntact = String(cells.every(cell => cell.isConnected && cell.parentElement.classList.contains('sm-grid')));
    requestAnimationFrame(() => { root.dataset.inspectorFrameMs = (performance.now() - start).toFixed(2); });
  };
  root.addEventListener('click', event => {
    const allocationProxy = event.target.closest('button[data-allocation-proxy]');
    if (allocationProxy && root.contains(allocationProxy)) {
      allocationTriggers.get(allocationProxy.dataset.allocationProxy)?.click();
      return;
    }
    const button = event.target.closest('button[data-host]');
    if (button && root.contains(button)) {
      select(button.dataset.host);
      if (button.classList.contains('sm-address-link') || matchMedia('(max-width:1100px)').matches) {
        inspector.scrollIntoView({block:'start', behavior:'auto'});
      }
    }
  });
  root.addEventListener('keydown', event => {
    if (event.ctrlKey || event.altKey || event.metaKey) return;
    const cell = event.target.closest('.sm-cell');
    if (!cell) return;
    const columns = getComputedStyle(cell.parentElement).gridTemplateColumns.split(' ').length;
    const offsets = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: columns, ArrowUp: -columns, Home: -cells.indexOf(cell), End: cells.length - 1 - cells.indexOf(cell) };
    if (!(event.key in offsets)) return;
    event.preventDefault();
    const index = Math.max(0, Math.min(cells.length - 1, cells.indexOf(cell) + offsets[event.key]));
    select(cells[index].dataset.host); cells[index].focus();
  });
  document.body.addEventListener('htmx:afterSwap', event => {
    const created = event.detail.target && event.detail.target.querySelector('#quick-add-object[data-target-id="subnet-map"]');
    if (!created || !selected) return;
    const destination = new URL(window.location.href);
    destination.searchParams.set('selected', selected.dataset.host);
    window.location.assign(destination);
  });
  const selectedFromRefresh = new URLSearchParams(window.location.search).get('selected');
  if (selectedFromRefresh && records.has(selectedFromRefresh)) select(selectedFromRefresh);
  performance.mark('subnet-map-ready');
  root.dataset.readyMs = performance.now().toFixed(2);
  requestAnimationFrame(() => requestAnimationFrame(() => {
    root.dataset.firstFrameMs = performance.now().toFixed(2);
    const navigation = performance.getEntriesByType('navigation')[0];
    if (navigation) root.dataset.responseStartMs = navigation.responseStart.toFixed(2);
    const paint = performance.getEntriesByName('first-contentful-paint')[0];
    if (paint) root.dataset.firstContentfulPaintMs = paint.startTime.toFixed(2);
  }));
})();
